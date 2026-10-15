"""Bounded monotone-box search over exact manifest-v2 repair ceilings."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from itertools import combinations
from math import comb, prod

from ._remediation import (
    REMEDIATION_SCHEMA,
    _changed,
    _dominates,
    _Edit,
    _edit_record,
    _manifest,
    _quantity,
    _repair_cost,
    _structural,
)
from .lint import check
from .manifest import IRREVERSIBLE, Quantity
from .reach import analyse

RESULT_SCHEMA = REMEDIATION_SCHEMA


@dataclass(frozen=True)
class _Axis:
    tool: str
    ceiling: Quantity
    step: Quantity
    last: int

    def value(self, index):
        if index == self.last:
            return self.ceiling
        _, digits, exponent = self.step.amount.as_tuple()
        text = str(index * int("".join(map(str, digits))))
        places = min(len(text) - len(text.rstrip("0")), max(0, -exponent))
        digits = tuple(int(char) for char in text[: len(text) - places]) or (0,)
        value = Decimal(0) if index == 0 else Decimal((0, digits, exponent + places))
        return Quantity(value, self.ceiling.unit)


def _axes(mandate, options):
    if len(options) > 8:
        raise ValueError("discovery supports at most 8 tools")
    axes = {}
    for option in options:
        if not isinstance(option, str):
            raise ValueError("discovery options must use TOOL=STEP")
        name, separator, amount = option.rpartition("=")
        if not separator or not name or not amount:
            raise ValueError("discovery options must use TOOL=STEP")
        tool = mandate.tool(name)
        if tool is None or tool.ceiling is None:
            raise ValueError(f"discovery {name!r} must name a declared spending tool")
        if name in axes:
            raise ValueError("discovery tools must be distinct")
        if len(amount) > 128:
            raise ValueError("discovery steps are limited to 128 characters")
        step = Quantity.parse({"amount": amount, "unit": tool.ceiling.unit}, "discovery step")
        ceiling = Quantity.parse(_quantity(tool.ceiling), "discovery ceiling")
        if step.amount == 0:
            raise ValueError("discovery STEP must be positive")
        tuples = [ceiling.amount.as_tuple(), step.amount.as_tuple()]
        if any(len(t.digits) > 100 or abs(t.exponent) > 100 for t in tuples):
            raise ValueError("discovery amounts require at most 100 digits and exponent +/-100")
        exponent = min(t.exponent for t in tuples)
        cap, stride = [
            int("".join(map(str, t.digits))) * 10 ** (t.exponent - exponent) for t in tuples
        ]
        axes[name] = _Axis(name, ceiling, step, (cap + stride - 1) // stride)
    return tuple(axes[name] for name in sorted(axes))


class _EvaluationLimit(Exception):
    pass


def discover(
    mandate,
    *,
    options,
    depth,
    max_edits,
    max_evaluations,
    max_candidates,
    keep_tools,
    required_workflows,
):
    for name, value in (
        ("max_edits", max_edits),
        ("max_evaluations", max_evaluations),
        ("max_candidates", max_candidates),
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive whole number")
    if max_edits > 8:
        raise ValueError("discovery supports at most 8 edits")
    if any(not isinstance(name, str) or name not in mandate.tool_names for name in keep_tools):
        raise ValueError("keep_tools must name declared tools")
    axes = _axes(mandate, options)
    baseline = analyse(mandate, depth=depth)
    if set(keep_tools) - baseline.reachable_tools:
        raise ValueError("kept tools must be reachable in the baseline at the selected depth")
    lint = check(mandate)
    approvals = sorted(
        t.name for t in mandate.tools if t.effect == IRREVERSIBLE and not t.requires_approval
    )
    configuration_count = sum(
        comb(len(approvals), size) for size in range(min(len(approvals), max_edits) + 1)
    )
    total = prod(axis.last + 1 for axis in axes) * configuration_count
    discovery = {
        "algorithm": "monotone_box_search",
        "status": "not_run",
        "scope": "complete frontier only within the discrete domain and fixed reachability bound",
        "tools_retained": sorted(mandate.tool_names),
        "domains": [
            {
                "tool": a.tool,
                "quantity": mandate.tool(a.tool).quantity,
                "step": _quantity(a.step),
                "minimum": "0",
                "maximum": _quantity(a.ceiling),
                "points": a.last + 1,
                "includes_unchanged_ceiling": True,
            }
            for a in axes
        ],
        "approval_tools": approvals,
        "approval_configurations": configuration_count,
        "domain_points": total,
        "resolved_points": 0,
        "remaining_points": total,
        "frontier_complete_within_domain": False,
        "probes": [],
    }
    search = {
        "depth": baseline.depth,
        "max_edits": max_edits,
        "max_evaluations": max_evaluations,
        "max_candidates": max_candidates,
        "combinations_total": total,
        "combinations_examined": 0,
        "candidates_analyzed": 0,
        "candidates_found": 0,
        "exhaustive_point_enumeration": False,
        "truncated_by_limit": False,
    }
    report = {
        "schema": RESULT_SCHEMA,
        "scope": "manifest-v2 reachability only; candidates require human selection",
        "baseline": baseline.as_dict(),
        "baseline_lint": [asdict(f) for f in lint],
        "keep_tools": sorted(set(keep_tools)),
        "search": search,
        "status": "no_reachable_breach_within_bound",
        "candidates": [],
        "discovery": discovery,
        "frontier": {
            "enabled": True,
            "status": "not_computed",
            "scope": "repair trade-offs among examined, rechecked candidates only",
            "objectives": {
                "edit_count": "minimize",
                "lost_reachable_tools": "set inclusion",
                "added_approval_tools": "set inclusion",
                "retained_ceilings": "maximize each declared tool ceiling",
            },
            "successful_candidates": 0,
            "non_dominated": None,
            "display_complete": True,
        },
    }
    if required_workflows is not None:
        assessments = required_workflows.assess(mandate, baseline.depth)
        invalid = next((a for a in assessments if a["failure"] is not None), None)
        if invalid is not None:
            raise ValueError(f"required workflow {invalid['name']!r} is invalid in the baseline")
        report["requirements"] = {**required_workflows.metadata(), "baseline": assessments}
        report["requirement_rejections"] = []
        search["required_workflow_rejections"] = 0
    if _structural(lint):
        report["status"] = "input_requires_review"
        return report
    if not baseline.breaches:
        discovery["status"] = "not_needed_baseline_clean"
        return report

    cache, candidates = {}, []

    def probe(vector, gates):
        key = (vector, gates)
        if key in cache:
            return cache[key]
        if len(cache) >= max_evaluations:
            raise _EvaluationLimit
        edits = tuple(_Edit(name, "require_approval") for name in gates) + tuple(
            _Edit(a.tool, "tighten_ceiling", a.value(i))
            for a, i in zip(axes, vector, strict=True)
            if i != a.last
        )
        record = {
            "ceilings": {a.tool: _quantity(a.value(i)) for a, i in zip(axes, vector, strict=True)},
            "added_approvals": list(gates),
            "edit_count": len(edits),
            "status": "edit_limit",
            "authority_truncated": None,
            "breach_kinds": [],
        }
        discovery["probes"].append(record)
        cache[key] = record
        search["combinations_examined"] += 1
        if len(edits) > max_edits:
            return record
        changed = _changed(mandate, edits)
        assessments = (
            [] if required_workflows is None else required_workflows.assess(changed, baseline.depth)
        )
        if any(a["failure"] is not None for a in assessments):
            record["status"] = "required_workflow_rejected"
            search["required_workflow_rejections"] += 1
            report["requirement_rejections"].append(
                {
                    "edits": [_edit_record(mandate, e) for e in edits],
                    "stage": "required_workflow_screen",
                    "assessments": assessments,
                }
            )
            return record
        authority = baseline if not edits else analyse(changed, depth=baseline.depth)
        search["candidates_analyzed"] += bool(edits)
        if not baseline.reachable_tools <= authority.reachable_tools:
            raise ValueError("discovery requires ceiling-independent tool reachability")
        record.update(
            status="breached" if authority.breaches else "candidate",
            authority_truncated=authority.truncated,
            breach_kinds=sorted({b.kind for b in authority.breaches}),
        )
        if not authority.breaches:
            candidate = {
                "status": "no_reachable_breach_within_bound",
                "edits": [_edit_record(mandate, e) for e in edits],
                "impact": {
                    "edit_count": len(edits),
                    "lost_reachable_tools": [],
                    "removed_role_members": {},
                },
                "authority": authority.as_dict(),
                "lint": [asdict(f) for f in check(changed)],
                "manifest": _manifest(changed),
            }
            if required_workflows is not None:
                candidate["required_workflows"] = assessments
            candidate["repair_cost"] = _repair_cost(mandate, candidate)
            candidates.append(candidate)
        return record

    def covered(high, gates):
        return any(
            set(c["repair_cost"]["added_approval_tools"]) <= set(gates)
            and all(
                Decimal(c["repair_cost"]["retained_ceilings"][a.tool]["amount"])
                >= a.value(i).amount
                for a, i in zip(axes, high, strict=True)
            )
            for c in candidates
        )

    stopped = False
    configurations = (
        gates
        for size in range(min(len(approvals), max_edits) + 1)
        for gates in combinations(approvals, size)
    )
    for gates in configurations:
        boxes = [(tuple(0 for _ in axes), tuple(a.last for a in axes))]
        while boxes:
            low, high = boxes.pop()
            volume = prod(end - start + 1 for start, end in zip(low, high, strict=True))
            try:
                if covered(high, gates):
                    discovery["resolved_points"] += volume
                    continue
                upper = probe(high, gates)
                if upper["status"] in ("candidate", "edit_limit", "required_workflow_rejected"):
                    discovery["resolved_points"] += volume
                    continue
                if low == high or probe(low, gates)["status"] == "breached":
                    discovery["resolved_points"] += volume
                    continue
            except _EvaluationLimit:
                stopped = True
                break
            axis = max(range(len(axes)), key=lambda i: high[i] - low[i])
            middle = (low[axis] + high[axis]) // 2
            left_high, right_low = list(high), list(low)
            left_high[axis], right_low[axis] = middle, middle + 1
            boxes.extend(((low, tuple(left_high)), (tuple(right_low), high)))
        if stopped:
            break
    discovery.update(
        status="evaluation_limit" if stopped else "complete",
        remaining_points=total - discovery["resolved_points"],
        frontier_complete_within_domain=not stopped,
    )
    search.update(
        candidates_found=len(candidates),
        exhaustive_point_enumeration=search["combinations_examined"] == total,
        truncated_by_limit=stopped,
    )
    frontier = [
        c
        for c in candidates
        if not any(_dominates(other["repair_cost"], c["repair_cost"]) for other in candidates)
    ]
    frontier.sort(
        key=lambda c: (
            c["impact"]["edit_count"],
            c["repair_cost"]["added_approval_tools"],
            tuple(
                Decimal(c["repair_cost"]["retained_ceilings"][name]["amount"]).copy_negate()
                for name in sorted(c["repair_cost"]["retained_ceilings"])
            ),
        )
    )
    report["frontier"].update(
        status="computed",
        successful_candidates=len(candidates),
        non_dominated=len(frontier),
        display_complete=len(frontier) <= max_candidates,
    )
    report["candidates"] = frontier[:max_candidates]
    report["status"] = (
        "candidates_found"
        if frontier
        else "no_candidate_found_within_limits"
        if stopped
        else "no_feasible_candidate_in_declared_domain"
    )
    return report
