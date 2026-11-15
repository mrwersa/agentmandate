"""Fixed costs remain visible on every call and independent in every pool."""

import copy
import hashlib
import json
from collections import deque
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from itertools import product
from pathlib import Path

import pytest

from agentmandate import Mandate, ManifestError, Quantity, Tool, analyse, compare, load
from agentmandate._ir import (
    AuthorityIR,
    IRFormatError,
    _analyse_ir,
    _from_mandate,
    _to_mandate,
)
from agentmandate._policy_export import stateful_losses
from agentmandate._remediation import _manifest, plan
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main
from agentmandate.lint import check
from agentmandate.obligations import derive, to_decision_suite
from agentmandate.scenarios import Scenario, ScenarioStep
from agentmandate.verify import Observation, parse_observations, replay

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/fixed-call-charges"


def quantity(value, unit="request"):
    return Quantity(Decimal(str(value)), unit)


def flat(charges=None, limits=None):
    return Mandate("metered", (Tool("read", "read", fixed_charges=charges or {
        "requests": quantity(1),
    }),), limits=load(EXAMPLE / "manifest.json").limits if limits is None else limits)


def test_one_call_can_charge_three_independent_pools_after_headroom_is_exhausted():
    mandate = load(EXAMPLE / "manifest.json")
    source = copy.deepcopy(mandate)
    result = analyse(mandate)
    assert mandate == source
    assert {name: q.amount for name, q in result.max_quantities.items()} == {
        "exported_records": 8, "requests": 3, "compute": 6,
    }
    assert {b.subject for b in result.breaches} == {"exported_records", "requests", "compute"}
    request = next(b for b in result.breaches if b.subject == "requests")
    assert [s.spent for s in request.path[1:]] == [4, 0, 0]
    assert all(s.fixed_charges == mandate.tools[1].fixed_charges for s in request.path[1:])
    assert "requests=1 request" in request.path[-1].render()
    assert result.truncated


def test_fixed_only_pure_reads_are_not_deduplicated_away():
    result = analyse(flat())
    assert result.max_quantities["requests"].amount == 4
    assert len(next(b for b in result.breaches if b.subject == "requests").path) == 3


def test_fixed_and_variable_consumption_in_one_pool_are_both_accumulated():
    source = load(EXAMPLE / "manifest.json")
    tool = replace(source.tools[1], fixed_charges={"exported_records": quantity(1, "record")})
    result = analyse(replace(source, tools=(source.tools[0], tool)))
    assert result.max_quantities["exported_records"].amount == 10
    breach = next(b for b in result.breaches if b.subject == "exported_records")
    assert len(breach.path) == 3


def test_same_unit_different_pools_do_not_merge_and_unbudgeted_costs_stay_visible():
    mandate = flat({"a": quantity(1), "b": quantity(2)})
    result = analyse(mandate, depth=3)
    assert result.max_quantities["a"].amount == 3
    assert result.max_quantities["b"].amount == 6
    assert not result.breaches


@pytest.mark.parametrize("raw", [[], None, "one", {"requests": None},
                                  {"requests": {"amount": "0", "unit": "request"}},
                                  {" requests": {"amount": "1", "unit": "request"}},
                                  {"requests": {"amount": "-1", "unit": "request"}},
                                  {"requests": {"amount": "1_0", "unit": "request"}}])
