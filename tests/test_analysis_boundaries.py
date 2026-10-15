import builtins
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from agentmandate import Mandate, ManifestError, Quantity, analyse, compare, loads
from agentmandate._conditions import (
    ConditionFormatError,
    ToolCondition,
    _profile_digest,
    _validate_condition_profile,
)
from agentmandate._ir import AuthorityIR, Entity, IRFormatError, _entity_id, _from_mandate
from agentmandate.cli import main
from agentmandate.obligations import Obligation, ObligationSet, derive, reconcile

ROOT = Path(__file__).resolve().parents[1]


def monetary(units, total=None):
    data = {
        "agent": "money",
        "limits": {"depth": 3, "quantities": {}},
        "tools": [
            {"name": "seed", "effect": "read", "produces": "case"},
            *[
                {
                    "quantity": "value",
                    "name": f"pay-{index}",
                    "effect": "write",
                    "requires": ["case"],
                    "scope_key": "case",
                    "value_arg": "amount",
                    "ceiling": {"amount": "40", "unit": unit},
                }
                for index, unit in enumerate(units)
            ],
        ],
    }
    if total is not None:
        data["limits"]["quantities"]["value"] = {"amount": "50", "unit": total}
    return Mandate.parse(data)


@pytest.mark.parametrize(
    "units,total",
    [
        (["GBP", "USD"], "GBP"),
        (["GBP", "USD"], None),
        (["USD"], "GBP"),
    ],
)
@pytest.mark.parametrize("consumer", ["reach", "diff", "obligations"])
def test_scalar_analysis_refuses_unit_mixing_for_every_public_consumer(
    units,
    total,
    consumer,
):
    mandate = monetary(units, total)
    with pytest.raises(ValueError, match="incompatible units"):
        if consumer == "reach":
            analyse(mandate)
        elif consumer == "diff":
            compare(mandate, mandate)
        else:
            derive(mandate)


@pytest.mark.parametrize("unit", ["GBP", "USD"])
def test_single_unit_analysis_keeps_real_breaches(unit):
    authority = analyse(monetary([unit, unit], unit))
    assert str(authority.max_quantities.get("value").amount) == "80"
    assert authority.max_quantities.get("value").unit == unit
    assert [b.kind for b in authority.breaches] == ["quantity_budget"]


def test_programmatic_unit_case_is_meaningful_and_never_normalized():
    parsed = monetary(["GBP", "GBP"], "GBP")
    constructed = replace(
        parsed,
        tools=(
            parsed.tools[0],
            replace(parsed.tools[1], ceiling=Quantity(Decimal(40), "gbp")),
            parsed.tools[2],
        ),
    )
    assert constructed != parsed
    with pytest.raises(ValueError, match="incompatible units"):
        analyse(constructed)


@pytest.mark.parametrize("command", ["reach", "diff", "obligations", "remediate"])
def test_mixed_unit_cli_fails_without_partial_results(command, tmp_path, capsys):
    # Explicit payload keeps this regression independent of internal manifest serialization.
    path = tmp_path / "mixed.json"
    path.write_text(
        json.dumps(
            {
                "agent": "mixed",
                "limits": {"quantities": {"value": {"amount": 50, "unit": "GBP"}}},
                "tools": [
                    {"name": "seed", "effect": "read", "produces": "case"},
                    {
                        "quantity": "value",
                        "name": "pay",
                        "effect": "write",
                        "requires": ["case"],
                        "scope_key": "case",
                        "value_arg": "amount",
                        "ceiling": {"amount": 40, "unit": "USD"},
                    },
                ],
            }
        )
    )
    argv = [command, str(path)] + ([str(path)] if command == "diff" else []) + ["--json"]
    assert main(argv) == 2
    output = capsys.readouterr()
    assert not output.out and "incompatible units" in output.err


