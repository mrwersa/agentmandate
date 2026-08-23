import json
from pathlib import Path

import pytest

from agentmandate import __version__
from agentmandate.cli import EXIT_FINDING, EXIT_OK, EXIT_USAGE, main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
V1 = str(EXAMPLES / "dispute-resolver.yaml")
V2 = str(EXAMPLES / "dispute-resolver-v2.yaml")
SOD = str(EXAMPLES / "dispute-resolver-sod.yaml")
TRACES = str(EXAMPLES / "observed-calls.jsonl")
ROOT = EXAMPLES.parent
AGENTKIT_INVENTORY = ROOT / "tests/fixtures/dynamic-inventory-agentkit-v1.json"
SENTRY_INVENTORY = ROOT / "tests/fixtures/dynamic-inventory-sentry-v1.json"


def test_lint_is_clean_on_the_shipped_v1_example(capsys):
    assert main(["lint", V1]) == EXIT_OK
    assert "no single-manifest findings" in capsys.readouterr().out


def test_lint_reports_findings_and_exits_non_zero(capsys):
    assert main(["lint", SOD]) == EXIT_FINDING
    assert "sod.single-identity" in capsys.readouterr().out


def test_reach_finds_no_breach_in_v1(capsys):
    assert main(["reach", V1]) == EXIT_OK
    out = capsys.readouterr().out
    assert "no reachable breach" in out
    assert "most extractable 500 GBP" in out


def test_reach_finds_the_compound_breach_in_v2(capsys):
    """The example that motivates the package must keep working."""
    assert main(["reach", V2]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "BREACH" in out
    assert "exceeds limit 500 GBP" in out
    assert "issue_refund" in out


def test_reach_reports_truncation_at_a_shallow_depth(capsys):
    assert main(["reach", V2, "--depth", "2"]) == EXIT_OK
    assert "search truncated" in capsys.readouterr().out


def test_diff_flags_the_read_only_addition_as_widening(capsys):
    assert main(["diff", V1, V2]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "verdict: WIDENING" in out
    assert "gained search_cases" in out


def test_diff_of_a_manifest_against_itself_passes(capsys):
    assert main(["diff", V1, V1]) == EXIT_OK
    assert "verdict: NEUTRAL" in capsys.readouterr().out


def test_verify_reports_violations_against_recorded_calls(capsys):
    assert main(["verify", V1, "--traces", TRACES]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "undeclared_tool" in out
    assert "ceiling_exceeded" in out


def test_verify_passes_on_a_conformant_record(tmp_path, capsys):
    path = tmp_path / "ok.jsonl"
    path.write_text(
        '{"tool": "open_case", "scope": "c1", "principal": "caller"}\n',
        encoding="utf-8",
    )
    assert main(["verify", V1, "--traces", str(path)]) == EXIT_OK
    assert "within the declared mandate" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["lint", V1, "--json"],
        ["reach", V2, "--json"],
        ["diff", V1, V2, "--json"],
        ["verify", V1, "--traces", TRACES, "--json"],
    ],
)
def test_every_command_emits_parseable_json(argv, capsys):
    main(argv)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, dict)


