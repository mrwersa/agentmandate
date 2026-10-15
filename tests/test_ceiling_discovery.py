"""Exact independent finite-domain oracles for automatic ceiling discovery."""

import copy
import hashlib
import json
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from itertools import combinations, product
from pathlib import Path

import pytest

from agentmandate import Mandate, analyse, load
from agentmandate._ceiling_discovery import _axes
from agentmandate._remediation import plan
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/dispute-resolver-v2.yaml"
REQUIRED = ROOT / "examples/remediation/required-refund.json"


def model(*, approved=True, total="3", second=False, ceiling="3.5"):
    tools = [
        {"name": "seed", "effect": "read", "produces": "item", "unbounded": True},
        {
            "quantity": "value",
            "name": "pay",
            "effect": "irreversible",
            "requires": ["item"],
            "scope_key": "item",
            "value_arg": "amount",
            "requires_approval": approved,
            "ceiling": {"amount": ceiling, "unit": "GBP"},
        },
    ]
    if second:
        tools.append({**tools[1], "name": "other"})
    return Mandate.parse(
        {
            "agent": "discovery-example",
            "tools": tools,
            "limits": {
                "depth": 3 if second else 4,
                "quantities": {"value": {"amount": total, "unit": "GBP"}},
            },
        }
    )


def requirements(source, amount="1", approved=True):
    steps = [{"tool": "seed", "principal": "caller", "approved": False}] + [
        {
            "quantity": "value",
            "tool": t.name,
            "principal": "caller",
            "approved": approved,
            "binding": 0,
            "value": amount,
            "unit": "GBP",
        }
        for t in source.tools
        if t.ceiling is not None
    ]
    value = {
        "schema": "agentmandate.required-workflows/v2",
        "agent": source.agent,
        "manifest_sha256": "0" * 64,
        "reviewer": "synthetic-reviewer",
        "reason": "Synthetic supplied path; not business-success evidence",
        "workflows": [{"name": "required-payments", "steps": steps}],
    }
    return _Requirements.load(json.dumps(value).encode(), source, "0" * 64)


def options(source, step="1"):
    return tuple(f"{t.name}={step}" for t in source.tools if t.ceiling is not None)


def signature(candidate):
    caps = tuple(
        (t["name"], Fraction(t["ceiling"]["amount"]))
        for t in sorted(candidate["manifest"]["tools"], key=lambda t: t["name"])
        if t.get("ceiling") is not None
    )
    gates = frozenset(e["tool"] for e in candidate["edits"] if e["kind"] == "require_approval")
    return caps, gates


def reference(source, *, step=Fraction(1), max_edits=2, minimum=None, approved_path=True):
    """Enumerate every point; derive this graph's maximum without reach helpers."""
    spending = sorted((t for t in source.tools if t.ceiling is not None), key=lambda t: t.name)
    original = tuple(Fraction(t.ceiling.amount) for t in spending)
    domains = [tuple(step * i for i in range((cap / step).__ceil__())) + (cap,) for cap in original]
    ungated = tuple(t.name for t in spending if not t.requires_approval)
    count = len(spending)
    depth = source.limits.depth
    passing = []
    for caps in product(*domains):
        maximum = max(
            sum(sorted(caps * seeds, reverse=True)[: depth - seeds])
            for seeds in range(1, depth + 1)
        )
        for size in range(len(ungated) + 1):
            for gates in combinations(ungated, size):
                edits = size + sum(a != b for a, b in zip(caps, original, strict=True))
                if not 0 < edits <= max_edits or set(ungated) - set(gates):
                    continue
                if maximum > Fraction(source.limits.quantities["value"].amount):
                    continue
                if minimum is not None and (
                    any(c < minimum for c in caps) or (gates and not approved_path)
                ):
                    continue
                passing.append((caps, frozenset(gates), edits))
    frontier = []
    for caps, gates, edits in passing:
        dominated = any(
            other_edits <= edits
            and other_gates <= gates
            and all(a >= b for a, b in zip(other_caps, caps, strict=True))
            and (other_edits < edits or other_gates < gates or other_caps != caps)
            for other_caps, other_gates, other_edits in passing
        )
        if not dominated:
            frontier.append(
                (tuple((t.name, c) for t, c in zip(spending, caps, strict=True)), gates)
            )
    assert count > 0
    return set(frontier)


