"""Fleet integrity, per-deployment identity and unfiltered finding preservation."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from agentmandate._fleet import inventory, render
from agentmandate._ir import _from_mandate
from agentmandate.cli import main
from agentmandate.manifest import loads

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/fleet-inventory"


def index(name="index.json"):
    return json.loads((EXAMPLE / name).read_bytes())


def run(value=None, *, root=ROOT, as_of="2026-10-11", **query):
    return inventory(
        json.dumps(index() if value is None else value).encode(), root=root, as_of=as_of, **query
    )


def codes(report):
    return {row["code"] for row in report["findings"]}


def local_index(tmp_path):
    value = index()
    for entry in value["entries"]:
        for kind in ("manifest", "ir"):
            original = entry[kind]["path"]
            name = original.split("/")[-2] + "-" + original.split("/")[-1]
            (tmp_path / name).write_bytes((ROOT / original).read_bytes())
            entry[kind]["path"] = name
    return value


def repin(value, tmp_path, kind, content):
    reference = value["entries"][0][kind]
    (tmp_path / reference["path"]).write_bytes(content)
    # Both release deployments intentionally refer to the same immutable snapshot.
    for entry in value["entries"]:
        if entry[kind]["path"] == reference["path"]:
            entry[kind]["sha256"] = hashlib.sha256(content).hexdigest()


def test_pinned_baseline_keeps_repositories_environments_and_same_named_tools_separate():
    report = inventory((EXAMPLE / "index.json").read_bytes(), root=ROOT, as_of="2026-10-11")
    assert report == json.loads((ROOT / "tests/fixtures/fleet-inventory-v2.json").read_text())
    assert report["summary"] == {
        "entries": 3,
        "selected_entries": 3,
        "eligible_snapshots": 3,
        "current_reviews": 3,
        "unassigned_owners": 0,
        "declared_tool_occurrences": 8,
    }
    assert report["inventory_complete_within_declared_index"]
    assert report["signatures"] == "not_verified"
    assert not report["findings"]
    assert len({row["id"] for row in report["entries"]}) == 3
    assert {row["agent"] for row in report["entries"]} == {"release-agent", "billing-agent"}
    assert "not runtime exposure" in render(report)
    assert "TOOL billing/prod/issue_refund effect=irreversible" in render(report)
    assert "Signatures: not verified" in render(report)


@pytest.mark.parametrize(
    "query,ids",
    [
        ({"owner": "billing-security"}, ["billing/prod"]),
        ({"environment": "prod"}, ["billing/prod", "release/prod"]),
        ({"tool": "read_release"}, ["billing/prod", "release/prod", "release/staging"]),
        ({"tool": "issue_refund"}, ["billing/prod"]),
        ({"environment": "staging", "owner": "release-security"}, ["release/staging"]),
        ({"owner": "unknown"}, []),
        ({"tool": "unknown"}, []),
    ],
)
def test_exact_queries_never_merge_same_named_tools(query, ids):
    report = run(**query)
    assert [row["id"] for row in report["entries"]] == ids
    assert report["summary"]["entries"] == 3
    assert report["summary"]["selected_entries"] == len(ids)
    assert report["summary"]["declared_tool_occurrences"] == 8
    assert not report["findings"]


@pytest.mark.parametrize("query", [{}, {"owner": "release-security"}, {"tool": "unknown"}])
def test_filters_never_suppress_global_integrity_owner_or_review_findings(query):
    report = run(index("findings.json"), **query)
    assert codes(report) == {
        "fleet.review-not-current",
        "fleet.owner-unassigned",
        "fleet.artifact-digest_mismatch",
    }
    assert len(report["findings"]) == 4
    assert report["summary"]["entries"] == 3
    assert report["summary"]["eligible_snapshots"] == 2
    assert not report["inventory_complete_within_declared_index"]
    assert report["status"] == "findings_or_unresolved"
    assert "FINDING fleet.owner-unassigned" in render(report)


@pytest.mark.parametrize("coverage", ["partial", "unknown"])
def test_incomplete_inventory_is_not_an_absence_claim(coverage):
    value = index()
    value.update(coverage=coverage, entries=[])
    report = run(value, tool="issue_refund")
    assert codes(report) == {"fleet.coverage-incomplete"}
    assert report["entries"] == []
    assert not report["inventory_complete_within_declared_index"]


def test_explicit_complete_empty_index_is_only_a_declaration():
    value = index()
    value["entries"] = []
    report = run(value)
    assert not report["findings"]
    assert report["inventory_complete_within_declared_index"]
    assert report["summary"]["entries"] == 0
    assert "declared" in report["scope"] and report["signatures"] == "not_verified"


@pytest.mark.parametrize(
    "as_of,current",
    [("2026-10-10", False), ("2026-10-11", True), ("2026-11-08", True), ("2026-11-09", False)],
)
def test_index_and_review_dates_are_inclusive_and_caller_selected(as_of, current):
    report = run(as_of=as_of)
    assert report["snapshot_current"] is current
    assert report["inventory_complete_within_declared_index"] is current
    assert all(row["review_current"] is current for row in report["entries"])
    assert codes(report) == (
        set() if current else {"fleet.snapshot-not-current", "fleet.review-not-current"}
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("state", "unreviewed"),
        ("state", "contested"),
        ("reviewer", None),
        ("reviewed_at", None),
        ("expires", None),
        ("reviewed_at", "2026-10-12"),
        ("expires", "2026-10-11"),
    ],
)
def test_review_eligibility_is_separate_from_snapshot_integrity(field, value):
    data = index()
    data["entries"][0]["review"][field] = value
    # Expiry today stays eligible; all other variants are unresolved for this entry.
    report = run(data)
    row = next(row for row in report["entries"] if row["id"] == "release/prod")
    assert row["review_current"] is (field == "expires" and value is not None)
    assert row["snapshot_eligible"]
    assert row["declared_tools"]
    assert report["inventory_complete_within_declared_index"]


@pytest.mark.parametrize("kind", ["manifest", "ir"])
def test_hash_mismatch_never_populates_tools_even_when_other_entries_are_healthy(kind):
    value = index()
    value["entries"][0][kind]["sha256"] = "0" * 64
    report = run(value)
    assert codes(report) == {"fleet.artifact-digest_mismatch"}
    broken = next(row for row in report["entries"] if row["id"] == "release/prod")
    assert not broken["snapshot_eligible"] and broken["declared_tools"] is None
    assert broken["agent"] is None
    assert report["summary"]["eligible_snapshots"] == 2
    assert not report["inventory_complete_within_declared_index"]


@pytest.mark.parametrize("missing", ["missing.json", "directory"])
def test_unavailable_artifacts_are_visible_and_other_repositories_survive(missing, tmp_path):
    value = local_index(tmp_path)
    (tmp_path / "directory").mkdir()
    value["entries"][0]["manifest"]["path"] = missing
    report = run(value, root=tmp_path)
    assert codes(report) == {"fleet.artifact-unavailable"}
    assert report["summary"]["eligible_snapshots"] == 2
    broken = next(row for row in report["entries"] if row["id"] == "release/prod")
    assert broken["artifacts"]["manifest"]["observed_sha256"] is None


@pytest.mark.parametrize(
    "kind,content",
    [("manifest", b"\xff"), ("manifest", b"[]"), ("ir", b"{"), ("ir", b"[]"), ("ir", b"\xff")],
)
def test_repinned_malformed_artifacts_stay_ineligible(kind, content, tmp_path):
    value = local_index(tmp_path)
    repin(value, tmp_path, kind, content)
    report = run(value, root=tmp_path)
    assert codes(report) == {"fleet.snapshot-ineligible"}
    assert report["summary"]["eligible_snapshots"] == 1
    assert not report["inventory_complete_within_declared_index"]


@pytest.mark.parametrize("change", ["source", "review", "confidence", "semantic", "duplicate"])
def test_repinned_ir_cannot_authorize_false_joins_or_unreviewed_facts(change, tmp_path):
    value = local_index(tmp_path)
    content = (tmp_path / value["entries"][0]["ir"]["path"]).read_bytes()
    raw = json.loads(content)
    if change == "source":
        next(s for s in raw["sources"] if s["id"] == "source:mandate")["content_sha256"] = "0" * 64
    elif change in ("review", "confidence"):
        raw["facts"][0]["evidence"][0][change] = "unreviewed" if change == "review" else "heuristic"
    elif change == "semantic":
        manifest_content = (tmp_path / value["entries"][0]["manifest"]["path"]).read_bytes()
        other = json.loads(manifest_content)
        other["identity"] = "another-operator"
        raw = _from_mandate(loads(json.dumps(other)), content=manifest_content).as_dict()
    else:
        content = content.replace(b'"ir_version":2', b'"ir_version":2,"ir_version":2')
    repin(value, tmp_path, "ir", content if change == "duplicate" else json.dumps(raw).encode())
    report = run(value, root=tmp_path)
    assert codes(report) == {"fleet.snapshot-ineligible"}
    assert report["summary"]["eligible_snapshots"] == 1
    if change == "semantic":
        assert all("IR mandate does not match" in f["detail"] for f in report["findings"])


def test_duplicate_deployment_is_not_deduplicated_or_treated_as_two_revisions():
    value = index()
    row = copy.deepcopy(value["entries"][0])
    row.update(id="release/prod-old", revision="synthetic-commit-0")
    value["entries"].append(row)
    report = run(value)
    assert codes(report) == {"fleet.deployment-ambiguous"}
    assert len(report["entries"]) == 4
    assert report["summary"]["declared_tool_occurrences"] == 11
    assert not report["inventory_complete_within_declared_index"]


@pytest.mark.parametrize(
    "path", ["/absolute.json", "../outside", "./x", "a//b", "x/", "C:file", "a\\b"]
)
def test_unsafe_reference_syntax_is_usage_error_before_any_filter(path):
    value = index()
    value["entries"][0]["manifest"]["path"] = path
    with pytest.raises(ValueError, match="normalized relative"):
        run(value, owner="unknown")


def test_escaping_symlink_is_usage_error_before_any_filter(tmp_path):
    value = local_index(tmp_path)
    (tmp_path / "outside").symlink_to(EXAMPLE / "release-repo/manifest.json")
    value["entries"][0]["manifest"]["path"] = "outside"
    with pytest.raises(ValueError, match="inside --root"):
        run(value, root=tmp_path, owner="unknown")


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "boolean-version",
        "fields",
        "fleet",
        "coverage",
        "entries",
        "entry-fields",
        "id",
        "duplicate-id",
        "owner",
        "state",
        "review-fields",
        "reviewer",
        "date",
        "index-window",
        "review-window",
        "reference",
        "digest",
    ],
)
def test_malformed_index_contract(change):
    value = index()
    entry = value["entries"][0]
    if change in ("version", "boolean-version"):
        value["fleet_version"] = 2 if change == "version" else True
    elif change == "fields":
        value["extra"] = True
    elif change == "fleet":
        value["fleet"] = ""
    elif change == "coverage":
        value["coverage"] = []
    elif change == "entries":
        value["entries"] = {}
    elif change == "entry-fields":
        del entry["owner"]
    elif change == "id":
        entry["id"] = "bad\nID"
    elif change == "duplicate-id":
        value["entries"].append(copy.deepcopy(entry))
    elif change == "owner":
        entry["owner"] = 0
    elif change == "state":
        entry["review"]["state"] = "approved"
    elif change == "review-fields":
        entry["review"]["extra"] = "x"
    elif change == "reviewer":
        entry["review"]["reviewer"] = " "
    elif change == "date":
        entry["review"]["expires"] = "2026-02-30"
    elif change == "index-window":
        value["expires"] = "2026-10-10"
    elif change == "review-window":
        entry["review"]["expires"] = "2026-10-10"
    elif change == "reference":
        entry["ir"] = "file"
    else:
        entry["ir"]["sha256"] = "invalid"
    with pytest.raises(ValueError):
        run(value)


def test_duplicate_index_json_keys_are_rejected():
    content = (
        (EXAMPLE / "index.json")
        .read_bytes()
        .replace(b'"fleet_version": 1', b'"fleet_version": 1, "fleet_version": 1')
    )
    with pytest.raises(ValueError, match="duplicate"):
        inventory(content, root=ROOT, as_of="2026-10-11")


def test_bad_query_date_and_root_are_usage_errors(tmp_path):
    with pytest.raises(ValueError):
        run(as_of="20261011")
    with pytest.raises(ValueError):
        run(owner=3)
    with pytest.raises(ValueError, match="directory"):
        run(root=tmp_path / "not-a-directory")


def test_cli_json_clean_and_filtered_findings_preserve_exit_code(capsys):
    argv = [
        "fleet",
        "inventory",
        str(EXAMPLE / "index.json"),
        "--root",
        str(ROOT),
        "--as-of",
        "2026-10-11",
        "--json",
    ]
    assert main(argv) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["schema"] == "agentmandate.fleet-inventory/v2"
    assert not output.err
    argv[2] = str(EXAMPLE / "findings.json")
    argv.remove("--json")
    assert main([*argv, "--tool", "unknown"]) == 1
    output = capsys.readouterr()
    assert "FINDING fleet.artifact-digest_mismatch" in output.out
    assert "ENTRY " not in output.out
    assert not output.err


def test_cli_missing_index_has_empty_stdout_and_usage_exit(tmp_path, capsys):
    assert (
        main(
            [
                "fleet",
                "inventory",
                str(tmp_path / "missing"),
                "--root",
                str(ROOT),
                "--as-of",
                "2026-10-11",
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert not captured.out and captured.err.startswith("error: ")


def test_cli_symlink_loop_is_an_unavailable_entry(tmp_path, capsys):
    value = local_index(tmp_path)
    (tmp_path / "loop").symlink_to("loop")
    value["entries"][0]["manifest"]["path"] = "loop"
    path = tmp_path / "index.json"
    path.write_text(json.dumps(value))
    assert (
        main(
            [
                "fleet",
                "inventory",
                str(path),
                "--root",
                str(tmp_path),
                "--as-of",
                "2026-10-11",
                "--json",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert codes(report) == {"fleet.artifact-unavailable"}
    assert report["summary"]["eligible_snapshots"] == 2
    assert not captured.err