def test_a_missing_manifest_is_a_usage_error(capsys):
    assert main(["lint", "no-such-file.yaml"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_a_malformed_manifest_is_a_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"agent": "a"}', encoding="utf-8")
    assert main(["lint", str(path)]) == EXIT_USAGE
    assert "tools must be" in capsys.readouterr().err


def test_a_malformed_manifest_on_the_diff_path_is_a_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    assert main(["diff", str(path), V1]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_diff_of_different_agents_is_a_usage_error(tmp_path, capsys):
    other = tmp_path / "other.yaml"
    other.write_text(
        Path(V1).read_text(encoding="utf-8").replace(
            "agent: dispute-resolver", "agent: another"
        ),
        encoding="utf-8",
    )
    assert main(["diff", V1, str(other)]) == EXIT_USAGE
    assert "cannot compare different agents" in capsys.readouterr().err


def test_a_malformed_trace_is_a_usage_error(tmp_path, capsys):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"tool": "open_case", "approved": "yes"}\n', encoding="utf-8")
    assert main(["verify", V1, "--traces", str(path)]) == EXIT_USAGE
    assert "approved must be true or false" in capsys.readouterr().err


def test_a_missing_trace_is_a_usage_error(capsys):
    assert main(["verify", V1, "--traces", "no-such-trace.jsonl"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_version_is_reported(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == EXIT_USAGE


CATALOGUE = str(EXAMPLES / "mcp-tools.json")


def test_scan_emits_a_manifest_skeleton(capsys):
    assert main(["scan", CATALOGUE, "--agent", "dispute-resolver"]) == EXIT_OK
    out = capsys.readouterr().out
    assert 'agent: "dispute-resolver"' in out
    assert "REVIEW" in out


def test_scan_output_is_a_loadable_manifest(capsys):
    main(["scan", CATALOGUE, "--agent", "x"])
    from agentmandate import loads

    assert loads(capsys.readouterr().out).agent == "x"


def test_scan_defaults_the_agent_name(capsys):
    main(["scan", CATALOGUE])
    assert 'agent: "unnamed-agent"' in capsys.readouterr().out


def test_scan_reports_a_missing_catalogue(capsys):
    assert main(["scan", "absent.json"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_scan_reports_a_payload_that_is_not_a_catalogue(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"nope": 1}', encoding="utf-8")
    assert main(["scan", str(path)]) == EXIT_USAGE
    assert "tools/list payload" in capsys.readouterr().err


def test_scan_source_reads_agent_code(tmp_path, capsys):
    source = tmp_path / "agent.py"
    source.write_text(
        'from strands import Agent, tool\n\n\n'
        '@tool\n'
        'def issue_refund(case_id: str, amount: float) -> str:\n'
        '    """Refund a case."""\n\n\n'
        'agent = Agent(tools=[issue_refund])\n',
        encoding="utf-8",
    )

    assert main(["scan", "--source", str(tmp_path), "--agent", "refunds"]) == EXIT_OK
    out = capsys.readouterr().out
    assert 'name: "issue_refund"' in out
    assert 'agent: "refunds"' in out


def test_scan_source_reports_a_path_with_no_tools(tmp_path, capsys):
    (tmp_path / "plain.py").write_text("x = 1\n", encoding="utf-8")

    assert main(["scan", "--source", str(tmp_path)]) == EXIT_USAGE
    assert "no tool declarations" in capsys.readouterr().err


def test_scan_requires_exactly_one_input():
    # Accepting both would silently scan one and ignore the other.
    with pytest.raises(SystemExit):
        main(["scan", CATALOGUE, "--source", "src"])
    with pytest.raises(SystemExit):
        main(["scan"])


def test_diff_record_emits_a_change_record(capsys):
    assert main(["diff", V1, V2, "--record"]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "# Agent authority change record" in out
    assert "## Authority gained" in out
    assert "named reviewer" in out


def test_reach_reports_an_ungated_irreversible_path(capsys):
    assert main(["reach", SOD]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "close_ledger_entry is irreversible and needs no approval" in out
    # The value of this over the lint rule is the route, so the route has to
    # be in the output.
    assert "1. open_case" in out


def test_a_non_positive_depth_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["reach", V2, "--depth", "0"])
    assert exit_info.value.code == EXIT_USAGE
    assert "positive integer" in capsys.readouterr().err


REVIEWED = str(EXAMPLES / "reviewed-obligations.json")


def test_obligations_exits_non_zero_until_decisions_are_mapped(capsys):
    assert main(["obligations", V1]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "irreversible:issue_refund" in out
    assert "REVIEW: map a decision" in out


def test_a_stale_review_cannot_generate_a_suite(tmp_path, capsys):
    """The blocker: a review from a different manifest would otherwise
    generate a suite for authority the agent no longer has."""
    renamed = tmp_path / "renamed.yaml"
    renamed.write_text(
        Path(V1).read_text(encoding="utf-8").replace("issue_refund", "issue_payout"),
        encoding="utf-8",
    )

    assert main(["obligations", str(renamed), "--reviewed", REVIEWED, "--suite"]) == EXIT_FINDING
    assert "issue_payout" in capsys.readouterr().err


def test_obligations_pass_once_every_row_is_reviewed(capsys):
    assert main(["obligations", V1, "--reviewed", REVIEWED]) == EXIT_OK
    assert "REVIEW: map a decision" not in capsys.readouterr().out


def test_obligations_emit_a_decision_suite_from_reviewed_rows(capsys):
    assert main(["obligations", V1, "--reviewed", REVIEWED, "--suite"]) == EXIT_OK
    suite = json.loads(capsys.readouterr().out)

    assert suite["schema"] == "agentverity.decision-suite/v1"
    assert suite["contract"]["allowed"] == ["refund_approved"]


def test_a_suite_is_refused_before_review(capsys):
    assert main(["obligations", V1, "--suite"]) == EXIT_FINDING
    assert "not fully reviewed yet" in capsys.readouterr().err


def test_obligations_emit_parseable_json(capsys):
    main(["obligations", V1, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"].startswith("agentmandate.obligations/")


def test_lint_json_reports_the_full_service_principal_finding(tmp_path, capsys):
    text = """
version: 1
agent: a
limits: {depth: 4}
tools:
  - name: ledger
    effect: write
    principal: service
    requires: [case]
"""
    manifest = tmp_path / "service-principal.yaml"
    manifest.write_text(text, encoding="utf-8")
    assert main(["lint", str(manifest), "--json"]) == EXIT_FINDING
    payload = json.loads(capsys.readouterr().out)

    finding = next(
        f for f in payload["findings"] if f["rule"] == "identity.service-principal"
    )
    assert finding["rule"] == "identity.service-principal"
    assert finding["severity"] == "error"
    assert finding["subject"] == "ledger"
    assert "confused-deputy" in finding["message"]
    assert "not always available" in finding["message"]
    assert "named review" in finding["message"]


def test_scenarios_export_the_reachable_breach_for_review(capsys):
    assert main(["scenarios", V2]) == EXIT_FINDING
    output = capsys.readouterr().out

    assert "cumulative_value:" in output
    assert "open_case -> search_cases -> issue_refund" in output
    assert "REVIEW: write the input" in output


def test_scenarios_emit_parseable_json(capsys):
    assert main(["scenarios", V2, "--json"]) == EXIT_FINDING
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"] == "agentmandate.scenarios/v1"
    assert payload["scenarios"][0]["agent_input"] == ""


def test_scenarios_write_a_neutral_file(tmp_path, capsys):
    output = tmp_path / "scenarios.json"

    assert main(["scenarios", V2, "--output", str(output)]) == EXIT_FINDING

    payload = json.loads(output.read_text())
    assert payload["scenarios"]
    assert "need review" in capsys.readouterr().out


def test_scenarios_reconcile_reviewed_application_fields(tmp_path, capsys):
    from agentmandate import (
        Scenario,
        ScenarioSet,
        derive_scenarios,
        load,
        save_scenarios,
    )

    scenarios = derive_scenarios(load(V2))
    reviewed = ScenarioSet(
        scenarios.agent,
        scenarios.depth,
        scenarios.truncated,
        tuple(
            Scenario(
                scenario.kind,
                scenario.detail,
                scenario.path,
                environment=("two approved cases exist",),
                agent_input="Refund both cases.",
                expected_control="block the second refund",
            )
            for scenario in scenarios.scenarios
        ),
    )
    review_path = tmp_path / "reviewed.json"
    save_scenarios(reviewed, review_path)

    assert main(["scenarios", V2, "--reviewed", str(review_path)]) == EXIT_FINDING
    assert "REVIEW:" not in capsys.readouterr().out


def test_scenarios_report_bad_review_and_output_paths(tmp_path, capsys):
    assert main(["scenarios", V2, "--reviewed", "missing.json"]) == EXIT_USAGE
    assert "cannot load scenarios" in capsys.readouterr().err

    directory = tmp_path / "directory"
    directory.mkdir()
    assert main(["scenarios", V2, "--output", str(directory)]) == EXIT_USAGE
    assert "cannot write scenarios" in capsys.readouterr().err


def test_a_malformed_reviewed_file_is_a_usage_error(tmp_path, capsys):
    bad = tmp_path / "reviewed.json"
    bad.write_text("{not json", encoding="utf-8")

    assert main(["obligations", V1, "--reviewed", str(bad)]) == EXIT_USAGE
    assert "cannot load obligations" in capsys.readouterr().err


OTEL = str(EXAMPLES / "otel-trace.json")
OTEL_MAP = [
    "--map", "scope=app.case.id", "--map", "value=app.refund.amount",
    "--map", "currency=app.currency", "--map", "approved=app.approved",
    "--map", "principal=app.principal",
]


def test_verify_reads_an_otel_trace_directly(capsys):
    assert main(["verify", V1, "--otel", OTEL, *OTEL_MAP]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "3 tool call(s)" in out
    assert "ceiling_exceeded" in out


def test_the_conversion_summary_precedes_the_verdict(capsys):
    """Two observations recovered from four hundred spans is usually a
    mapping mistake, and a clean report on almost no evidence should not
    read as success."""
    main(["verify", V1, "--otel", OTEL, *OTEL_MAP])
    out = capsys.readouterr().out
    assert out.index("read 5 span(s)") < out.index("replayed")


def test_an_unmapped_trace_fails_closed_and_says_which_fields(capsys):
    assert main(["verify", V1, "--otel", OTEL]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "no attribute mapped for" in out
    assert "missing_principal" in out


def test_emit_round_trips_to_the_plain_replay_format(tmp_path, capsys):
    out_path = tmp_path / "observed.jsonl"
    main(["verify", V1, "--otel", OTEL, *OTEL_MAP, "--emit", str(out_path)])
    capsys.readouterr()

    lines = [json.loads(x) for x in out_path.read_text().splitlines()]
    assert [row["tool"] for row in lines] == ["open_case", "issue_refund", "issue_refund"]
    # an absent field stays absent rather than becoming null
    assert "value" not in lines[0]

    assert main(["verify", V1, "--traces", str(out_path)]) == EXIT_FINDING
    assert "ceiling_exceeded" in capsys.readouterr().out


def test_a_trace_and_a_jsonl_file_cannot_both_be_given():
    with pytest.raises(SystemExit) as exit_info:
        main(["verify", V1, "--traces", TRACES, "--otel", OTEL])
    assert exit_info.value.code == EXIT_USAGE


def test_one_source_is_required():
    with pytest.raises(SystemExit) as exit_info:
        main(["verify", V1])
    assert exit_info.value.code == EXIT_USAGE


def test_a_malformed_trace_file_is_a_usage_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["verify", V1, "--otel", str(bad)]) == EXIT_USAGE
    assert "ExportTraceServiceRequest" in capsys.readouterr().err


def test_a_malformed_mapping_is_a_usage_error(capsys):
    assert main(["verify", V1, "--otel", OTEL, "--map", "nonsense"]) == EXIT_USAGE
    assert "malformed mapping" in capsys.readouterr().err


def test_two_independent_traces_do_not_share_a_budget(tmp_path, capsys):
    """The blocker: two runs each under the ceiling were combined into one
    breach that neither run committed."""
    def refund(trace, start):
        return {
            "name": "execute_tool issue_refund", "traceId": trace,
            "startTimeUnixNano": str(start),
            "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                {"key": "gen_ai.tool.name", "value": {"stringValue": "issue_refund"}},
                {"key": "app.case.id", "value": {"stringValue": "c1"}},
                {"key": "app.refund.amount", "value": {"stringValue": "300"}},
                {"key": "app.currency", "value": {"stringValue": "GBP"}},
                {"key": "app.approved", "value": {"boolValue": True}},
                {"key": "app.principal", "value": {"stringValue": "caller"}},
            ],
        }
    def opener(trace, start):
        return {
            "name": "execute_tool open_case", "traceId": trace,
            "startTimeUnixNano": str(start),
            "attributes": [
                {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                {"key": "gen_ai.tool.name", "value": {"stringValue": "open_case"}},
                {"key": "app.case.id", "value": {"stringValue": "c1"}},
                {"key": "app.principal", "value": {"stringValue": "caller"}},
            ],
        }
    path = tmp_path / "two.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [
        opener("A", 100), refund("A", 200), opener("B", 300), refund("B", 400)]}]}]}),
        encoding="utf-8")

    assert main(["verify", V1, "--otel", str(path), *OTEL_MAP]) == EXIT_OK
    out = capsys.readouterr().out
    assert "2 trace(s)" in out
    assert "verified separately" in out
    assert "ceiling_exceeded" not in out


def test_json_output_carries_the_conversion_counts(tmp_path, capsys):
    """CI reads the JSON. Omitting the counts hides the warnings that explain
    a suspiciously clean result."""
    main(["verify", V1, "--otel", OTEL, *OTEL_MAP, "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema"].startswith("agentmandate.verify/")
    assert payload["conversion"]["total_spans"] == 5
    assert payload["conversion"]["tool_calls"] == 3
    assert payload["conversion"]["traces"] >= 1
    assert "unmapped" in payload["conversion"]
    assert "conformance" in payload


def test_otel_only_flags_are_refused_with_a_jsonl_file(capsys):
    assert main(["verify", V1, "--traces", TRACES, "--map", "scope=x"]) == EXIT_USAGE
    assert "--otel only" in capsys.readouterr().err


def test_lenient_mode_is_opt_in(tmp_path, capsys):
    path = tmp_path / "bare.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "t", "traceId": "t1", "startTimeUnixNano": "1", "attributes": [
            {"key": "gen_ai.tool.name", "value": {"stringValue": "open_case"}}]}]}]}]}),
        encoding="utf-8")

    main(["verify", V1, "--otel", str(path)])
    assert "0 tool call(s)" in capsys.readouterr().out

    main(["verify", V1, "--otel", str(path), "--lenient-tool-spans"])
    assert "1 tool call(s)" in capsys.readouterr().out


