import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

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
    assert protocol["pilot"]["max_work_units_per_session"] == 8
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


def test_capture_does_not_echo_anthropic_error_values(tmp_path, monkeypatch, capsys):
    capture = _capture_module()

    class FakeAnthropicError(Exception):
        pass

    FakeAnthropicError.__module__ = "anthropic.fake"

    def fail(_output):
        raise FakeAnthropicError("live-workspace-identifier")

    monkeypatch.setattr(capture, "capability", fail)

    assert capture.main(["capability", "--output", str(tmp_path / "out")]) == 2
    error = capsys.readouterr().err
    assert "FakeAnthropicError" in error
    assert "live-workspace-identifier" not in error


def test_wait_idle_does_not_accept_the_prestart_idle_state(monkeypatch):
    capture = _capture_module()
    states = iter(("idle", "running", "idle"))
    event_sets = iter(
        (
            [SimpleNamespace(id="event-1", type="user.message")],
            [
                SimpleNamespace(id="event-1", type="user.message"),
                SimpleNamespace(id="model-1", type="span.model_request_start"),
            ],
            [
                SimpleNamespace(id="event-1", type="user.message"),
                SimpleNamespace(id="idle-1", type="session.status_idle"),
            ],
        )
    )

    class Sessions:
        def __init__(self):
            self.events = SimpleNamespace(list=self.list_events)

        @staticmethod
        def list_events(*_args, **_kwargs):
            return SimpleNamespace(
                data=next(event_sets),
                has_next_page=lambda: False,
            )

        @staticmethod
        def retrieve(*_args, **_kwargs):
            return SimpleNamespace(status=next(states))

    client = SimpleNamespace(beta=SimpleNamespace(sessions=Sessions()))
    monkeypatch.setattr(capture.time, "sleep", lambda _seconds: None)

    result = capture._wait_idle(client, "session-1", "event-1")

    assert result.status == "idle"


def test_anthropic_error_recognises_sdk_root_module():
    capture = _capture_module()

    class FakeRootError(Exception):
        pass

    FakeRootError.__module__ = "anthropic"

    assert capture._is_anthropic_error(FakeRootError()) is True


def test_delete_session_interrupts_running_work_and_verifies_absence(monkeypatch):
    capture = _capture_module()

    class FakeNotFoundError(Exception):
        pass

    FakeNotFoundError.__module__ = "anthropic.fake"
    FakeNotFoundError.__name__ = "NotFoundError"

    class Events:
        @staticmethod
        def send(*_args, **_kwargs):
            return SimpleNamespace(data=[SimpleNamespace(id="interrupt-1")])

    class Sessions:
        def __init__(self):
            self.events = Events()
            self.delete_calls = 0
            self.retrieve_calls = 0

        def delete(self, *_args, **_kwargs):
            self.delete_calls += 1
            if self.delete_calls == 1:
                raise RuntimeError("running")

        def retrieve(self, *_args, **_kwargs):
            self.retrieve_calls += 1
            if self.retrieve_calls == 1:
                return SimpleNamespace(status="running")
            raise FakeNotFoundError()

    sessions = Sessions()
    client = SimpleNamespace(beta=SimpleNamespace(sessions=sessions))
    monkeypatch.setattr(capture, "_wait_idle", lambda *_args: SimpleNamespace(status="idle"))

    capture._delete_session(client, "session-1")

    assert sessions.delete_calls == 2
