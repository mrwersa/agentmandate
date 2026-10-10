"""Eligibility of caller-supplied acceptance, separate from authority analysis."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from .diff import compare
from .manifest import loads

CHANGE_REVIEW_SCHEMA = "agentmandate.change-review/v1"
REVIEW_RESULT_SCHEMA = "agentmandate.review/v1"
REVIEW_SCOPE = "all_widening_changes_in_pinned_comparison"


def _object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("change-review record has unsupported or missing fields")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\x00"):
        raise ValueError("change-review names and annotations must be nonblank strings")
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("change-review digest must be lowercase SHA-256")
    return value


def _date(value):
    if not isinstance(value, str):
        raise ValueError("change-review date must be YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("change-review date must be YYYY-MM-DD")
    return parsed


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate change-review field {key!r}")
        result[key] = value
    return result


def _decision(content):
    raw = _object(
        json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object),
        (
            "schema",
            "agent",
            "before_sha256",
            "after_sha256",
            "comparison_sha256",
            "depth",
            "scope",
            "owner",
            "reviewer",
            "reason",
            "decision",
            "reviewed_at",
            "expires",
            "evidence",
            "target_policy",
        ),
    )
    if raw["schema"] != CHANGE_REVIEW_SCHEMA or raw["scope"] != REVIEW_SCOPE:
        raise ValueError("unsupported change-review schema or scope")
    for field in ("agent", "owner", "reviewer", "reason"):
        _text(raw[field])
    for field in ("before_sha256", "after_sha256", "comparison_sha256"):
        _digest(raw[field])
    if type(raw["depth"]) is not int or raw["depth"] < 1:
        raise ValueError("change-review depth must be a positive whole number")
    if raw["decision"] not in ("accept", "reject", "defer"):
        raise ValueError("unsupported change-review decision")
    if _date(raw["reviewed_at"]) > _date(raw["expires"]):
        raise ValueError("change-review expiry precedes its review date")
    policy = _object(raw["target_policy"], ("status", "reason"))
    if policy["status"] not in ("evidence_recorded", "not_applicable", "unresolved"):
        raise ValueError("unsupported change-review target-policy status")
    _text(policy["reason"])
    evidence = raw["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("change-review needs named decision evidence")
    names = set()
    purposes = set()
    for row in evidence:
        row = _object(row, ("locator", "sha256", "purpose"))
        name = _text(row["locator"])
        if "=" in name:
            raise ValueError("change-review evidence locator must not contain '='")
        if name in names:
            raise ValueError("duplicate change-review evidence locator")
        names.add(name)
        _digest(row["sha256"])
        if row["purpose"] not in ("decision", "target_policy"):
            raise ValueError("unsupported change-review evidence purpose")
        purposes.add(row["purpose"])
    if "decision" not in purposes or (
        policy["status"] == "evidence_recorded" and "target_policy" not in purposes
    ):
        raise ValueError("change-review lacks evidence for its decision or target-policy status")
    return raw


def evaluate(before_content, after_content, *, as_of, depth=None, decision=None, sources=None):
    """Recompute the diff; a record can satisfy only its separate review gate."""
    today = _date(as_of)
    before = loads(before_content.decode("utf-8"))
    after = loads(after_content.decode("utf-8"))
    delta = compare(before, after, depth=depth)
    comparison = delta.as_dict()
    comparison_bytes = json.dumps(comparison, sort_keys=True, separators=(",", ":")).encode()
    inputs = {
        "agent": after.agent,
        "before_sha256": hashlib.sha256(before_content).hexdigest(),
        "after_sha256": hashlib.sha256(after_content).hexdigest(),
        "comparison_sha256": hashlib.sha256(comparison_bytes).hexdigest(),
        "depth": delta.after.depth,
    }
    findings = []
    report = {
        "schema": REVIEW_RESULT_SCHEMA,
        "scope": (
            "recorded acceptance of a bounded diff; "
            "not reviewer authentication or deployment approval"
        ),
        "as_of": as_of,
        "inputs": inputs,
        "comparison": comparison,
        "review": None,
        "findings": findings,
    }

    def finding(rule, detail):
        findings.append({"rule": rule, "detail": detail})

    sources = {} if sources is None else sources
    if decision is None:
        if sources:
            raise ValueError("review sources require a decision record")
        if delta.widened:
            finding("review.decision-missing", "widening needs a scoped, evidenced acceptance")
    else:
        raw = _decision(decision)
        declared = {row["locator"] for row in raw["evidence"]}
        if set(sources) != declared:
            raise ValueError("review sources must map exactly every declared evidence locator")
        checks = []
        for row in raw["evidence"]:
            actual = hashlib.sha256(sources[row["locator"]]).hexdigest()
            matches = actual == row["sha256"]
            checks.append({**row, "actual_sha256": actual, "matches": matches})
            if not matches:
                finding("review.evidence-mismatch", f"source bytes differ for {row['locator']!r}")
        for field, actual in inputs.items():
            if raw[field] != actual:
                finding("review.comparison-mismatch", f"review does not match computed {field}")
        if today < _date(raw["reviewed_at"]):
            finding("review.not-yet-effective", "evaluation date precedes the recorded decision")
        if today > _date(raw["expires"]):
            finding("review.expired", "recorded acceptance has expired (inclusive UTC date)")
        if raw["decision"] != "accept":
            finding("review.not-accepted", f"recorded decision is {raw['decision']}")
        if raw["target_policy"]["status"] == "unresolved":
            finding("review.target-policy-unresolved", "target-policy disposition needs review")
        report["review"] = {
            **raw,
            "source_sha256": hashlib.sha256(decision).hexdigest(),
            "evidence_checks": checks,
            "eligible": not findings,
            "attestation": (
                "caller-supplied annotations and pinned bytes; "
                "author identity and enforcement not verified"
            ),
        }
    report["status"] = (
        "recorded_acceptance_unresolved"
        if findings
        else "eligible_recorded_acceptance"
        if delta.widened
        else "review_not_required_within_bound"
    )
    report["gate_satisfied"] = not findings
    return report


def render(report):
    lines = [f"REVIEW {report['status']}", f"SCOPE {report['scope']}"]
    if report["review"] is not None:
        review = report["review"]
        lines.append(
            f"RECORD owner={review['owner']} reviewer={review['reviewer']} "
            f"decision={review['decision']} eligible={review['eligible']} "
            f"expires={review['expires']}"
        )
        lines.append(f"ATTESTATION {review['attestation']}")
        lines.append(
            f"TARGET POLICY {review['target_policy']['status']}: "
            f"{review['target_policy']['reason']}"
        )
    comparison = report["comparison"]
    truncated = comparison["before"]["truncated"] or comparison["after"]["truncated"]
    lines.append(
        f"DIFF {comparison['direction']} depth={report['inputs']['depth']} truncated={truncated}"
    )
    lines.extend(
        f"CHANGE {row['direction']} {row['kind']}: {row['detail']}" for row in comparison["changes"]
    )
    lines.extend(
        f"BREACH {row['kind']}: {row['detail']}" for row in comparison["after"]["breaches"]
    )
    lines.extend(f"FINDING {row['rule']}: {row['detail']}" for row in report["findings"])
    lines.append("Authority findings remain unchanged; run lint/reach separately before release.")
    return "\n".join(lines)
