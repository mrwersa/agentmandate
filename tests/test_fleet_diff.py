"""Fleet comparisons keep membership, review and independent authority separate."""

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from agentmandate._fleet import inventory
from agentmandate._fleet_diff import compare, render
from agentmandate._ir import _from_mandate
from agentmandate.cli import main
from agentmandate.diff import compare as authority_compare
from agentmandate.manifest import loads

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/fleet-diff"
AS_OF = "2026-10-14"


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def index(name="baseline"):
    return json.loads((EXAMPLE / (name + ".json")).read_bytes())


def run(before=None, after=None, *, root=ROOT, other=None, as_of=AS_OF, depth=8):
    return compare(encoded(index() if before is None else before),
                   encoded(index("candidate") if after is None else after),
                   baseline_root=root, candidate_root=other or root, as_of=as_of, depth=depth)


def codes(report):
    return {item["code"] for item in report["findings"]}


def deployment(report, repository="release-repo", environment="prod"):
    return next(row for row in report["comparisons"]
                if row["deployment"]["repository"] == repository
                and row["deployment"]["environment"] == environment)


@pytest.fixture
def artifacts(tmp_path):
    for name in ("fleet-inventory", "fleet-diff"):
        shutil.copytree(ROOT / "examples" / name, tmp_path / "examples" / name)
    return tmp_path


def snapshot(value, root, mutate, identifier="release/prod", name="changed"):
    entry = next(e for e in value["entries"] if e["id"] == identifier)
    manifest = json.loads((root / entry["manifest"]["path"]).read_bytes())
    mutate(manifest)
    content = encoded(manifest)
    graph = _from_mandate(loads(content.decode()), content=content)
    for kind, material in (("manifest", content), ("ir", graph.to_json().encode())):
        path = f"{name}-{kind}.json"
        (root / path).write_bytes(material)
        entry[kind] = {"path": path, "sha256": hashlib.sha256(material).hexdigest()}


def command(before, after, root=ROOT, other=None, as_of=AS_OF):
    return ["fleet", "diff", "--baseline", str(before), "--candidate", str(after),
            "--baseline-root", str(root), "--candidate-root", str(other or root),
            "--as-of", as_of]


def test_headline_keeps_inventory_reports_and_each_authority_diff_unchanged():
    before, after = index(), index("candidate")
    report = run(before, after)
    assert report["summary"] == {"deployments": 4, "compared": 3, "widened": 1, "added": 1,
                                 "removed": 0, "unresolved": 0, "unresolved_entries": 0}
    assert codes(report) == {"fleet.diff-authority-widened", "fleet.diff-authority-breach",
                             "fleet.diff-deployment-added", "fleet.review-not-current"}
    for label, value in (("baseline", before), ("candidate", after)):
        assert report[label] == inventory(encoded(value), root=ROOT, as_of=AS_OF)
    for row in report["comparisons"]:
        if row["authority_diff"] is None:
            continue
        mandates = []
        for label, value in (("baseline", before), ("candidate", after)):
            entry = next(e for e in value["entries"] if e["id"] == row[label + "_entries"][0])
            mandates.append(loads((ROOT / entry["manifest"]["path"]).read_text()))
        assert row["authority_diff"] == authority_compare(*mandates, depth=8).as_dict()
    assert deployment(report)["relation"] == "widening_within_compared_manifest_scope"
    assert deployment(report, environment="staging")["relation"].startswith("neutral_")
    assert "FINDING candidate fleet.review-not-current" in render(report)
    assert "Each mandate and budget remains separate" in render(report)
    assert not report["gate_passed"] and report["signatures"] == "not_verified"


@pytest.mark.parametrize("before,after,direction", [
    ("baseline", "baseline", "neutral"), ("widening", "baseline", "narrowing"),
])
def test_unchanged_and_narrowing_are_clean(before, after, direction):
    report = run(index(before), index(after))
    assert report["gate_passed"] and not report["findings"]
    assert deployment(report)["relation"] == direction + "_within_compared_manifest_scope"
    assert report["membership_comparable"]