def test_newline_delimited_requests_are_accepted(tmp_path, capsys):
    """OpenTelemetry's file exporter writes one request per line."""
    one = json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "e", "traceId": "t1", "startTimeUnixNano": "1", "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "open_case"}},
            {"key": "app.principal", "value": {"stringValue": "caller"}}]}]}]}]})
    path = tmp_path / "ndjson.json"
    path.write_text(one + "\n" + one + "\n", encoding="utf-8")

    main(["verify", V1, "--otel", str(path), *OTEL_MAP])
    assert "2 tool call(s)" in capsys.readouterr().out


def test_an_errored_call_survives_the_emit_round_trip(tmp_path, capsys):
    """The errored flag has to reach the emitted file, or a re-run from it
    would silently pass where the trace did not."""
    path = tmp_path / "err.json"
    path.write_text(json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [{
        "name": "e", "traceId": "t1", "startTimeUnixNano": "1",
        "status": {"code": "STATUS_CODE_ERROR"},
        "attributes": [
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "issue_refund"}},
            {"key": "app.principal", "value": {"stringValue": "caller"}}]}]}]}]}),
        encoding="utf-8")
    out_path = tmp_path / "observed.jsonl"

    main(["verify", V1, "--otel", str(path), *OTEL_MAP, "--emit", str(out_path)])
    capsys.readouterr()

    assert json.loads(out_path.read_text().splitlines()[0])["errored"] is True
    assert main(["verify", V1, "--traces", str(out_path)]) == EXIT_FINDING
    assert "errored_effect" in capsys.readouterr().out


