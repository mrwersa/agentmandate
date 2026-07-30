"""Tests for exporting static counterexamples as scenario skeletons."""

from __future__ import annotations

import json

import pytest

from agentmandate import (
    SCENARIOS_SCHEMA,
    Scenario,
    ScenarioSet,
    ScenarioStep,
    derive_scenarios,
    load_scenarios,
    loads,
    reconcile_scenarios,
    save_scenarios,
)

BREACHING = """
agent: dispute-resolver
limits: {total: {amount: 500, currency: GBP}, depth: 8}
tools:
  - name: open_case
    effect: read
    produces: case
  - name: search_cases
    effect: read
    produces: case
    unbounded: true
  - name: issue_refund
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: {amount: 500, currency: GBP}
    requires_approval: true
"""


def derived() -> ScenarioSet:
    return derive_scenarios(loads(BREACHING))


def reviewed(scenario: Scenario) -> Scenario:
    return Scenario(
        kind=scenario.kind,
        detail=scenario.detail,
        path=scenario.path,
        environment=("two approved dispute cases exist",),
        agent_input="Refund both duplicate charges.",
        expected_control="block the second refund before issue_refund",
    )


def test_a_reachable_breach_becomes_a_structured_scenario():
    scenario = next(
        item for item in derived().scenarios if item.kind == "cumulative_value"
    )

    assert [step.tool for step in scenario.path] == [
        "open_case",
        "search_cases",
        "issue_refund",
        "issue_refund",
    ]
    assert scenario.path[-1].spent == "500"
    assert scenario.path[-1].currency == "GBP"
    assert not scenario.reviewed


def test_the_export_never_invents_application_input_or_setup():
    scenario = derived().scenarios[0]

    assert scenario.environment == ()
    assert scenario.agent_input == ""
    assert scenario.expected_control == ""
    assert "REVIEW:" in derived().render()


def test_reviewed_fields_survive_reconciliation_by_witness_id():
    current = derived()
    earlier = ScenarioSet(
        agent=current.agent,
        depth=current.depth,
        truncated=current.truncated,
        scenarios=tuple(reviewed(scenario) for scenario in current.scenarios),
    )

    result = reconcile_scenarios(current, earlier)

    assert result.unreviewed == ()
    assert result.scenarios[0].agent_input == "Refund both duplicate charges."


def test_a_new_witness_returns_unreviewed():
    current = derived()
    earlier = ScenarioSet(
        agent=current.agent,
        depth=current.depth,
        truncated=current.truncated,
        scenarios=(),
    )

    result = reconcile_scenarios(current, earlier)

    assert result.unreviewed
    assert result.scenarios == current.scenarios


def test_a_changed_limit_does_not_inherit_an_old_review():
    current = derived()
    earlier = ScenarioSet(
        agent=current.agent,
        depth=current.depth,
        truncated=current.truncated,
        scenarios=tuple(reviewed(scenario) for scenario in current.scenarios),
    )
    changed = derive_scenarios(loads(BREACHING.replace("amount: 500", "amount: 400")))

    result = reconcile_scenarios(changed, earlier)

    assert result.unreviewed
    assert all(not scenario.reviewed for scenario in result.scenarios)


def test_a_disappearing_witness_drops_its_old_review():
    earlier = derived()
    safe = loads(BREACHING.replace("    unbounded: true\n", ""))

    result = reconcile_scenarios(
        derive_scenarios(safe),
        ScenarioSet(
            agent=earlier.agent,
            depth=earlier.depth,
            truncated=earlier.truncated,
            scenarios=tuple(reviewed(scenario) for scenario in earlier.scenarios),
        ),
    )

    assert result.scenarios == ()


def test_scenarios_for_different_agents_cannot_be_reconciled():
    current = derived()
    other = ScenarioSet("other", current.depth, current.truncated, current.scenarios)

    with pytest.raises(ValueError, match="cannot reconcile"):
        reconcile_scenarios(current, other)


def test_scenario_files_round_trip(tmp_path):
    path = tmp_path / "scenarios.json"

    save_scenarios(derived(), path)
    loaded = load_scenarios(path)

    assert loaded == derived()
    assert json.loads(path.read_text())["schema"] == SCENARIOS_SCHEMA


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "root must be an object"),
        ({"schema": "other/v1"}, "unsupported scenarios schema"),
        (
            {
                "schema": SCENARIOS_SCHEMA,
                "agent": "a",
                "depth": 0,
                "truncated": False,
                "scenarios": [],
            },
            "positive integer",
        ),
        (
            {
                "schema": SCENARIOS_SCHEMA,
                "agent": "a",
                "depth": 1,
                "truncated": "no",
                "scenarios": [],
            },
            "true or false",
        ),
        (
            {
                "schema": SCENARIOS_SCHEMA,
                "agent": "a",
                "depth": 1,
                "truncated": False,
                "scenarios": {},
            },
            "must be a list",
        ),
    ],
)
def test_malformed_roots_are_rejected(payload, message):
    with pytest.raises(ValueError, match=message):
        ScenarioSet.from_dict(payload)


@pytest.mark.parametrize(
    "payload, message",
    [
        ("not-an-object", "must be an object"),
        ({"tool": ""}, "must not be blank"),
        ({"tool": "pay", "spent": "1"}, "supplied together"),
        ({"tool": "pay", "currency": "GBP"}, "supplied together"),
    ],
)
def test_malformed_steps_are_rejected(payload, message):
    with pytest.raises(ValueError, match=message):
        ScenarioStep.from_dict(payload)


def test_malformed_scenario_fields_are_rejected():
    base = {
        "kind": "breach",
        "detail": "bad",
        "path": [{"tool": "pay"}],
    }
    with pytest.raises(ValueError, match="must be an object"):
        Scenario.from_dict("not-an-object")
    with pytest.raises(ValueError, match="must be a string"):
        Scenario.from_dict({**base, "kind": 7})
    with pytest.raises(ValueError, match="non-empty list"):
        Scenario.from_dict({**base, "path": []})
    with pytest.raises(ValueError, match="non-blank strings"):
        Scenario.from_dict({**base, "environment": [""]})
    with pytest.raises(ValueError, match="must not be whitespace"):
        Scenario.from_dict({**base, "agent_input": " "})
    with pytest.raises(ValueError, match="does not match"):
        Scenario.from_dict({**base, "id": "wrong"})


def test_duplicate_scenario_ids_are_rejected():
    scenario = Scenario("breach", "bad", (ScenarioStep("pay"),))
    payload = ScenarioSet("a", 1, False, (scenario, scenario)).to_dict()

    with pytest.raises(ValueError, match="duplicate ids"):
        ScenarioSet.from_dict(payload)


def test_load_wraps_file_and_json_errors(tmp_path):
    with pytest.raises(ValueError, match="cannot load scenarios"):
        load_scenarios(tmp_path / "missing.json")
    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot load scenarios"):
        load_scenarios(malformed)


def test_render_names_empty_and_truncated_searches():
    empty = ScenarioSet("a", 2, True, ())

    assert "none within depth 2" in empty.render()

    current = derived()
    truncated = ScenarioSet(
        current.agent,
        2,
        True,
        current.scenarios,
    )
    assert "deeper paths were not analysed" in truncated.render()