@pytest.mark.parametrize(
    "requires,expected",
    [
        (["case"], ["write on case"]),
        ([], ["write on ticket"]),
    ],
)
def test_diff_effect_claims_match_reachability_scopes(requires, expected):
    before = Mandate.parse(
        {
            "agent": "scope",
            "tools": [
                {"name": "seed", "effect": "read", "produces": "case"},
            ],
        }
    )
    after = Mandate.parse(
        {
            "agent": "scope",
            "tools": [
                {"name": "seed", "effect": "read", "produces": "case"},
                {"name": "post", "effect": "write", "requires": requires, "produces": "ticket"},
            ],
        }
    )
    delta = compare(before, after)
    gained = [c.detail.removeprefix("gained ") for c in delta.changes if c.kind == "effect"]
    assert gained == expected
    assert {tuple(effect.split(" on ")) for effect in gained} <= analyse(after).effects


def test_review_cannot_cross_agents_even_when_identifiers_and_cases_match():
    current = ObligationSet("agent-a", (Obligation("irreversible", "pay", "current"),))
    reviewed = ObligationSet(
        "agent-b", (Obligation("irreversible", "pay", "reviewed", "deny", ("synthetic-probe",)),)
    )
    with pytest.raises(ValueError, match="different agents"):
        reconcile(current, reviewed)
    assert current.unreviewed == ("irreversible:pay",)
    assert reconcile(current, replace(reviewed, agent="agent-a")).unreviewed == ()


def test_cli_refuses_cross_agent_obligation_review(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "agent": "agent-a",
                "tools": [
                    {"name": "pay", "effect": "irreversible"},
                ],
            }
        )
    )
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            ObligationSet(
                "agent-b",
                (Obligation("irreversible", "pay", "reviewed", "deny", ("synthetic-probe",)),),
            ).to_dict()
        )
    )
    assert main(["obligations", str(manifest), "--reviewed", str(review), "--suite"]) == 2
    output = capsys.readouterr()
    assert not output.out and "different agents" in output.err


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_ir_rejects_non_finite_json_including_overflowed_numbers(literal, tmp_path, capsys):
    graph = _from_mandate(Mandate.parse({"agent": "a", "tools": [{"name": "t", "effect": "read"}]}))
    raw = graph.as_dict()
    raw["facts"][0]["value"] = {"nested": ["REPLACE_WITH_NONFINITE"]}
    text = json.dumps(raw).replace('"REPLACE_WITH_NONFINITE"', literal)
    with pytest.raises(IRFormatError):
        AuthorityIR.from_json(text)
    path = tmp_path / "nonfinite.json"
    path.write_text(text)
    assert main(["ir", "validate", str(path)]) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        {"nested": float("-inf")},
        {1, 2},
        {1: "a"},
        {"nested": [{None: "a"}]},
        {True: "a", "true": "b"},
        {"nested": (1, 2)},
    ],
)
def test_programmatic_ir_cannot_validate_or_emit_noncanonical_values(value):
    graph = _from_mandate(Mandate.parse({"agent": "a", "tools": [{"name": "t", "effect": "read"}]}))
    graph = replace(graph, facts=(replace(graph.facts[0], value=value), *graph.facts[1:]))
    with pytest.raises(IRFormatError, match="not canonical JSON"):
        graph.validate()
    with pytest.raises((ValueError, TypeError)):
        graph.to_json()


def test_ir_preserves_finite_generic_json_fact_values():
    graph = _from_mandate(Mandate.parse({"agent": "a", "tools": [{"name": "t", "effect": "read"}]}))
    graph = replace(
        graph,
        facts=(replace(graph.facts[0], value={"nested": [0.5, None, True]}), *graph.facts[1:]),
    )
    graph.validate()
    assert AuthorityIR.from_json(graph.to_json()) == graph


