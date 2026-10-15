"""An exception can accept review delay, never repair an inventory trust failure."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from agentmandate._fleet import inventory
from agentmandate._fleet_exceptions import evaluate, render
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/fleet-exceptions"


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def data(name):
    return json.loads((EXAMPLE / name).read_bytes())


def fingerprint(finding):
    return hashlib.sha256(
        json.dumps(finding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def run(index=None, document=None, *, as_of="2026-10-11", root=ROOT, repin=True):
    index = data("index.json") if index is None else index
    document = data("exceptions.json") if document is None else document
    content = encode(index)
    if repin:
        document = copy.deepcopy(document)
        document["fleet_index_sha256"] = hashlib.sha256(content).hexdigest()
    return evaluate(content, encode(document), root=root, as_of=as_of)


def codes(report):
    return {f["code"] for f in report["findings"]}


def copy_root(tmp_path):
    for entry in data("index.json")["entries"]:
        for kind in ("manifest", "ir"):
            p = tmp_path / entry[kind]["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((ROOT / entry[kind]["path"]).read_bytes())
    note = tmp_path / "examples/fleet-exceptions/decision-note.txt"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_bytes((EXAMPLE / "decision-note.txt").read_bytes())
    return note


def test_eligible_and_expired_baselines_preserve_original_review_and_findings():
    for as_of, fixture in (
        ("2026-10-11", "fleet-exceptions-v2.json"),
        ("2026-10-19", "fleet-exceptions-expired-v2.json"),
    ):
        report = run(as_of=as_of)
        assert report == json.loads((ROOT / "tests/fixtures" / fixture).read_bytes())
        original = inventory(encode(data("index.json")), root=ROOT, as_of=as_of)
        assert report["inventory"] == original
        assert original["entries"][1]["review_current"] is False
        assert original["findings"][0]["code"] == "fleet.review-not-current"
        assert report["renewal"] == "not_performed"
        assert report["review_authentication"] == "not_verified"
        assert "BASELINE FINDING fleet.review-not-current" in render(report)
    assert run()["gate_passed"]


@pytest.mark.parametrize(
    "as_of,eligible",
    [
        ("2026-10-10", False),
        ("2026-10-11", True),
        ("2026-10-18", True),
        ("2026-10-19", False),
        ("2026-11-09", False),
    ],
)
def test_inclusive_window_and_lapsed_inventory(as_of, eligible):
    report = run(as_of=as_of)
    assert report["gate_passed"] is eligible
    assert (report["exceptions"][0]["status"] != "ineligible") is eligible
    if as_of == "2026-11-09":
        assert "fleet.snapshot-not-current" in {f["code"] for f in report["uncovered_findings"]}
        assert report["routes"][0]["owner"] is None


def test_index_byte_join_cannot_be_updated_by_reusing_an_old_exception():
    content = encode(data("index.json")) + b" "
    report = evaluate(content, encode(data("exceptions.json")), root=ROOT, as_of="2026-10-11")
    assert "fleet-exception.index-mismatch" in codes(report)
    assert not report["gate_passed"] and report["uncovered_findings"]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("owner", "other-owner", "owner-mismatch"),
        ("entry_id", "missing-entry", "entry-missing"),
        ("finding_sha256", "0" * 64, "finding-mismatch"),
    ],
)
def test_exact_target_and_owner_joins(field, value, code):
    document = data("exceptions.json")
    document["exceptions"][0][field] = value
    report = run(document=document)
    assert "fleet-exception." + code in codes(report)
    assert not report["gate_passed"]


@pytest.mark.parametrize(
    "change",
    [
        "unreviewed",
        "contested",
        "reviewer",
        "reviewed_at",
        "expires",
        "future",
        "owner",
        "partial",
        "unknown",
        "manifest_digest",
        "ir_digest",
        "snapshot",
    ],
)
def test_trust_and_unreviewed_gaps_cannot_be_excused_even_with_replaced_pins(change):
    index = data("index.json")
    entry = index["entries"][0]
    if change in ("unreviewed", "contested"):
        entry["review"]["state"] = change
    elif change in ("reviewer", "reviewed_at", "expires"):
        entry["review"][change] = None
    elif change == "future":
        entry["review"].update(reviewed_at="2026-10-12", expires="2026-10-18")
    elif change == "owner":
        entry["owner"] = None
    elif change in ("partial", "unknown"):
        index["coverage"] = change
    elif change.endswith("_digest"):
        entry[change.split("_")[0]]["sha256"] = "0" * 64
    else:
        index["expires"] = "2026-10-10"
        index["observed_at"] = "2026-10-01"
    report = run(index=index)
    assert not report["gate_passed"]
    assert report["exceptions"][0]["status"] == "ineligible"
    assert report["uncovered_findings"]


def test_exception_cannot_cover_another_finding_class_or_another_entry():
    index = data("index.json")
    index["entries"][0]["owner"] = None
    baseline = inventory(encode(index), root=ROOT, as_of="2026-10-11")
    document = data("exceptions.json")
    document["exceptions"][0]["finding_sha256"] = fingerprint(
        next(f for f in baseline["findings"] if f["code"] == "fleet.owner-unassigned")
    )
    report = run(index=index, document=document)
    assert "fleet-exception.finding-mismatch" in codes(report)
    assert all(r["disposition"] == "blocked" for r in report["routes"])
    document = data("exceptions.json")
    document["exceptions"][0]["entry_id"] = "release/staging"
    assert "fleet-exception.finding-mismatch" in codes(run(document=document))


def test_duplicate_targets_are_ambiguous_and_neither_record_wins():
    document = data("exceptions.json")
    document["exceptions"].append({**document["exceptions"][0], "id": "other-decision"})
    report = run(document=document)
    assert "fleet-exception.target-ambiguous" in codes(report)
    assert all(r["status"] == "ineligible" for r in report["exceptions"])
    assert report["routes"][0]["exception_id"] is None


def test_multiple_entries_can_use_one_pinned_note_but_not_one_finding():
    index = data("index.json")
    index["entries"][1]["review"].update(reviewed_at="2026-10-01", expires="2026-10-10")
    baseline = inventory(encode(index), root=ROOT, as_of="2026-10-11")
    document = data("exceptions.json")
    document["exceptions"].append(
        {
            **document["exceptions"][0],
            "id": "staging-review-delay",
            "entry_id": "release/staging",
            "finding_sha256": fingerprint(
                next(f for f in baseline["findings"] if f["subject"] == "release/staging")
            ),
        }
    )
    report = run(index=index, document=document)
    assert report["gate_passed"] and len(report["routes"]) == 2
    assert {r["owner"] for r in report["routes"]} == {"release-security"}


@pytest.mark.parametrize("change", ["tampered", "missing", "wrong-pin", "loop"])
def test_missing_or_tampered_evidence_blocks_acceptance_without_dropping_findings(tmp_path, change):
    note = copy_root(tmp_path)
    document = data("exceptions.json")
    if change == "tampered":
        note.write_bytes(note.read_bytes() + b" ")
    elif change == "missing":
        document["exceptions"][0]["evidence"]["decision-note"]["path"] = "absent.txt"
    elif change == "wrong-pin":
        document["exceptions"][0]["evidence"]["decision-note"]["sha256"] = "0" * 64
    else:
        loop = tmp_path / "loop.txt"
        loop.symlink_to("loop.txt")
        document["exceptions"][0]["evidence"]["decision-note"]["path"] = "loop.txt"
    report = run(root=tmp_path, document=document)
    assert "fleet-exception.evidence-untrusted" in codes(report)
    assert not report["gate_passed"] and report["uncovered_findings"]


def test_evidence_alias_does_not_hide_a_wrong_digest(tmp_path):
    copy_root(tmp_path)
    document = data("exceptions.json")
    evidence = document["exceptions"][0]["evidence"]
    evidence["other-note"] = {**evidence["decision-note"], "sha256": "0" * 64}
    report = run(root=tmp_path, document=document)
    assert "fleet-exception.evidence-untrusted" in codes(report)
    assert not report["gate_passed"]


def test_evidence_body_is_not_returned(tmp_path):
    note = copy_root(tmp_path)
    content = b"SYNTHETIC_PRIVATE_DECISION_BODY"
    note.write_bytes(content)
    document = data("exceptions.json")
    document["exceptions"][0]["evidence"]["decision-note"]["sha256"] = hashlib.sha256(
        content
    ).hexdigest()
    report = run(root=tmp_path, document=document)
    assert report["gate_passed"] and content.decode() not in json.dumps(report)


def test_evidence_symlink_escape_is_usage_error(tmp_path):
    copy_root(tmp_path)
    (tmp_path / "escape.txt").symlink_to(EXAMPLE / "decision-note.txt")
    document = data("exceptions.json")
    document["exceptions"][0]["evidence"]["decision-note"]["path"] = "escape.txt"
    with pytest.raises(ValueError, match="inside --root"):
        run(root=tmp_path, document=document)


def test_artifact_failures_route_to_the_entry_owner_and_cannot_be_excepted():
    index = data("index.json")
    index["entries"][2]["manifest"]["sha256"] = "0" * 64
    report = run(index=index)
    route = next(
        r for r in report["routes"] if r["finding"]["code"] == "fleet.artifact-digest_mismatch"
    )
    assert route["entry_id"] == "billing/prod" and route["owner"] == "billing-security"
    assert route["disposition"] == "blocked"
    assert report["exceptions"][0]["status"] != "ineligible"
    assert not report["gate_passed"]


def test_no_records_never_clear_an_overdue_review_and_clean_index_needs_no_exception():
    document = data("none.json")
    report = run(document=document)
    assert not report["gate_passed"] and report["uncovered_findings"]
    index = json.loads((ROOT / "examples/fleet-inventory/index.json").read_bytes())
    clean = run(index=index, document=document)
    assert clean["gate_passed"] and clean["status"] == "no_exception_needed"
    assert not clean["routes"] and not clean["exceptions"]
    assert not run(index=index)["gate_passed"]  # A stale exception is not silently ignored.


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "version",
        "version-bool",
        "index-digest",
        "array",
        "record-extra",
        "record-id",
        "decision",
        "reason",
        "owner",
        "reviewer",
        "date",
        "reverse-window",
        "finding-digest",
        "evidence-empty",
        "evidence-array",
        "evidence-name",
        "reference-extra",
        "reference-path",
        "reference-digest",
        "duplicate-id",
    ],
)
def test_malformed_records_are_usage_errors(change):
    document = data("exceptions.json")
    record = document["exceptions"][0]
    if change == "extra":
        document["unknown"] = True
    elif change.startswith("version"):
        document["exceptions_version"] = True if change.endswith("bool") else 2
    elif change == "index-digest":
        document["fleet_index_sha256"] = 123
    elif change == "array":
        document["exceptions"] = {}
    elif change == "record-extra":
        record["unknown"] = True
    elif change == "record-id":
        record["id"] = ""
    elif change == "decision":
        record["decision"] = "renew_review"
    elif change in ("reason", "owner", "reviewer"):
        record[change] = None
    elif change == "date":
        record["issued_at"] = "not-a-date"
    elif change == "reverse-window":
        record["expires"] = "2026-10-10"
    elif change == "finding-digest":
        record["finding_sha256"] = "hash"
    elif change.startswith("evidence-"):
        record["evidence"] = {
            "evidence-empty": {},
            "evidence-array": [],
            "evidence-name": {"": record["evidence"]["decision-note"]},
        }[change]
    elif change.startswith("reference-"):
        reference = record["evidence"]["decision-note"]
        if change == "reference-extra":
            reference["unknown"] = True
        elif change == "reference-path":
            reference["path"] = "../escape"
        else:
            reference["sha256"] = "hash"
    else:
        document["exceptions"].append(copy.deepcopy(record))
    with pytest.raises(ValueError):
        run(document=document, repin=False)


def test_duplicate_json_keys_are_not_overwritten():
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(
            encode(data("index.json")),
            b'{"exceptions_version":1,"exceptions_version":1}',
            root=ROOT,
            as_of="2026-10-11",
        )


def test_cli_baseline_finding_stays_visible_for_both_pass_and_failure(capsys, tmp_path):
    argv = [
        "fleet",
        "exceptions",
        str(EXAMPLE / "index.json"),
        "--exceptions",
        str(EXAMPLE / "exceptions.json"),
        "--root",
        str(ROOT),
        "--as-of",
        "2026-10-11",
        "--json",
    ]
    assert main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["inventory"]["findings"] and not report["uncovered_findings"]
    argv.remove("--json")
    argv[-1] = "2026-10-19"
    assert main(argv) == 1
    output = capsys.readouterr()
    assert "BASELINE FINDING" in output.out and "fleet-exception.not-current" in output.out
    argv[argv.index("--exceptions") + 1] = str(tmp_path / "missing")
    assert main(argv) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error:")


def test_cli_filters_cannot_hide_fleet_blockers(capsys):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "fleet",
                "exceptions",
                str(EXAMPLE / "index.json"),
                "--exceptions",
                str(EXAMPLE / "exceptions.json"),
                "--root",
                str(ROOT),
                "--as-of",
                "2026-10-11",
                "--owner",
                "release-security",
            ]
        )
    assert exc.value.code == 2 and not capsys.readouterr().out
