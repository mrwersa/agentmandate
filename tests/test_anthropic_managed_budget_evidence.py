import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_protocol_records_the_excluded_pilot_and_frozen_confirmation_cap():
    protocol = json.loads((EVIDENCE / "protocol.json").read_text())

    assert protocol["status"] == "pilot_complete_confirmation_not_implemented"
    assert protocol["pilot"]["excluded_from_confirmation"] is True
    assert protocol["pilot"]["max_work_units_per_session"] == 8
    assert protocol["confirmation"]["trials_per_cell"] == 10
    assert protocol["confirmation"]["cap_minor_units"] == 1
    assert protocol["confirmation"]["max_work_units_per_budget"] == 8
    assert protocol["confirmation"]["random_seed"] == 20260830
    assert protocol["binding"]["managed_platform_verifies_binding"] is False
    binding_bytes = (
        json.dumps(protocol["binding"]["canonical_record"], sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    assert hashlib.sha256(binding_bytes).hexdigest() == protocol["binding"]["sha256"]
    assert protocol["confirmation"]["cells"] == [
        "sequential_control",
        "fresh_session_replication",
        "cap_revision_control",
        "agent_revision_unmeasurable",
        "subagent_handoff",
        "concurrent_subagents_2",
        "concurrent_subagents_4",
    ]


def test_multiagent_protocol_freezes_topology_and_nonreplacement_rules():
    protocol = json.loads((EVIDENCE / "multiagent-protocol.json").read_text())

    assert protocol["status"] == "capability_pending_confirmation_not_implemented"
    assert protocol["binding_sha256"] == json.loads(
        (EVIDENCE / "protocol.json").read_text()
    )["binding"]["sha256"]
    assert {name: cell["child_count"] for name, cell in protocol["cells"].items()} == {
        "subagent_handoff": 1,
        "concurrent_subagents_2": 2,
        "concurrent_subagents_4": 4,
    }
    assert protocol["eligibility"]["confirmation_retries"] == 0
    assert protocol["eligibility"]["nonconforming_trials"].startswith("retain and report")


def test_multiagent_capability_refuses_after_protocol_status_changes(tmp_path, monkeypatch):
    capture = _capture_module()
    monkeypatch.setattr(
        capture,
        "_load_multiagent_protocol",
        lambda: {"status": "capability_complete"},
    )

    with pytest.raises(RuntimeError, match="capability is closed"):
        capture.multiagent_capability(tmp_path / "private-output")


def test_multiagent_capability_summary_proves_topology_without_live_identifiers():
    text = (EVIDENCE / "multiagent-capability-summary.json").read_text()
    summary = json.loads(text)

    assert summary["excluded_from_confirmation"] is True
    assert summary["protocol_sha256"] == hashlib.sha256(
        (EVIDENCE / "multiagent-protocol.json").read_bytes()
    ).hexdigest()
    assert [cell["requested_children"] for cell in summary["cells"]] == [1, 2, 4]
    assert [cell["observed_children"] for cell in summary["cells"]] == [1, 2, 4]
    assert [cell["final_list_cost_minor_units"] for cell in summary["cells"]] == [2, 4, 6]
    assert all(cell["primary_threads"] == 1 for cell in summary["cells"])
    assert all(cell["all_children_attached_to_primary"] for cell in summary["cells"])
    assert all(
        cell["all_children_created_before_first_child_idle"] for cell in summary["cells"]
    )
    assert summary["cleanup"] == {
        "sessions_deleted_and_verified_absent": 3,
        "agents_archived": 2,
        "environment_deleted": True,
    }
    assert re.search(r"\b(?:sesn|sthr|agent|env|ws)_[A-Za-z0-9]{12,}\b", text) is None


def test_multiagent_topology_requires_exact_parentage_and_event_backed_overlap():
    capture = _capture_module()
    primary = SimpleNamespace(id="primary", parent_thread_id=None)
    child_a = SimpleNamespace(id="child-a", parent_thread_id="primary")
    child_b = SimpleNamespace(id="child-b", parent_thread_id="primary")
    snapshot = {
        "threads": [primary, child_a, child_b],
        "events": [
            SimpleNamespace(type="session.thread_created", session_thread_id="child-a"),
            SimpleNamespace(type="session.thread_created", session_thread_id="child-b"),
            SimpleNamespace(type="session.thread_status_running", session_thread_id="child-a"),
            SimpleNamespace(type="session.thread_status_running", session_thread_id="child-b"),
            SimpleNamespace(type="session.thread_status_idle", session_thread_id="child-a"),
        ],
    }

    assert capture._multiagent_topology(snapshot, 2) == {
        "requested_children": 2,
        "observed_primary_threads": 1,
        "observed_children": 2,
        "all_children_attached_to_primary": True,
        "all_children_created_before_first_child_idle": True,
        "all_children_running_before_first_child_idle": True,
        "protocol_conformant": True,
    }

    snapshot["events"] = [
        snapshot["events"][0],
        snapshot["events"][1],
        snapshot["events"][2],
        snapshot["events"][4],
        snapshot["events"][3],
    ]
    assert capture._multiagent_topology(snapshot, 2)["protocol_conformant"] is False


def test_single_child_topology_does_not_claim_concurrent_overlap():
    capture = _capture_module()
    snapshot = {
        "threads": [
            SimpleNamespace(id="primary", parent_thread_id=None),
            SimpleNamespace(id="child", parent_thread_id="primary"),
        ],
        "events": [],
    }

    topology = capture._multiagent_topology(snapshot, 1)

    assert topology["all_children_created_before_first_child_idle"] is False
    assert topology["all_children_running_before_first_child_idle"] is False
    assert topology["protocol_conformant"] is True


def test_multiagent_topology_rejects_wrong_parent_and_missing_primary():
    capture = _capture_module()
    wrong_parent = {
        "threads": [
            SimpleNamespace(id="primary", parent_thread_id=None),
            SimpleNamespace(id="child", parent_thread_id="different"),
        ],
        "events": [],
    }
    no_primary = {
        "threads": [SimpleNamespace(id="child", parent_thread_id="missing")],
        "events": [],
    }

    assert capture._multiagent_topology(wrong_parent, 1)["protocol_conformant"] is False
    assert capture._multiagent_topology(no_primary, 1)["protocol_conformant"] is False


def test_multiagent_confirmation_preserves_concurrency_result_without_identifiers():
    text = (EVIDENCE / "multiagent-confirmation.json").read_text()
    result = json.loads(text)
    trials = result["trials"]

    assert result["protocol_sha256"] == hashlib.sha256(
        (EVIDENCE / "multiagent-protocol.json").read_bytes()
    ).hexdigest()
    assert len(result["raw_capture_sha256"]) == 32
    assert len(trials) == 30
    assert [trial["order"] for trial in trials] == list(range(1, 31))
    assert all(trial["topology"]["protocol_conformant"] for trial in trials)
    assert all(trial["idle_reason"] == "budget_reached" for trial in trials)
    assert all(
        trial["post_budget_refusal"]["api_error_type"] == "invalid_request_error"
        for trial in trials
    )

    cells = {
        name: [trial for trial in trials if trial["cell"] == name]
        for name in (
            "subagent_handoff",
            "concurrent_subagents_2",
            "concurrent_subagents_4",
        )
    }
    assert all(len(cell) == 10 for cell in cells.values())
    assert sorted(trial["list_cost_minor_units"] for trial in cells["subagent_handoff"]) == [
        1,
        1,
        1,
        1,
        2,
        2,
        2,
        2,
        2,
        2,
    ]
    assert sorted(
        trial["list_cost_minor_units"] for trial in cells["concurrent_subagents_2"]
    ) == [2] * 9 + [3]
    assert [
        trial["list_cost_minor_units"] for trial in cells["concurrent_subagents_4"]
    ] == [4] * 10
    assert all(
        trial["topology"]["all_children_running_before_first_child_idle"]
        for name in ("concurrent_subagents_2", "concurrent_subagents_4")
        for trial in cells[name]
    )
    assert result["cleanup"] == {
        "sessions_deleted_and_verified_absent": 30,
        "agents_archived": 2,
        "environment_deleted": True,
    }
    assert re.search(r"\b(?:sesn|sthr|agent|env|ws)_[A-Za-z0-9]{12,}\b", text) is None
    assert "processed_at" not in text


def test_capture_uses_managed_beta_and_pinned_sdk():
    capture = _capture_module()

    assert capture.BETAS == ["managed-agents-2026-04-01"]
    assert (EVIDENCE / "requirements-capture.txt").read_text() == "anthropic==1.2.0\n"


def test_private_capture_outputs_and_environment_are_gitignored():
    ignored = (ROOT / ".gitignore").read_text().splitlines()

    assert ".capture-venv/" in ignored
    assert "private-*/" in ignored


def test_confirmation_refuses_without_api_credentials(tmp_path, monkeypatch, capsys):
    capture = _capture_module()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert capture.main(["confirm", "--output", str(tmp_path / "confirm")]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_pilot_summary_selects_one_cent_without_live_identifiers():
    summary_text = (EVIDENCE / "pilot-summary.json").read_text()
    summary = json.loads(summary_text)

    assert summary["excluded_from_confirmation"] is True
    assert summary["selected_confirmation_cap_minor_units"] == 1
    assert [item["work_units_to_first_non_zero_cost"] for item in summary["pilot_sessions"]] == [
        2,
        3,
        2,
    ]
    assert summary["cleanup"]["sessions_deleted_and_verified_absent"] == 3
    assert re.search(r"\b(?:sesn|agent|env)_[A-Za-z0-9]{16,}\b", summary_text) is None


def test_single_agent_confirmation_preserves_session_boundary_results_without_identifiers():
    text = (EVIDENCE / "confirmation.json").read_text()
    result = json.loads(text)
    trials = result["trials"]

    assert result["evidence_version"] == 1
    assert result["protocol_sha256"] == hashlib.sha256(
        (EVIDENCE / "protocol.json").read_bytes()
    ).hexdigest()
    assert len(result["raw_capture_sha256"]) == 32
    assert len(trials) == 30
    assert [trial["order"] for trial in trials] == list(range(1, 31))

    sequential = [trial for trial in trials if trial["cell"] == "sequential_control"]
    fresh = [trial for trial in trials if trial["cell"] == "fresh_session_replication"]
    revised = [trial for trial in trials if trial["cell"] == "cap_revision_control"]
    assert len(sequential) == len(fresh) == len(revised) == 10
    assert all(trial["work_units"][-1]["idle_reason"] == "budget_reached" for trial in sequential)
    assert all(trial["work_units"][-1]["list_cost_minor_units"] == 1 for trial in sequential)
    assert all(
        trial["post_budget_refusal"]["api_error_type"] == "invalid_request_error"
        for trial in sequential
    )
    assert all(len(trial["sessions"]) == 2 for trial in fresh)
    assert all(
        session["work_units"][-1]["idle_reason"] == "budget_reached"
        and session["work_units"][-1]["list_cost_minor_units"] == 1
        for trial in fresh
        for session in trial["sessions"]
    )
    assert all(
        trial["revision"]
        == {"cap_after": 2, "consumed_before": 1, "cost_immediately_after": 1}
        for trial in revised
    )
    assert all(trial["after_revision"][-1]["idle_reason"] == "budget_reached" for trial in revised)
    assert sorted(
        trial["after_revision"][-1]["list_cost_minor_units"] for trial in revised
    ) == [2] * 9 + [3]
    assert result["cleanup"] == {
        "agent_archived": True,
        "environment_deleted": True,
        "sessions_deleted_and_verified_absent": 40,
    }
    assert re.search(r"\b(?:sesn|agent|env|ws)_[A-Za-z0-9]{12,}\b", text) is None
    assert "processed_at" not in text


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
