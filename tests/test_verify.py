from decimal import Decimal

import pytest

from agentmandate import loads, replay, replay_file
from agentmandate.verify import Observation, parse_observations

MANDATE = loads(
    """
    agent: dispute
    limits:
      total: { amount: 500, currency: GBP }
    tools:
      - name: open_case
        effect: read
        produces: case
      - name: issue_refund
        effect: irreversible
        requires: [case]
        value_arg: amount
        scope_key: case
        ceiling: { amount: 500, currency: GBP }
        requires_approval: true
    """
)


def kinds(lines):
    return [v.kind for v in replay(MANDATE, parse_observations(lines)).violations]


def test_a_conformant_run_reports_no_violation():
    lines = (
        '{"tool": "open_case", "scope": "c1", "principal": "caller"}\n'
        '{"tool": "issue_refund", "scope": "c1", "value": "500", '
        '"currency": "GBP", "approved": true, "principal": "caller"}\n'
    )
    conformance = replay(MANDATE, parse_observations(lines))
    assert conformance.conformant is True
    assert conformance.observed == 2
    assert "within the declared mandate" in conformance.render()


def test_an_undeclared_tool_is_a_violation():
    assert kinds('{"tool": "export_everything"}') == ["undeclared_tool"]


def test_a_missing_approval_is_a_violation():
    assert "missing_approval" in kinds(
        '{"tool": "issue_refund", "scope": "c1", "value": "10", "currency": "GBP",'
        ' "principal": "caller"}'
    )


def test_a_cumulative_ceiling_breach_is_detected_across_calls():
    lines = (
        '{"tool": "issue_refund", "scope": "c1", "value": "300", '
        '"currency": "GBP", "approved": true, "principal": "caller"}\n'
        '{"tool": "issue_refund", "scope": "c1", "value": "300", '
        '"currency": "GBP", "approved": true, "principal": "caller"}\n'
    )
    assert "ceiling_exceeded" in kinds(lines)


def test_the_same_value_split_across_scopes_stays_under_each_ceiling():
    lines = (
        '{"tool": "issue_refund", "scope": "c1", "value": "300", '
        '"currency": "GBP", "approved": true, "principal": "caller"}\n'
        '{"tool": "issue_refund", "scope": "c2", "value": "300", '
        '"currency": "GBP", "approved": true, "principal": "caller"}\n'
    )
    found = kinds(lines)
    assert "ceiling_exceeded" not in found
    # It still breaks the run limit, which is exactly the compound shape.
    assert "total_exceeded" in found


def test_a_wrong_principal_is_a_violation():
    assert "wrong_principal" in kinds(
        '{"tool": "open_case", "scope": "c1", "principal": "service"}'
    )


def test_a_matching_principal_is_accepted():
    assert kinds('{"tool": "open_case", "scope": "c1", "principal": "caller"}') == []


def test_blank_and_comment_lines_are_skipped():
    observations = parse_observations('\n# a note\n{"tool": "open_case"}\n\n')
    assert len(observations) == 1
    assert observations[0].line == 3


def test_an_empty_trace_cannot_establish_conformance():
    conformance = replay(MANDATE, parse_observations("\n# no calls\n"))
    assert conformance.conformant is False
    assert [violation.kind for violation in conformance.violations] == [
        "no_observations"
    ]


def test_invalid_json_names_the_line():
    with pytest.raises(ValueError, match="line 1"):
        parse_observations("{not json}")


def test_a_non_object_line_is_rejected():
    with pytest.raises(ValueError, match="expected a JSON object"):
        parse_observations("[1, 2]")


def test_an_unparseable_value_is_rejected():
    with pytest.raises(ValueError, match="line 1: value is not a number"):
        Observation.parse({"tool": "t", "value": "abc"}, 1)


def test_a_numeric_value_is_read_as_decimal():
    assert Observation.parse({"tool": "t", "value": 12.5}, 1).value == Decimal("12.5")


def test_replay_file_reads_from_disk(tmp_path):
    path = tmp_path / "calls.jsonl"
    path.write_text('{"tool": "export_all"}\n', encoding="utf-8")
    assert replay_file(MANDATE, path).conformant is False


def test_conformance_serialises():
    payload = replay(MANDATE, parse_observations('{"tool": "nope"}')).as_dict()
    assert payload["conformant"] is False
    assert payload["violations"][0]["kind"] == "undeclared_tool"
    assert payload["observed"] == 1


def test_a_violation_renders_the_tool_and_line():
    conformance = replay(MANDATE, parse_observations('{"tool": "nope"}'))
    rendered = conformance.render()
    assert "VIOLATION" in rendered
    assert "nope" in rendered
    assert "line 1" in rendered


def test_a_currency_mismatch_is_reported_rather_than_converted():
    assert "currency_mismatch" in kinds(
        '{"tool": "issue_refund", "scope": "c1", "value": "10",'
        ' "currency": "USD", "approved": true, "principal": "caller"}'
    )


def test_a_matching_currency_passes():
    assert kinds(
        '{"tool": "issue_refund", "scope": "c1", "value": "10",'
        ' "currency": "gbp", "approved": true, "principal": "caller"}'
    ) == []


def test_control_evidence_is_required_for_a_spending_call():
    found = kinds('{"tool": "issue_refund", "approved": true}')
    assert found == ["missing_principal", "missing_scope", "missing_value", "missing_currency"]


def test_principal_is_required_even_when_the_tool_only_reads():
    assert kinds('{"tool": "open_case", "scope": "c1"}') == ["missing_principal"]


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"tool": "pay", "approved": "false"}, "approved must be"),
        ({"tool": "pay", "value": "-1"}, "must not be negative"),
        ({"tool": "pay", "value": "NaN"}, "must be finite"),
        ({"tool": ""}, "tool must be"),
        ({"tool": "pay", "currency": "12"}, "three-letter"),
    ],
)
def test_malformed_observation_fields_are_rejected(payload, message):
    with pytest.raises(ValueError, match=message):
        Observation.parse(payload, 7)


def test_value_on_a_tool_without_a_declared_ceiling_is_a_violation():
    assert kinds(
        '{"tool": "open_case", "scope": "c1", "principal": "caller",'
        ' "value": "10", "currency": "GBP"}'
    ) == ["unexpected_value"]
