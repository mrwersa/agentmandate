"""Build the paper-facing evidence summary from committed capture records.

The summary is deterministic and offline. It never guesses a missing correction
class. Legacy records without one stay explicitly unclassified, and
``--require-complete-classification`` fails until that scientific boundary is
resolved.
"""

from __future__ import annotations

import argparse
import json
import math
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
    measurement = _read(directory / "analysis-measurement.json")
    measurement_fields = {
        "measurement_version",
        "capture",
        "measured_at",
        "counterexample_length",
        "counterexample_definition",
        "analysis_wall_clock_ms",
        "timing_definition",
        "samples",
        "environment",
        "result",
    }
    if not isinstance(measurement, dict) or set(measurement) != measurement_fields:
        raise ValueError("managed comparison measurement fields are not exact")
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
    expected_measurement = {
        "capture": "agentcore-refund-policy",
        "measurement_version": 1,
        "counterexample_length": 1,
        "counterexample_definition": (
            "minimum canonical managed requests needed to witness the deny-to-allow change"
        ),
        "timing_definition": (
            "median in-process compare_managed_cedar wall-clock time after input loading"
        ),
    }
    for field, expected in expected_measurement.items():
        if measurement.get(field) != expected:
            raise ValueError(f"managed comparison measurement has invalid {field}")
    elapsed = measurement.get("analysis_wall_clock_ms")
    samples = measurement.get("samples")
    sample_fields = {"warmups", "repetitions", "minimum_ms", "median_ms", "maximum_ms"}
    timing_values = (
        samples.get("minimum_ms") if isinstance(samples, dict) else None,
        samples.get("median_ms") if isinstance(samples, dict) else None,
        samples.get("maximum_ms") if isinstance(samples, dict) else None,
    )
    if (
        not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or not math.isfinite(elapsed)
        or elapsed <= 0
        or not isinstance(samples, dict)
        or set(samples) != sample_fields
        or samples.get("median_ms") != elapsed
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
            for value in timing_values
        )
        or not timing_values[0] <= timing_values[1] <= timing_values[2]
        or not isinstance(samples.get("warmups"), int)
        or isinstance(samples.get("warmups"), bool)
        or samples["warmups"] < 0
        or not isinstance(samples.get("repetitions"), int)
        or isinstance(samples.get("repetitions"), bool)
        or samples["repetitions"] < 1
    ):
        raise ValueError("managed comparison measurement has invalid timing")
    environment = measurement.get("environment")
    if (
        not isinstance(measurement.get("measured_at"), str)
        or not measurement["measured_at"].strip()
        or not isinstance(environment, dict)
        or set(environment) != {"python", "implementation", "platform", "machine"}
        or any(not isinstance(value, str) or not value.strip() for value in environment.values())
    ):
        raise ValueError("managed comparison measurement has invalid environment")
    observed_changes = [item["change"] for item in requests]
    measured_result = measurement.get("result")
    if (
        not isinstance(measured_result, dict)
        or set(measured_result) != {"classifications", "finding_count"}
        or measured_result.get("finding_count") != 0
        or sorted(measured_result.get("classifications") or []) != sorted(observed_changes)
    ):
        raise ValueError("managed comparison measurement result does not match the oracles")
    return {
        "capture": "agentcore-refund-policy",
        "baseline_revision": baseline["policy_inventory"]["members"][0]["name"],
        "candidate_revision": candidate["policy_inventory"]["members"][0]["name"],
        "requests": requests,
        "counterexample_length": measurement["counterexample_length"],
        "analysis_wall_clock_ms": elapsed,
        "instrumentation_status": "complete",
        "measurement": {
            "measured_at": measurement["measured_at"],
            "timing_definition": measurement["timing_definition"],
            "warmups": samples["warmups"],
            "repetitions": samples["repetitions"],
            "environment": environment,
        },
    }


