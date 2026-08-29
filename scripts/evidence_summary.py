"""Build the paper-facing evidence summary from committed capture records.

The summary is deterministic and offline. It never guesses a missing correction
class. Legacy records without one stay explicitly unclassified, and
``--require-complete-classification`` fails until that scientific boundary is
resolved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
OUTPUT = EVIDENCE / "evidence-summary.json"
GENERATED_AT = "2026-08-29T18:06:26Z"
CLASSES = {"extractor defect", "source ambiguity", "model gap", "deployment policy"}

CAPTURES = (
    (
        "agentkit",
        "Coinbase AgentKit",
        "0.1.6 -> 0.7.4",
        "digital assets",
        "framework capability gate",
        20,
        20,
        "static-source",
        True,
    ),
    (
        "github-mcp-server",
        "GitHub MCP Server",
        "1.8.0",
        "software delivery",
        "downstream service",
        23,
        23,
        "local-runtime",
        True,
    ),
    (
        "aws-postgres-mcp",
        "AWS PostgreSQL MCP Server",
        "1.1.11",
        "data systems",
        "downstream service",
        7,
        7,
        "static-source",
        True,
    ),
    (
        "sentry-mcp",
        "Sentry MCP Server",
        "0.37.0",
        "operations SaaS",
        "tool implementation",
        8,
        8,
        "local-runtime",
        True,
    ),
    (
        "initiative-mcp",
        "Initiative",
        "0.63.4",
        "work management",
        "tool implementation",
        25,
        25,
        "local-runtime",
        True,
    ),
    (
        "authorizer-delegation",
        "Authorizer",
        "2.4.0",
        "identity",
        "credential scope",
        None,
        0,
        "local-runtime",
        False,
    ),
    (
        "agentcore-refund-policy",
        "Amazon Bedrock AgentCore",
        "CLI 0.28.1 / capture 2026-08-29",
        "cloud platform",
        "gateway policy engine",
        1,
        1,
        "managed-live",
        True,
    ),
    (
        "aws-iam-access-keys",
        "AWS IAM MCP Server",
        "1.0.11",
        "cloud identity",
        "downstream service",
        29,
        1,
        "managed-live",
        True,
    ),
)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _corrections(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for capture in CAPTURES:
        capture_id = capture[0]
        payload = _read(root / capture_id / "corrections.json")
        if payload.get("corrections_version") != 1 or payload.get("capture") != capture_id:
            raise ValueError(f"{capture_id}: invalid corrections envelope")
        for record in payload.get("corrections", []):
            required = {
                "id",
                "reported_class",
                "classes",
                "classification_status",
                "affected_artifact",
                "description",
            }
            if set(record) != required:
                raise ValueError(f"{capture_id}: correction fields are not exact")
            classes = record.get("classes")
            status = record.get("classification_status")
            if not isinstance(classes, list) or any(item not in CLASSES for item in classes):
                raise ValueError(f"{capture_id}: correction has an invalid canonical class")
            if status not in {"canonical", "missing", "noncanonical"}:
                raise ValueError(f"{capture_id}: correction has an invalid classification status")
            if (status == "canonical") != bool(classes):
                raise ValueError(f"{capture_id}: correction class and status disagree")
            artifact = record["affected_artifact"]
            if not isinstance(artifact, str) or not (root / capture_id / artifact).is_file():
                raise ValueError(f"{capture_id}: correction artifact is not committed")
            if not isinstance(record["description"], str) or not record["description"].strip():
                raise ValueError(f"{capture_id}: correction description is empty")
            records.append({"capture": capture_id, **record})
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("correction ids are not unique")
    return records


def _managed_comparison(root: Path) -> dict[str, Any]:
    directory = root / "agentcore-refund-policy"
    baseline = _read(directory / "managed-oracle-v1.json")
    candidate = _read(directory / "candidate-managed-oracle-v1.json")
    baseline_by_args = {
        json.dumps(item["arguments"], sort_keys=True): item for item in baseline["decisions"]
    }
    candidate_by_args = {
        json.dumps(item["arguments"], sort_keys=True): item for item in candidate["decisions"]
    }
    if baseline_by_args.keys() != candidate_by_args.keys():
        raise ValueError("managed comparison request sets differ")
    changes = {
        ("allow", "allow"): "stable_allow",
        ("deny", "deny"): "stable_deny",
        ("deny", "allow"): "widens",
        ("allow", "deny"): "tightens",
    }
    requests = []
    for key in sorted(baseline_by_args):
        before = baseline_by_args[key]
        after = candidate_by_args[key]
        requests.append(
            {
                "arguments": before["arguments"],
                "baseline": before["outcome"],
                "candidate": after["outcome"],
                "change": changes[(before["outcome"], after["outcome"])],
            }
        )
    return {
        "capture": "agentcore-refund-policy",
        "baseline_revision": baseline["policy_inventory"]["members"][0]["name"],
        "candidate_revision": candidate["policy_inventory"]["members"][0]["name"],
        "requests": requests,
        "counterexample_length": None,
        "analysis_wall_clock_ms": None,
        "instrumentation_status": "missing",
    }


def build_summary(root: Path = EVIDENCE) -> dict[str, Any]:
    corrections = _corrections(root)
    canonical = sum(record["classification_status"] == "canonical" for record in corrections)
    captures = [
        {
            "id": item[0],
            "upstream_project": item[1],
            "pinned_version": item[2],
            "domain": item[3],
            "enforcement_pattern": item[4],
            "captured_tool_count": item[5],
            "analysed_tool_count": item[6],
            "capture_kind": item[7],
            "authority_graph": item[8],
        }
        for item in CAPTURES
    ]
    return {
        "summary_version": 1,
        "generated_at": GENERATED_AT,
        "capture_count": len(captures),
        "authority_graph_count": sum(item["authority_graph"] for item in captures),
        "captures": captures,
        "correction_classification": {
            "complete": canonical == len(corrections),
            "canonical_records": canonical,
            "total_records": len(corrections),
            "class_counts": None,
            "reason": (
                None
                if canonical == len(corrections)
                else "legacy correction records lack canonical pre-study class labels"
            ),
        },
        "corrections": corrections,
        "live_comparisons": [_managed_comparison(root)],
    }


def render(summary: dict[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--require-complete-classification", action="store_true")
    args = parser.parse_args(argv)
    summary = build_summary()
    content = render(summary)
    if (
        args.require_complete_classification
        and not summary["correction_classification"]["complete"]
    ):
        print("error: correction classification is incomplete", file=sys.stderr)
        return 1
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            print("error: evidence summary is stale", file=sys.stderr)
            return 1
        print("evidence summary: current")
        return 0
    args.output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
