"""Advisory repairs share frozen inputs and cannot alter the Action gate."""

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_action_gate import EXAMPLES, action_check, action_gate, git, outputs
from test_action_gate import workspace as workspace
from test_action_workflows import add_review

from agentmandate import compare, loads


@pytest.fixture
def repair_workspace(workspace, monkeypatch):
    git(workspace, "init", "-q")
    policies = workspace / "policies"
    policies.mkdir()
    for name, target in (
        ("released.json", "released.json"),
        ("required-export.json", "required.json"),
    ):
        shutil.copy(EXAMPLES / "release-remediation" / name, policies / target)
    shutil.copy(EXAMPLES / "release-remediation/proposed.json", workspace / "candidate.json")
    git(workspace, "add", "policies")
    git(workspace, "commit", "-qm", "Synthetic released manifest and workflows")
    git(workspace, "update-ref", "refs/heads/baseline", "HEAD")
    for name, value in {
        "MANIFEST": "candidate.json",
        "BASELINE": "policies/released.json",
        "DEPTH": "4",
        "REQUIRED_WORKFLOWS": "policies/required.json",
        "REQUIRED_WORKFLOWS_REF": "refs/heads/baseline",
        "SARIF": "false",
        "REPAIR_SUGGESTIONS": "true",
        "REPAIR_KEEP_TOOLS": "select_rows\nexport_rows",
        "REPAIR_CEILING_GRIDS": "export_rows=0:2:1",
    }.items():
        monkeypatch.setenv(f"INPUT_{name}", value)
    return workspace


def report(workspace):
    return json.loads(Path(outputs(workspace)["report"]).read_text())


def repairs(workspace):
    combined = report(workspace)
    assert json.loads(Path(outputs(workspace)["repair-report"]).read_text()) == combined["repairs"]
    return combined["repairs"]


def test_real_candidates_preserve_all_original_checks_counts_and_files(
    repair_workspace, monkeypatch
):
    source = {
        p: (repair_workspace / p).read_bytes()
        for p in ("candidate.json", "policies/released.json", "policies/required.json")
    }
    monkeypatch.setenv("INPUT_REPAIR_SUGGESTIONS", "false")
    assert action_gate.main() == 1
    previous = report(repair_workspace)
    assert "repairs" not in previous and outputs(repair_workspace)["repair-report"] == ""
    monkeypatch.setenv("INPUT_REPAIR_SUGGESTIONS", "true")
    assert action_gate.main() == 1
    current = report(repair_workspace)
    assert {k: v for k, v in current.items() if k != "repairs"} == previous
    repair = repairs(repair_workspace)
    assert repair["status"] == "completed" and repair["exit"] == 1
    assert repair["trigger_checks"] == ["diff"]
    assert (
        repair["result"]["release"]["comparison"]
        == action_check(repair_workspace, "diff")["result"]
    )
    (candidate,) = repair["result"]["candidates"]
    assert candidate["manifest"]["tools"][1]["ceiling"]["amount"] == "2"
    assert [e["kind"] for e in candidate["edits"]] == ["remove_tool", "tighten_ceiling"]
    assert candidate["release"]["gate_passed"]
    assert candidate["impact"]["lost_reachable_tools"] == ["purge_rows"]
    assert (
        repair["selection"]["manifest"]["sha256"]
        == hashlib.sha256(source["candidate.json"]).hexdigest()
    )
    assert (
        repair["workflow_selection"] == action_check(repair_workspace, "diff")["workflow_selection"]
    )
    summary = (repair_workspace / "summary.md").read_text()
    assert "Repair suggestions (advisory; not applied)" in summary
    assert '"truncated": true' in summary and "remove_tool" in summary
    assert '"released_truncated": true' in summary and '"proposed_truncated": true' in summary
    assert '"max-evaluations": 128' in summary and '"display_complete": true' in summary
    assert all((repair_workspace / p).read_bytes() == content for p, content in source.items())
    assert not list(repair_workspace.glob("agentmandate-analysis-*"))
    assert not list(repair_workspace.glob("agentmandate-workflows-*"))


