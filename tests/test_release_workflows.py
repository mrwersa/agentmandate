"""Release comparisons recheck caller-authored paths against both manifests."""

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agentmandate import loads
from agentmandate._change_review import evaluate as evaluate_review
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main
from agentmandate.diff import compare as compare_authority

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/release-workflows"
AS_OF = "2026-10-15"
RELEASED = "released.json"
ANNOTATION = "required-export.json"


def released():
    return (EXAMPLE / RELEASED).read_bytes()


def released_text():
    return (EXAMPLE / RELEASED).read_text()


def requirements(name=ANNOTATION):
    return _Requirements.load((EXAMPLE / name).read_bytes(), loads(released_text()),
                              hashlib.sha256(released()).hexdigest())


def compare_pair(before=RELEASED, after="narrowed.json", *, workflows=ANNOTATION, depth=None):
    return compare_authority(
        loads((EXAMPLE / before).read_text()), loads((EXAMPLE / after).read_text()),
        depth=depth,
        required_workflows=requirements(workflows) if workflows else None,
    )


def command(before=RELEASED, after="narrowed.json", *, workflows=ANNOTATION, record=False):
    argv = ["diff", str(EXAMPLE / before), str(EXAMPLE / after)]
    if workflows is not None:
        argv += ["--required-workflows", str(EXAMPLE / workflows)]
    if record:
        argv += ["--record"]
    return argv


@pytest.mark.parametrize("candidate,relation,rule", [
    ("narrowed.json", "preserved", None),
    ("breaking.json", "regressed", "workflow.ceiling-exceeded"),
    ("budget-shortfall.json", "regressed", "workflow.quantity-exceeded"),
    ("dropped-producer.json", "regressed", "workflow.undeclared-tool"),
    ("gated-producer.json", "regressed", "workflow.approval-missing"),
])
def test_each_release_names_its_own_failing_step(candidate, relation, rule):
    row, = compare_pair(after=candidate).required_workflows
    assert row["name"] == "bulk-export" and row["relation"] == relation
    assert row["baseline"] == "conformant_within_manifest_model"
    assert row["candidate"] == ("not_conformant_within_manifest_model" if rule else row["baseline"])
    if rule is None:
        assert row["failure"] is None
    else:
        assert row["failure"]["rule"] == rule and row["failure"]["step"] >= 1


def test_a_release_can_narrow_authority_and_still_break_required_work():
    delta = compare_pair(after="breaking.json")
    assert not delta.widened and delta.direction == "narrowing"
    assert delta.workflow_regressions == ("bulk-export",)
    assert main(command(after="breaking.json")) == 1


def test_a_preserved_path_does_not_block_an_otherwise_clean_release():
    delta = compare_pair(after="narrowed.json")
    assert not delta.widened and not delta.workflow_regressions
    assert main(command(after="narrowed.json")) == 0
    assert "required_workflows" in delta.as_dict()
    assert delta.as_dict()["required_workflows_metadata"] == requirements().metadata()
    # The default result keeps its shape and its exit code.
    plain = compare_pair(after="narrowed.json", workflows=False).as_dict()
    assert "required_workflows" not in plain
    assert "required_workflows_metadata" not in plain
    assert compare_pair(after="narrowed.json", workflows=False).as_dict() == (
        compare_authority(
            loads((EXAMPLE / RELEASED).read_text()),
            loads((EXAMPLE / "narrowed.json").read_text()),
        ).as_dict()
    )
    assert main(command(after="narrowed.json", workflows=None)) == 0


def test_widening_and_workflow_preservation_are_reported_separately():
    delta = compare_pair(after="proposed.json")
    assert delta.widened and not delta.workflow_regressions
    assert main(command(after="proposed.json")) == 1
    assert "gained summarise_batch" in delta.render("released", "proposed")


def test_default_output_is_byte_identical_without_the_flag(capsys):
    assert main(command(after="breaking.json", workflows=None)) == 0
    plain = capsys.readouterr().out
    assert "REQUIRED" not in plain
    assert main(command(after="breaking.json")) == 1
    checked = capsys.readouterr().out
    assert checked.startswith(plain)
    assert checked[len(plain):].splitlines()[:1] == [
        "REQUIRED bulk-export: conformant_within_manifest_model -> "
        "not_conformant_within_manifest_model (regressed)"
    ]
    # The record needs no extra assumptions about the ordinary text output.
    assert main(command(after="breaking.json", workflows=None, record=True)) == 0
    assert "## Required workflows" not in capsys.readouterr().out


def test_render_and_change_record_name_the_failing_step():
    text = compare_pair(after="breaking.json").render("released", "breaking")
    assert "REQUIRED bulk-export fails at step 2 workflow.ceiling-exceeded" in text
    assert "preserved" not in text
    record = compare_pair(after="narrowed.json").record("released", "narrowed")
    assert "## Required workflows" in record and "bulk-export: preserved" in record
    plain_record = compare_pair(after="narrowed.json", workflows=False)
    assert "## Required workflows" not in plain_record.record("released", "narrowed")


