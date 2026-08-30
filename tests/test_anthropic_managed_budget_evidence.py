import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "anthropic-managed-budget"


def _capture_module():
    spec = importlib.util.spec_from_file_location(
        "anthropic_budget_capture", EVIDENCE / "capture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_protocol_is_preregistered_and_confirmation_is_locked():
    protocol = json.loads((EVIDENCE / "protocol.json").read_text())

    assert protocol["status"] == "pilot_not_run"
    assert protocol["pilot"]["excluded_from_confirmation"] is True
    assert protocol["confirmation"]["trials_per_cell"] == 10
    assert protocol["confirmation"]["cap_minor_units"] is None
    assert protocol["confirmation"]["cells"] == [
        "sequential_control",
        "fresh_session_replication",
        "cap_revision_control",
        "agent_revision_unmeasurable",
        "subagent_handoff",
        "concurrent_subagents_2",
        "concurrent_subagents_4",
    ]


def test_capture_uses_managed_beta_and_pinned_sdk():
    capture = _capture_module()

    assert capture.BETAS == ["managed-agents-2026-04-01"]
    assert (EVIDENCE / "requirements-capture.txt").read_text() == "anthropic==1.2.0\n"


def test_private_capture_outputs_and_environment_are_gitignored():
    ignored = (ROOT / ".gitignore").read_text().splitlines()

    assert ".capture-venv/" in ignored
    assert "private-*/" in ignored


def test_confirmation_refuses_to_run_before_pilot_cap(tmp_path, capsys):
    capture = _capture_module()

    assert capture.main(["confirm", "--output", str(tmp_path / "confirm")]) == 2
    assert "confirmation is locked" in capsys.readouterr().err


def test_capture_refuses_to_run_without_api_key(tmp_path, monkeypatch, capsys):
    capture = _capture_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert capture.main(["capability", "--output", str(tmp_path / "out")]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_capture_refuses_to_run_without_valid_workspace(tmp_path, monkeypatch, capsys):
    capture = _capture_module()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", "not-a-workspace")

    assert capture.main(["capability", "--output", str(tmp_path / "out")]) == 2
    assert "ANTHROPIC_WORKSPACE_ID is not set" in capsys.readouterr().err
