import json
from decimal import Decimal

import pytest

from agentmandate import loads, replay, replay_file
from agentmandate.verify import Observation, parse_observations

MANDATE = loads(
    """
    agent: dispute
    limits:
      quantities: {value: { amount: 500, unit: GBP }}
    tools:
      - name: open_case
        effect: read
        produces: case
      - name: issue_refund
        effect: irreversible
        requires: [case]
        value_arg: amount
        scope_key: case
        quantity: value
        ceiling: { amount: 500, unit: GBP }
        requires_approval: true
    """
)


def kinds(lines):
    return [v.kind for v in replay(MANDATE, parse_observations(lines)).violations]


def test_a_conformant_run_reports_no_violation():
    lines = (
        '{"tool": "open_case", "scope": "c1", "principal": "caller"}\n{"to'
        'ol": "issue_refund", "scope": "c1", "value": "500", "unit": "GBP'
        '", "approved": true, "principal": "caller", "quantity": "value"}'
        "\n"
    )
    conformance = replay(MANDATE, parse_observations(lines))
    assert conformance.conformant is True
    assert conformance.observed == 2
    assert "within the declared mandate" in conformance.render()


def test_an_undeclared_tool_is_a_violation():
    assert kinds('{"tool": "export_everything"}') == ["undeclared_tool"]


def test_a_missing_approval_is_a_violation():
    assert "missing_approval" in kinds(
        '{"tool": "issue_refund", "scope": "c1", "value": "10", "unit": "'
        'GBP", "principal": "caller", "quantity": "value"}'
    )


def test_a_cumulative_ceiling_breach_is_detected_across_calls():
    lines = (
        '{"tool": "issue_refund", "scope": "c1", "value": "300", "unit": '
        '"GBP", "approved": true, "principal": "caller", "quantity": "val'
        'ue"}\n{"tool": "issue_refund", "scope": "c1", "value": "300", "un'
        'it": "GBP", "approved": true, "principal": "caller", "quantity":'
        ' "value"}\n'
    )
    assert "ceiling_exceeded" in kinds(lines)


def test_the_same_value_split_across_scopes_stays_under_each_ceiling():
    lines = (
        '{"tool": "issue_refund", "scope": "c1", "value": "300", "unit": '
        '"GBP", "approved": true, "principal": "caller", "quantity": "val'
        'ue"}\n{"tool": "issue_refund", "scope": "c2", "value": "300", "un'
        'it": "GBP", "approved": true, "principal": "caller", "quantity":'
        ' "value"}\n'
    )
    found = kinds(lines)
    assert "ceiling_exceeded" not in found
    # It still breaks the run limit, which is exactly the compound shape.
    assert "quantity_exceeded" in found


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
    assert [violation.kind for violation in conformance.violations] == ["no_observations"]


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
    path.write_text('{"tool": "export_all"}', encoding="utf-8")
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


def test_a_unit_mismatch_is_reported_rather_than_converted():
    assert "unit_mismatch" in kinds(
        '{"tool": "issue_refund", "scope": "c1", "value": "10", "unit": "'
        'USD", "approved": true, "principal": "caller", "quantity": "valu'
        'e"}'
    )


def test_a_matching_unit_passes():
    assert (
        kinds(
            '{"tool": "issue_refund", "scope": "c1", "value": "10", "unit": "'
            'GBP", "approved": true, "principal": "caller", "quantity": "valu'
            'e"}'
        )
        == []
    )


def test_control_evidence_is_required_for_a_spending_call():
    found = kinds('{"tool": "issue_refund", "approved": true}')
    assert found == [
        "missing_principal",
        "missing_scope",
        "missing_value",
        "missing_unit",
        "missing_quantity",
    ]


def test_principal_is_required_even_when_the_tool_only_reads():
    assert kinds('{"tool": "open_case", "scope": "c1"}') == ["missing_principal"]


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"tool": "pay", "approved": "false"}, "approved must be"),
        ({"tool": "pay", "value": "-1"}, "must not be negative"),
        ({"tool": "pay", "value": "NaN"}, "must be finite"),
        ({"tool": ""}, "tool must be"),
        ({"tool": "pay", "unit": ""}, "non-empty"),
    ],
)
def test_malformed_observation_fields_are_rejected(payload, message):
    with pytest.raises(ValueError, match=message):
        Observation.parse(payload, 7)


def test_value_on_a_tool_without_a_declared_ceiling_is_a_violation():
    assert kinds(
        '{"tool": "open_case", "scope": "c1", "principal": "caller", "val'
        'ue": "10", "unit": "GBP", "quantity": "value"}'
    ) == ["unexpected_value", "unexpected_quantity", "unexpected_unit"]


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"quantity": "records"}, ["unexpected_quantity"]),
        ({"unit": "record"}, ["unexpected_unit"]),
        ({"quantity": "records", "unit": "record"},
         ["unexpected_quantity", "unexpected_unit"]),
    ],
)
def test_measurement_labels_on_a_non_spending_call_are_violations(fields, expected):
    assert kinds(json.dumps({"tool": "open_case", "principal": "caller", **fields})) == expected