def test_refund_discovery_finds_125_in_six_probes_without_changing_the_source():
    source = load(EXAMPLE)
    original = copy.deepcopy(source)
    required = _Requirements.load(
        REQUIRED.read_bytes(), source, hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
    )
    result = plan(source, discover_ceilings=("issue_refund=0.01",), required_workflows=required)
    assert source == original and result["schema"] == "agentmandate.remediation/v6"
    assert result["baseline"] == analyse(source).as_dict()
    assert result["discovery"]["domain_points"] == 50001
    assert result["discovery"]["resolved_points"] == 50001
    assert result["discovery"]["remaining_points"] == 0
    assert result["discovery"]["frontier_complete_within_domain"]
    assert result["search"]["combinations_examined"] == 6
    assert not result["search"]["exhaustive_point_enumeration"]
    (candidate,) = result["candidates"]
    assert candidate["edits"][0]["after"] == {"amount": "125", "unit": "GBP"}
    assert candidate["authority"]["truncated"]
    changed = Mandate.parse(candidate["manifest"])
    assert changed.limits == source.limits and changed.tool_names == source.tool_names
    assert candidate["authority"] == analyse(changed).as_dict()
    assert candidate["required_workflows"] == required.assess(changed, 8)


CASES = [
    case
    for case in product([False, True], [False, True], ["0", "3", "5"], [1, 2, 3], [False, True])
    if not case[4] or (int(case[2]) >= (2 if case[1] else 1))
]


@pytest.mark.parametrize("approved,second,total,max_edits,required", CASES)
def test_complete_frontier_matches_independent_fraction_and_call_allocation_oracle(
    approved, second, total, max_edits, required
):
    source = model(approved=approved, second=second, total=total)
    needs = requirements(source) if required else None
    result = plan(
        source,
        discover_ceilings=options(source),
        required_workflows=needs,
        max_edits=max_edits,
        max_evaluations=4096,
        max_candidates=1000,
    )
    if not result["baseline"]["breaches"]:
        assert result["candidates"] == []
        assert result["discovery"]["status"] == "not_needed_baseline_clean"
        return
    expected = reference(source, max_edits=max_edits, minimum=Fraction(1) if required else None)
    assert {signature(c) for c in result["candidates"]} == expected
    assert result["discovery"]["frontier_complete_within_domain"]
    assert result["discovery"]["remaining_points"] == 0
    assert result["search"]["combinations_examined"] <= result["discovery"]["domain_points"]
    for candidate in result["candidates"]:
        changed = Mandate.parse(candidate["manifest"])
        assert changed.limits == source.limits
        assert not analyse(changed).breaches
        if needs is not None:
            assert all(a["failure"] is None for a in needs.assess(changed, source.limits.depth))


@pytest.mark.parametrize("budget", [1, 2, 3, 4, 5, 8, 12, 20])
def test_evaluation_limits_never_certify_an_incomplete_frontier(budget):
    source = model(second=True, total="3")
    result = plan(
        source, discover_ceilings=options(source), max_evaluations=budget, max_candidates=1000
    )
    discovery = result["discovery"]
    assert len(discovery["probes"]) == result["search"]["combinations_examined"] <= budget
    assert result["search"]["candidates_analyzed"] <= budget
    actual = {signature(c) for c in result["candidates"]}
    expected = reference(source)
    if discovery["frontier_complete_within_domain"]:
        assert actual == expected and discovery["remaining_points"] == 0
    else:
        assert discovery["status"] == "evaluation_limit" and discovery["remaining_points"] > 0
    for candidate in result["candidates"]:
        assert not analyse(Mandate.parse(candidate["manifest"])).breaches


