"""Compare declared fleet releases without composing their mandates."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from ._deployment_drift import _read
from ._fleet import inventory
from .diff import compare as compare_authority
from .manifest import loads
from .reach import analyse

RESULT_SCHEMA = "agentmandate.fleet-diff/v1"


def _side(content, root, as_of):
    report = inventory(content, root=root, as_of=as_of)
    mandates, captured, findings = {}, {}, []
    for row in report["entries"]:
        if not row["snapshot_eligible"]:
            continue
        reference = row["artifacts"]["manifest"]
        try:
            locator = reference["path"]
            if locator not in captured:
                captured[locator] = _read(root.resolve(), locator)
            material = captured[locator]
            if hashlib.sha256(material).hexdigest() != reference["observed_sha256"]:
                raise ValueError("manifest changed after inventory validation")
            mandates[row["id"]] = loads(material.decode("utf-8"))
        except (ValueError, OSError, RuntimeError) as exc:
            findings.append({
                "code": "fleet.diff-snapshot-untrusted", "subject": row["id"], "detail": str(exc),
            })
    return report, mandates, findings


def compare(
    baseline_content: bytes, candidate_content: bytes, *,
    baseline_root: Path, candidate_root: Path, as_of: str, depth: int = 8,
):
    """Retain inventory findings and per-deployment bounded authority results."""
    if type(depth) is not int or depth < 1:
        raise ValueError("depth must be a positive integer")
    sides = {
        "baseline": _side(baseline_content, baseline_root, as_of),
        "candidate": _side(candidate_content, candidate_root, as_of),
    }
    reports = {label: side[0] for label, side in sides.items()}
    findings = [
        {"side": label, **finding}
        for label, side in sides.items() for finding in side[0]["findings"] + side[2]
    ]

    def finding(code, subject, detail):
        findings.append({"side": "comparison", "code": "fleet.diff-" + code,
                         "subject": subject, "detail": detail})

    same_fleet = reports["baseline"]["fleet"] == reports["candidate"]["fleet"]
    if not same_fleet:
        finding("boundary-mismatch", "fleet", "index labels describe different fleet boundaries")
    membership = same_fleet and all(
        report["inventory_complete_within_declared_index"] and not sides[label][2]
        for label, report in reports.items()
    )
    groups = {label: defaultdict(list) for label in sides}
    unresolved_entries = {label: [] for label in sides}
    for label, report in reports.items():
        for row in report["entries"]:
            if row["agent"] is None:
                unresolved_entries[label].append(row["id"])
            else:
                groups[label][(row["repository"], row["environment"], row["agent"])].append(row)

    comparisons = []
    for key in sorted(groups["baseline"].keys() | groups["candidate"].keys()):
        entries = {label: group.get(key, []) for label, group in groups.items()}
        deployment = dict(zip(("repository", "environment", "agent"), key, strict=True))
        subject = json.dumps(deployment, sort_keys=True)
        row = {
            "deployment": deployment,
            "baseline_entries": [item["id"] for item in entries["baseline"]],
            "candidate_entries": [item["id"] for item in entries["candidate"]],
            "membership": "unresolved", "relation": "unresolved", "authority_diff": None,
            "metadata_changes": [],
        }
        comparisons.append(row)
        authorities = {label: {} for label in sides}
        if any(len(value) > 1 for value in entries.values()):
            finding("deployment-ambiguous", subject, "exactly one entry per deployment is required")
        elif all(entries.values()):
            row["membership"] = "matched"
            left, right = entries["baseline"][0], entries["candidate"][0]
            row["metadata_changes"] = [
                {"field": field, "before": left[field], "after": right[field]}
                for field in ("id", "revision", "owner", "review") if left[field] != right[field]
            ]
            if left["owner"] != right["owner"]:
                finding("owner-changed", subject, "ownership handoff requires separate review")
            if same_fleet and all(items[0]["id"] in sides[label][1]
                                  for label, items in entries.items()):
                delta = compare_authority(
                    sides["baseline"][1][left["id"]], sides["candidate"][1][right["id"]],
                    depth=depth,
                )
                row["authority_diff"] = delta.as_dict()
                row["relation"] = delta.direction + "_within_compared_manifest_scope"
                authorities["baseline"][left["id"]] = delta.before.as_dict()
                authorities["candidate"][right["id"]] = delta.after.as_dict()
                if delta.widened:
                    finding("authority-widened", subject, "matched manifest authority widened")
        elif membership:
            added = bool(entries["candidate"])
            row["membership"] = "added" if added else "removed"
            row["relation"] = row["membership"] + "_within_declared_index"
            if added:
                finding("deployment-added", subject,
                        "new declared deployment requires release review")
        else:
            finding("presence-unresolved", subject,
                    "incomplete, stale, ambiguous or different indexes cannot establish absence")

        for label, items in entries.items():
            for entry in items:
                identifier = entry["id"]
                if identifier not in authorities[label]:
                    mandate = sides[label][1].get(identifier)
                    authorities[label][identifier] = (
                        analyse(mandate, depth=depth).as_dict() if mandate is not None else None
                    )
                authority = authorities[label][identifier]
                if label == "candidate" and authority is not None and authority["breaches"]:
                    finding("authority-breach", identifier,
                            "candidate has reachable breaches within the search bound")
            row[label + "_authorities"] = authorities[label]

    return {
        "schema": RESULT_SCHEMA,
        "scope": "bounded per-deployment manifest authority and declared index membership; "
                 "not authenticated live exposure or cross-agent reachability",
        "status": "findings_or_unresolved" if findings else "clean_within_declared_fleet_scope",
        "as_of": as_of, "depth": depth, "membership_comparable": membership,
        "gate_passed": not findings,
        "baseline": reports["baseline"], "candidate": reports["candidate"],
        "comparisons": comparisons, "unresolved_entries": unresolved_entries,
        "summary": {
            "deployments": len(comparisons),
            "compared": sum(row["authority_diff"] is not None for row in comparisons),
            "widened": sum(row["authority_diff"] is not None
                           and row["authority_diff"]["direction"] == "widening"
                           for row in comparisons),
            "added": sum(row["membership"] == "added" for row in comparisons),
            "removed": sum(row["membership"] == "removed" for row in comparisons),
            "unresolved": sum(row["relation"] == "unresolved" for row in comparisons),
            "unresolved_entries": sum(len(ids) for ids in unresolved_entries.values()),
        },
        "signatures": "not_verified", "findings": findings,
    }


def render(report):
    lines = [f"FLEET DIFF {report['status']}", f"SCOPE {report['scope']}",
             f"BOUND depth={report['depth']} "
             f"membership_comparable={report['membership_comparable']}",
             "SUMMARY " + json.dumps(report["summary"], sort_keys=True)]
    for row in report["comparisons"]:
        lines.append("DEPLOYMENT " + json.dumps(row["deployment"], sort_keys=True)
                     + " " + row["relation"])
        for change in row["metadata_changes"]:
            lines.append("METADATA " + json.dumps(change, sort_keys=True))
        if row["authority_diff"] is not None:
            for change in row["authority_diff"]["changes"]:
                lines.append(f"CHANGE {change['direction']} {change['kind']}: {change['detail']}")
        for label in ("baseline", "candidate"):
            for identifier, authority in row[label + "_authorities"].items():
                lines.append(f"AUTHORITY {label} {identifier} "
                             + json.dumps(authority, sort_keys=True))
    for label, ids in report["unresolved_entries"].items():
        for identifier in ids:
            lines.append(f"UNRESOLVED {label} {identifier}: snapshot identity unavailable")
    lines.extend(f"FINDING {item['side']} {item['code']} {item['subject']}: {item['detail']}"
                 for item in report["findings"])
    lines.append("Signatures: not verified. Each mandate and budget remains separate.")
    return "\n".join(lines) + "\n"