@pytest.mark.parametrize("never", [False, True])
@pytest.mark.parametrize("kind", ["grid", "discovery", "infeasible", "broken", "clean", "cutoff"])
def test_real_modes_keep_the_gate_and_completion_boundaries(
    repair_workspace, monkeypatch, never, kind
):
    if never:
        monkeypatch.setenv("INPUT_FAIL_ON", "never")
    if kind in {"discovery", "cutoff", "clean"}:
        filename = "released.json" if kind == "clean" else "ceiling-only.json"
        shutil.copy(
            EXAMPLES / "release-remediation" / filename, repair_workspace / "candidate.json"
        )
    if kind == "broken":
        monkeypatch.delenv("INPUT_REPAIR_CEILING_GRIDS")
        shutil.copy(
            EXAMPLES / "release-remediation/breaking.json", repair_workspace / "candidate.json"
        )
    if kind in {"discovery", "infeasible", "cutoff"}:
        monkeypatch.delenv("INPUT_REPAIR_CEILING_GRIDS")
        monkeypatch.setenv("INPUT_REPAIR_DISCOVER_CEILINGS", "export_rows=1")
    if kind == "cutoff":
        monkeypatch.setenv("INPUT_REPAIR_MAX_EVALUATIONS", "1")
    expected = 0 if never or kind == "clean" else 1
    assert action_gate.main() == expected
    repair = repairs(repair_workspace)
    assert outputs(repair_workspace)["verdict"] == ("clean" if kind == "clean" else "findings")
    if kind == "clean":
        assert repair["status"] == "not_needed" and "result" not in repair
        return
    assert repair["status"] == "completed" and repair["exit"] == 1
    result = repair["result"]
    if kind in {"infeasible", "broken", "cutoff"}:
        assert not result["candidates"]
    else:
        assert len(result["candidates"]) == 1
    if kind == "infeasible":
        assert result["discovery"]["frontier_complete_within_domain"]
        summary = (repair_workspace / "summary.md").read_text()
        assert '"released_truncated": true' in summary and '"proposed_truncated": true' in summary
    if kind == "cutoff":
        assert not result["discovery"]["frontier_complete_within_domain"]
        assert result["search"]["truncated_by_limit"]


def test_working_tree_and_ref_changes_cannot_replace_selected_inputs(repair_workspace, monkeypatch):
    expected = {
        p: (repair_workspace / p).read_bytes()
        for p in ("candidate.json", "policies/released.json", "policies/required.json")
    }
    commit = git(repair_workspace, "rev-parse", "baseline")
    original = action_gate._diff_check

    def changed(*args):
        diff = original(*args)
        # Swap every working-tree input and move the annotation ref after the
        # initial diff. Repairs and later checks must retain the selected bytes.
        shutil.copy(
            EXAMPLES / "release-remediation/released.json", repair_workspace / "candidate.json"
        )
        (repair_workspace / "policies/released.json").write_text("{}")
        (repair_workspace / "policies/required.json").write_text("{}")
        git(repair_workspace, "add", "policies")
        git(repair_workspace, "commit", "-qm", "Synthetic input replacement attempt")
        git(repair_workspace, "update-ref", "refs/heads/baseline", "HEAD")
        return diff

    monkeypatch.setattr(action_gate, "_diff_check", changed)
    assert action_gate.main() == 1
    repair = repairs(repair_workspace)
    assert repair["status"] == "completed" and len(repair["result"]["candidates"]) == 1
    assert repair["workflow_selection"]["commit"] == commit
    assert (
        repair["workflow_selection"]["source_sha256"]
        == hashlib.sha256(
            expected["policies/required.json"],
        ).hexdigest()
    )
    assert repair["result"]["input"] == {
        "manifest_sha256": hashlib.sha256(expected["candidate.json"]).hexdigest(),
        "released_sha256": hashlib.sha256(expected["policies/released.json"]).hexdigest(),
    }


def test_review_and_repairs_share_one_selected_annotation(repair_workspace, monkeypatch):
    add_review(repair_workspace, monkeypatch)
    monkeypatch.setenv("INPUT_REVIEW_SOURCES", "\n" + os.environ["INPUT_REVIEW_SOURCES"] + "\n\n")
    # Accepted widening alone is not a blocking manifest finding.
    assert action_gate.main() == 0
    assert repairs(repair_workspace)["status"] == "not_needed"
    assert action_check(repair_workspace, "diff")["accepted_widenings"] > 0


