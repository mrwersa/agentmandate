"""Report-only repair candidates over the existing manifest-v1 model."""

from __future__ import annotations

from dataclasses import asdict, replace
from itertools import chain, combinations, islice
from math import comb
from typing import Any

from .lint import Finding, check
from .manifest import IRREVERSIBLE, Mandate, Money
from .reach import analyse

REMEDIATION_SCHEMA = "agentmandate.remediation/v1"
_STRUCTURAL_RULES = {
    "scope.missing-producer",
    "ceiling.unbound-scope",
    "ceiling.mixed-currency",
}


def _money(value: Money | None) -> dict | None:
    return None if value is None else {"amount": str(value.amount), "currency": value.currency}


def _manifest(mandate: Mandate) -> dict:
    tools = []
    for tool in mandate.tools:
        row = asdict(tool)
        row["requires"] = list(tool.requires)
        row["ceiling"] = _money(tool.ceiling)
        tools.append({key: value for key, value in row.items() if value is not None})
    limits = {"depth": mandate.limits.depth, "effects": dict(mandate.limits.effects)}
    if mandate.limits.total is not None:
        limits["total"] = _money(mandate.limits.total)
    return {
        "version": 1,
        "agent": mandate.agent,
        "identity": mandate.identity,
        "tools": tools,
        "roles": {k: list(v) for k, v in mandate.roles.items()},
        "limits": limits,
    }


def _changed(mandate: Mandate, edits: tuple[tuple[str, str], ...]) -> Mandate | None:
    names = [name for name, _ in edits]
    if len(set(names)) != len(names):
        return None  # Removing and gating the same tool is not two meaningful edits.
    removed = {name for name, kind in edits if kind == "remove_tool"}
    gated = {name for name, kind in edits if kind == "require_approval"}
    tools = tuple(
        replace(tool, requires_approval=True) if tool.name in gated else tool
        for tool in mandate.tools
        if tool.name not in removed
    )
    if not tools:
        return None  # An empty tool list is not a loadable manifest-v1 policy.
    roles = {
        role: tuple(name for name in members if name not in removed)
        for role, members in mandate.roles.items()
    }
    return replace(mandate, tools=tools, roles=roles)


def _structural(findings: list[Finding]) -> bool:
    return any(f.rule in _STRUCTURAL_RULES for f in findings)


def plan(
    mandate: Mandate,
    *,
    depth: int | None = None,
    max_edits: int = 2,
    max_evaluations: int = 128,
    max_candidates: int = 5,
    keep_tools: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Enumerate edits, recheck the full graph, and rank scoped candidates.

    This private record is presentation, never reviewed authority or a mutation.
    Combinations examined include rejected conflicting/structural edits.
    """
    for name, value in (
        ("max_edits", max_edits),
        ("max_evaluations", max_evaluations),
        ("max_candidates", max_candidates),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive whole number")
    if any(not isinstance(name, str) or name not in mandate.tool_names for name in keep_tools):
        raise ValueError("keep_tools must name declared tools")
    baseline = analyse(mandate, depth=depth)
    if set(keep_tools) - baseline.reachable_tools:
        raise ValueError("kept tools must be reachable in the baseline at the selected depth")
    findings = check(mandate)
    report = {
        "schema": REMEDIATION_SCHEMA,
        "scope": "manifest-v1 reachability only; candidates require human selection",
        "baseline": baseline.as_dict(),
        "baseline_lint": [asdict(f) for f in findings],
        "keep_tools": sorted(set(keep_tools)),
        "search": {
            "depth": baseline.depth,
            "max_edits": max_edits,
            "max_evaluations": max_evaluations,
            "max_candidates": max_candidates,
            "combinations_total": 0,
            "combinations_examined": 0,
            "candidates_analyzed": 0,
            "candidates_found": 0,
            "enumeration_complete": None,
        },
        "status": "no_reachable_breach_within_bound",
        "candidates": [],
    }
    if _structural(findings):
        report["status"] = "input_requires_review"
        return report
    if not baseline.breaches:
        return report
    actions = tuple(
        (tool.name, kind)
        for tool in sorted(mandate.tools, key=lambda t: t.name)
        for kind in (
            (["remove_tool"] if tool.name not in keep_tools else [])
            + (
                ["require_approval"]
                if tool.effect == IRREVERSIBLE and not tool.requires_approval
                else []
            )
        )
    )
    sizes = range(1, min(max_edits, len(actions)) + 1)
    search = report["search"]
    search["combinations_total"] = sum(comb(len(actions), size) for size in sizes)
    choices = chain.from_iterable(combinations(actions, size) for size in sizes)
    candidates = []
    for edits in islice(choices, max_evaluations):
        search["combinations_examined"] += 1
        candidate = _changed(mandate, edits)
        if candidate is None:
            continue
        lint = check(candidate)
        if _structural(lint):
            continue  # Losing a producer must not manufacture a clean graph.
        authority = analyse(candidate, depth=baseline.depth)
        search["candidates_analyzed"] += 1
        if authority.breaches or set(keep_tools) - authority.reachable_tools:
            continue
        removed = sorted(set(mandate.tool_names) - set(candidate.tool_names))
        candidates.append(
            {
                "status": "no_reachable_breach_within_bound",
                "edits": [{"tool": name, "kind": kind} for name, kind in edits],
                "impact": {
                    "edit_count": len(edits),
                    "lost_reachable_tools": sorted(
                        baseline.reachable_tools - authority.reachable_tools
                    ),
                    "removed_role_members": {
                        role: sorted(set(members) & set(removed))
                        for role, members in mandate.roles.items()
                        if set(members) & set(removed)
                    },
                },
                "authority": authority.as_dict(),
                "lint": [asdict(f) for f in lint],
                "manifest": _manifest(candidate),
            }
        )
    candidates.sort(
        key=lambda c: (
            c["impact"]["edit_count"],
            len(c["impact"]["lost_reachable_tools"]),
            sum(e["kind"] == "remove_tool" for e in c["edits"]),
            tuple((e["tool"], e["kind"]) for e in c["edits"]),
        )
    )
    search["candidates_found"] = len(candidates)
    search["enumeration_complete"] = search["combinations_examined"] == search["combinations_total"]
    report["candidates"] = candidates[:max_candidates]
    report["status"] = "candidates_found" if candidates else "no_candidate_found_within_limits"
    return report