def test_removed_deployment_requires_complete_membership_but_is_not_a_candidate_breach():
    before, after = index("widening"), index()
    after["entries"] = [e for e in after["entries"] if e["id"] != "release/prod"]
    report = run(before, after)
    row = deployment(report)
    assert row["relation"] == "removed_within_declared_index"
    assert row["baseline_authorities"]["release/prod"]["breaches"]
    assert row["candidate_authorities"] == {}
    assert report["gate_passed"]


@pytest.mark.parametrize("side", ["baseline", "candidate"])
@pytest.mark.parametrize("fault", ["partial", "unknown", "expired", "future", "ineligible"])
def test_untrusted_membership_never_establishes_addition_or_removal(side, fault):
    before, after = index(), index("candidate")
    value = before if side == "baseline" else after
    if fault in ("partial", "unknown"):
        value["coverage"] = fault
    elif fault == "expired":
        value["expires"] = "2026-10-13"
    elif fault == "future":
        value["observed_at"] = "2026-10-15"
    else:
        value["entries"][0]["ir"]["sha256"] = "0" * 64
    report = run(before, after)
    assert not report["membership_comparable"] and not report["gate_passed"]
    assert report["summary"]["added"] == report["summary"]["removed"] == 0
    assert "fleet.diff-presence-unresolved" in codes(report)
    assert deployment(report, "billing-repo", "staging")["relation"] == "unresolved"


@pytest.mark.parametrize("side", ["baseline", "candidate"])
def test_ambiguous_deployment_never_pairs_by_id_or_hides_candidate_breaches(side):
    before, after = index(), index("widening")
    value = before if side == "baseline" else after
    extra = copy.deepcopy(value["entries"][0])
    extra.update(id="release/duplicate", revision="synthetic-older")
    value["entries"].append(extra)
    report = run(before, after)
    row = deployment(report)
    assert row["authority_diff"] is None and row["relation"] == "unresolved"
    assert "fleet.diff-deployment-ambiguous" in codes(report)
    assert "fleet.diff-authority-breach" in codes(report)
    assert row["candidate_authorities"]["release/prod"]["breaches"]
    assert report["summary"]["compared"] == 2


def test_entry_id_revision_and_array_order_are_labels_not_pairing_keys():
    before, after = index(), index()
    after["entries"][0].update(id="renamed-entry", revision="synthetic-next")
    after["entries"].reverse()
    report = run(before, after)
    row = deployment(report)
    assert row["membership"] == "matched" and row["candidate_entries"] == ["renamed-entry"]
    assert {item["field"] for item in row["metadata_changes"]} == {"id", "revision"}
    assert report["gate_passed"]


@pytest.mark.parametrize("field,new", [("repository", "another-repo"), ("environment", "preview")])
def test_repository_and_environment_changes_are_not_cross_boundary_authority_diffs(field, new):
    before, after = index(), index()
    after["entries"][0][field] = new
    report = run(before, after)
    assert report["summary"]["added"] == report["summary"]["removed"] == 1
    assert report["summary"]["compared"] == 2
    assert deployment(report)["membership"] == "removed"
    assert "fleet.diff-deployment-added" in codes(report)


def test_agent_rename_is_not_an_authority_diff_or_reuse_of_the_old_entry_id(artifacts):
    before, after = index(), index()
    snapshot(after, artifacts, lambda m: m.update(agent="another-agent"))
    report = run(before, after, root=artifacts)
    assert report["summary"]["added"] == report["summary"]["removed"] == 1
    assert report["summary"]["compared"] == 2


def test_fleet_boundary_mismatch_preserves_individual_authority_without_comparison():
    after = index("candidate")
    after["fleet"] = "another-fleet"
    report = run(index(), after)
    assert not report["membership_comparable"]
    assert all(r["authority_diff"] is None for r in report["comparisons"])
    assert {"fleet.diff-boundary-mismatch", "fleet.diff-authority-breach"} <= codes(report)
    assert deployment(report)["candidate_authorities"]["release/prod"]["breaches"]


@pytest.mark.parametrize("owner", ["another-team", None])
def test_owner_handoffs_block_without_overwriting_authority(owner):
    after = index("widening")
    after["entries"][0]["owner"] = owner
    report = run(index(), after)
    assert "fleet.diff-owner-changed" in codes(report)
    assert deployment(report)["authority_diff"]["direction"] == "widening"
    assert deployment(report)["metadata_changes"]
    if owner is None:
        assert "fleet.owner-unassigned" in codes(report)


