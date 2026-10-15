"""Index exact local manifest/IR pairs without merging their authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

from ._deployment_drift import _coverage, _date
from ._ir import AuthorityIR, _to_mandate
from ._policy_export import object_fields, pairs, string
from .manifest import loads

FLEET_VERSION = 1
RESULT_SCHEMA = "agentmandate.fleet-inventory/v2"


def _reference(value):
    object_fields(value, {"path", "sha256"}, "fleet artifact reference")
    locator = string(value["path"])
    if (
        "\\" in locator
        or ":" in locator.split("/")[0]
        or any(part in ("", ".", "..") for part in locator.split("/"))
    ):
        raise ValueError("fleet artifact paths must be normalized relative paths")
    if not isinstance(value["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", value["sha256"]):
        raise ValueError("fleet artifact sha256 must be 64 lowercase hexadecimal characters")


def _index(content):
    value = object_fields(
        json.loads(content, object_pairs_hook=pairs),
        {"fleet_version", "fleet", "coverage", "observed_at", "expires", "entries"},
        "fleet index",
    )
    if type(value["fleet_version"]) is not int or value["fleet_version"] != 1:
        raise ValueError("unsupported fleet_version")
    string(value["fleet"])
    _coverage(value["coverage"])
    if _date(value["observed_at"]) > _date(value["expires"]):
        raise ValueError("fleet expiry precedes observation date")
    if not isinstance(value["entries"], list):
        raise ValueError("fleet entries must be an array")
    seen = set()
    for entry in value["entries"]:
        object_fields(
            entry,
            {"id", "repository", "revision", "environment", "owner", "review", "manifest", "ir"},
            "fleet entry",
        )
        for field in ("id", "repository", "revision", "environment"):
            string(entry[field])
        if entry["id"] in seen:
            raise ValueError("fleet entry IDs must be distinct")
        seen.add(entry["id"])
        if entry["owner"] is not None:
            string(entry["owner"])
        review = object_fields(
            entry["review"], {"state", "reviewer", "reviewed_at", "expires"}, "fleet review"
        )
        if review["state"] not in ("accepted", "unreviewed", "contested"):
            raise ValueError("fleet review state must be accepted, unreviewed or contested")
        if review["reviewer"] is not None:
            string(review["reviewer"])
        for field in ("reviewed_at", "expires"):
            if review[field] is not None:
                _date(review[field])
        if (
            review["reviewed_at"] is not None
            and review["expires"] is not None
            and _date(review["reviewed_at"]) > _date(review["expires"])
        ):
            raise ValueError("fleet review expiry precedes review date")
        for field in ("manifest", "ir"):
            _reference(entry[field])
    return value


def inventory(content: bytes, *, root: Path, as_of: str, owner=None, environment=None, tool=None):
    """Query supplied declarations; filters never hide gate findings."""
    today = _date(as_of)
    index = _index(content)
    for query in (owner, environment, tool):
        if query is not None:
            string(query)
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("--root must be a fleet artifact directory")
    findings = []

    def finding(code, subject, detail):
        findings.append({"code": code, "subject": subject, "detail": detail})

    current = _date(index["observed_at"]) <= today <= _date(index["expires"])
    if not current:
        finding(
            "fleet.snapshot-not-current", index["fleet"], "index is outside its declared window"
        )
    if index["coverage"] != "complete":
        finding(
            "fleet.coverage-incomplete", index["fleet"], "index does not declare complete coverage"
        )
    cache = {}

    def read(locator):
        if locator not in cache:
            try:
                path = (root / locator).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("fleet artifact must resolve inside --root")
                cache[locator] = (path.read_bytes(), None)
            except (OSError, RuntimeError) as exc:
                cache[locator] = (None, str(exc))
        return cache[locator]

    rows = []
    deployments = {}
    for entry in sorted(index["entries"], key=lambda item: item["id"]):
        identifier = entry["id"]
        review = entry["review"]
        reviewed = (
            review["state"] == "accepted"
            and review["reviewer"] is not None
            and review["reviewed_at"] is not None
            and review["expires"] is not None
            and _date(review["reviewed_at"]) <= today <= _date(review["expires"])
        )
        if not reviewed:
            finding(
                "fleet.review-not-current",
                identifier,
                "declared acceptance, reviewer and inclusive review window are required",
            )
        if entry["owner"] is None:
            finding("fleet.owner-unassigned", identifier, "no accountable owner is declared")
        row = {
            **{
                field: entry[field]
                for field in ("id", "repository", "revision", "environment", "owner")
            },
            "review": review,
            "review_current": reviewed,
            "snapshot_eligible": False,
            "agent": None,
            "identity": None,
            "declared_tools": None,
            "artifacts": {},
        }
        rows.append(row)
        contents = {}
        for kind in ("manifest", "ir"):
            reference = entry[kind]
            captured, error = read(reference["path"])
            digest = hashlib.sha256(captured).hexdigest() if captured is not None else None
            status = (
                "unavailable"
                if captured is None
                else "verified"
                if digest == reference["sha256"]
                else "digest_mismatch"
            )
            row["artifacts"][kind] = {
                "path": reference["path"],
                "expected_sha256": reference["sha256"],
                "observed_sha256": digest,
                "status": status,
            }
            if status != "verified":
                finding(
                    "fleet.artifact-" + status,
                    f"{identifier}.{kind}",
                    error if error is not None else "bytes do not match the pinned artifact digest",
                )
            else:
                contents[kind] = captured
        if len(contents) != 2:
            continue
        try:
            mandate = loads(contents["manifest"].decode("utf-8"))
            raw_graph = json.loads(contents["ir"], object_pairs_hook=pairs)
            graph = AuthorityIR.from_json(json.dumps(raw_graph))
            restored = _to_mandate(graph)
            source = next(s for s in graph.sources if s.id == "source:mandate")
            if source.content_sha256 != entry["manifest"]["sha256"]:
                raise ValueError("IR source digest does not join the exact manifest bytes")
            if replace(restored, source=None) != mandate:
                raise ValueError("IR mandate does not match the supplied manifest")
        except (ValueError, UnicodeError, RecursionError) as exc:
            finding("fleet.snapshot-ineligible", identifier, str(exc))
            continue
        row.update(
            snapshot_eligible=True,
            agent=mandate.agent,
            identity=mandate.identity,
            declared_tools=[
                {
                    "name": item.name,
                    "effect": item.effect,
                    "principal": item.principal,
                    "requires_approval": item.requires_approval,
                }
                for item in sorted(mandate.tools, key=lambda item: item.name)
            ],
        )
        # Different IDs must not silently double-count the same declared deployment.
        deployment = (entry["repository"], entry["environment"], mandate.agent)
        if deployment in deployments:
            finding(
                "fleet.deployment-ambiguous",
                identifier,
                f"same repository/environment/agent also listed as {deployments[deployment]!r}; "
                "revisions are not separate deployment identities",
            )
        deployments[deployment] = identifier
    selected = [
        row
        for row in rows
        if (owner is None or row["owner"] == owner)
        and (environment is None or row["environment"] == environment)
        and (tool is None or any(item["name"] == tool for item in row["declared_tools"] or []))
    ]
    return {
        "schema": RESULT_SCHEMA,
        "scope": (
            "declared manifest tools and local IR joins; "
            "not runtime exposure or cross-agent reachability"
        ),
        "status": "findings_or_unresolved" if findings else "consistent_with_declared_index",
        "fleet": index["fleet"],
        "as_of": as_of,
        "snapshot_current": current,
        "declared_coverage": index["coverage"],
        "inventory_complete_within_declared_index": (
            current
            and index["coverage"] == "complete"
            and all(row["snapshot_eligible"] for row in rows)
            and not any(f["code"] == "fleet.deployment-ambiguous" for f in findings)
        ),
        "signatures": "not_verified",
        "index_sha256": hashlib.sha256(content).hexdigest(),
        "query": {"owner": owner, "environment": environment, "tool": tool},
        "summary": {
            "entries": len(rows),
            "selected_entries": len(selected),
            "eligible_snapshots": sum(row["snapshot_eligible"] for row in rows),
            "current_reviews": sum(row["review_current"] for row in rows),
            "unassigned_owners": sum(row["owner"] is None for row in rows),
            "declared_tool_occurrences": sum(len(row["declared_tools"] or []) for row in rows),
        },
        "entries": selected,
        "findings": findings,
    }


def render(report):
    lines = [
        f"FLEET {report['fleet']}: {report['status']}",
        f"SCOPE {report['scope']}",
        f"COVERAGE {report['declared_coverage']} as_of={report['as_of']}",
        "SUMMARY " + json.dumps(report["summary"], sort_keys=True),
    ]
    for row in report["entries"]:
        lines.append(
            f"ENTRY {row['id']} repository={row['repository']} revision={row['revision']} "
            f"environment={row['environment']} owner={row['owner']} "
            f"snapshot_eligible={row['snapshot_eligible']} review_current={row['review_current']}"
        )
        for item in row["declared_tools"] or []:
            lines.append(
                f"TOOL {row['id']}/{item['name']} effect={item['effect']} "
                f"principal={item['principal']} approval={item['requires_approval']}"
            )
    lines.extend(
        f"FINDING {row['code']} {row['subject']}: {row['detail']}" for row in report["findings"]
    )
    lines.append("Signatures: not verified. Declared tools are not authenticated live exposure.")
    return "\n".join(lines) + "\n"
