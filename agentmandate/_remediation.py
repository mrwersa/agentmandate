"""Report-only repair candidates over the existing manifest-v1 model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from itertools import chain, combinations, islice
from math import comb
from typing import Any

from ._required_workflows import _Requirements
from .lint import Finding, check
from .manifest import EFFECT_RANK, IRREVERSIBLE, Mandate, Money
from .reach import analyse

REMEDIATION_SCHEMA = "agentmandate.remediation/v1"
CEILING_REMEDIATION_SCHEMA = "agentmandate.remediation/v2"
WORKFLOW_REMEDIATION_SCHEMA = "agentmandate.remediation/v3"
FRONTIER_REMEDIATION_SCHEMA = "agentmandate.remediation/v4"
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


@dataclass(frozen=True)
class _Edit:
    tool: str
    kind: str
    ceiling: Money | None = None


def _ceiling_domain(mandate: Mandate, options: tuple[str, ...]) -> tuple[_Edit, ...]:
    if any(not isinstance(option, str) for option in options):
        raise ValueError("ceiling options must use TOOL=AMOUNT")
    domain = {}
    for option in sorted(options):
        name, separator, amount = option.rpartition("=")
        if not separator or not name or not amount:
            raise ValueError("ceiling options must use TOOL=AMOUNT")
        tool = mandate.tool(name)
        if tool is None or tool.ceiling is None:
            raise ValueError(f"ceiling option {name!r} must name a declared spending tool")
        ceiling = Money.parse({"amount": amount, "currency": tool.ceiling.currency},
                              f"ceiling option {name!r}")
        if ceiling.amount >= tool.ceiling.amount:
            raise ValueError(f"ceiling option {name!r} must be strictly below its current ceiling")
        # Numeric duplicates choose the first lexical spelling, independent of flag order.
        domain.setdefault((name, ceiling.amount), _Edit(name, "tighten_ceiling", ceiling))
    return tuple(domain[key] for key in sorted(domain))


def _grid_domain(mandate: Mandate, grids: tuple[str, ...]) -> tuple[tuple[str, ...], list]:
    """Expand a finite reviewer-authored domain with exact scaled integers."""
    options, records = [], []
    for grid in sorted(grids):
        name, separator, values = grid.rpartition("=")
        parts = values.split(":")
        if not separator or not name or len(parts) != 3:
            raise ValueError("ceiling grids must use TOOL=MIN:MAX:STEP")
        tool = mandate.tool(name)
        if tool is None or tool.ceiling is None:
            raise ValueError(f"ceiling grid {name!r} must name a declared spending tool")
        if any(len(part) > 128 for part in parts):
            raise ValueError("ceiling grid numbers are limited to 128 characters")
        amounts = [Money.parse({"amount": part, "currency": tool.ceiling.currency},
                               f"ceiling grid {name!r}").amount for part in parts]
        tuples = [amount.as_tuple() for amount in amounts]
        if any(len(t.digits) > 100 or abs(t.exponent) > 100 for t in tuples):
            raise ValueError("ceiling grid numbers require at most 100 digits and exponent +/-100")
        lower, upper, step = amounts
        if step == 0 or lower > upper:
            raise ValueError("ceiling grid requires MIN <= MAX and STEP > 0")
        if upper >= tool.ceiling.amount:
            raise ValueError(
                f"ceiling grid {name!r} MAX must be strictly below its current ceiling"
            )
        exponent = min(t.exponent for t in tuples)
        start, stop, stride = [
            int("".join(map(str, t.digits))) * 10 ** (t.exponent - exponent) for t in tuples
        ]
        count = (stop - start) // stride + 1
        if len(options) + count > 512:
            raise ValueError(
                "ceiling grids may generate at most 512 points in total before deduplication"
            )
        for index in range(count):
            text = str(start + index * stride)
            # Remove only fractional trailing zeros; do not round in caller context.
            places = min(len(text) - len(text.rstrip("0")), max(0, -exponent))
            digits = tuple(int(char) for char in text[:len(text) - places]) or (0,)
            value = Decimal((0, digits, exponent + places))
            options.append(f"{name}={value or '0'}")
        records.append({"tool": name, "minimum": str(lower), "maximum": str(upper),
                        "step": str(step), "currency": tool.ceiling.currency,
                        "points_generated": count})
    return tuple(options), records


def _repair_cost(mandate: Mandate, candidate: dict) -> dict:
    tools = {tool["name"]: tool for tool in candidate["manifest"]["tools"]}
    return {
        "edit_count": candidate["impact"]["edit_count"],
        "lost_reachable_tools": candidate["impact"]["lost_reachable_tools"],
        "added_approval_tools": sorted(e["tool"] for e in candidate["edits"]
                                       if e["kind"] == "require_approval"),
        "retained_ceilings": {
            tool.name: tools[tool.name]["ceiling"] if tool.name in tools else
            {"amount": "0", "currency": tool.ceiling.currency}
            for tool in sorted(mandate.tools, key=lambda t: t.name) if tool.ceiling is not None
        },
    }


def _dominates(left: dict, right: dict) -> bool:
    """Compare repair costs, preserving named capabilities rather than counts."""
    comparisons = [
        (left["edit_count"] <= right["edit_count"], left["edit_count"] < right["edit_count"]),
        (set(left["lost_reachable_tools"]) <= set(right["lost_reachable_tools"]),
         set(left["lost_reachable_tools"]) < set(right["lost_reachable_tools"])),
        (set(left["added_approval_tools"]) <= set(right["added_approval_tools"]),
         set(left["added_approval_tools"]) < set(right["added_approval_tools"])),
    ]
    for name, value in left["retained_ceilings"].items():
        a, b = Decimal(value["amount"]), Decimal(right["retained_ceilings"][name]["amount"])
        comparisons.append((a >= b, a > b))
    return all(no_worse for no_worse, _ in comparisons) and any(
        better for _, better in comparisons
    )


def _changed(mandate: Mandate, edits: tuple[_Edit, ...]) -> Mandate | None:
    keys = [(edit.tool, edit.kind) for edit in edits]
    removed = {edit.tool for edit in edits if edit.kind == "remove_tool"}
    gated = {edit.tool for edit in edits if edit.kind == "require_approval"}
    tightened = {edit.tool: edit.ceiling for edit in edits if edit.kind == "tighten_ceiling"}
    if len(set(keys)) != len(keys) or removed & (gated | set(tightened)):
        return None  # One ceiling choice per tool; removal cannot accompany another edit.
    tools = tuple(
        replace(tool, requires_approval=tool.requires_approval or tool.name in gated,
                ceiling=tightened.get(tool.name, tool.ceiling))
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


def _edit_record(mandate: Mandate, edit: _Edit) -> dict:
    record = {"tool": edit.tool, "kind": edit.kind}
    if edit.kind == "tighten_ceiling":
        record["before"] = _money(mandate.tool(edit.tool).ceiling)
        record["after"] = _money(edit.ceiling)
    return record


def _retained_value(candidate: dict) -> Decimal:
    value = candidate["authority"]["max_extractable"]
    # Copying the sign is exact under any caller context and keeps large
    # exponents compact. Negating with '-' would round to that context.
    return Decimal(0) if value is None else Decimal(value["amount"]).copy_negate()


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
    ceiling_options: tuple[str, ...] = (),
    required_workflows: _Requirements | None = None,
    ceiling_grids: tuple[str, ...] = (),
    pareto: bool = False,
    discover_ceilings: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Enumerate edits, recheck the full graph, and rank scoped candidates.

    This private record is presentation, never reviewed authority or a mutation.
    Combinations examined include rejected conflicting/structural edits.
    """
    if not isinstance(discover_ceilings, (tuple, list)):
        raise ValueError("discovery options must use TOOL=STEP")
    if discover_ceilings:
        if ceiling_options or ceiling_grids:
            raise ValueError("discovery cannot be combined with explicit ceilings or grids")
        if type(pareto) is not bool:
            raise ValueError("pareto must be a boolean")
        from ._ceiling_discovery import discover

        return discover(
            mandate, options=discover_ceilings, depth=depth, max_edits=max_edits,
            max_evaluations=max_evaluations, max_candidates=max_candidates,
            keep_tools=keep_tools, required_workflows=required_workflows,
        )
    for name, value in (
        ("max_edits", max_edits),
        ("max_evaluations", max_evaluations),
        ("max_candidates", max_candidates),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive whole number")
    if any(not isinstance(name, str) or name not in mandate.tool_names for name in keep_tools):
        raise ValueError("keep_tools must name declared tools")
    if type(pareto) is not bool:
        raise ValueError("pareto must be a boolean")
    if any(not isinstance(grid, str) for grid in ceiling_grids):
        raise ValueError("ceiling grids must use TOOL=MIN:MAX:STEP")
    grid_options, grids = _grid_domain(mandate, ceiling_grids)
    ceiling_edits = _ceiling_domain(mandate, ceiling_options + grid_options)
    baseline = analyse(mandate, depth=depth)
    if set(keep_tools) - baseline.reachable_tools:
        raise ValueError("kept tools must be reachable in the baseline at the selected depth")
    findings = check(mandate)
    report = {
        "schema": CEILING_REMEDIATION_SCHEMA if ceiling_edits else REMEDIATION_SCHEMA,
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
    if required_workflows is not None:
        assessments = required_workflows.assess(mandate, baseline.depth)
        invalid = next((row for row in assessments if row["failure"] is not None), None)
        if invalid is not None:
            failure = invalid["failure"]
            raise ValueError(f"required workflow {invalid['name']!r} is invalid in the baseline: "
                             f"step {failure['step']} {failure['rule']}: {failure['detail']}")
        report["schema"] = WORKFLOW_REMEDIATION_SCHEMA
        report["requirements"] = {**required_workflows.metadata(), "baseline": assessments}
        report["requirement_rejections"] = []
        report["search"]["required_workflow_rejections"] = 0
    if ceiling_edits:
        report["ceiling_options"] = [
            {"tool": edit.tool, "ceiling": _money(edit.ceiling)} for edit in ceiling_edits
        ]
    if grids or pareto:
        report["schema"] = FRONTIER_REMEDIATION_SCHEMA
        report["ceiling_grids"] = grids
        report["frontier"] = {
            "enabled": pareto, "status": "not_computed" if pareto else "disabled",
            "scope": "repair trade-offs among examined, rechecked candidates only",
            "objectives": {"edit_count": "minimize", "lost_reachable_tools": "set inclusion",
                           "added_approval_tools": "set inclusion",
                           "retained_ceilings": "maximize each declared tool ceiling"},
            "successful_candidates": 0, "non_dominated": None,
            "display_complete": True,
        }
    if _structural(findings):
        report["status"] = "input_requires_review"
        return report
    if not baseline.breaches:
        return report
    actions = tuple(
        _Edit(tool.name, kind)
        for tool in sorted(mandate.tools, key=lambda t: t.name)
        for kind in (
            (["remove_tool"] if tool.name not in keep_tools else [])
            + (
                ["require_approval"]
                if tool.effect == IRREVERSIBLE and not tool.requires_approval
                else []
            )
        )
    ) + ceiling_edits
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
        assessments = []
        if required_workflows is not None:
            assessments = required_workflows.assess(candidate, baseline.depth)
            if any(row["failure"] is not None for row in assessments):
                search["required_workflow_rejections"] += 1
                report["requirement_rejections"].append({
                    "edits": [_edit_record(mandate, edit) for edit in edits],
                    "stage": "required_workflow_screen", "assessments": assessments,
                })
                continue
        authority = analyse(candidate, depth=baseline.depth)
        search["candidates_analyzed"] += 1
        if authority.breaches or set(keep_tools) - authority.reachable_tools:
            continue
        removed = sorted(set(mandate.tool_names) - set(candidate.tool_names))
        record = {
            "status": "no_reachable_breach_within_bound",
            "edits": [_edit_record(mandate, edit) for edit in edits],
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
        if required_workflows is not None:
            record["required_workflows"] = assessments
        candidates.append(record)
    effect_ranks = {tool.name: EFFECT_RANK[tool.effect] for tool in mandate.tools}
    candidates.sort(
        key=lambda c: (
            c["impact"]["edit_count"],
            len(c["impact"]["lost_reachable_tools"]),
            tuple(sorted(
                (effect_ranks[name] for name in c["impact"]["lost_reachable_tools"]),
                reverse=True,
            )),
            sum(e["kind"] == "remove_tool" for e in c["edits"]),
            _retained_value(c) if ceiling_edits else Decimal(0),
            tuple((e["tool"], e["kind"], e.get("after", {}).get("amount", ""))
                  for e in c["edits"]),
        )
    )
    search["candidates_found"] = len(candidates)
    search["enumeration_complete"] = search["combinations_examined"] == search["combinations_total"]
    if pareto:
        for candidate in candidates:
            candidate["repair_cost"] = _repair_cost(mandate, candidate)
        candidates = [c for c in candidates if not any(
            _dominates(other["repair_cost"], c["repair_cost"]) for other in candidates
        )]
        report["frontier"].update(
            status="computed", successful_candidates=search["candidates_found"],
            non_dominated=len(candidates),
        )
    if "frontier" in report:
        report["frontier"]["display_complete"] = len(candidates) <= max_candidates
    report["candidates"] = candidates[:max_candidates]
    report["status"] = "candidates_found" if candidates else "no_candidate_found_within_limits"
    return report
