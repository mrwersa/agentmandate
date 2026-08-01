"""Tests for the GitHub Action body.

It shells out to `mandate`, so these run it for real against the shipped
examples rather than mocking the thing under test into agreement.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

_spec = importlib.util.spec_from_file_location(
    "action_gate", ROOT / "scripts" / "action_gate.py"
)
assert _spec is not None and _spec.loader is not None
action_gate = importlib.util.module_from_spec(_spec)
sys.modules["action_gate"] = action_gate
_spec.loader.exec_module(action_gate)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("dispute-resolver.yaml", "dispute-resolver-v2.yaml", "otel-trace.json"):
        shutil.copy(EXAMPLES / name, tmp_path / name)
    monkeypatch.setattr(action_gate, "WORKSPACE", tmp_path)
    monkeypatch.setattr(action_gate, "STEP_SUMMARY", str(tmp_path / "summary.md"))
    monkeypatch.setattr(action_gate, "STEP_OUTPUT", str(tmp_path / "output.txt"))
    for key in list(os.environ):
        if key.startswith("INPUT_"):
            monkeypatch.delenv(key)
    return tmp_path


def outputs(workspace: Path) -> dict[str, str]:
    path = workspace / "output.txt"
    if not path.exists():
        return {}
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def test_a_clean_manifest_passes_with_no_findings(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver.yaml")

    assert action_gate.main() == 0
    assert outputs(workspace)["verdict"] == "clean"
    assert outputs(workspace)["findings"] == "0"


def test_a_reachable_breach_fails_and_is_counted(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver-v2.yaml")

    assert action_gate.main() == 1
    assert outputs(workspace)["verdict"] == "findings"
    assert int(outputs(workspace)["findings"]) >= 1


def test_only_the_checks_with_inputs_run(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An action demanding a baseline, agent source, and an OTLP export before
    # it says anything would be adopted by nobody.
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver.yaml")
    action_gate.main()

    report = json.loads((workspace / "agentmandate-report.json").read_text())

    assert [c["name"] for c in report["checks"]] == ["lint", "reach"]


def test_a_baseline_adds_the_diff_and_counts_only_widenings(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `diff` reports a `direction`, not a `verdict`, and reading the wrong key
    # counted every widening as zero. Counting the whole change list instead
    # would count a removal as a finding, which is the opposite of a gate.
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver-v2.yaml")
    monkeypatch.setenv("INPUT_BASELINE", "dispute-resolver.yaml")
    action_gate.main()

    report = json.loads((workspace / "agentmandate-report.json").read_text())
    diff = next(c for c in report["checks"] if c["name"] == "diff")

    assert diff["ok"] is False
    assert diff["findings"] >= 1


def test_narrowing_is_not_counted_as_a_finding(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver.yaml")
    monkeypatch.setenv("INPUT_BASELINE", "dispute-resolver-v2.yaml")
    action_gate.main()

    report = json.loads((workspace / "agentmandate-report.json").read_text())
    diff = next(c for c in report["checks"] if c["name"] == "diff")

    assert diff["findings"] == 0


def test_source_adds_drift(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = workspace / "src"
    agent.mkdir()
    (agent / "agent.py").write_text(
        "from strands import Agent, tool\n\n\n"
        "@tool\n"
        "def open_case(customer_id: str) -> str:\n"
        '    """Open."""\n\n\n'
        "agent = Agent(tools=[open_case])\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver.yaml")
    monkeypatch.setenv("INPUT_SOURCE", "src")
    action_gate.main()

    report = json.loads((workspace / "agentmandate-report.json").read_text())

    assert "drift" in [c["name"] for c in report["checks"]]


def test_traces_add_verify_with_the_mapping(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver-v2.yaml")
    monkeypatch.setenv("INPUT_TRACES", "otel-trace.json")
    monkeypatch.setenv(
        "INPUT_MAP",
        "scope=app.case.id\nvalue=app.refund.amount\ncurrency=app.currency\n"
        "approved=app.approved\nprincipal=app.principal",
    )
    action_gate.main()

    report = json.loads((workspace / "agentmandate-report.json").read_text())

    assert "verify" in [c["name"] for c in report["checks"]]


def test_fail_on_never_reports_without_blocking(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A gate nobody can adopt incrementally is a gate that gets removed rather
    # than fixed.
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver-v2.yaml")
    monkeypatch.setenv("INPUT_FAIL_ON", "never")

    assert action_gate.main() == 0
    assert outputs(workspace)["verdict"] == "findings"


def test_the_summary_carries_the_finding_and_the_graph(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver-v2.yaml")
    action_gate.main()

    summary = (workspace / "summary.md").read_text(encoding="utf-8")

    assert "## AgentMandate" in summary
    assert "cumulative value 1000 GBP exceeds limit 500 GBP" in summary
    assert "```mermaid" in summary
    # The boundary has to travel with the finding, or the finding overclaims.
    assert "not what the model tends to do" in summary


def test_a_clean_summary_still_draws_the_graph(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver.yaml")
    action_gate.main()

    summary = (workspace / "summary.md").read_text(encoding="utf-8")

    assert "No finding" in summary
    assert "What was found" not in summary
    assert "```mermaid" in summary


def test_sarif_is_written_and_its_path_returned(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver-v2.yaml")
    action_gate.main()

    path = Path(outputs(workspace)["sarif-file"])
    log = json.loads(path.read_text(encoding="utf-8"))

    assert log["version"] == "2.1.0"
    assert log["runs"][0]["results"]


def test_sarif_can_be_turned_off(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver.yaml")
    monkeypatch.setenv("INPUT_SARIF", "false")
    action_gate.main()

    assert outputs(workspace)["sarif-file"] == ""
    assert not (workspace / "agentmandate.sarif").exists()


def test_a_usage_error_is_reported_rather_than_crashing(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A missing manifest prints prose, not JSON. The action must fail with a
    # legible reason rather than a traceback about decoding.
    monkeypatch.setenv("INPUT_MANIFEST", "no-such-file.yaml")

    assert action_gate.main() == 1
    report = json.loads((workspace / "agentmandate-report.json").read_text())

    assert report["verdict"] == "findings"
    assert all(c["ok"] is False for c in report["checks"])


def test_the_action_declares_every_input_the_body_reads() -> None:
    """A body reading an input the action never declares is unreachable."""
    declared = {
        f"INPUT_{name.upper().replace('-', '_')}"
        for name in yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))[
            "inputs"
        ]
    }
    source = (ROOT / "scripts" / "action_gate.py").read_text(encoding="utf-8")
    read = set(__import__("re").findall(r'"(INPUT_[A-Z_]+)"', source))

    assert read <= declared, f"read but not declared: {sorted(read - declared)}"


def test_the_action_passes_every_declared_input_to_the_body() -> None:
    """And a declared input the composite step never forwards is inert."""
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    step = next(s for s in action["runs"]["steps"] if s.get("id") == "gate")
    forwarded = set(step["env"])
    expected = {
        f"INPUT_{name.upper().replace('-', '_')}"
        for name in action["inputs"]
        if name != "python-version"
    }

    assert expected <= forwarded, f"declared but not forwarded: {expected - forwarded}"