def test_recorded_acceptance_cannot_make_a_repaired_breach_clean(repair_workspace, monkeypatch):
    path = repair_workspace / "candidate.json"
    raw = json.loads(path.read_text())
    raw["limits"]["quantities"]["exported_rows"]["amount"] = "4"
    path.write_text(json.dumps(raw))
    add_review(repair_workspace, monkeypatch)
    assert action_gate.main() == 1
    repair = repairs(repair_workspace)
    assert repair["status"] == "completed" and repair["result"]["candidates"]
    assert action_check(repair_workspace, "reach")["ok"] is False
    assert repair["trigger_checks"] == ["reach"]
    assert action_check(repair_workspace, "diff")["accepted_widenings"] > 0
    assert outputs(repair_workspace)["verdict"] == "findings"
    assert (
        repair["workflow_selection"] == action_check(repair_workspace, "diff")["workflow_selection"]
    )
    assert (
        repair["result"]["release"]["comparison"]
        == action_check(repair_workspace, "review")["result"]["comparison"]
    )


@pytest.mark.parametrize("mode", ["missing", "pin", "syntax"])
def test_invalid_workflows_skip_repairs_without_fallback(repair_workspace, monkeypatch, mode):
    if mode == "missing":
        monkeypatch.setenv("INPUT_REQUIRED_WORKFLOWS", "missing.json")
    else:
        path = repair_workspace / "policies/required.json"
        raw = json.loads(path.read_text())
        raw["manifest_sha256"] = "0" * 64
        path.write_text("{" if mode == "syntax" else json.dumps(raw))
        git(repair_workspace, "add", "policies")
        git(repair_workspace, "commit", "-qm", "Synthetic bad annotation")
        git(repair_workspace, "update-ref", "refs/heads/baseline", "HEAD")
    assert action_gate.main() == 1
    repair = repairs(repair_workspace)
    assert repair["status"] == "skipped" and "result" not in repair
    assert outputs(repair_workspace)["verdict"] == "findings"


@pytest.mark.parametrize(
    "field", ["MAX_EDITS", "MAX_EVALUATIONS", "MAX_CANDIDATES", "TIMEOUT_SECONDS"]
)
@pytest.mark.parametrize("value", ["0", "-1", " 1", "1.0", "99999", "no", "01"])
def test_invalid_processing_limits_are_reported(repair_workspace, monkeypatch, field, value):
    monkeypatch.setenv(f"INPUT_REPAIR_{field}", value)
    repair = action_gate._repair_configuration()
    assert repair["status"] == "configuration_error" and "must be an integer" in repair["error"]


@pytest.mark.parametrize(
    "field,maximum",
    [
        ("MAX_EDITS", 8),
        ("MAX_EVALUATIONS", 1024),
        ("MAX_CANDIDATES", 20),
        ("TIMEOUT_SECONDS", 300),
    ],
)
@pytest.mark.parametrize("endpoint", ["minimum", "maximum", "above"])
def test_processing_limit_endpoints_are_explicit(
    repair_workspace,
    monkeypatch,
    field,
    maximum,
    endpoint,
):
    value = 1 if endpoint == "minimum" else maximum + (endpoint == "above")
    monkeypatch.setenv(f"INPUT_REPAIR_{field}", str(value))
    repair = action_gate._repair_configuration()
    assert repair["status"] == ("configuration_error" if endpoint == "above" else "pending")


@pytest.mark.parametrize("case", ["enabled", "missing-baseline", "incompatible", "too-large"])
def test_bad_repair_configuration_does_not_fail_a_clean_gate(repair_workspace, monkeypatch, case):
    shutil.copy(EXAMPLES / "release-remediation/released.json", repair_workspace / "candidate.json")
    if case == "enabled":
        monkeypatch.setenv("INPUT_REPAIR_SUGGESTIONS", "yes")
    elif case == "missing-baseline":
        monkeypatch.delenv("INPUT_BASELINE")
        monkeypatch.delenv("INPUT_REQUIRED_WORKFLOWS")
        monkeypatch.delenv("INPUT_REQUIRED_WORKFLOWS_REF")
    elif case == "incompatible":
        monkeypatch.setenv("INPUT_REPAIR_DISCOVER_CEILINGS", "export_rows=1")
    else:
        monkeypatch.setenv("INPUT_REPAIR_MAX_EDITS", "9")
    assert action_gate.main() == 0
    assert repairs(repair_workspace)["status"] == "configuration_error"
    assert outputs(repair_workspace)["findings"] == "0"
    assert outputs(repair_workspace)["verdict"] == "clean"


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "oserror",
        "usage",
        "json",
        "shape",
        "inputs",
        "comparison",
        "candidate",
        "bounds",
        "nonfinite",
        "nested",
    ],
)
def test_repair_process_failures_cannot_clear_original_findings(
    repair_workspace, monkeypatch, failure
):
    original = action_gate.subprocess.run

    def injected(args, **kwargs):
        if "remediate" not in args:
            return original(args, **kwargs)
        assert kwargs["timeout"] == 60 and "shell" not in kwargs
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 60)
        if failure == "oserror":
            raise OSError("synthetic subprocess unavailable")
        if failure == "usage":
            return subprocess.CompletedProcess(args, 2, "", "synthetic usage error")
        if failure == "json":
            return subprocess.CompletedProcess(args, 1, "{", "")
        completed = original(args, **kwargs)
        raw = json.loads(completed.stdout)
        if failure == "shape":
            raw = []
        elif failure == "inputs":
            raw["input"]["manifest_sha256"] = "0" * 64
        elif failure == "comparison":
            raw["release"]["comparison"] = {}
        elif failure == "candidate":
            raw["candidates"] = [None]
        elif failure == "bounds":
            raw["search"]["max_edits"] = 99
        elif failure == "nonfinite":
            raw["unexpected"] = float("nan")
        else:
            raw["release"] = None
        return subprocess.CompletedProcess(args, completed.returncode, json.dumps(raw), "")

    monkeypatch.setattr(action_gate.subprocess, "run", injected)
    assert action_gate.main() == 1
    repair = repairs(repair_workspace)
    assert repair["status"] == ("timeout" if failure == "timeout" else "error")
    assert "result" not in repair
    assert outputs(repair_workspace)["verdict"] == "findings"
    assert action_check(repair_workspace, "diff")["widening_findings"] == 4