def test_display_limits_do_not_change_domain_completion_or_non_dominated_count():
    source = model(second=True, total="3")
    full = plan(source, discover_ceilings=options(source), max_candidates=1000)
    short = plan(source, discover_ceilings=options(source), max_candidates=1)
    assert len(full["candidates"]) > 1 and short["candidates"] == full["candidates"][:1]
    assert short["discovery"]["frontier_complete_within_domain"]
    assert not short["frontier"]["display_complete"]
    assert short["frontier"]["non_dominated"] == len(full["candidates"])


@pytest.mark.parametrize("shape,selected", list(product(range(6), [("pay",), ("pay", "other")])))
def test_pruned_frontier_matches_full_rechecks_on_different_scope_and_producer_graphs(
    shape, selected
):
    source = model(second=True, total="5", approved=bool(shape % 2))
    tools = list(source.tools)
    if shape in (0, 1):
        tools[0] = replace(tools[0], unbounded=False)
    elif shape in (2, 3):
        tools[1] = replace(tools[1], produces="next", unbounded=bool(shape % 2))
        tools[2] = replace(tools[2], requires=("next",), scope_key="next")
    else:
        tools[1] = replace(tools[1], produces="item", unbounded=True)
    source = replace(source, tools=tuple(tools), limits=replace(source.limits, depth=4))
    actual = plan(
        source,
        discover_ceilings=tuple(f"{name}=1" for name in selected),
        max_edits=3,
        max_evaluations=4096,
        max_candidates=1000,
    )
    spending = sorted((t for t in tools if t.ceiling), key=lambda t: t.name)
    ungated = [t.name for t in tools if t.effect == "irreversible" and not t.requires_approval]
    passing = []
    domains = [
        [Decimal(0), Decimal(1), Decimal(2), Decimal(3), t.ceiling.amount]
        if t.name in selected
        else [t.ceiling.amount]
        for t in spending
    ]
    for amounts in product(*domains):
        ceilings = dict(zip((t.name for t in spending), amounts, strict=True))
        for count in range(len(ungated) + 1):
            for gates in combinations(ungated, count):
                edit_count = count + sum(ceilings[t.name] != t.ceiling.amount for t in spending)
                if not 0 < edit_count <= 3:
                    continue
                changed = replace(
                    source,
                    tools=tuple(
                        replace(
                            t,
                            ceiling=replace(t.ceiling, amount=ceilings[t.name])
                            if t.ceiling
                            else None,
                            requires_approval=t.requires_approval or t.name in gates,
                        )
                        for t in source.tools
                    ),
                )
                if not analyse(changed).breaches:
                    passing.append(
                        (
                            tuple((t.name, Fraction(ceilings[t.name])) for t in spending),
                            frozenset(gates),
                            edit_count,
                        )
                    )
    expected = {
        (caps, gates)
        for caps, gates, cost in passing
        if not any(
            other_cost <= cost
            and other_gates <= gates
            and all(a[1] >= b[1] for a, b in zip(other_caps, caps, strict=True))
            and (other_cost < cost or other_gates < gates or other_caps != caps)
            for other_caps, other_gates, other_cost in passing
        )
    }
    assert actual["discovery"]["frontier_complete_within_domain"]
    if actual["baseline"]["breaches"]:
        assert {signature(c) for c in actual["candidates"]} == expected
    else:
        assert not actual["candidates"]


def test_exact_domains_keep_unchanged_off_grid_endpoint_and_ignore_decimal_context():
    source = model(ceiling="0.35", total="0.4")
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        saved = dict(context.flags)
        (axis,) = _axes(source, ("pay=0.10",))
        values = [axis.value(i).amount for i in range(axis.last + 1)]
        result = plan(source, discover_ceilings=("pay=0.10",))
        assert dict(context.flags) == saved and context.prec == 1
    assert values == list(map(Decimal, ["0", "0.1", "0.2", "0.3", "0.35"]))
    assert result["candidates"][0]["edits"][0]["after"]["amount"] == "0.2"


