"""Regression checks for authored YAML, workflow units and review explanations."""

from dataclasses import replace
from decimal import Decimal

import pytest

from agentmandate import Limits, Mandate, ManifestError, Quantity, Tool, compare, loads
from agentmandate._ir import _from_mandate
from agentmandate._required_workflows import _assessment, _Workflow


def amount(unit="record"):
    return Quantity(Decimal(1), unit)


def yaml_manifest(pools):
    return "version: 3\nagent: a\nlimits:\n  quantities:\n" + pools + (
        "tools:\n  - name: t\n    effect: read\n"
    )


def test_yaml_explicit_override_is_not_an_authored_duplicate():
    mandate = loads(yaml_manifest(
        '    q: &cap {amount: "5", unit: record}\n'
        '    r:\n      <<: *cap\n      unit: token\n'
    ))
    assert mandate.limits.quantities == {
        "q": Quantity(Decimal(5), "record"), "r": Quantity(Decimal(5), "token"),
    }


def test_yaml_nested_reused_merges_preserve_override_and_sequence_precedence():
    mandate = loads(yaml_manifest(
        '    q: &cap {amount: "5", unit: record}\n'
        '    r: &adjusted {<<: *cap, unit: token}\n'
        '    s: {<<: *adjusted, amount: "7"}\n'
        '    t: {<<: [*cap, *adjusted], amount: "9"}\n'
        '    u: *adjusted\n'
    ))
    assert mandate.limits.quantities["s"] == Quantity(Decimal(7), "token")
    assert mandate.limits.quantities["t"] == Quantity(Decimal(9), "record")
    assert mandate.limits.quantities["u"] == mandate.limits.quantities["r"]


@pytest.mark.parametrize("pools", [
    '    q: &cap {amount: "5", unit: record}\n'
    '    r: {<<: *cap, unit: token, unit: byte}\n',
    '    q: &cap {amount: "5", unit: record, unit: token}\n'
    '    r: {<<: *cap}\n',
    '    q: &cap {amount: "5", unit: record}\n'
    '    r: {<<: *cap, <<: *cap}\n',
])
def test_yaml_merges_do_not_hide_authored_duplicates(pools):
    with pytest.raises(ManifestError, match="duplicate field"):
        loads(yaml_manifest(pools))


def test_yaml_unhashable_keys_remain_a_typed_format_error():
    with pytest.raises(ManifestError, match="invalid YAML"):
        loads(yaml_manifest('    ? [bad, key]\n    : {amount: "1", unit: record}\n'))


def path(*tools):
    return _Workflow.parse({"name": "unit-check", "steps": [
        {"tool": tool, "principal": "caller", "approved": False}
        for tool in tools
    ]})


@pytest.mark.parametrize("calls", [1, 6])
def test_direct_workflow_refuses_fixed_budget_unit_mismatch_before_accumulating(calls):
    mandate = Mandate("a", (Tool("charge", "read", fixed_charges={"q": amount("u")}),),
                      limits=Limits(quantities={"q": Quantity(Decimal(5), "v")}))
    row = _assessment(mandate, path(*(["charge"] * calls)), 6)
    assert row["status"] == "not_conformant_within_manifest_model"
    assert row["failure"]["step"] == 1
    assert row["failure"]["rule"] == "workflow.unit-mismatch"


@pytest.mark.parametrize("same_pool", [False, True])
def test_workflow_fixed_pools_require_consistent_units_even_without_a_budget(same_pool):
    mandate = Mandate("a", (
        Tool("a", "read", fixed_charges={"q": amount("u")}),
        Tool("b", "read", fixed_charges={"q" if same_pool else "r": amount("v")}),
    ))
    row = _assessment(mandate, path("a", "b"), 2)
    if same_pool:
        assert row["failure"]["rule"] == "workflow.unit-mismatch"
        assert row["failure"]["step"] == 2
    else:
        assert row["failure"] is None


@pytest.mark.parametrize("fixed_first", [False, True])
def test_workflow_fixed_and_variable_units_cannot_mix_in_either_order(fixed_first):
    mandate = Mandate("a", (
        Tool("seed", "read", produces="scope"),
        Tool("fixed", "read", fixed_charges={"q": amount("u")}),
        Tool("variable", "read", requires=("scope",), scope_key="scope", value_arg="amount",
             quantity="q", ceiling=amount("v")),
    ))
    raw = [{"tool": "seed", "principal": "caller", "approved": False}]
    fixed = {"tool": "fixed", "principal": "caller", "approved": False}
    variable = {"tool": "variable", "principal": "caller", "approved": False,
                "binding": 0, "value": "1", "quantity": "q", "unit": "v"}
    raw.extend([fixed, variable] if fixed_first else [variable, fixed])
    row = _assessment(mandate, _Workflow.parse({"name": "mixed", "steps": raw}), 3)
    assert row["failure"]["step"] == 3
    assert row["failure"]["rule"] == "workflow.unit-mismatch"


@pytest.mark.parametrize("change,reason", [
    ("raise", "increased"), ("lower", "decreased"), ("remove", "retained tool"),
    ("unit", "unit changed"), ("add", "added"), ("remove-tool", "tool removed"),
    ("add-tool", "added"),
])
def test_diff_explanation_describes_the_actual_charge_change(change, reason):
    tool = Tool("t", "read", fixed_charges={"q": Quantity(Decimal(2), "u")})
    other = Tool("other", "read")
    before = Mandate("a", (tool, other))
    changed = {"raise": {"q": Quantity(Decimal(3), "u")}, "lower": {"q": amount("u")},
               "remove": {}, "unit": {"q": amount("v")}, "add": {"q": amount("u")}}
    if change == "remove-tool":
        after = replace(before, tools=(other,))
    elif change == "add-tool":
        before = replace(before, tools=(other,))
        after = Mandate("a", (tool, other))
    else:
        if change == "add":
            before = replace(before, tools=(replace(tool, fixed_charges={}), other))
        after = replace(before, tools=(replace(tool, fixed_charges=changed[change]), other))
    row = next(c for c in compare(before, after).changes if c.kind == "fixed charge")
    assert reason in row.detail
    assert ("retained tool" in row.detail) == (change == "remove")


def test_ir_default_locations_name_their_actual_manifest_schema():
    graph = _from_mandate(Mandate("a", (Tool("t", "read"),)))
    source = next(s for s in graph.sources if s.kind == "manifest-schema")
    locations = [e.location for f in graph.facts for e in f.evidence if e.source == source.id]
    assert locations
    assert all(loc.startswith(f"manifest:v{source.format_version}#/defaults/") for loc in locations)
    assert f"manifest:v{source.format_version}#/defaults/tool.fixed_charges" in locations


def test_tool_hashing_does_not_claim_immutable_charge_mappings():
    with pytest.raises(TypeError, match="unhashable"):
        hash(Tool("t", "read"))