def test_current_review_declarations_do_not_accept_widening_or_new_deployments():
    after = index("candidate")
    after["entries"][2]["review"] = copy.deepcopy(after["entries"][0]["review"])
    report = run(index(), after)
    assert "fleet.review-not-current" not in codes(report)
    assert {"fleet.diff-deployment-added", "fleet.diff-authority-widened"} <= codes(report)
    assert not report["gate_passed"]


@pytest.mark.parametrize("as_of,current", [
    ("2026-10-10", False), ("2026-10-11", True), ("2026-11-08", True), ("2026-11-09", False),
])
def test_inclusive_dates_block_the_gate_without_erasing_matched_manifest_findings(as_of, current):
    report = run(index(), index("widening"), as_of=as_of)
    assert report["membership_comparable"] is current
    assert deployment(report)["authority_diff"]["direction"] == "widening"
    assert "fleet.diff-authority-widened" in codes(report)
    assert ("fleet.snapshot-not-current" in codes(report)) is not current


@pytest.mark.parametrize("kind", ["manifest", "ir"])
def test_source_tampering_leaves_identity_unresolved_and_keeps_other_comparisons(kind):
    after = index("widening")
    after["entries"][0][kind]["sha256"] = "0" * 64
    report = run(index(), after)
    assert report["unresolved_entries"] == {"baseline": [], "candidate": ["release/prod"]}
    assert report["summary"]["compared"] == 2
    assert "fleet.artifact-digest_mismatch" in codes(report)
    assert "UNRESOLVED candidate release/prod" in render(report)


@pytest.mark.parametrize("fault", ["changed", "missing", "cycle"])
def test_late_manifest_changes_cannot_replace_inventory_verified_bytes(fault, monkeypatch):
    from agentmandate import _fleet_diff

    original = _fleet_diff._read

    def changed(root, locator):
        if "candidate-release/manifest.json" in locator:
            if fault == "missing":
                raise OSError("removed after inventory")
            if fault == "cycle":
                raise RuntimeError("symlink cycle after inventory")
            return original(root, locator) + b" "
        return original(root, locator)

    monkeypatch.setattr(_fleet_diff, "_read", changed)
    report = run()
    row = deployment(report)
    assert row["authority_diff"] is None and row["candidate_authorities"] == {"release/prod": None}
    assert "fleet.diff-snapshot-untrusted" in codes(report)
    assert not report["membership_comparable"] and not report["gate_passed"]


@pytest.mark.parametrize("change", ["approval", "tool", "effects", "identity", "ceiling"])
def test_existing_diff_drives_each_change_class_and_preserves_baseline(change, artifacts):
    before, after = index(), index()
    if change == "approval":
        def mutate(m):
            m["tools"][1].update(requires_approval=False)
    elif change == "tool":
        def mutate(m):
            m["tools"].append({"name": "another-tool", "effect": "read"})
    elif change == "identity":
        def mutate(m):
            m.update(identity="another-operator")
    elif change == "effects":
        snapshot(before, artifacts, lambda m: m.update(limits={"effects": {"irreversible": 3}}),
                 name="before")
        after = copy.deepcopy(before)
        def mutate(m):
            m["limits"]["effects"].update(irreversible=5)
    else:
        def monetary(m):
            m["tools"] = [
                {"name": "seed", "effect": "read", "produces": "case"},
                {"name": "pay", "effect": "irreversible", "requires_approval": True,
                 "requires": ["case"], "scope_key": "case", "value_arg": "amount",
                 "ceiling": {"amount": "40", "currency": "GBP"}},
            ]
            m["limits"] = {"total": {"amount": "50", "currency": "GBP"}}
        snapshot(before, artifacts, monetary, name="before")
        after = copy.deepcopy(before)
        def mutate(m):
            m["tools"][1]["ceiling"].update(amount="60")
    snapshot(after, artifacts, mutate)
    report = run(before, after, root=artifacts)
    row = deployment(report)
    left = loads((artifacts / before["entries"][0]["manifest"]["path"]).read_text())
    right = loads((artifacts / after["entries"][0]["manifest"]["path"]).read_text())
    assert row["authority_diff"] == authority_compare(left, right, depth=8).as_dict()
    assert row["authority_diff"]["direction"] == "widening"
    assert report["baseline"] == inventory(encoded(before), root=artifacts, as_of=AS_OF)