@pytest.mark.parametrize("outside", [False, True])
def test_sarif_uses_original_source_paths_and_lines(
    repair_workspace, monkeypatch, tmp_path, outside
):
    path = repair_workspace / "candidate.json"
    raw = json.loads(path.read_text())
    raw["limits"]["quantities"]["exported_rows"]["amount"] = "4"
    path.write_text(json.dumps(raw, indent=2))
    monkeypatch.setenv("INPUT_SARIF", "true")
    if outside:
        artifacts = tmp_path.parent / ("runner-temp-" + tmp_path.name)
        artifacts.mkdir()
        monkeypatch.setattr(action_gate, "ARTEFACTS", artifacts)
    monkeypatch.setenv("INPUT_REPAIR_SUGGESTIONS", "false")
    assert action_gate.main() == 1
    expected = json.loads(Path(outputs(repair_workspace)["sarif-file"]).read_text())
    monkeypatch.setenv("INPUT_REPAIR_SUGGESTIONS", "true")
    assert action_gate.main() == 1
    actual = json.loads(Path(outputs(repair_workspace)["sarif-file"]).read_text())
    assert actual == expected
    assert all(
        loc["physicalLocation"]["artifactLocation"]["uri"] == "candidate.json"
        for run in actual["runs"]
        for result in run["results"]
        for loc in result["locations"]
    )