def test_step_above_ceiling_and_zero_ceiling_have_finite_domains():
    source = model(ceiling="0", approved=False)
    (axis,) = _axes(source, ("pay=100",))
    assert axis.last == 0 and axis.value(0).amount == 0
    result = plan(source, discover_ceilings=("pay=100",))
    assert result["discovery"]["domain_points"] == 2
    assert result["candidates"][0]["edits"] == [{"tool": "pay", "kind": "require_approval"}]
    assert result["search"]["exhaustive_point_enumeration"]


def test_approval_and_ceiling_changes_are_joint_and_required_approval_is_not_invented():
    source = model(approved=False)
    result = plan(
        source, discover_ceilings=options(source), required_workflows=requirements(source)
    )
    assert {e["kind"] for e in result["candidates"][0]["edits"]} == {
        "require_approval",
        "tighten_ceiling",
    }
    rejected = plan(
        source,
        discover_ceilings=options(source),
        required_workflows=requirements(source, approved=False),
    )
    assert not rejected["candidates"] and rejected["discovery"]["frontier_complete_within_domain"]
    assert any(
        a["failure"]["rule"] == "workflow.approval-missing"
        for r in rejected["requirement_rejections"]
        for a in r["assessments"]
        if a["failure"] is not None
    )


def test_effect_budget_breaches_survive_zero_ceiling_and_approval_changes():
    source = model()
    source = replace(source, limits=replace(source.limits, effects={"irreversible": 0}))
    result = plan(source, discover_ceilings=options(source))
    assert not result["candidates"] and result["discovery"]["frontier_complete_within_domain"]
    assert all("effect_count" in p["breach_kinds"] for p in result["discovery"]["probes"])


def test_clean_and_structurally_invalid_baselines_do_not_claim_a_computed_frontier():
    clean = plan(model(total="100"), discover_ceilings=("pay=1",))
    assert clean["discovery"]["status"] == "not_needed_baseline_clean"
    assert clean["frontier"]["status"] == "not_computed"
    source = model()
    dead = replace(source, tools=tuple(t for t in source.tools if t.name != "seed"))
    result = plan(dead, discover_ceilings=("pay=1",))
    assert result["status"] == "input_requires_review"
    assert result["discovery"]["status"] == "not_run"


@pytest.mark.parametrize(
    "option,message",
    [
        (None, "TOOL=STEP"),
        (True, "TOOL=STEP"),
        ("pay", "TOOL=STEP"),
        ("=1", "TOOL=STEP"),
        ("pay=", "TOOL=STEP"),
        ("seed=1", "spending tool"),
        ("missing=1", "spending tool"),
        ("pay=0", "positive"),
        ("pay=-1", "negative"),
        ("pay=NaN", "finite"),
        ("pay=Infinity", "finite"),
        ("pay=bad", "number"),
        ("pay=1e-101", "exponent"),
        ("pay=1e101", "exponent"),
        ("pay=" + "1" * 101, "100 digits"),
        ("pay=" + "1" * 129, "128 characters"),
    ],
)
def test_invalid_domains_fail_before_any_search(option, message, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("malformed domain reached the analyzer")

    monkeypatch.setattr("agentmandate._ceiling_discovery.analyse", unexpected)
    with pytest.raises(ValueError, match=message):
        plan(model(), discover_ceilings=(option,))


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"discover_ceilings": None}, "TOOL=STEP"),
        ({"ceiling_options": ("pay=1",)}, "combined"),
        ({"ceiling_grids": ("pay=0:1:1",)}, "combined"),
        ({"pareto": 1}, "boolean"),
        ({"max_edits": 0}, "positive whole"),
        ({"max_edits": 9}, "8 edits"),
        ({"max_evaluations": True}, "positive whole"),
        ({"max_candidates": 0}, "positive whole"),
        ({"keep_tools": ("unknown",)}, "declared tools"),
        ({"discover_ceilings": ("pay=1", "pay=2")}, "distinct"),
        ({"discover_ceilings": ("pay=1",) * 9}, "8 tools"),
    ],
)
def test_bad_composition_and_limits_are_usage_errors(kwargs, message):
    with pytest.raises(ValueError, match=message):
        plan(model(), **{"discover_ceilings": ("pay=1",), **kwargs})