def test_amounts_from_separate_deployments_are_never_added(artifacts):
    value = index()
    def monetary(m):
        m["tools"] = [{"name": "seed", "effect": "read", "produces": "case"},
                      {"name": "pay", "effect": "irreversible", "requires_approval": True,
                       "requires": ["case"], "scope_key": "case", "value_arg": "amount",
                       "ceiling": {"amount": "40", "currency": "GBP"}}]
        m["limits"] = {"total": {"amount": "50", "currency": "GBP"}}
    snapshot(value, artifacts, monetary)
    extra = copy.deepcopy(value["entries"][0])
    extra.update(id="separate/prod", repository="separate-repo")
    value["entries"] = [value["entries"][0], extra]
    report = run(value, value, root=artifacts)
    assert report["gate_passed"] and len(report["comparisons"]) == 2
    for row in report["comparisons"]:
        assert row["authority_diff"]["after"]["max_extractable"] == {
            "amount": "40", "currency": "GBP",
        }
        assert not row["authority_diff"]["after"]["breaches"]
    assert "max_extractable" not in report["summary"]


def test_separate_artifact_roots_join_equal_relative_paths_to_their_own_snapshots(artifacts):
    other = artifacts / "other"
    shutil.copytree(artifacts / "examples", other / "examples")
    after = index()
    snapshot(after, other, lambda m: m["tools"][1].update(requires_approval=False))
    report = run(index(), after, root=artifacts, other=other)
    assert deployment(report)["authority_diff"]["direction"] == "widening"


@pytest.mark.parametrize("depth", [None, True, 0, -1, "8"])
def test_invalid_bounds_are_usage_errors_even_for_empty_indexes(depth):
    value = index()
    value["entries"] = []
    with pytest.raises(ValueError, match="depth must be a positive integer"):
        run(value, value, depth=depth)


def test_explicit_complete_empty_indexes_are_clean_declarations():
    value = index()
    value["entries"] = []
    report = run(value, value)
    assert report["gate_passed"] and report["comparisons"] == []
    assert report["summary"]["deployments"] == 0


@pytest.mark.parametrize("coverage", ["complete", "partial"])
def test_new_candidate_breaches_survive_unresolved_presence_without_empty_mandate_diff(coverage):
    before = index()
    before.update(entries=[], coverage=coverage)
    report = run(before, index("widening"))
    row = deployment(report)
    assert row["authority_diff"] is None and row["baseline_authorities"] == {}
    assert row["candidate_authorities"]["release/prod"]["breaches"]
    assert "fleet.diff-authority-breach" in codes(report)
    assert not report["gate_passed"]
    assert row["membership"] == ("added" if coverage == "complete" else "unresolved")


def test_unchanged_candidate_breach_remains_blocking_even_without_widening():
    report = run(index("widening"), index("widening"))
    assert not report["gate_passed"]
    assert codes(report) == {"fleet.diff-authority-breach"}
    assert report["summary"]["widened"] == 0


def test_several_agents_in_one_repository_environment_keep_distinct_comparisons(artifacts):
    value = index()
    second = copy.deepcopy(value["entries"][0])
    second["id"] = "second-agent/prod"
    value["entries"] = [value["entries"][0], second]
    snapshot(value, artifacts, lambda m: m.update(agent="secondary-agent"),
             identifier="second-agent/prod")
    report = run(value, value, root=artifacts)
    assert report["gate_passed"] and report["summary"]["compared"] == 2
    assert {row["deployment"]["agent"] for row in report["comparisons"]} == {
        "release-agent", "secondary-agent",
    }


def test_search_bound_and_truncation_travel_with_each_authority(artifacts):
    value = index()
    snapshot(value, artifacts, lambda m: m.update(limits={"effects": {"irreversible": 1}}))
    shallow = run(value, value, root=artifacts, depth=1)
    deep = run(value, value, root=artifacts, depth=2)
    row = deployment(shallow)
    assert shallow["gate_passed"]
    assert row["authority_diff"]["after"]["depth"] == 1
    assert row["candidate_authorities"]["release/prod"]["truncated"]
    assert not deep["gate_passed"] and "fleet.diff-authority-breach" in codes(deep)