def test_empty_obligation_suite_is_a_usage_error_not_a_finding(tmp_path, capsys):
    path = tmp_path / "readonly.json"
    path.write_text(json.dumps({"agent": "a", "tools": [{"name": "t", "effect": "read"}]}))
    assert main(["obligations", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["obligations"] == []
    assert main(["obligations", str(path), "--suite"]) == 2
    output = capsys.readouterr()
    assert not output.out and "no obligations" in output.err


def test_obligation_suite_separates_missing_review_from_duplicate_probes(tmp_path, capsys):
    path = tmp_path / "pay.json"
    path.write_text(
        json.dumps(
            {
                "agent": "a",
                "tools": [
                    {"name": "seed", "effect": "read", "produces": "case"},
                    {
                        "quantity": "value",
                        "name": "pay",
                        "effect": "irreversible",
                        "requires": ["case"],
                        "scope_key": "case",
                        "value_arg": "amount",
                        "ceiling": {"amount": 40, "unit": "GBP"},
                    },
                ],
            }
        )
    )
    assert main(["obligations", str(path), "--suite"]) == 1
    assert "not fully reviewed" in capsys.readouterr().err
    obligations = derive(loads(path.read_text()))
    assert len(obligations.obligations) >= 2
    reviewed = replace(
        obligations,
        obligations=tuple(
            replace(item, decision="paid", cases=("probe-x",)) for item in obligations.obligations
        ),
    )
    review = tmp_path / "review.json"
    review.write_text(json.dumps(reviewed.to_dict()))
    assert main(["obligations", str(path), "--reviewed", str(review), "--suite"]) == 2
    output = capsys.readouterr()
    assert not output.out and "the same probe is reviewed twice: probe-x" in output.err


@pytest.mark.parametrize("literal", ["0123", "1:20", "1_000", '!!int "7"'])
@pytest.mark.parametrize("leading", ['{"agent"', '{ \n "agent"'])
def test_malformed_json_numbers_never_fall_back_to_yaml(literal, leading, tmp_path, capsys):
    text = (
        leading + ':"a","tools":[{"name":"t","effect":"read"}],"limits":{"depth":' + literal + "}}"
    )
    with pytest.raises(ManifestError, match="invalid JSON"):
        loads(text)
    path = tmp_path / "malformed.json"
    path.write_text(text)
    assert main(["reach", str(path), "--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and "invalid JSON" in output.err


def test_yaml_flow_mappings_and_json_have_identical_semantics():
    flow = "{agent: a, tools: [{name: t, effect: read}]}"
    strict_json = '{"agent": "a", "tools": [{"name": "t", "effect": "read"}], "version": 2}'
    assert loads(flow) == loads(strict_json)


def test_bare_json_still_works_and_flow_yaml_reports_the_optional_dependency(monkeypatch):
    original = builtins.__import__

    def without_yaml(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("synthetic bare install")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_yaml)
    assert (
        loads('{"agent": "a", "tools": [{"name": "t", "effect": "read"}], "version": 2}').agent
        == "a"
    )
    with pytest.raises(ManifestError, match="Reading YAML flow mappings needs PyYAML"):
        loads("{agent: a, tools: [{name: t, effect: read}]}")
    with pytest.raises(ManifestError, match="reading a YAML manifest needs PyYAML"):
        loads("agent: a\ntools: [{name: t, effect: read}]")


def test_unknown_condition_entity_kind_is_rejected_without_keyerror():
    graph = ToolCondition.from_json(
        (ROOT / "tests/fixtures/condition-statement-v1.json").read_text()
    )
    projected = graph.to_ir()
    entity = Entity(_entity_id("extension", "unexpected"), "extension", "unexpected")
    entities = (*projected.entities, entity)
    source = replace(
        projected.sources[0],
        semantic_sha256=_profile_digest(
            entities,
            projected.facts,
            projected.edges,
        ),
    )
    with pytest.raises(ConditionFormatError, match="unsupported entities"):
        _validate_condition_profile(replace(projected, sources=(source,), entities=entities))
