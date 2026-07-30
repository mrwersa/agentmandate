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
    assert "cannot load trace" in capsys.readouterr().err


def test_a_malformed_mapping_is_a_usage_error(capsys):
    assert main(["verify", V1, "--otel", OTEL, "--map", "nonsense"]) == EXIT_USAGE
    assert "malformed mapping" in capsys.readouterr().err