def test_an_unreadable_manifest_and_a_wrong_baseline_are_usage_errors(tmp_path, capsys):
    missing = tmp_path / "absent.json"
    assert main(["diff", str(missing), str(EXAMPLE / RELEASED)]) == 2
    assert capsys.readouterr().err.startswith("error: cannot read manifest")
    for name in ("impossible-export.json", "other-agent.json", "other-baseline.json"):
        assert main(command(after="narrowed.json", workflows=name)) == 2
        assert capsys.readouterr().err.startswith("error: ")


def test_the_released_manifest_must_already_satisfy_the_workflow():
    with pytest.raises(ValueError, match="is invalid in the baseline manifest: step 2"):
        compare_pair(after="breaking.json", workflows="impossible-export.json")
    for name in ("other-baseline.json", "other-agent.json"):
        with pytest.raises(ValueError, match="do not match the exact baseline manifest"):
            requirements(name)


def test_review_blocks_a_regressed_workflow_without_a_decision_record(capsys):
    argv = ["review", str(EXAMPLE / RELEASED), str(EXAMPLE / "breaking.json"),
            "--as-of", AS_OF, "--required-workflows", str(EXAMPLE / ANNOTATION)]
    assert main(argv) == 1
    output = capsys.readouterr()
    assert "REQUIRED bulk-export: regressed in the proposed release" in output.out
    assert "review.required-workflow-regressed" in output.out
    assert "review.decision-missing" not in output.out
    evaluated = evaluate_review(released(), (EXAMPLE / "breaking.json").read_bytes(),
                                as_of=AS_OF, required_workflows=requirements())
    assert evaluated["status"] == "recorded_acceptance_unresolved"
    assert not evaluated["gate_satisfied"]
    assert [row["name"] for row in evaluated["required_workflows"]] == ["bulk-export"]
    assert evaluated["required_workflows"][0]["relation"] == "regressed"
    assert evaluate_review(released(), released(), as_of=AS_OF).get("required_workflows") is None


def test_a_preserved_workflow_does_not_require_an_acceptance_record(capsys):
    argv = ["review", str(EXAMPLE / RELEASED), str(EXAMPLE / "narrowed.json"),
            "--as-of", AS_OF, "--required-workflows", str(EXAMPLE / ANNOTATION)]
    assert main(argv) == 0
    output = capsys.readouterr()
    assert "REQUIRED bulk-export: preserved in the proposed release" in output.out


def test_a_decision_record_covers_the_compared_workflows():
    before, after = released(), (EXAMPLE / "narrowed.json").read_bytes()
    plain = evaluate_review(before, after, as_of=AS_OF)
    checked = evaluate_review(
        before, after, as_of=AS_OF, required_workflows=requirements()
    )
    assert plain["inputs"]["comparison_sha256"] != checked["inputs"]["comparison_sha256"]
    assert "required_workflows" in checked["comparison"]
    note = b"synthetic decision note\n"
    record = {
        "schema": "agentmandate.change-review/v1", "agent": "release-agent",
        "before_sha256": plain["inputs"]["before_sha256"],
        "after_sha256": plain["inputs"]["after_sha256"],
        "comparison_sha256": plain["inputs"]["comparison_sha256"], "depth": 4,
        "scope": "all_widening_changes_in_pinned_comparison", "owner": "synthetic-owner",
        "reviewer": "synthetic-reviewer", "reason": "synthetic acceptance", "decision": "accept",
        "reviewed_at": "2026-10-14", "expires": "2026-11-30",
        "evidence": [{"locator": "note", "sha256": hashlib.sha256(note).hexdigest(),
                      "purpose": "decision"}],
        "target_policy": {"status": "not_applicable", "reason": "no deployed policy"},
    }
    # A record pinned to the flag-free comparison cannot accept the checked one.
    mismatched = evaluate_review(
        before, after, as_of=AS_OF, required_workflows=requirements(),
        decision=json.dumps(record).encode(), sources={"note": note},
    )
    assert "review.comparison-mismatch" in {row["rule"] for row in mismatched["findings"]}
    accepted = evaluate_review(
        before, after, as_of=AS_OF, required_workflows=requirements(),
        decision=json.dumps({**record,
                             "comparison_sha256": checked["inputs"]["comparison_sha256"]}
                            ).encode(),
        sources={"note": note},
    )
    assert accepted["gate_satisfied"] and accepted["status"] == "review_not_required_within_bound"