@pytest.mark.parametrize("before,after,expected", [
    ("baseline", "baseline", 0), ("baseline", "widening", 1),
    ("widening", "baseline", 0), ("baseline", "candidate", 1),
])
@pytest.mark.parametrize("machine", [True, False])
def test_cli_preserves_gate_exit_and_complete_outputs(before, after, expected, machine, capsys):
    args = command(EXAMPLE / (before + ".json"), EXAMPLE / (after + ".json"))
    assert main(args + (["--json"] if machine else [])) == expected
    output = capsys.readouterr()
    assert not output.err
    if machine:
        assert json.loads(output.out) == run(index(before), index(after))
    else:
        assert output.out == render(run(index(before), index(after)))


@pytest.mark.parametrize("fault", [
    "duplicate-key", "fields", "date", "deep", "utf8", "missing-index", "missing-root",
    "duplicate-id", "traversal", "absolute", "backslash", "depth",
])
def test_malformed_cli_inputs_fail_2_without_partial_output(fault, artifacts, capsys):
    value = index()
    path = artifacts / "input.json"
    args = command(path, EXAMPLE / "baseline.json", artifacts)
    if fault == "fields":
        value["extra"] = True
    elif fault == "duplicate-id":
        value["entries"].append(copy.deepcopy(value["entries"][0]))
    elif fault in ("traversal", "absolute", "backslash"):
        value["entries"][0]["manifest"]["path"] = {
            "traversal": "../outside.json", "absolute": "/etc/passwd", "backslash": "a\\b.json",
        }[fault]
    content = encoded(value)
    if fault == "duplicate-key":
        content = content.replace(b'"fleet_version": 1', b'"fleet_version": 1,"fleet_version": 1')
    elif fault == "deep":
        content = b"[" * 10000 + b"]" * 10000
    elif fault == "utf8":
        content = b"\xff"
    elif fault == "date":
        args[-1] = "tomorrow"
    elif fault == "missing-root":
        args[args.index("--baseline-root") + 1] = str(artifacts / "absent")
    elif fault == "depth":
        args += ["--depth", "0"]
    if fault != "missing-index":
        path.write_bytes(content)
    assert main(args + ["--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")
    assert "Traceback" not in output.err


def test_symlink_escape_is_rejected_without_partial_output(artifacts, capsys):
    outside = artifacts / "outside.json"
    outside.write_bytes((ROOT / index()["entries"][0]["manifest"]["path"]).read_bytes())
    child = artifacts / "contained"
    child.mkdir()
    (child / "escape.json").symlink_to(outside)
    value = index()
    value["entries"][0]["manifest"]["path"] = "escape.json"
    path = artifacts / "input.json"
    path.write_bytes(encoded(value))
    assert main(command(path, path, child) + ["--json"]) == 2
    assert not capsys.readouterr().out


def test_unsupported_currency_arithmetic_is_usage_2_and_not_a_partial_fleet_verdict(
    artifacts, capsys
):
    value = index()
    def monetary(m):
        m["tools"] = [{"name": "seed", "effect": "read", "produces": "case"},
                      {"name": "pay", "effect": "irreversible", "requires_approval": True,
                       "requires": ["case"], "scope_key": "case", "value_arg": "amount",
                       "ceiling": {"amount": "40", "currency": "USD"}}]
        m["limits"] = {"total": {"amount": "50", "currency": "GBP"}}
    snapshot(value, artifacts, monetary)
    path = artifacts / "input.json"
    path.write_bytes(encoded(value))
    assert main(command(path, path, artifacts) + ["--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and "require one currency" in output.err


def test_pinned_v1_cases_replay_complete_results_and_exit_codes(capsys):
    for case in json.loads((ROOT / "tests/fixtures/fleet-diff-v1.json").read_text()):
        before = EXAMPLE / (case["baseline"] + ".json")
        after = EXAMPLE / (case["candidate"] + ".json")
        result = compare(before.read_bytes(), after.read_bytes(), baseline_root=ROOT,
                         candidate_root=ROOT, as_of=case["as_of"])
        assert result == case["result"]
        assert main(command(before, after, as_of=case["as_of"]) + ["--json"]) == case["exit"]
        assert json.loads(capsys.readouterr().out) == result