@pytest.mark.parametrize("fields", [{"quantity": "records"}, {"unit": "record"}])
def test_verify_cli_blocks_measurement_labels_on_a_non_spending_call(tmp_path, capsys, fields):
    from agentmandate.cli import main

    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"agent":"reader","tools":[{"name":"read","effect":"read"}]}')
    trace = tmp_path / "calls.jsonl"
    trace.write_text(json.dumps({"tool": "read", "principal": "caller", **fields}) + "\n")
    assert main(["verify", str(manifest), "--traces", str(trace), "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["conformant"] is False


def test_a_blank_scope_is_rejected_rather_than_treated_as_absent():
    with pytest.raises(ValueError, match="scope must be a non-empty string"):
        parse_observations('{"tool": "open_case", "scope": "   "}')


def test_a_blank_principal_is_rejected():
    with pytest.raises(ValueError, match="principal must be a non-empty string"):
        parse_observations('{"tool": "open_case", "principal": ""}')


def test_a_value_on_a_tool_that_declares_none_is_reported():
    assert "unexpected_value" in kinds(
        '{"tool": "open_case", "scope": "c1", "principal": "caller", "value": "10"}'
    )


def test_a_unit_that_matches_the_ceiling_but_not_the_run_limit_is_reported():
    """`lint` warns about a manifest whose ceiling and run limit disagree, but
    the manifest still parses, and the run total is summed across tools. A
    call that clears its own ceiling can still make that total meaningless."""
    mandate = loads(
        """
        agent: mixed
        limits: {quantities: {value: {amount: 500, unit: GBP}}}
        tools:
          - name: seed
            effect: read
            produces: case
          - name: pay
            effect: irreversible
            requires: [case]
            value_arg: amount
            scope_key: case
            quantity: value
            ceiling: {amount: 100, unit: USD}
            requires_approval: true
        """
    )
    with pytest.raises(ValueError, match="incompatible units"):
        replay(
            mandate,
            parse_observations(
                '{"tool":"pay","scope":"c1","principal":"caller","value":"10",'
                '"unit":"USD","quantity":"value","approved":true}'
            ),
        )


def test_a_bad_errored_flag_is_rejected():
    with pytest.raises(ValueError, match="errored must be"):
        Observation.parse({"tool": "t", "errored": "yes"}, 1)


class TestErroredEffectsAreIncompleteEvidence:
    """An OpenTelemetry error status means the operation ended with an error.
    It does not establish that an irreversible effect failed to commit, and a
    timeout is exactly the case where the write may already have landed."""

    MANDATE = loads(
        """
        agent: a
        limits: {quantities: {value: {amount: 500, unit: GBP}}}
        tools:
          - name: look
            effect: read
            produces: case
          - name: note
            effect: write
            requires: [case]
          - name: pay
            effect: irreversible
            requires: [case]
            value_arg: amount
            scope_key: case
            quantity: value
            ceiling: {amount: 500, unit: GBP}
            requires_approval: true
        """
    )

    def test_an_errored_irreversible_call_is_a_violation(self):
        conformance = replay(
            self.MANDATE,
            [
                Observation(tool="look", principal="caller", line=1),
                Observation(
                    tool="pay",
                    scope="c1",
                    value=Decimal(300),
                    unit="GBP",
                    approved=True,
                    principal="caller",
                    errored=True,
                    line=2,
                    quantity="value",
                ),
            ],
        )
        assert [v.kind for v in conformance.violations] == ["errored_effect"]
        assert "not that the effect was not applied" not in conformance.render()
        assert "does not establish" in conformance.render()

    def test_an_errored_write_is_also_a_violation(self):
        conformance = replay(
            self.MANDATE,
            [
                Observation(tool="look", principal="caller", line=1),
                Observation(tool="note", principal="caller", errored=True, line=2),
            ],
        )
        assert [v.kind for v in conformance.violations] == ["errored_effect"]

    def test_an_errored_read_is_not_a_violation(self):
        """A read that failed changed nothing, so there is nothing ambiguous
        about it."""
        conformance = replay(
            self.MANDATE, [Observation(tool="look", principal="caller", errored=True, line=1)]
        )
        assert conformance.conformant is True

    def test_an_errored_call_does_not_accumulate_value(self):
        """Whether it spent is exactly what the evidence fails to establish,
        so it must not silently count toward the ceiling either."""
        conformance = replay(
            self.MANDATE,
            [
                Observation(tool="look", principal="caller", line=1),
                Observation(
                    tool="pay",
                    scope="c1",
                    value=Decimal(400),
                    unit="GBP",
                    approved=True,
                    principal="caller",
                    errored=True,
                    line=2,
                    quantity="value",
                ),
                Observation(
                    tool="pay",
                    scope="c1",
                    value=Decimal(400),
                    unit="GBP",
                    approved=True,
                    principal="caller",
                    line=3,
                    quantity="value",
                ),
            ],
        )
        kinds = [v.kind for v in conformance.violations]
        assert kinds == ["errored_effect"]
        assert "ceiling_exceeded" not in kinds