@pytest.mark.parametrize("change", ["amount", "calls", "reviewer", "reason", "approval", "format"])
def test_an_acceptance_cannot_transfer_to_different_workflow_bytes(change, tmp_path, capsys):
    before, after = released(), (EXAMPLE / "proposed.json").read_bytes()
    original = requirements()
    checked = evaluate_review(before, after, as_of=AS_OF, required_workflows=original)
    note = b"Synthetic acceptance of these exact workflow annotations.\n"
    record = {
        "schema": "agentmandate.change-review/v1", **checked["inputs"],
        "scope": "all_widening_changes_in_pinned_comparison", "owner": "synthetic-owner",
        "reviewer": "synthetic-reviewer", "reason": "Accept the pinned widening comparison",
        "decision": "accept", "reviewed_at": AS_OF, "expires": "2026-11-30",
        "evidence": [{"locator": "note", "sha256": hashlib.sha256(note).hexdigest(),
                      "purpose": "decision"}],
        "target_policy": {"status": "not_applicable", "reason": "synthetic only"},
    }
    accepted = evaluate_review(
        before, after, as_of=AS_OF, required_workflows=original,
        decision=json.dumps(record).encode(), sources={"note": note},
    )
    assert accepted["gate_satisfied"] and accepted["status"] == "eligible_recorded_acceptance"

    raw = json.loads((EXAMPLE / ANNOTATION).read_bytes())
    changed = copy.deepcopy(raw)
    if change == "amount":
        changed["workflows"][0]["steps"][1]["value"] = "101"
    elif change == "calls":
        changed["workflows"][0]["steps"][1] = {
            "tool": "open_batch", "principal": "caller", "approved": False,
        }
    elif change in {"reviewer", "reason"}:
        changed[change] = "different synthetic annotation"
    elif change == "approval":
        changed["workflows"][0]["steps"][0]["approved"] = True
    content = ((EXAMPLE / ANNOTATION).read_bytes() + b"\n" if change == "format"
               else json.dumps(changed).encode())
    revised = _Requirements.load(
        content, loads(before.decode()), hashlib.sha256(before).hexdigest()
    )
    rejected = evaluate_review(
        before, after, as_of=AS_OF, required_workflows=revised,
        decision=json.dumps(record).encode(), sources={"note": note},
    )
    assert rejected["required_workflows"] == checked["required_workflows"]
    assert revised.source_sha256 != original.source_sha256
    assert rejected["comparison"]["required_workflows_metadata"] == revised.metadata()
    assert rejected["inputs"]["comparison_sha256"] != checked["inputs"]["comparison_sha256"]
    assert not rejected["gate_satisfied"] and not rejected["review"]["eligible"]
    assert {row["rule"] for row in rejected["findings"]} == {"review.comparison-mismatch"}

    annotation = tmp_path / "required.json"
    decision = tmp_path / "decision.json"
    source = tmp_path / "note.txt"
    annotation.write_bytes(content)
    decision.write_text(json.dumps(record))
    source.write_bytes(note)
    assert main([
        "review", str(EXAMPLE / RELEASED), str(EXAMPLE / "proposed.json"),
        "--required-workflows", str(annotation), "--decision", str(decision),
        "--source", f"note={source}", "--as-of", AS_OF, "--json",
    ]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == rejected


def test_an_annotated_tool_keeps_its_identity_across_the_comparison():
    delta = compare_pair(after="narrowed.json")
    assert delta.required_workflows[0]["steps"] == 2
    assert [row["name"] for row in delta.required_workflows] == ["bulk-export"]
    # A second annotation on the same baseline is checked as its own path.
    renamed = replace(requirements().workflows[0], name="second-path")
    doubled = _Requirements.load(
        json.dumps({
            "schema": "agentmandate.required-workflows/v2", "agent": "release-agent",
            "manifest_sha256": hashlib.sha256(released()).hexdigest(),
            "reviewer": "synthetic-reviewer", "reason": "synthetic",
            "workflows": [
                {"name": row.name, "steps": [
                    {"tool": step.tool, "principal": step.principal, "approved": step.approved,
                     **({"binding": step.binding, "value": str(step.value.amount),
                         "unit": step.value.unit, "quantity": step.quantity}
                        if step.value is not None else {})}
                    for step in row.steps]}
                for row in requirements().workflows + (renamed,)
            ],
        }).encode(),
        loads(released_text()), hashlib.sha256(released()).hexdigest(),
    )
    rows = compare_authority(
        loads((EXAMPLE / RELEASED).read_text()), loads((EXAMPLE / "narrowed.json").read_text()),
        required_workflows=doubled,
    ).required_workflows
    assert [row["name"] for row in rows] == ["bulk-export", "second-path"]
    assert {row["relation"] for row in rows} == {"preserved"}


@pytest.mark.parametrize(
    "case",
    json.loads((ROOT / "tests/fixtures/release-workflows-v1.json").read_text()),
    ids=lambda case: case["name"],
)
def test_initial_cases_replay_complete_results_and_exit_codes(case, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    assert main(case["argv"]) == case["exit"]
    captured = capsys.readouterr()
    assert captured.out == json.dumps(case["result"], indent=2, sort_keys=True) + "\n"
    assert not captured.err
