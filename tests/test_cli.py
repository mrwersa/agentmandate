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
    path.write_text('{"tool": "open_case", "scope": "c1"}\n', encoding="utf-8")
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


def test_version_is_reported(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == EXIT_USAGE
