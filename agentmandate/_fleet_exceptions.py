"""Check temporary recorded review delays without rewriting inventory findings."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from ._deployment_drift import _date
from ._fleet import _reference, inventory
from ._policy_export import object_fields, pairs, string

EXCEPTIONS_VERSION = 1
RESULT_SCHEMA = "agentmandate.fleet-exceptions/v1"


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError("exception digests must be 64 lowercase hexadecimal characters")
    return value


def _fingerprint(finding):
    return hashlib.sha256(
        json.dumps(finding, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _document(content):
    value = object_fields(
        json.loads(content, object_pairs_hook=pairs),
        {"exceptions_version", "fleet_index_sha256", "exceptions"},
        "fleet exceptions",
    )
    if type(value["exceptions_version"]) is not int or value["exceptions_version"] != 1:
        raise ValueError("unsupported exceptions_version")
    _digest(value["fleet_index_sha256"])
    if not isinstance(value["exceptions"], list):
        raise ValueError("exceptions must be an array")
    seen = set()
    for record in value["exceptions"]:
        object_fields(
            record,
            {
                "id",
                "entry_id",
                "owner",
                "reviewer",
                "reason",
                "decision",
                "issued_at",
                "expires",
                "finding_sha256",
                "evidence",
            },
            "fleet exception record",
        )
        for field in ("id", "entry_id", "owner", "reviewer", "reason"):
            string(record[field])
        if record["id"] in seen:
            raise ValueError("exception IDs must be distinct")
        seen.add(record["id"])
        if record["decision"] != "accept_review_delay":
            raise ValueError("only accept_review_delay exceptions are supported")
        if _date(record["issued_at"]) > _date(record["expires"]):
            raise ValueError("exception expiry precedes its decision date")
        _digest(record["finding_sha256"])
        if not isinstance(record["evidence"], dict) or not record["evidence"]:
            raise ValueError("exception evidence must be a nonempty named reference object")
        for name, reference in record["evidence"].items():
            string(name)
            _reference(reference)
    return value


def evaluate(index_content: bytes, exception_content: bytes, *, root: Path, as_of: str):
    document = _document(exception_content)
    baseline = inventory(index_content, root=root, as_of=as_of)
    today = _date(as_of)
    root = root.resolve()
    entries = {row["id"]: row for row in baseline["entries"]}
    findings = []

    def finding(code, subject, detail):
        findings.append({"code": "fleet-exception." + code, "subject": subject, "detail": detail})

    exact = document["fleet_index_sha256"] == baseline["index_sha256"]
    if not exact:
        finding(
            "index-mismatch", baseline["fleet"], "exception index pin differs from supplied bytes"
        )
    counts = Counter(record["entry_id"] for record in document["exceptions"])
    fingerprints = {_fingerprint(f): f for f in baseline["findings"]}
    accepted = {}
    assessments = []
    cache = {}
    for record in sorted(document["exceptions"], key=lambda r: r["id"]):
        identifier = record["id"]
        entry = entries.get(record["entry_id"])
        target = fingerprints.get(record["finding_sha256"])
        valid = exact
        row = {
            **{
                k: record[k]
                for k in (
                    "id",
                    "entry_id",
                    "owner",
                    "reviewer",
                    "reason",
                    "issued_at",
                    "expires",
                    "finding_sha256",
                )
            },
            "status": "ineligible",
            "evidence": {},
        }
        assessments.append(row)
        if counts[record["entry_id"]] != 1:
            finding("target-ambiguous", identifier, "multiple exceptions target the same entry")
            valid = False
        if not _date(record["issued_at"]) <= today <= _date(record["expires"]):
            finding("not-current", identifier, "exception is outside its inclusive decision window")
            valid = False
        if entry is None:
            finding("entry-missing", identifier, "exception entry is not in the supplied index")
            valid = False
        else:
            review = entry["review"]
            overdue = (
                review["state"] == "accepted"
                and review["reviewer"] is not None
                and review["reviewed_at"] is not None
                and review["expires"] is not None
                and _date(review["expires"]) < today
            )
            if entry["owner"] != record["owner"]:
                finding("owner-mismatch", identifier, "exception owner differs from indexed owner")
                valid = False
            if not (
                overdue
                and entry["snapshot_eligible"]
                and baseline["snapshot_current"]
                and baseline["declared_coverage"] == "complete"
            ):
                finding(
                    "review-delay-ineligible",
                    identifier,
                    "only an overdue accepted review on a current complete pinned snapshot "
                    "can receive a temporary review-delay exception",
                )
                valid = False
        if target is None or (
            target["code"] != "fleet.review-not-current" or target["subject"] != record["entry_id"]
        ):
            finding(
                "finding-mismatch",
                identifier,
                "exception must pin this entry's current review-not-current finding",
            )
            valid = False
        for name, reference in sorted(record["evidence"].items()):
            locator = reference["path"]
            if locator not in cache:
                try:
                    path = (root / locator).resolve()
                    if not path.is_relative_to(root):
                        raise ValueError("exception evidence must resolve inside --root")
                    cache[locator] = (hashlib.sha256(path.read_bytes()).hexdigest(), None)
                except (OSError, RuntimeError) as exc:
                    cache[locator] = (None, str(exc))
            observed, error = cache[locator]
            verified = observed == reference["sha256"]
            row["evidence"][name] = {
                "path": locator,
                "expected_sha256": reference["sha256"],
                "observed_sha256": observed,
                "status": "verified" if verified else "untrusted",
            }
            if not verified:
                finding(
                    "evidence-untrusted",
                    f"{identifier}.{name}",
                    error if error is not None else "evidence bytes differ from their pin",
                )
                valid = False
        if valid:
            row["status"] = "eligible_review_delay_within_recorded_scope"
            accepted[record["finding_sha256"]] = identifier
    routes = []
    uncovered = []
    global_codes = {"fleet.snapshot-not-current", "fleet.coverage-incomplete"}
    for item in baseline["findings"]:
        fingerprint = _fingerprint(item)
        subject = item["subject"]
        if item["code"].startswith("fleet.artifact-"):
            subject = subject.rsplit(".", 1)[0]
        entry = None if item["code"] in global_codes else entries.get(subject)
        exception_id = accepted.get(fingerprint)
        routes.append(
            {
                "finding": item,
                "finding_sha256": fingerprint,
                "entry_id": None if entry is None else entry["id"],
                "owner": None if entry is None else entry["owner"],
                "exception_id": exception_id,
                "disposition": (
                    "accepted_review_delay_within_recorded_scope" if exception_id else "blocked"
                ),
            }
        )
        if exception_id is None:
            uncovered.append(item)
    gate_passed = not findings and not uncovered
    return {
        "schema": RESULT_SCHEMA,
        "scope": "recorded temporary review delay; not renewed review or deployment approval",
        "status": (
            "recorded_exceptions_eligible"
            if gate_passed and accepted
            else "no_exception_needed"
            if gate_passed
            else "findings_or_unresolved"
        ),
        "gate_passed": gate_passed,
        "as_of": as_of,
        "inputs": {
            "index_sha256": baseline["index_sha256"],
            "exceptions_sha256": hashlib.sha256(exception_content).hexdigest(),
        },
        "review_authentication": "not_verified",
        "renewal": "not_performed",
        "inventory": baseline,
        "routes": routes,
        "exceptions": assessments,
        "uncovered_findings": uncovered,
        "findings": findings,
    }


def render(report):
    lines = [f"FLEET EXCEPTIONS {report['status']}", f"SCOPE {report['scope']}"]
    for route in report["routes"]:
        item = route["finding"]
        lines.append(f"BASELINE FINDING {item['code']} {item['subject']}: {item['detail']}")
        lines.append(
            f"ROUTE owner={route['owner']} disposition={route['disposition']} "
            f"exception={route['exception_id']}"
        )
    for record in report["exceptions"]:
        lines.append(
            f"EXCEPTION {record['id']} owner={record['owner']} "
            f"reviewer={record['reviewer']} expires={record['expires']} "
            f"status={record['status']}"
        )
    lines.extend(f"FINDING {r['code']} {r['subject']}: {r['detail']}" for r in report["findings"])
    lines.append("Review authentication: not verified. Renewal: not performed.")
    return "\n".join(lines) + "\n"