def test_binding_flags_are_refused_with_a_catalogue(capsys):
    assert main(["scan", CATALOGUE, "--binding", "x"]) == EXIT_USAGE
    assert "apply to --source" in capsys.readouterr().err


def test_scan_source_refuses_two_agents_and_names_them(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(
        "from strands import Agent, tool\n\n\n"
        "@tool\n"
        "def a(case_id: str) -> str:\n"
        '    """A."""\n\n\n'
        "@tool\n"
        "def b(case_id: str) -> str:\n"
        '    """B."""\n\n\n'
        "triage = Agent(tools=[a])\n"
        "resolver = Agent(tools=[b])\n",
        encoding="utf-8",
    )

    assert main(["scan", "--source", str(tmp_path)]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert "more than one agent" in err
    assert "triage" in err and "resolver" in err

    assert main(["scan", "--source", str(tmp_path), "--binding", "resolver"]) == EXIT_OK
    assert 'name: "b"' in capsys.readouterr().out


DRIFT_SOURCE = (
    "from strands import Agent, tool\n\n\n"
    "@tool\n"
    "def open_case(customer_id: str) -> str:\n"
    '    """Open."""\n\n\n'
    "@tool\n"
    "def wipe(case_id: str) -> None:\n"
    '    """Undeclared."""\n\n\n'
    "agent = Agent(tools=[open_case, wipe])\n"
)


def test_drift_reports_a_tool_the_mandate_never_declared(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(DRIFT_SOURCE, encoding="utf-8")

    assert main(["drift", V1, "--source", str(tmp_path)]) == EXIT_FINDING
    out = capsys.readouterr().out
    assert "UNDECLARED  wipe" in out
    assert "smaller graph than the real one" in out


def test_drift_emits_parseable_json(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(DRIFT_SOURCE, encoding="utf-8")

    main(["drift", V1, "--source", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["clean"] is False
    assert "wipe" in payload["discovered"]
    assert "inventory_as_of" not in payload
    assert any(f["kind"] == "undeclared" for f in payload["findings"])


def test_drift_reports_an_unreadable_source_as_a_usage_error(capsys):
    assert main(["drift", V1, "--source", "no-such-directory"]) == EXIT_USAGE
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize("fixture", [AGENTKIT_INVENTORY, SENTRY_INVENTORY])
def test_inventory_validate_checks_both_evidence_declarations(fixture, capsys):
    assert main(["inventory", "validate", str(fixture)]) == EXIT_OK
    assert capsys.readouterr().out == "valid dynamic inventory v1\n"


def test_inventory_validate_failure_emits_no_stdout(tmp_path, capsys):
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"inventory_version":1,"unexpected":true}', encoding="utf-8")

    assert main(["inventory", "validate", str(invalid)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error:" in captured.err


def test_drift_accepts_complete_reviewed_dynamic_inventory(tmp_path, capsys):
    source = tmp_path / "python/examples/strands-agents-cdp-server-chatbot"
    source.mkdir(parents=True)
    (source / "chatbot.py").write_text(
        "tools = get_strands_tools(agentkit)\nagent = Agent(tools=tools)\n",
        encoding="utf-8",
    )
    selection = json.dumps(
        {
            "provider": [
                "cdp_api",
                "compound",
                "erc20",
                "pyth",
                "wallet",
                "weth",
                "wow",
            ]
        }
    )

    assert main(
        [
            "drift",
            str(ROOT / "docs/evidence/agentkit/mandate.yaml"),
            "--source",
            str(tmp_path),
            "--binding",
            "agent",
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(ROOT / "docs/evidence/agentkit/inventory-v074.json"),
            "--inventory-selection",
            selection,
            "--inventory-as-of",
            "2027-01-01",
            "--json",
        ]
    ) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["clean"] is True
    assert payload["inventory_as_of"] == "2027-01-01"
    assert len(payload["discovered"]) == 20


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ([], "--inventory-capture"),
        (
            ["--inventory-capture", "missing"],
            "--inventory-selection",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{}",
            ],
            "--inventory-as-of",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{",
                "--inventory-as-of",
                "2027-01-01",
            ],
            "valid JSON",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "[]",
                "--inventory-as-of",
                "2027-01-01",
            ],
            "JSON object",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{}",
                "--inventory-as-of",
                "not-a-date",
            ],
            "YYYY-MM-DD",
        ),
        (
            [
                "--inventory-capture",
                "missing",
                "--inventory-selection",
                "{}",
                "--inventory-as-of",
                "20270101",
            ],
            "YYYY-MM-DD",
        ),
    ],
)
def test_dynamic_inventory_option_errors_emit_no_stdout(tmp_path, capsys, extra, message):
    (tmp_path / "agent.py").write_text(
        "def open_case(): pass\nagent = Agent(tools=[open_case])\n",
        encoding="utf-8",
    )
    arguments = [
        "drift",
        V1,
        "--source",
        str(tmp_path),
        "--inventory-declaration",
        str(AGENTKIT_INVENTORY),
        *extra,
    ]

    assert main(arguments) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert message in captured.err


def test_dynamic_inventory_requires_a_declaration(tmp_path, capsys):
    (tmp_path / "agent.py").write_text(
        "def open_case(): pass\nagent = Agent(tools=[open_case])\n",
        encoding="utf-8",
    )

    assert main(
        ["drift", V1, "--source", str(tmp_path), "--inventory-capture", "missing"]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--inventory-declaration" in captured.err


def test_dynamic_inventory_rejects_different_bytes_for_one_locator(tmp_path, capsys):
    source = tmp_path / "python/examples/strands-agents-cdp-server-chatbot"
    source.mkdir(parents=True)
    (source / "chatbot.py").write_text(
        "tools = get_strands_tools(agentkit)\nagent = Agent(tools=tools)\n",
        encoding="utf-8",
    )
    changed = tmp_path / "changed.json"
    changed.write_text("{}", encoding="utf-8")
    capture = ROOT / "docs/evidence/agentkit/inventory-v074.json"

    assert main(
        [
            "drift",
            str(ROOT / "docs/evidence/agentkit/mandate.yaml"),
            "--source",
            str(tmp_path),
            "--binding",
            "agent",
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(capture),
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(changed),
            "--inventory-selection",
            '{"provider":"cdp_api"}',
            "--inventory-as-of",
            "2027-01-01",
        ]
    ) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "different capture bytes" in captured.err


def test_dynamic_inventory_text_records_the_evaluation_date(tmp_path, capsys):
    source = tmp_path / "python/examples/strands-agents-cdp-server-chatbot"
    source.mkdir(parents=True)
    (source / "chatbot.py").write_text(
        "tools = get_strands_tools(agentkit)\nagent = Agent(tools=tools)\n",
        encoding="utf-8",
    )
    declaration = json.loads(AGENTKIT_INVENTORY.read_text(encoding="utf-8"))

    main(
        [
            "drift",
            str(ROOT / "docs/evidence/agentkit/mandate.yaml"),
            "--source",
            str(tmp_path),
            "--binding",
            "agent",
            "--inventory-declaration",
            str(AGENTKIT_INVENTORY),
            "--inventory-capture",
            str(ROOT / "docs/evidence/agentkit/inventory-v074.json"),
            "--inventory-selection",
            json.dumps(declaration["selection"]),
            "--inventory-as-of",
            "2027-01-01",
        ]
    )
    assert "dynamic inventory evaluated as of 2027-01-01" in capsys.readouterr().out


def test_reach_emits_sarif(capsys):
    assert main(["reach", V2, "--sarif"]) == EXIT_FINDING
    log = json.loads(capsys.readouterr().out)

    assert log["version"] == "2.1.0"
    assert log["runs"][0]["results"][0]["level"] == "error"


def test_reach_emits_a_mermaid_graph(capsys):
    assert main(["reach", V2, "--graph"]) == EXIT_FINDING
    out = capsys.readouterr().out

    assert out.startswith("flowchart LR")
    assert "--> breach" in out


def test_reach_refuses_two_output_formats(capsys):
    # Each writes to stdout. Emitting two would produce a file that is neither.
    assert main(["reach", V2, "--sarif", "--graph"]) == EXIT_USAGE
    assert "choose one output format" in capsys.readouterr().err
