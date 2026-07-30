"""Tests for reading OpenTelemetry traces into the replay format."""

from __future__ import annotations

import json

import pytest

from agentmandate import loads, replay
from agentmandate.otel import (
    MAPPABLE,
    TraceError,
    convert,
    load_trace,
    parse_mapping,
)

FULL_MAP = {
    "scope": "app.case.id",
    "value": "app.refund.amount",
    "currency": "app.currency",
    "approved": "app.approved",
    "principal": "app.principal",
}


def attr(key, value, kind="stringValue"):
    return {"key": key, "value": {kind: value}}


def tool(name, start, extra=(), trace="trace-1"):
    return {
        "name": f"execute_tool {name}",
        "traceId": trace,
        "startTimeUnixNano": str(start),
        "attributes": [
            attr("gen_ai.operation.name", "execute_tool"),
            attr("gen_ai.tool.name", name),
            *extra,
        ],
    }


def doc(*spans):
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


class TestOnlyToolCallsBecomeObservations:
    def test_a_chat_span_is_not_a_tool_call(self):
        payload = doc(
            tool("open_case", 100),
            {"name": "chat", "startTimeUnixNano": "200",
             "attributes": [attr("gen_ai.operation.name", "chat")]},
        )
        result = convert(payload)

        assert result.total_spans == 2
        assert result.tool_spans == 1
        assert [o.tool for o in result.observations] == ["open_case"]

    def test_an_agent_span_is_not_a_tool_call(self):
        payload = doc({"name": "invoke_agent x", "startTimeUnixNano": "100",
                       "attributes": [attr("gen_ai.operation.name", "invoke_agent")]})
        assert convert(payload).observations == ()

    def test_a_bare_tool_name_is_ignored_by_default(self):
        """The convention requires both attributes on a tool span. Inferring
        an execution from a name alone is a guess."""
        payload = doc({"name": "t", "startTimeUnixNano": "100",
                       "attributes": [attr("gen_ai.tool.name", "open_case")]})
        assert convert(payload).observations == ()

    def test_a_bare_tool_name_is_accepted_only_when_asked(self):
        payload = doc({"name": "t", "startTimeUnixNano": "100",
                       "attributes": [attr("gen_ai.tool.name", "open_case")]})
        result = convert(payload, lenient=True)
        assert [o.tool for o in result.observations] == ["open_case"]

    def test_a_tool_span_with_no_name_is_refused(self):
        payload = doc({"name": "t", "startTimeUnixNano": "100",
                       "attributes": [attr("gen_ai.operation.name", "execute_tool")]})
        with pytest.raises(TraceError, match="cannot be identified"):
            convert(payload)