def test_invalid_required_path_and_unreachable_kept_tool_fail_closed():
    source = model()
    with pytest.raises(ValueError, match="invalid in the baseline"):
        plan(
            source, discover_ceilings=options(source), required_workflows=requirements(source, "10")
        )
    dead = replace(source, tools=tuple(t for t in source.tools if t.name != "seed"))
    with pytest.raises(ValueError, match="reachable in the baseline"):
        plan(dead, discover_ceilings=("pay=1",), keep_tools=("pay",))


def test_tool_names_use_last_equals_and_selected_ceiling_range_is_bounded():
    source = model()
    renamed = replace(
        source,
        tools=tuple(replace(t, name="pay=fee") if t.name == "pay" else t for t in source.tools),
    )
    result = plan(renamed, discover_ceilings=("pay=fee=1",))
    assert result["discovery"]["domains"][0]["tool"] == "pay=fee"
    with pytest.raises(ValueError, match="exponent"):
        plan(model(ceiling="1e101"), discover_ceilings=("pay=1",))


def test_future_amount_dependent_reachability_cannot_silently_use_the_pruning_argument(monkeypatch):
    from agentmandate import _ceiling_discovery

    original = _ceiling_discovery.analyse
    calls = []

    def changed(source, depth=None):
        calls.append(None)
        authority = original(source, depth=depth)
        return replace(authority, reachable_tools=frozenset()) if len(calls) > 1 else authority

    monkeypatch.setattr(_ceiling_discovery, "analyse", changed)
    with pytest.raises(ValueError, match="ceiling-independent"):
        plan(model(), discover_ceilings=("pay=1",))


def command():
    return [
        "remediate",
        str(EXAMPLE),
        "--discover-ceiling",
        "issue_refund=0.01",
        "--required-workflows",
        str(REQUIRED),
    ]


@pytest.mark.parametrize("machine", [False, True])
def test_cli_preserves_original_findings_and_reports_three_distinct_limits(machine, capsys):
    assert main(command() + (["--json"] if machine else [])) == 1
    output = capsys.readouterr()
    assert not output.err
    if machine:
        report = json.loads(output.out)
        assert report["schema"] == "agentmandate.remediation/v6"
        assert (
            report["input"]["manifest_sha256"] == hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
        )
        assert report["discovery"]["frontier_complete_within_domain"]
        assert not report["search"]["exhaustive_point_enumeration"]
        assert report["candidates"][0]["authority"]["truncated"]
    else:
        assert "DISCOVERY complete frontier_complete_within_domain=True" in output.out
        assert "500 -> 125 GBP" in output.out and "truncated=True" in output.out


@pytest.mark.parametrize(
    "flags",
    [
        ["--ceiling", "issue_refund=100"],
        ["--ceiling-grid", "issue_refund=0:100:1"],
        ["--discover-ceiling", "issue_refund=NaN"],
        ["--max-edits", "9"],
    ],
)
def test_cli_bad_discovery_requests_return_2_without_partial_output(flags, capsys):
    assert main(command() + flags + ["--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")


def test_initial_v5_cases_replay_full_json_and_cli_exits(capsys):
    cases = json.loads((ROOT / "tests/fixtures/remediation-discovery-v6.json").read_text())
    for case in cases:
        flags = ["remediate", str(ROOT / case["manifest"])]
        for option in case["options"]:
            flags += ["--discover-ceiling", option]
        if case["requirements"] is not None:
            flags += ["--required-workflows", str(ROOT / case["requirements"])]
        for name, value in case["kwargs"].items():
            flags += ["--" + name.replace("_", "-"), str(value)]
        assert main(flags + ["--json"]) == case["exit"]
        assert json.loads(capsys.readouterr().out) == case["result"]
