"""Exercise pinned workflow inputs through the real Action subprocesses."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from test_action_gate import (
    EXAMPLES,
    action_check,
    action_gate,
    commit_review,
    git,
    outputs,
)
from test_action_gate import (
    workspace as workspace,
)

from agentmandate import loads
from agentmandate._change_review import evaluate
from agentmandate._required_workflows import _Requirements


@pytest.fixture
def workflow_workspace(workspace, monkeypatch):
    git(workspace, "init", "-q")
    policies = workspace / "policies"
    policies.mkdir()
    shutil.copy(EXAMPLES / "release-workflows/released.json", policies / "released.json")
    shutil.copy(EXAMPLES / "release-workflows/required-export.json", policies / "required.json")
    shutil.copy(EXAMPLES / "release-workflows/breaking.json", workspace / "candidate.json")
    git(workspace, "add", "policies")
    git(workspace, "commit", "-qm", "Synthetic baseline workflow")
    git(workspace, "update-ref", "refs/heads/baseline", "HEAD")
    for name, value in {
        "MANIFEST": "candidate.json", "BASELINE": "policies/released.json", "DEPTH": "4",
        "REQUIRED_WORKFLOWS": "policies/required.json",
        "REQUIRED_WORKFLOWS_REF": "refs/heads/baseline",
    }.items():
        monkeypatch.setenv(f"INPUT_{name}", value)
    return workspace


def add_review(workspace, monkeypatch, *, include_workflows=True):
    before = (workspace / "policies/released.json").read_bytes()
    required = _Requirements.load(
        (workspace / "policies/required.json").read_bytes(), loads(before.decode()),
        hashlib.sha256(before).hexdigest(),
    )
    result = evaluate(
        before, (workspace / "candidate.json").read_bytes(), as_of="2026-10-16", depth=4,
        required_workflows=required if include_workflows else None,
    )
    directory = workspace / "reviews"
    directory.mkdir()
    note = b"Synthetic, exact release review; not deployment approval.\n"
    record = {
        "schema": "agentmandate.change-review/v1", **result["inputs"],
        "scope": "all_widening_changes_in_pinned_comparison", "owner": "synthetic-owner",
        "reviewer": "synthetic-reviewer", "reason": "Synthetic matched comparison",
        "decision": "accept", "reviewed_at": "2026-10-16", "expires": "2026-11-30",
        "evidence": [{"locator": "note", "sha256": hashlib.sha256(note).hexdigest(),
                      "purpose": "decision"}],
        "target_policy": {"status": "not_applicable", "reason": "synthetic only"},
    }
    (directory / "decision.json").write_text(json.dumps(record))
    (directory / "note.txt").write_bytes(note)
    commit_review(workspace)
    for name, value in {
        "REVIEW_REF": "refs/heads/reviews", "REVIEW_DECISION": "reviews/decision.json",
        "REVIEW_SOURCES": "note=reviews/note.txt", "REVIEW_AS_OF": "2026-10-16",
    }.items():
        monkeypatch.setenv(f"INPUT_{name}", value)


def sarif_results(workspace):
    log = json.loads(Path(outputs(workspace)["sarif-file"]).read_text())
    return [result for run in log["runs"] for result in run["results"]]


def test_narrowing_regression_is_counted_and_visible_in_all_reports(workflow_workspace):
    assert action_gate.main() == 1
    diff = action_check(workflow_workspace, "diff")
    assert diff["result"]["direction"] == "narrowing"
    assert diff["findings"] == diff["workflow_regressions"] == 1
    assert diff["widening_findings"] == 0
    assert outputs(workflow_workspace)["findings"] == "1"
    assert outputs(workflow_workspace)["verdict"] == "findings"
    selection = diff["workflow_selection"]
    assert selection["commit"] == git(workflow_workspace, "rev-parse", "baseline")
    assert selection["source_sha256"] == hashlib.sha256(
        (workflow_workspace / "policies/required.json").read_bytes()
    ).hexdigest()
    summary = (workflow_workspace / "summary.md").read_text()
    assert selection["source_sha256"] in summary and selection["commit"] in summary
    assert "bulk-export: regressed; step 2 workflow.ceiling-exceeded" in summary
    result, = sarif_results(workflow_workspace)
    assert result["ruleId"] == "workflow.regressed" and result["level"] == "error"
    assert result["properties"]["failure"]["step"] == 2
    assert result["properties"]["inputs"]["source_sha256"] == selection["source_sha256"]
    assert not list(workflow_workspace.glob("agentmandate-workflows-*"))


def test_preserved_narrowing_passes_and_still_reports_pins(workflow_workspace):
    shutil.copy(EXAMPLES / "action-workflows/preserved.json", workflow_workspace / "candidate.json")
    assert action_gate.main() == 0
    assert outputs(workflow_workspace)["findings"] == "0"
    assert "bulk-export: preserved" in (workflow_workspace / "summary.md").read_text()
    assert sarif_results(workflow_workspace) == []


def test_report_only_retains_workflow_regression(workflow_workspace, monkeypatch):
    monkeypatch.setenv("INPUT_FAIL_ON", "never")
    assert action_gate.main() == 0
    assert outputs(workflow_workspace)["verdict"] == "findings"
    assert action_check(workflow_workspace, "diff")["findings"] == 1
    assert sarif_results(workflow_workspace)[0]["ruleId"] == "workflow.regressed"


def test_working_tree_cannot_weaken_or_remove_required_work(workflow_workspace):
    path = workflow_workspace / "policies/required.json"
    raw = json.loads(path.read_text())
    raw["workflows"][0]["steps"][1]["value"] = "1"
    path.write_text(json.dumps(raw))
    assert action_gate.main() == 1
    path.unlink()
    assert action_gate.main() == 1
    assert action_check(workflow_workspace, "diff")["workflow_regressions"] == 1


@pytest.mark.parametrize("name", ["BASELINE", "REQUIRED_WORKFLOWS", "REQUIRED_WORKFLOWS_REF"])
def test_partial_workflow_configuration_is_a_counted_failure(workflow_workspace, monkeypatch, name):
    monkeypatch.delenv(f"INPUT_{name}")
    assert action_gate.main() == 1
    check = action_check(workflow_workspace, "required-workflows")
    assert check["exit"] == 2 and check["findings"] == 1
    assert "required workflows need" in check["detail"]
    assert sarif_results(workflow_workspace)[0]["ruleId"] == "workflow.invalid"


@pytest.mark.parametrize("path", ["../required.json", "./policies/required.json", "policies/*",
                                  "policies", "missing.json"])
def test_invalid_workflow_paths_never_fall_back_to_checkout(workflow_workspace, monkeypatch, path):
    monkeypatch.setenv("INPUT_REQUIRED_WORKFLOWS", path)
    assert action_gate.main() == 1
    assert action_check(workflow_workspace, "required-workflows")["exit"] == 2
    # The independent ordinary authority comparison is retained.
    assert action_check(workflow_workspace, "diff")["result"]["direction"] == "narrowing"


def test_pinned_symlink_is_refused(workflow_workspace):
    path = workflow_workspace / "policies/required.json"
    path.unlink()
    path.symlink_to("released.json")
    git(workflow_workspace, "add", "policies")
    git(workflow_workspace, "commit", "-qm", "Synthetic symlink")
    git(workflow_workspace, "update-ref", "refs/heads/baseline", "HEAD")
    assert action_gate.main() == 1
    assert "not a regular file" in action_check(workflow_workspace, "required-workflows")["detail"]


@pytest.mark.parametrize("kind", ["syntax", "binding", "impossible"])
def test_pinned_invalid_annotations_are_not_clean(workflow_workspace, kind):
    path = workflow_workspace / "policies/required.json"
    raw = json.loads(path.read_text())
    if kind == "binding":
        raw["manifest_sha256"] = "0" * 64
    elif kind == "impossible":
        raw["workflows"][0]["steps"][1]["value"] = "400"
    path.write_text("{" if kind == "syntax" else json.dumps(raw))
    git(workflow_workspace, "add", "policies")
    git(workflow_workspace, "commit", "-qm", "Synthetic invalid annotations")
    git(workflow_workspace, "update-ref", "refs/heads/baseline", "HEAD")
    assert action_gate.main() == 1
    diff = action_check(workflow_workspace, "diff")
    assert diff["exit"] == 2 and diff["findings"] > 0
    assert sarif_results(workflow_workspace)[0]["ruleId"] == "workflow.invalid"


def test_a_matched_review_cannot_waive_a_regression(workflow_workspace, monkeypatch):
    add_review(workflow_workspace, monkeypatch)
    assert action_gate.main() == 1
    assert action_check(workflow_workspace, "diff")["workflow_regressions"] == 1
    review = action_check(workflow_workspace, "review")
    assert [f["rule"] for f in review["result"]["findings"]] == [
        "review.required-workflow-regressed"
    ]
    assert "blocks_gate" not in action_check(workflow_workspace, "diff")


def test_widening_acceptance_uses_the_same_pinned_annotation(workflow_workspace, monkeypatch):
    shutil.copy(EXAMPLES / "action-workflows/widened.json", workflow_workspace / "candidate.json")
    add_review(workflow_workspace, monkeypatch)
    assert action_gate.main() == 0
    diff = action_check(workflow_workspace, "diff")
    review = action_check(workflow_workspace, "review")
    assert diff["result"] == review["result"]["comparison"]
    assert diff["accepted_widenings"] > 0 and diff["blocking_findings"] == 0
    assert diff["workflow_regressions"] == 0


def test_flag_free_acceptance_cannot_cover_checked_workflows(workflow_workspace, monkeypatch):
    shutil.copy(EXAMPLES / "action-workflows/widened.json", workflow_workspace / "candidate.json")
    add_review(workflow_workspace, monkeypatch, include_workflows=False)
    assert action_gate.main() == 1
    assert "review.comparison-mismatch" in {
        f["rule"] for f in action_check(workflow_workspace, "review")["result"]["findings"]
    }


def test_changed_pinned_annotations_require_new_acceptance(workflow_workspace, monkeypatch):
    shutil.copy(EXAMPLES / "action-workflows/widened.json", workflow_workspace / "candidate.json")
    add_review(workflow_workspace, monkeypatch)
    path = workflow_workspace / "policies/required.json"
    path.write_bytes(path.read_bytes() + b"\n")
    git(workflow_workspace, "add", "policies")
    git(workflow_workspace, "commit", "-qm", "Synthetic annotation substitution")
    git(workflow_workspace, "update-ref", "refs/heads/baseline", "HEAD")
    assert action_gate.main() == 1
    assert "review.comparison-mismatch" in {
        f["rule"] for f in action_check(workflow_workspace, "review")["result"]["findings"]
    }


def test_ref_changes_mid_run_do_not_replace_the_snapshot(workflow_workspace, monkeypatch):
    add_review(workflow_workspace, monkeypatch)
    initial = git(workflow_workspace, "rev-parse", "baseline")
    original_run = action_gate.run_json

    def moving_ref(args):
        result = original_run(args)
        if args[0] == "diff":
            path = workflow_workspace / "policies/required.json"
            raw = json.loads(path.read_text())
            raw["workflows"][0]["steps"][1]["value"] = "1"
            path.write_text(json.dumps(raw))
            git(workflow_workspace, "add", "policies")
            git(workflow_workspace, "commit", "-qm", "Synthetic moving ref")
            git(workflow_workspace, "update-ref", "refs/heads/baseline", "HEAD")
        return result

    monkeypatch.setattr(action_gate, "run_json", moving_ref)
    assert action_gate.main() == 1
    diff = action_check(workflow_workspace, "diff")
    review = action_check(workflow_workspace, "review")
    assert diff["workflow_selection"]["commit"] == initial
    assert diff["result"] == review["result"]["comparison"]
    assert diff["workflow_regressions"] == 1


@pytest.mark.parametrize("ref", ["does-not-exist", "--all"])
def test_invalid_workflow_refs_fail_closed(workflow_workspace, monkeypatch, ref):
    monkeypatch.setenv("INPUT_REQUIRED_WORKFLOWS_REF", ref)
    assert action_gate.main() == 1
    assert action_check(workflow_workspace, "required-workflows")["exit"] == 2


def test_report_only_configuration_error_remains_a_finding(workflow_workspace, monkeypatch):
    monkeypatch.delenv("INPUT_REQUIRED_WORKFLOWS_REF")
    monkeypatch.setenv("INPUT_FAIL_ON", "never")
    assert action_gate.main() == 0
    assert outputs(workflow_workspace)["verdict"] == "findings"
    assert int(outputs(workflow_workspace)["findings"]) > 0


def test_git_replace_cannot_weaken_the_pinned_annotation(workflow_workspace):
    original = git(workflow_workspace, "rev-parse", "baseline")
    path = workflow_workspace / "policies/required.json"
    raw = json.loads(path.read_text())
    raw["workflows"][0]["steps"][1]["value"] = "1"
    path.write_text(json.dumps(raw))
    git(workflow_workspace, "add", "policies")
    git(workflow_workspace, "commit", "-qm", "Synthetic replacement")
    replacement = git(workflow_workspace, "rev-parse", "HEAD")
    git(workflow_workspace, "replace", original, replacement)
    assert action_gate.main() == 1
    assert action_check(workflow_workspace, "diff")["workflow_selection"]["commit"] == original
    assert action_check(workflow_workspace, "diff")["workflow_regressions"] == 1


def test_sarif_manifest_locations_are_uri_encoded(workflow_workspace, monkeypatch):
    candidate = workflow_workspace / "candidate #1.json"
    shutil.copy(workflow_workspace / "candidate.json", candidate)
    monkeypatch.setenv("INPUT_MANIFEST", candidate.name)
    assert action_gate.main() == 1
    location = sarif_results(workflow_workspace)[0]["locations"][0]
    assert location["physicalLocation"]["artifactLocation"]["uri"] == "candidate%20%231.json"


def test_review_for_a_different_comparison_cannot_clear_the_diff(workflow_workspace, monkeypatch):
    shutil.copy(EXAMPLES / "action-workflows/widened.json", workflow_workspace / "candidate.json")
    add_review(workflow_workspace, monkeypatch)
    original_review = action_gate._review_check

    def different_comparison(*args):
        review = original_review(*args)
        assert review["ok"]
        review["result"]["comparison"]["direction"] = "neutral"
        return review

    monkeypatch.setattr(action_gate, "_review_check", different_comparison)
    assert action_gate.main() == 1
    assert "blocks_gate" not in action_check(workflow_workspace, "diff")
    assert "do not match" in action_check(workflow_workspace, "review")["detail"]
