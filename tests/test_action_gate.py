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

_spec = importlib.util.spec_from_file_location("action_gate", ROOT / "scripts" / "action_gate.py")
assert _spec is not None and _spec.loader is not None
action_gate = importlib.util.module_from_spec(_spec)
sys.modules["action_gate"] = action_gate
_spec.loader.exec_module(action_gate)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("dispute-resolver.yaml", "dispute-resolver-v2.yaml", "otel-trace.json"):
        shutil.copy(EXAMPLES / name, tmp_path / name)
    monkeypatch.setattr(action_gate, "WORKSPACE", tmp_path)
    monkeypatch.setattr(action_gate, "ARTEFACTS", tmp_path)
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
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line
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


def test_only_the_checks_with_inputs_run(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    # The count alone does not pin the property. What matters is that removing
    # authority does not block a release, and that rests on `diff` exiting
    # zero when nothing widened. Asserting the exit code catches a change in
    # that behaviour; asserting the count would not.
    assert action_gate.main() == 0

    report = json.loads((workspace / "agentmandate-report.json").read_text())
    diff = next(c for c in report["checks"] if c["name"] == "diff")

    assert diff["findings"] == 0
    assert diff["ok"] is True
    assert outputs(workspace)["verdict"] == "clean"


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


def test_sarif_can_be_turned_off(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        for name in yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))["inputs"]
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