@pytest.mark.parametrize("failure", ["snapshot", "read", "artifact", "write"])
def test_repair_io_errors_remain_advisory(repair_workspace, monkeypatch, failure):
    if failure == "snapshot":
        original = action_gate.TemporaryDirectory

        def fail_snapshot(*args, **kwargs):
            if kwargs.get("prefix") == "agentmandate-analysis-":
                raise OSError("synthetic snapshot failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(action_gate, "TemporaryDirectory", fail_snapshot)
    elif failure == "read":
        original = Path.read_bytes

        def fail_read(path):
            if path == repair_workspace / "candidate.json":
                raise OSError("synthetic snapshot read failure")
            return original(path)

        monkeypatch.setattr(Path, "read_bytes", fail_read)
    elif failure == "artifact":
        original = action_gate.NamedTemporaryFile

        def fail_artifact(*args, **kwargs):
            if kwargs.get("prefix") == "agentmandate-repairs-":
                raise OSError("synthetic artifact creation failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(action_gate, "NamedTemporaryFile", fail_artifact)
    else:
        original = action_gate.NamedTemporaryFile

        @contextmanager
        def fail_write(*args, **kwargs):
            with original(*args, **kwargs) as handle:
                if kwargs.get("prefix") != "agentmandate-repairs-":
                    yield handle
                    return

                class Writer:
                    name = handle.name

                    def write(self, text):
                        raise OSError("synthetic partial write failure")

                yield Writer()

        monkeypatch.setattr(action_gate, "NamedTemporaryFile", fail_write)
    assert action_gate.main() == 1
    payload = report(repair_workspace)["repairs"]
    assert payload["status"] == "error" and "Cannot" in payload["error"]
    assert outputs(repair_workspace)["verdict"] == "findings"
    if failure in {"artifact", "write"}:
        assert outputs(repair_workspace)["repair-report"] == ""
        assert not list(repair_workspace.glob("agentmandate-repairs-*.json"))


def test_summary_bounds_its_size_and_fences_untrusted_text():
    payload = {"status": "error", "error": "````\n" + "x" * 13000}
    text = action_gate.summary([], "clean", 0, 0, "", payload)
    assert "`````" in text and "Summary shortened" in text
    assert len(text) < 13000


def test_missing_comparison_skips_without_invoking_planner(repair_workspace, monkeypatch):
    repair = action_gate._repair_configuration()
    action_gate._repair_suggestions(repair, [], "before", "after", "4", "")
    assert repair["status"] == "skipped"


def test_controls_are_passed_as_argv_without_shell_execution(repair_workspace, monkeypatch):
    monkeypatch.setenv("INPUT_REPAIR_KEEP_TOOLS", "$(touch owned)")
    assert action_gate.main() == 1
    assert repairs(repair_workspace)["status"] == "error"
    assert not (repair_workspace / "owned").exists()


def test_repair_artifacts_do_not_follow_a_predictable_checkout_symlink(repair_workspace):
    original = (repair_workspace / "candidate.json").read_bytes()
    link = repair_workspace / "agentmandate-repairs.json"
    link.symlink_to("candidate.json")
    assert action_gate.main() == 1
    assert repairs(repair_workspace)["status"] == "completed"
    assert Path(outputs(repair_workspace)["repair-report"]) != link
    assert link.is_symlink() and (repair_workspace / "candidate.json").read_bytes() == original


def test_malformed_lint_results_do_not_drop_the_cli_failure(repair_workspace, monkeypatch):
    original = action_gate.run_json

    def malformed(args):
        return (2, {"findings": None}) if args[0] == "lint" else original(args)

    monkeypatch.setattr(action_gate, "run_json", malformed)
    assert action_gate.main() == 1
    assert action_check(repair_workspace, "lint")["findings"] == 1
    assert outputs(repair_workspace)["verdict"] == "findings"


@pytest.mark.parametrize("enabled", [False, True])
def test_candidate_package_cannot_replace_the_installed_analyzer(
    repair_workspace,
    monkeypatch,
    enabled,
):
    package = repair_workspace / "agentmandate"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "Path('candidate-code-executed').write_text('unsafe import')\n"
        "raise RuntimeError('the candidate must not replace the analyzer')\n"
    )
    monkeypatch.setenv("INPUT_REPAIR_SUGGESTIONS", str(enabled).lower())
    monkeypatch.setenv("PYTHONPATH", str(repair_workspace))
    assert action_gate.main() == 1
    assert action_check(repair_workspace, "diff")["widening_findings"] == 4
    assert not (repair_workspace / "candidate-code-executed").exists()
    if enabled:
        assert repairs(repair_workspace)["status"] == "completed"


def test_action_entrypoint_uses_installed_code_with_a_hostile_checkout(repair_workspace):
    package = repair_workspace / "agentmandate"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from pathlib import Path\n"
        "Path('candidate-code-executed').touch()\n"
        "raise RuntimeError('untrusted candidate import')\n"
    )
    source = Path(action_gate.__file__)
    env = {
        **os.environ,
        "PYTHONPATH": str(repair_workspace),
        "GITHUB_WORKSPACE": str(repair_workspace),
        "RUNNER_TEMP": str(repair_workspace),
        "GITHUB_OUTPUT": str(repair_workspace / "output.txt"),
        "GITHUB_STEP_SUMMARY": str(repair_workspace / "summary.md"),
    }
    process = subprocess.run(
        [sys.executable, "-I", str(source)],
        cwd=repair_workspace,
        capture_output=True,
        text=True,
        env=env,
    )
    assert process.returncode == 1
    assert repairs(repair_workspace)["status"] == "completed"
    assert not (repair_workspace / "candidate-code-executed").exists()


def test_candidates_recompare_against_the_actual_released_manifest(repair_workspace):
    assert action_gate.main() == 1
    repair = repairs(repair_workspace)
    before = loads((repair_workspace / "policies/released.json").read_text())
    for candidate in repair["result"]["candidates"]:
        after = loads(json.dumps(candidate["manifest"]))
        delta = compare(before, after, depth=4)
        assert not delta.widened and not delta.after.breaches
        # No input model is mutated by displaying or serializing a candidate.
        saved = copy.deepcopy(candidate)
        assert json.loads(json.dumps(candidate)) == saved