class TestNothingIsInvented:
    """The conventions carry the tool name. They do not carry which resource
    was touched, what it cost, whose authority it spent, or who approved it."""

    def test_unmapped_fields_stay_absent(self):
        payload = doc(tool("issue_refund", 100, [attr("app.case.id", "c1")]))
        observation = convert(payload).observations[0]

        assert observation.scope is None
        assert observation.value is None
        assert observation.principal is None
        assert observation.approved is False

    def test_unmapped_fields_are_reported_so_silence_is_not_success(self):
        result = convert(doc(tool("open_case", 100)))

        assert set(result.unmapped) == set(MAPPABLE)
        assert "fail closed" in result.summary

    def test_an_unmapped_trace_makes_verify_fail_closed(self):
        """The point of the whole design: missing evidence is a violation,
        not a pass."""
        mandate = loads(
            """
            agent: a
            tools:
              - name: open_case
                effect: read
                produces: case
              - name: issue_refund
                effect: irreversible
                requires: [case]
                value_arg: amount
                scope_key: case
                ceiling: {amount: 500, currency: GBP}
                requires_approval: true
            """
        )
        payload = doc(tool("open_case", 100), tool("issue_refund", 200))
        conformance = replay(mandate, list(convert(payload).observations))
        kinds = {v.kind for v in conformance.violations}

        assert conformance.conformant is False
        assert "missing_principal" in kinds
        assert "missing_approval" in kinds
        assert "missing_scope" in kinds

    def test_a_mapped_trace_verifies_cleanly(self):
        mandate = loads(
            """
            agent: a
            limits: {total: {amount: 500, currency: GBP}}
            tools:
              - name: open_case
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
        )
        payload = doc(
            tool("open_case", 100, [attr("app.case.id", "c1"),
                                    attr("app.principal", "caller")]),
            tool("issue_refund", 200, [
                attr("app.case.id", "c1"), attr("app.refund.amount", "500"),
                attr("app.currency", "GBP"), attr("app.approved", True, "boolValue"),
                attr("app.principal", "caller")]),
        )
        conformance = replay(mandate, list(convert(payload, FULL_MAP).observations))
        assert conformance.conformant is True


class TestOrdering:
    """Cumulative ceilings accumulate in call order, so the order the
    converter produces has to be the order the calls happened."""

    def test_spans_are_ordered_by_start_time_not_document_order(self):
        payload = doc(tool("second", 900), tool("first", 100))
        assert [o.tool for o in convert(payload).observations] == ["first", "second"]

    def test_ties_keep_document_order(self):
        payload = doc(tool("a", 100), tool("b", 100))
        assert [o.tool for o in convert(payload).observations] == ["a", "b"]

    def test_a_missing_start_time_does_not_crash(self):
        payload = doc({"name": "t", "traceId": "t1", "attributes": [
            attr("gen_ai.operation.name", "execute_tool"),
            attr("gen_ai.tool.name", "x")]})
        assert [o.tool for o in convert(payload).observations] == ["x"]


class TestAttributeDecoding:
    @pytest.mark.parametrize(
        "kind, raw, expected",
        [("stringValue", "caller", "caller"), ("intValue", "42", "42")],
    )
    def test_scalar_kinds_are_unwrapped(self, kind, raw, expected):
        payload = doc(tool("t", 100, [attr("app.principal", raw, kind)]))
        result = convert(payload, {"principal": "app.principal"})
        assert result.observations[0].principal == expected

    @pytest.mark.parametrize("raw, expected", [(True, True), ("true", True), ("false", False)])
    def test_approval_accepts_bool_or_string(self, raw, expected):
        kind = "boolValue" if isinstance(raw, bool) else "stringValue"
        payload = doc(tool("t", 100, [attr("app.approved", raw, kind)]))
        result = convert(payload, {"approved": "app.approved"})
        assert result.observations[0].approved is expected

    def test_an_int_value_reaches_decimal_without_a_float_detour(self):
        payload = doc(tool("t", 100, [attr("app.amount", "500", "intValue")]))
        result = convert(payload, {"value": "app.amount"})
        assert str(result.observations[0].value) == "500"


class TestMapping:
    def test_an_unknown_field_is_refused_with_the_valid_list(self):
        with pytest.raises(TraceError, match="mappable fields are"):
            convert(doc(tool("t", 100)), {"colour": "app.colour"})

    def test_a_mapping_pointing_at_a_missing_attribute_is_simply_absent(self):
        payload = doc(tool("t", 100))
        result = convert(payload, {"scope": "app.not.present"})
        assert result.observations[0].scope is None

    @pytest.mark.parametrize("bad", ["noequals", "=value", "field="])
    def test_malformed_mapping_arguments_are_refused(self, bad):
        with pytest.raises(TraceError, match="malformed mapping"):
            parse_mapping([bad])

    def test_mapping_arguments_parse(self):
        assert parse_mapping(["scope=app.case.id", "value=app.amount"]) == {
            "scope": "app.case.id", "value": "app.amount"}

    def test_an_attribute_containing_an_equals_sign_survives(self):
        assert parse_mapping(["scope=a=b"]) == {"scope": "a=b"}


class TestMalformedDocuments:
    @pytest.mark.parametrize(
        "payload, message",
        [
            ([], "no OTLP requests"),
            ([[]], "must be an OTLP JSON object"),
            ({"spans": []}, "no 'resourceSpans'"),
            ({"resourceSpans": "nope"}, "no 'resourceSpans'"),
        ],
    )
    def test_bad_shapes_are_refused_with_the_expected_format_named(self, payload, message):
        with pytest.raises(TraceError, match=message):
            convert(payload)

    def test_an_empty_trace_produces_no_observations(self):
        result = convert({"resourceSpans": []})
        assert result.observations == ()
        assert result.total_spans == 0

    def test_a_missing_file_is_a_trace_error(self, tmp_path):
        with pytest.raises(TraceError, match="cannot load trace"):
            load_trace(tmp_path / "absent.json")

    def test_malformed_json_names_the_expected_shape(self, tmp_path):
        path = tmp_path / "t.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(TraceError, match="ExportTraceServiceRequest"):
            load_trace(path)

    def test_an_empty_file_is_refused(self, tmp_path):
        path = tmp_path / "t.json"
        path.write_text("   \n", encoding="utf-8")
        with pytest.raises(TraceError, match="empty"):
            load_trace(path)


def test_the_shipped_example_trace_converts_and_finds_the_breach():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    result = load_trace(root / "examples/otel-trace.json", FULL_MAP)

    assert result.total_spans == 5
    assert result.tool_spans == 3
    assert result.unmapped == ()

    mandate = loads((root / "examples/dispute-resolver.yaml").read_text())
    conformance = replay(mandate, list(result.observations))
    kinds = [v.kind for v in conformance.violations]

    assert "ceiling_exceeded" in kinds
    assert json.dumps(conformance.as_dict())


class TestAttributeEdgeCases:
    def test_a_plain_attribute_value_is_passed_through(self):
        """Some exporters write a bare value rather than an AnyValue wrapper."""
        payload = doc({"name": "t", "traceId": "t1", "startTimeUnixNano": "1",
                       "attributes": [
                           {"key": "gen_ai.operation.name", "value": "execute_tool"},
                           {"key": "gen_ai.tool.name", "value": "open_case"}]})
        assert [o.tool for o in convert(payload).observations] == ["open_case"]

    def test_an_array_attribute_is_unwrapped(self):
        from agentmandate.otel import attributes

        span = {"attributes": [{"key": "app.tags", "value": {"arrayValue": {
            "values": [{"stringValue": "a"}, {"stringValue": "b"}]}}}]}
        assert attributes(span)["app.tags"] == ["a", "b"]

    def test_an_unrecognised_attribute_shape_becomes_none(self):
        from agentmandate.otel import attributes

        span = {"attributes": [{"key": "app.odd", "value": {"bytesValue": "zz"}}]}
        assert attributes(span)["app.odd"] is None

    def test_an_attribute_explicitly_set_to_null_is_treated_as_absent(self):
        payload = doc({"name": "t", "traceId": "t1", "startTimeUnixNano": "1", "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "pay"}},
            {"key": "app.case.id", "value": {"bytesValue": "x"}}]})
        result = convert(payload, {"scope": "app.case.id"})
        assert result.observations[0].scope is None


class TestFalseBreachesAreTheFailureThatMatters:
    """Every defect in this class produced a ceiling breach that never
    happened. A gate that cries wolf gets switched off, so a false positive
    costs more than a missed finding here."""

    def test_a_chat_span_carrying_a_tool_name_is_not_an_execution(self):
        """Instrumentations commonly attach the tool name to the LLM span
        that REQUESTED the call. Counting it doubles the value."""
        payload = doc(
            {"name": "chat", "traceId": "t", "startTimeUnixNano": "100", "attributes": [
                attr("gen_ai.operation.name", "chat"),
                attr("gen_ai.tool.name", "issue_refund"),
                attr("app.amount", "500")]},
            tool("issue_refund", 200, [attr("app.amount", "500")]),
        )
        result = convert(payload, {"value": "app.amount"})

        assert result.tool_spans == 1
        assert [str(o.value) for o in result.observations] == ["500"]

    def test_an_explicit_operation_is_authoritative_over_a_tool_name(self):
        payload = doc({"name": "x", "traceId": "t", "startTimeUnixNano": "100", "attributes": [
            attr("gen_ai.operation.name", "invoke_agent"),
            attr("gen_ai.tool.name", "issue_refund")]})
        assert convert(payload).observations == ()

    def test_an_errored_call_is_carried_as_incomplete_evidence(self):
        """An error means the operation failed, not that the effect was not
        applied. A timeout is exactly the case where the write may have
        landed, so the call must not vanish into a clean report."""
        payload = doc(
            {"name": "e", "traceId": "t", "startTimeUnixNano": "100",
             "status": {"code": "STATUS_CODE_ERROR", "message": "timeout"},
             "attributes": [attr("gen_ai.operation.name", "execute_tool"),
                            attr("gen_ai.tool.name", "issue_refund"),
                            attr("app.amount", "500")]})
        result = convert(payload, {"value": "app.amount"})

        assert len(result.observations) == 1
        assert result.observations[0].errored is True
        assert result.errored == 1
        assert "not that the effect was not applied" in result.summary

    @pytest.mark.parametrize("code", ["STATUS_CODE_ERROR", 2, "2"])
    def test_error_status_is_recognised_in_either_encoding(self, code):
        payload = doc({**tool("t", 100), "status": {"code": code}})
        result = convert(payload)
        assert result.errored == 1
        assert result.observations[0].errored is True

    @pytest.mark.parametrize("code", ["STATUS_CODE_OK", "STATUS_CODE_UNSET", 0, 1])
    def test_a_successful_or_unset_status_is_not_marked_errored(self, code):
        payload = doc({**tool("t", 100), "status": {"code": code}})
        result = convert(payload)
        assert result.errored == 0
        assert result.observations[0].errored is False

    def test_one_call_instrumented_twice_is_collapsed_by_call_id(self):
        """A client span and a server span for the same call share the tool
        call id and are one logical call."""
        def span(start):
            return tool("issue_refund", start, [
                attr("gen_ai.tool.call.id", "call_abc"),
                attr("app.amount", "500")])
        result = convert(doc(span(100), span(110)), {"value": "app.amount"})

        assert len(result.observations) == 1
        assert result.duplicates == 1
        assert "collapsed by" in result.summary

    def test_distinct_call_ids_are_kept_as_separate_calls(self):
        payload = doc(
            tool("issue_refund", 100, [attr("gen_ai.tool.call.id", "a")]),
            tool("issue_refund", 200, [attr("gen_ai.tool.call.id", "b")]),
        )
        result = convert(payload)
        assert len(result.observations) == 2
        assert result.duplicates == 0

    def test_calls_without_an_id_are_never_collapsed(self):
        """Two genuine refunds with no call id must stay two refunds."""
        payload = doc(tool("issue_refund", 100), tool("issue_refund", 200))
        result = convert(payload)

        assert len(result.observations) == 2
        assert result.duplicates == 0

    def test_the_first_of_a_duplicate_pair_is_the_one_kept(self):
        payload = doc(
            tool("issue_refund", 100, [attr("gen_ai.tool.call.id", "a"),
                                       attr("app.amount", "500")]),
            tool("issue_refund", 200, [attr("gen_ai.tool.call.id", "a"),
                                       attr("app.amount", "999")]),
        )
        result = convert(payload, {"value": "app.amount"})
        assert [str(o.value) for o in result.observations] == ["500"]


def test_a_span_with_no_operation_and_no_tool_name_is_ignored():
    """Not every span in a trace is a GenAI span at all. An HTTP or database
    span carries neither attribute and must pass through untouched."""
    payload = doc({"name": "GET /health", "startTimeUnixNano": "100",
                   "attributes": [attr("http.route", "/health")]})
    result = convert(payload)

    assert result.observations == ()
    assert result.total_spans == 1
    assert result.tool_spans == 0


def test_a_span_without_a_trace_id_still_groups():
    """Not every exporter writes traceId at the span level. Those calls share
    one unnamed run rather than being dropped."""
    payload = doc({"name": "e", "startTimeUnixNano": "1", "attributes": [
        attr("gen_ai.operation.name", "execute_tool"), attr("gen_ai.tool.name", "x")]})
    result = convert(payload)

    assert len(result.runs) == 1
    assert result.runs[0][0] == ""
    assert len(result.observations) == 1


def test_a_non_string_trace_id_is_normalised():
    payload = doc({"name": "e", "traceId": 7, "startTimeUnixNano": "1", "attributes": [
        attr("gen_ai.operation.name", "execute_tool"), attr("gen_ai.tool.name", "x")]})
    assert convert(payload).runs[0][0] == ""


def test_a_span_that_is_not_a_dict_is_skipped():
    payload = {"resourceSpans": [{"scopeSpans": [{"spans": ["not a span"]}]}]}
    assert convert(payload).total_spans == 0


def test_blank_lines_between_requests_are_skipped(tmp_path):
    """A file exporter may separate requests with a blank line."""
    one = json.dumps(doc(tool("open_case", 100)))
    path = tmp_path / "nd.json"
    path.write_text(one + "\n\n" + one + "\n", encoding="utf-8")

    assert len(load_trace(path).observations) == 2