def test_a_lint_warning_is_reported_without_blocking(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean verdict must never mean nothing was found.

    `lint` exits zero on a warning and non-zero on an error. Counting both
    into one number produced `verdict=clean` beside `findings=1`, a
    self-contradicting pair, and the warning appeared nowhere in the summary.
    Silencing it would have made the arithmetic agree by losing a real
    finding, which is the failure this package is about.
    """
    (workspace / "warned.yaml").write_text(
        "version: 1\n"
        "agent: warner\n"
        "limits: { total: { amount: 500, currency: GBP }, depth: 8 }\n"
        "tools:\n"
        "  - { name: open_case, effect: read, principal: caller, produces: case }\n"
        "  - { name: list_notes, effect: read, principal: service, requires: [case] }\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INPUT_MANIFEST", "warned.yaml")

    assert action_gate.main() == 0

    out = outputs(workspace)
    assert out["verdict"] == "clean"
    assert out["findings"] == "0"
    assert out["notes"] == "1"

    summary = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "Advisory, not blocking" in summary
    assert "service-principal" in summary
    # Neither a tick nor a cross: a tick is what hid it.
    assert "| ⚠️ | `lint` |" in summary


def test_an_error_still_blocks_and_is_not_a_note(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (workspace / "broken.yaml").write_text(
        "version: 1\n"
        "agent: broken\n"
        "limits: { total: { amount: 500, currency: GBP }, depth: 8 }\n"
        "tools:\n"
        "  - { name: open_case, effect: read, principal: caller, produces: case }\n"
        "  - { name: pay, effect: irreversible, principal: service, requires: [case] }\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INPUT_MANIFEST", "broken.yaml")

    assert action_gate.main() == 1

    out = outputs(workspace)
    assert out["verdict"] == "findings"
    assert int(out["findings"]) >= 1
    assert out["notes"] == "0"


def test_artefacts_stay_out_of_the_checkout(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dirty working tree is somebody else's failing build."""
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    monkeypatch.setattr(action_gate, "ARTEFACTS", runner_temp)
    monkeypatch.setenv("INPUT_MANIFEST", "dispute-resolver-v2.yaml")
    action_gate.main()

    assert (runner_temp / "agentmandate.sarif").exists()
    assert not (workspace / "agentmandate.sarif").exists()
    assert not (workspace / "agentmandate-report.json").exists()
    assert outputs(workspace)["sarif-file"].startswith(str(runner_temp))


def git(workspace: Path, *args: str) -> str:
    import subprocess

    return subprocess.check_output(
        [
            "git",
            "-c",
            "user.name=Synthetic reviewer",
            "-c",
            "user.email=review@example.invalid",
            *args,
        ],
        cwd=workspace,
        text=True,
    ).strip()


def commit_review(workspace: Path) -> str:
    git(workspace, "add", "reviews")
    git(workspace, "commit", "-qm", "Synthetic review materials")
    commit = git(workspace, "rev-parse", "HEAD")
    git(workspace, "update-ref", "refs/heads/reviews", commit)
    return commit


@pytest.fixture
def reviewed_workspace(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import hashlib

    from agentmandate._change_review import evaluate

    git(workspace, "init", "-q")
    before = json.loads((EXAMPLES / "change-review/before.json").read_text())
    before["limits"]["effects"] = {"irreversible": 3}
    after = json.loads(json.dumps(before))
    after["limits"]["effects"]["irreversible"] = 5
    for name, value in (("before", before), ("after", after)):
        (workspace / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    result = evaluate(
        (workspace / "before.json").read_bytes(),
        (workspace / "after.json").read_bytes(),
        as_of="2026-10-10",
        depth=2,
    )
    record = json.loads((EXAMPLES / "change-review/accepted.json").read_text())
    record.update(result["inputs"])
    review_dir = workspace / "reviews"
    review_dir.mkdir()
    note = b"Synthetic acceptance of this bounded allowance increase."
    (review_dir / "note.txt").write_bytes(note)
    record["evidence"][0]["sha256"] = hashlib.sha256(note).hexdigest()
    (review_dir / "decision.json").write_text(json.dumps(record), encoding="utf-8")
    commit_review(workspace)
    for name, value in {
        "MANIFEST": "after.json",
        "BASELINE": "before.json",
        "DEPTH": "2",
        "REVIEW_REF": "refs/heads/reviews",
        "REVIEW_DECISION": "reviews/decision.json",
        "REVIEW_SOURCES": "review-note=reviews/note.txt",
        "REVIEW_AS_OF": "2026-10-10",
        "SARIF": "false",
    }.items():
        monkeypatch.setenv(f"INPUT_{name}", value)
    return workspace


def action_report(workspace: Path) -> dict:
    return json.loads((workspace / "agentmandate-report.json").read_text())


def action_check(workspace: Path, name: str) -> dict:
    return next(c for c in action_report(workspace)["checks"] if c["name"] == name)


def test_pinned_acceptance_resolves_only_the_diff_blocker(reviewed_workspace: Path) -> None:
    assert action_gate.main() == 0
    diff = action_check(reviewed_workspace, "diff")
    review = action_check(reviewed_workspace, "review")
    assert diff["ok"] is False and diff["findings"] > 0
    assert diff["blocking_findings"] == 0 and diff["blocks_gate"] is False
    assert diff["accepted_widenings"] == diff["findings"]
    assert review["result"]["status"] == "eligible_recorded_acceptance"
    assert review["selection"]["commit"] == git(reviewed_workspace, "rev-parse", "reviews")
    assert outputs(reviewed_workspace)["findings"] == "0"
    summary = (reviewed_workspace / "summary.md").read_text()
    assert "widening change(s) with recorded acceptance" in summary
    assert "not deployment approval" in summary
    assert "**`diff`**" in summary
    assert not list(reviewed_workspace.glob("agentmandate-review-*"))


def test_candidate_working_tree_cannot_supply_acceptance(reviewed_workspace: Path) -> None:
    path = reviewed_workspace / "reviews/decision.json"
    accepted = path.read_bytes()
    record = json.loads(accepted)
    record["decision"] = "defer"
    path.write_text(json.dumps(record), encoding="utf-8")
    commit_review(reviewed_workspace)
    path.write_bytes(accepted)
    assert action_gate.main() == 1
    assert action_check(reviewed_workspace, "review")["result"]["review"]["decision"] == "defer"
    assert "blocks_gate" not in action_check(reviewed_workspace, "diff")


def test_candidate_source_edits_do_not_replace_pinned_sources(reviewed_workspace: Path) -> None:
    (reviewed_workspace / "reviews/note.txt").write_bytes(b"Untrusted working-tree replacement")
    (reviewed_workspace / "reviews/decision.json").write_bytes(b"malformed replacement")
    assert action_gate.main() == 0


def test_tampered_pinned_source_blocks_review(reviewed_workspace: Path) -> None:
    with (reviewed_workspace / "reviews/note.txt").open("ab") as handle:
        handle.write(b" ")
    commit_review(reviewed_workspace)
    assert action_gate.main() == 1
    assert action_check(reviewed_workspace, "review")["ok"] is False
    assert "blocks_gate" not in action_check(reviewed_workspace, "diff")


@pytest.mark.parametrize("date", ["2026-10-09", "2026-11-09"])
def test_review_dates_fail_closed(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch, date: str
) -> None:
    monkeypatch.setenv("INPUT_REVIEW_AS_OF", date)
    assert action_gate.main() == 1
    assert action_check(reviewed_workspace, "review")["findings"] > 0


def test_expired_review_still_reports_in_report_only_mode(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_REVIEW_AS_OF", "2026-11-09")
    monkeypatch.setenv("INPUT_FAIL_ON", "never")
    assert action_gate.main() == 0
    assert outputs(reviewed_workspace)["verdict"] == "findings"


def test_review_cannot_clear_a_reachable_breach(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("before.json", "after.json"):
        shutil.copy(EXAMPLES / "change-review" / name, reviewed_workspace / name)
    shutil.copy(
        EXAMPLES / "change-review/accepted.json", reviewed_workspace / "reviews/decision.json"
    )
    shutil.copy(
        EXAMPLES / "change-review/decision-note.txt", reviewed_workspace / "reviews/note.txt"
    )
    commit_review(reviewed_workspace)
    monkeypatch.setenv("INPUT_DEPTH", "4")
    assert action_gate.main() == 1
    assert action_check(reviewed_workspace, "review")["ok"] is True
    assert action_check(reviewed_workspace, "diff")["blocks_gate"] is False
    assert action_check(reviewed_workspace, "reach")["ok"] is False
    assert action_report(reviewed_workspace)["findings"] > 0


def test_review_cannot_clear_drift(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (reviewed_workspace / "agent.py").write_text(
        "from strands import Agent\nagent = Agent(tools=[])\n", encoding="utf-8"
    )
    monkeypatch.setenv("INPUT_SOURCE", "agent.py")
    assert action_gate.main() == 1
    assert action_check(reviewed_workspace, "review")["ok"] is True
    assert action_check(reviewed_workspace, "diff")["blocks_gate"] is False
    assert action_check(reviewed_workspace, "drift")["ok"] is False


@pytest.mark.parametrize("name", ["BASELINE", "REVIEW_REF", "REVIEW_DECISION", "REVIEW_AS_OF"])
def test_partial_review_configuration_is_a_blocker(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.delenv(f"INPUT_{name}")
    assert action_gate.main() == 1
    review = action_check(reviewed_workspace, "review")
    assert review["exit"] == 2 and review["findings"] == 1


@pytest.mark.parametrize(
    "mapping",
    [
        "review-note=reviews/note.txt\nreview-note=reviews/note.txt",
        "missing-separator",
        "=reviews/note.txt",
        "review-note=",
        "unknown=reviews/note.txt",
        "",
    ],
)
def test_invalid_or_incomplete_source_maps_fail_closed(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch, mapping: str
) -> None:
    monkeypatch.setenv("INPUT_REVIEW_SOURCES", mapping)
    assert action_gate.main() == 1
    review = action_check(reviewed_workspace, "review")
    assert review["exit"] == 2 and review["findings"] >= 1


@pytest.mark.parametrize(
    "path",
    [
        "../decision.json",
        "/decision.json",
        "./reviews/decision.json",
        "reviews//decision.json",
        "reviews/",
        "reviews\\decision.json",
        "reviews/\x00decision.json",
        "reviews/decision.json\nelse",
        "reviews",
        "reviews/missing.json",
    ],
)
def test_review_paths_are_literal_regular_files(reviewed_workspace: Path, path: str) -> None:
    with pytest.raises(ValueError):
        action_gate._review_blob(git(reviewed_workspace, "rev-parse", "reviews"), path)


def test_symlink_decision_is_not_followed(reviewed_workspace: Path) -> None:
    path = reviewed_workspace / "reviews/link.json"
    path.symlink_to("decision.json")
    commit = commit_review(reviewed_workspace)
    with pytest.raises(ValueError, match="not a regular file"):
        action_gate._review_blob(commit, "reviews/link.json")


@pytest.mark.parametrize("ref", ["nonexistent-ref", "--all"])
def test_unknown_or_option_like_refs_fail_closed(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch, ref: str
) -> None:
    monkeypatch.setenv("INPUT_REVIEW_REF", ref)
    assert action_gate.main() == 1
    assert action_check(reviewed_workspace, "review")["exit"] == 2


def test_ref_is_resolved_once_before_reading_any_material(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = git(reviewed_workspace, "rev-parse", "reviews")
    path = reviewed_workspace / "reviews/decision.json"
    record = json.loads(path.read_bytes())
    record["decision"] = "reject"
    path.write_text(json.dumps(record), encoding="utf-8")
    rejected = commit_review(reviewed_workspace)
    git(reviewed_workspace, "update-ref", "refs/heads/reviews", accepted)
    original = action_gate._git

    def move_ref(*args: str) -> bytes:
        result = original(*args)
        if args[0] == "rev-parse":
            git(reviewed_workspace, "update-ref", "refs/heads/reviews", rejected)
        return result

    monkeypatch.setattr(action_gate, "_git", move_ref)
    assert action_gate.main() == 0
    assert action_check(reviewed_workspace, "review")["selection"]["commit"] == accepted
    assert git(reviewed_workspace, "rev-parse", "reviews") == rejected


def test_mismatched_action_and_review_comparisons_do_not_clear_diff(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = action_gate.run_json

    def changed_comparison(args: list[str]) -> tuple[int, object]:
        code, result = original(args)
        if args[0] == "review":
            result["comparison"]["direction"] = "neutral"
        return code, result

    monkeypatch.setattr(action_gate, "run_json", changed_comparison)
    assert action_gate.main() == 1
    assert "blocks_gate" not in action_check(reviewed_workspace, "diff")
    assert "do not match" in action_check(reviewed_workspace, "review")["detail"]


def test_review_expiry_is_inclusive(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INPUT_REVIEW_AS_OF", "2026-11-08")
    assert action_gate.main() == 0


def test_changed_candidate_bytes_do_not_inherit_a_record(reviewed_workspace: Path) -> None:
    with (reviewed_workspace / "after.json").open("ab") as handle:
        handle.write(b" ")
    assert action_gate.main() == 1
    assert action_check(reviewed_workspace, "review")["ok"] is False
    assert "blocks_gate" not in action_check(reviewed_workspace, "diff")


def test_malformed_pinned_record_has_a_blocking_usage_finding(reviewed_workspace: Path) -> None:
    (reviewed_workspace / "reviews/decision.json").write_bytes(b"{")
    commit_review(reviewed_workspace)
    assert action_gate.main() == 1
    review = action_check(reviewed_workspace, "review")
    assert review["exit"] == 2 and review["findings"] == 1


def test_local_replace_objects_cannot_replace_review_history(reviewed_workspace: Path) -> None:
    accepted = git(reviewed_workspace, "rev-parse", "reviews")
    path = reviewed_workspace / "reviews/decision.json"
    record = json.loads(path.read_bytes())
    record["decision"] = "reject"
    path.write_text(json.dumps(record), encoding="utf-8")
    rejected = commit_review(reviewed_workspace)
    git(reviewed_workspace, "replace", accepted, rejected)
    git(reviewed_workspace, "update-ref", "refs/heads/reviews", accepted)
    assert action_gate.main() == 0
    assert action_check(reviewed_workspace, "review")["selection"]["commit"] == accepted
    assert action_check(reviewed_workspace, "review")["result"]["review"]["decision"] == "accept"


def test_invalid_resolved_digest_is_not_used_to_read_materials(
    reviewed_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(action_gate, "_git", lambda *args: b"not-a-commit-digest")
    review = action_gate._review_check("before.json", "after.json", "2")
    assert review["ok"] is False and review["exit"] == 2
    assert "commit digest" in review["detail"]