def test_malformed_fixed_charges_are_usage_errors(raw, tmp_path, capsys):
    document = {"version": 3, "agent": "a", "tools": [
        {"name": "t", "effect": "read", "fixed_charges": raw},
    ]}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(document))
    assert main(["reach", str(path), "--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and "error:" in output.err


@pytest.mark.parametrize("version", [None, 1, 2, 4, "3", True, 3.0])
def test_fixed_charges_cannot_be_silently_read_as_an_older_model(version):
    raw = {"agent": "a", "tools": [{"name": "t", "effect": "read", "fixed_charges": {}}]}
    if version is not None:
        raw["version"] = version
    with pytest.raises(ManifestError, match="version"):
        Mandate.parse(raw)


@pytest.mark.parametrize("charges", [[], {"r": "1"}, {"r": quantity(0)},
                                      {" r": quantity(1)}])
def test_public_tool_constructor_refuses_malformed_costs(charges):
    with pytest.raises(ValueError):
        Tool("read", "read", fixed_charges=charges)


def test_cost_inputs_are_owned_and_runtime_validation_catches_later_mutation():
    charges = {"r": quantity(1)}
    tool = Tool("read", "read", fixed_charges=charges)
    charges["r"] = quantity(10)
    assert tool.fixed_charges["r"].amount == 1
    tool.fixed_charges["r"] = "not a Quantity"
    with pytest.raises(ValueError, match="positive Quantity"):
        analyse(Mandate("a", (tool,)))


def test_returned_witness_costs_do_not_follow_later_manifest_mutation():
    mandate = flat()
    result = analyse(mandate)
    path = next(b.path for b in result.breaches if b.subject == "requests")
    mandate.tools[0].fixed_charges["requests"] = quantity(99)
    assert path[-1].fixed_charges["requests"].amount == 1


@pytest.mark.parametrize("text", [
    '{"version":3,"agent":"a","tools":[{"name":"t","effect":"read","fixed_charges":'
    '{"r":{"amount":"1","unit":"u"},"r":{"amount":"9","unit":"u"}}}]}',
    'version: 3\nagent: a\ntools:\n- name: t\n  effect: read\n  fixed_charges:\n'
    '    r: {amount: "1", unit: u}\n    r: {amount: "9", unit: u}\n',
])
def test_duplicate_charge_names_are_not_silently_overwritten(text):
    from agentmandate import loads

    with pytest.raises(ManifestError, match="duplicate field"):
        loads(text)


def test_removing_a_whole_tool_is_distinct_from_removing_its_accounting():
    charged = flat()
    other = Tool("other", "read")
    before = replace(charged, tools=(*charged.tools, other))
    after = replace(charged, tools=(other,))
    assert compare(before, after).direction == "narrowing"


@pytest.mark.parametrize("same_tool", [False, True])
def test_incompatible_units_fail_closed_across_fixed_and_variable_charges(same_tool):
    source = load(EXAMPLE / "manifest.json")
    pool = "exported_records" if same_tool else "requests"
    charge = quantity(1, "incompatible")
    tool = replace(source.tools[1], fixed_charges={pool: charge})
    mandate = replace(source, tools=(source.tools[0], tool))
    assert any(f.rule == "quantity.unit-mismatch" for f in check(mandate))
    with pytest.raises(ValueError, match="incompatible units"):
        analyse(mandate)
    with pytest.raises(IRFormatError, match="incompatible units"):
        _to_mandate(_from_mandate(mandate))


def test_generic_ir_validation_is_separate_from_usable_accounting(tmp_path, capsys):
    source = load(EXAMPLE / "manifest.json")
    tool = replace(source.tools[1], fixed_charges={"requests": quantity(1, "other_unit")})
    mandate = replace(source, tools=(source.tools[0], tool))
    path = tmp_path / "transport.json"
    path.write_text(_from_mandate(mandate).to_json())
    assert main(["ir", "validate", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "valid"
    assert main(["reach", "--ir", str(path), "--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and "incompatible units" in output.err


def test_ir_roundtrip_and_breach_provenance_keep_fixed_costs():
    source = load(EXAMPLE / "manifest.json")
    graph = AuthorityIR.from_json(_from_mandate(source).to_json())
    assert _to_mandate(graph) == source
    result = _analyse_ir(graph)
    assert result.authority.as_dict() == analyse(source).as_dict()
    fact = next(f for f in graph.facts if f.subject == "tool:export_records"
                and f.predicate == "fixed_charges")
    for edge in result.graph.edges:
        if edge.relation == "has_breach" and edge.target.endswith("requests"):
            assert fact.id in edge.support


@pytest.mark.parametrize("value", [None, [], {"r": None}, {" r": {"amount": "1",
    "unit": "request"}}, {"r": {"amount": "0", "unit": "request"}},
    {"r": {"amount": 1, "unit": "request"}},
    {"r": {"amount": "-1", "unit": "request"}}])
def test_ir_cannot_certify_malformed_or_nonpositive_fixed_costs(value):
    graph = _from_mandate(flat())
    graph = replace(graph, facts=tuple(
        replace(fact, value=value) if fact.predicate == "fixed_charges" else fact
        for fact in graph.facts
    ))
    with pytest.raises(IRFormatError):
        _to_mandate(graph)


@pytest.mark.parametrize("change,direction", [("raise", "widening"), ("lower", "narrowing"),
                                             ("remove", "widening"), ("reassign", "widening"),
                                             ("unit", "widening"), ("add", "widening")])
def test_cost_diff_is_explicit_even_when_the_tool_is_unreachable(change, direction):
    charge = {"r": quantity(2)}
    before = Mandate("a", (Tool("t", "read", requires=("never",), fixed_charges=charge),))
    changed = {"raise": {"r": quantity(3)}, "lower": {"r": quantity(1)},
               "remove": {}, "reassign": {"other": quantity(2)},
               "unit": {"r": quantity(2, "other")},
               "add": {**charge, "other": quantity(1)}}[change]
    after = replace(before, tools=(replace(before.tools[0], fixed_charges=changed),))
    result = compare(before, after)
    assert not result.before.reachable_tools and not result.after.reachable_tools
    assert result.direction == direction
    assert any(c.kind == "fixed charge" and c.direction == direction for c in result.changes)


def test_trace_costs_are_derived_once_and_zero_variable_calls_still_cost():
    source = load(EXAMPLE / "manifest.json")
    trace = parse_observations((EXAMPLE / "trace.jsonl").read_text())
    result = replay(source, trace)
    assert {v.kind for v in result.violations} == {"quantity_exceeded"}
    assert any("'requests' consumed 3 request" in v.message for v in result.violations)
    assert any("'compute' consumed 6 compute_unit" in v.message for v in result.violations)
    assert not any("'exported_records'" in v.message for v in result.violations)
    assert replay(source, trace[:2]).conformant


def test_documented_completed_call_example_crosses_the_cli(capsys):
    assert main(["reach", str(EXAMPLE / "manifest.json"), "--json"]) == 1
    authority = json.loads(capsys.readouterr().out)
    assert authority["max_quantities"]["requests"]["amount"] == "3"
    assert main(["verify", str(EXAMPLE / "manifest.json"), "--traces",
                 str(EXAMPLE / "trace.jsonl"), "--json"]) == 1
    replayed = json.loads(capsys.readouterr().out)
    assert not replayed["conformant"]
    assert {v["kind"] for v in replayed["violations"]} == {"quantity_exceeded"}


def test_failed_reads_with_fixed_costs_do_not_claim_conformance_or_known_consumption():
    result = replay(flat(), [Observation("read", principal="caller", errored=True)])
    assert {v.kind for v in result.violations} == {"errored_effect"}


def test_required_paths_and_remediation_keep_all_fixed_costs():
    source = load(EXAMPLE / "manifest.json")
    raw = {
        "schema": "agentmandate.required-workflows/v2", "agent": source.agent,
        "manifest_sha256": hashlib.sha256((EXAMPLE / "manifest.json").read_bytes()).hexdigest(),
        "reviewer": "synthetic-reviewer", "reason": "synthetic fixed-charge path",
        "workflows": [{"name": "export", "steps": [
            {"tool": "open_batch", "principal": "caller", "approved": False},
            *[{"tool": "export_records", "principal": "caller", "approved": True,
               "binding": 0, "value": "1", "quantity": "exported_records", "unit": "record"}
              for _ in range(3)],
        ]}],
    }
    required = _Requirements.load(json.dumps(raw).encode(), source, raw["manifest_sha256"])
    assert required.assess(source, 4)[0]["failure"]["step"] == 4
    raw["workflows"][0]["steps"].pop()
    required = _Requirements.load(json.dumps(raw).encode(), source, raw["manifest_sha256"])
    assert required.assess(source, 4)[0]["failure"] is None
    for domain in ({"ceiling_grids": ("export_records=0:3:1",)},
                   {"discover_ceilings": ("export_records=1",)}):
        result = plan(source, required_workflows=required, keep_tools=source.tool_names, **domain)
        assert not result["candidates"]  # A lower value ceiling cannot eliminate request charges.
        assert result["baseline"]["max_quantities"]["requests"]["amount"] == "3"
    assert Mandate.parse(_manifest(source), source=source.source) == source


def test_scenario_roundtrip_retains_every_charge():
    source = load(EXAMPLE / "manifest.json")
    scenario = Scenario.from_breach(next(b for b in analyse(source).breaches
                                        if b.subject == "requests"))
    restored = Scenario.from_dict(scenario.to_dict())
    assert restored == scenario
    assert restored.path[-1].fixed_charges == source.tools[1].fixed_charges
    assert any(row["code"] == "tool.ceiling" for row in stateful_losses(source, "test"))
    assert any(row["code"] == "tool.fixed_charges" for row in stateful_losses(source, "test"))


@pytest.mark.parametrize("raw", [[], {"r": {"amount": "0", "unit": "request"}},
                                  {"r": {"amount": 1, "unit": "request"}}, {"r": None}])
def test_scenario_costs_refuse_malformed_payloads(raw):
    with pytest.raises(ValueError):
        ScenarioStep.from_dict({"tool": "t", "fixed_charges": raw})


@pytest.mark.parametrize("where", ["tool", "manifest"])
def test_unknown_fields_cannot_silently_discard_a_charge_declaration(where):
    raw = {"version": 3, "agent": "a", "tools": [{"name": "t", "effect": "read"}]}
    target = raw["tools"][0] if where == "tool" else raw
    target["fixed_charge"] = {"requests": {"amount": "1", "unit": "request"}}
    with pytest.raises(ManifestError, match="unknown fields"):
        Mandate.parse(raw)


def test_fixed_read_consumption_requires_reviewed_obligations():
    obligations = derive(flat())
    cost = next(o for o in obligations.obligations if o.kind == "value-bearing")
    assert "requests" in cost.reason
    reviewed = replace(obligations, obligations=(
        replace(cost, decision="allowed", cases=("probe",)),
    ))
    assert to_decision_suite(reviewed)["contract"]["critical"] == ["allowed"]


def test_fractional_fixed_costs_and_variable_sums_ignore_caller_decimal_context():
    source = load(EXAMPLE / "manifest.json")
    tool = replace(source.tools[1], fixed_charges={
        "exported_records": quantity("0." + "0" * 59 + "1", "record"),
    })
    mandate = replace(source, tools=(source.tools[0], tool))
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        actual = analyse(mandate).max_quantities["exported_records"].amount
    assert actual == Decimal("8." + "0" * 59 + "2")


def test_replay_retains_fixed_overhead_below_the_default_decimal_precision():
    source = load(EXAMPLE / "manifest.json")
    tool = replace(source.tools[1], fixed_charges={
        "exported_records": quantity("1e-60", "record"),
    })
    mandate = replace(source, tools=(source.tools[0], tool), limits=replace(
        source.limits, quantities={"exported_records": quantity(4, "record")},
    ))
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        result = replay(mandate, parse_observations((EXAMPLE / "trace.jsonl").read_text())[:2])
    assert not result.conformant
    assert result.violations[0].kind == "quantity_exceeded"


def test_fixed_charges_and_effect_counters_both_survive_each_transition():
    source = flat()
    source = replace(source, limits=replace(source.limits, effects={"read": 1}))
    result = analyse(source)
    assert result.max_quantities["requests"].amount == 4
    assert {b.kind for b in result.breaches} == {"quantity_budget", "effect_count"}


def test_reviewed_producer_refusal_before_execution_does_not_charge():
    from agentmandate.reach import _analyse_with_trace

    source = flat()
    source = replace(source, tools=(replace(source.tools[0], produces="s", unbounded=True),))
    result, _ = _analyse_with_trace(source, producer_caps={"read": 0})
    assert result.max_quantities["requests"].amount == 0
    assert not result.reachable_tools and not result.breaches


def test_reviewed_effect_narrowing_does_not_remove_declared_costs():
    import test_conditional_remediation as conditional

    from agentmandate._conditions import analyse_conditions

    source = load(conditional.EXAMPLE / "manifest.json")
    source = replace(source, tools=tuple(
        replace(t, fixed_charges={"requests": quantity(1)}) if t.name == "run_query" else t
        for t in source.tools
    ), limits=replace(source.limits, quantities={**source.limits.quantities,
                                               "requests": quantity(2)}))
    records = conditional.inputs()
    result = analyse_conditions(source, *records[:3], as_of=records[3])
    assert not result.findings
    assert result.authority.max_quantities["requests"].amount == 4
    assert any(b.subject == "requests" for b in result.authority.breaches)


def exhaustive(mandate, depth):
    """Fraction oracle: every legal integer amount, every binding, no greedy helpers."""
    names = set(mandate.limits.quantities)
    names.update(t.quantity for t in mandate.tools if t.ceiling)
    names.update(pool for t in mandate.tools for pool in t.fixed_charges)
    maxima = dict.fromkeys(names, Fraction(0))
    shortest = {}
    start = ((), (), ())
    queue = deque([(start, 0)])
    seen = {start}
    while queue:
        (held_rows, spent_rows, fixed_rows), length = queue.popleft()
        if length == depth:
            continue
        held, spent, fixed = dict(held_rows), dict(spent_rows), dict(fixed_rows)
        for tool in mandate.tools:
            if any(not held.get(scope, 0) for scope in tool.requires):
                continue
            next_held = dict(held)
            if tool.produces and (tool.unbounded or not held.get(tool.produces, 0)):
                next_held[tool.produces] = held.get(tool.produces, 0) + 1
            choices = [(None, 0)]
            if tool.ceiling:
                choices = [(key, amount)
                           for binding in range(next_held.get(tool.scope_key, 0))
                           for key in [(tool.name, tool.quantity, binding)]
                           for amount in range(int(tool.ceiling.amount) - spent.get(key, 0) + 1)]
            for key, amount in choices:
                used = dict(spent)
                if amount:
                    used[key] = used.get(key, 0) + amount
                costs = dict(fixed)
                for pool, q in tool.fixed_charges.items():
                    costs[pool] = costs.get(pool, Fraction(0)) + Fraction(q.amount)
                totals = dict(costs)
                for (_, pool, _), value in used.items():
                    totals[pool] = totals.get(pool, Fraction(0)) + value
                for pool, total in totals.items():
                    maxima[pool] = max(maxima[pool], total)
                    cap = mandate.limits.quantities.get(pool)
                    if cap and total > Fraction(cap.amount):
                        shortest.setdefault(pool, length + 1)
                successor = (tuple(sorted(next_held.items())), tuple(sorted(used.items())),
                             tuple(sorted(costs.items())))
                if successor not in seen:
                    seen.add(successor)
                    queue.append((successor, length + 1))
    return maxima, shortest


@pytest.mark.parametrize("depth,unbounded,where,ceiling,same_pool", list(product(
    range(1, 5), [False, True], ["seed", "spend", "both"], [0, 2], [False, True],
)))
def test_greedy_search_matches_every_integer_amount_and_binding(
    depth, unbounded, where, ceiling, same_pool,
):
    charges = {"requests": quantity(1, "unit"), "compute": quantity(2, "unit")}
    pool = "requests" if same_pool else "records"
    raw = {
        "version": 3, "agent": "oracle", "limits": {"depth": depth, "quantities": {
            name: {"amount": "2", "unit": "unit"} for name in ["requests", "compute", pool]
        }}, "tools": [
            {"name": "seed", "effect": "read", "produces": "s", "unbounded": unbounded},
            {"name": "spend", "effect": "write", "requires": ["s"], "scope_key": "s",
             "value_arg": "n", "quantity": pool, "ceiling": {"amount": str(ceiling),
                                                               "unit": "unit"}},
        ],
    }
    for tool in raw["tools"]:
        if where in {tool["name"], "both"}:
            tool["fixed_charges"] = {name: {"amount": str(
                q.amount if tool["name"] == "seed" else (2 if name == "requests" else 1)
            ), "unit": q.unit}
                                     for name, q in charges.items()}
    mandate = Mandate.parse(raw)
    expected, shortest = exhaustive(mandate, depth)
    actual = analyse(mandate)
    assert {name: Fraction(q.amount) for name, q in actual.max_quantities.items()} == expected
    assert {b.subject: len(b.path) for b in actual.breaches} == shortest