def _managed_controls(root: Path) -> dict[str, Any]:
    result = _read(root / "agentcore-refund-policy" / "controls-result.json")
    expected = {
        "noop": ["stable_deny", "stable_allow"],
        "narrow": ["stable_deny", "tightens"],
    }
    if result.get("controls_version") != 1 or result.get("comparisons") != expected:
        raise ValueError("managed policy controls do not match the reviewed outcomes")
    sequence = result.get("sequence")
    if (
        not isinstance(sequence, dict)
        or sequence.get("per_request_threshold") != 1000
        or sequence.get("aggregate_amount") != 1200
        or [item.get("outcome") for item in sequence.get("calls", [])] != ["allow", "allow"]
    ):
        raise ValueError("managed permitted sequence does not match the reviewed outcomes")
    return {
        "capture": "agentcore-refund-policy",
        "baseline_revision": "PaperBaselinePolicy",
        "noop_revision": "PaperNoOpPolicy",
        "narrowing_revision": "PaperNarrowPolicy",
        "comparisons": result["comparisons"],
        "permitted_sequence": sequence,
    }


def _temporal_session(root: Path) -> dict[str, Any]:
    result = _read(root / "agentcore-refund-policy" / "temporal-session-result.json")
    expected_fields = {
        "temporal_session_version",
        "threshold",
        "request_amount",
        "same_session",
        "fresh_sessions",
        "conformance",
        "finding",
    }
    if not isinstance(result, dict) or set(result) != expected_fields:
        raise ValueError("temporal session result fields are not exact")
    same = result.get("same_session")
    fresh = result.get("fresh_sessions")
    conformance = result.get("conformance")
    if (
        result.get("temporal_session_version") != 1
        or result.get("threshold") != 1000
        or result.get("request_amount") != 600
        or not isinstance(same, dict)
        or [item.get("outcome") for item in same.get("calls", [])] != ["allow", "deny"]
        or same.get("attempted_aggregate") != 1200
        or same.get("permitted_aggregate") != 600
        or not isinstance(fresh, dict)
        or [item.get("outcome") for item in fresh.get("calls", [])] != ["allow", "allow"]
        or fresh.get("aggregate_across_sessions") != 1200
    ):
        raise ValueError("temporal session result does not match the reviewed outcomes")
    expected_conformance = {
        "within_session_accumulation": "observed",
        "fresh_session_reset": "observed",
        "authenticated_principal_binding": "configured-not-adversarially-tested",
        "multi_hop_continuity": "documented-not-live-tested",
    }
    if conformance != expected_conformance:
        raise ValueError("temporal session conformance states are not exact")
    return {
        "capture": "agentcore-refund-policy",
        "threshold": result["threshold"],
        "request_amount": result["request_amount"],
        "same_session": same,
        "fresh_sessions": fresh,
        "conformance": conformance,
        "finding": result["finding"],
    }


def _mandate_binding(root: Path) -> dict[str, Any]:
    result = _read(root / "agentcore-refund-policy" / "mandate-binding-result.json")
    expected_fields = {
        "mandate_binding_evaluation_version",
        "scheme",
        "threshold",
        "request_amount",
        "same_signed_mandate",
        "different_signed_mandate",
        "local_controls",
        "median_adapter_ms",
        "claim_boundary",
    }
    same = result.get("same_signed_mandate")
    different = result.get("different_signed_mandate")
    controls = result.get("local_controls")
    if (
        not isinstance(result, dict)
        or set(result) != expected_fields
        or result.get("mandate_binding_evaluation_version") != 1
        or result.get("threshold") != 1000
        or result.get("request_amount") != 600
        or not isinstance(same, dict)
        or same.get("separate_client_processes") != 2
        or same.get("derived_session_ids_equal") is not True
        or [item.get("outcome") for item in same.get("calls", [])] != ["allow", "deny"]
        or not isinstance(different, dict)
        or different.get("derived_session_id_distinct") is not True
        or [item.get("outcome") for item in different.get("calls", [])] != ["allow"]
        or not isinstance(controls, list)
        or [item.get("result") for item in controls]
        != ["rejected-before-network", "rejected-before-network"]
        or not isinstance(result.get("median_adapter_ms"), (int, float))
        or result["median_adapter_ms"] <= 0
    ):
        raise ValueError("mandate binding result does not match the reviewed outcomes")
    return {"capture": "agentcore-refund-policy", **result}


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
        "managed_controls": [_managed_controls(root)],
        "temporal_sessions": [_temporal_session(root)],
        "mandate_bindings": [_mandate_binding(root)],
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
