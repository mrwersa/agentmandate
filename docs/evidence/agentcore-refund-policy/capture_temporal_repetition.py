"""Project live temporal-policy repetitions into credential-free review artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _outcomes(calls: list[dict[str, Any]]) -> list[str]:
    return [call["outcome"] for call in calls]


def _duration_ms(call: dict[str, Any]) -> float:
    return round((call["finished_ns"] - call["started_ns"]) / 1_000_000, 6)


def _summary(raw: dict[str, Any]) -> dict[str, Any]:
    trials = raw.get("trials")
    sequential = raw.get("sequential")
    fresh = raw.get("fresh")
    concurrent = raw.get("concurrent")
    if not isinstance(trials, int) or trials < 1:
        raise ValueError("repetition trial count is invalid")
    cells = (sequential, fresh, concurrent)
    if not all(isinstance(value, list) and len(value) == trials for value in cells):
        raise ValueError("repetition cells do not match the trial count")
    rows = []
    for index in range(trials):
        seq = sequential[index]
        new = fresh[index]
        overlap = concurrent[index]
        simultaneous = overlap.get("calls")
        if (
            _outcomes(seq) != ["allow", "deny"]
            or _outcomes(new) != ["allow", "allow"]
            or sorted(_outcomes(simultaneous)) != ["allow", "deny"]
            or overlap.get("intervals_overlap") is not True
        ):
            raise ValueError(f"repetition trial {index} does not match the reviewed outcomes")
        rows.append(
            {
                "trial": index,
                "same_session": _outcomes(seq),
                "fresh_sessions": _outcomes(new),
                "concurrent_same_session": sorted(_outcomes(simultaneous)),
                "concurrent_intervals_overlap": True,
                "managed_call_ms": {
                    "same_session": [_duration_ms(call) for call in seq],
                    "fresh_sessions": [_duration_ms(call) for call in new],
                    "concurrent_same_session": [_duration_ms(call) for call in simultaneous],
                },
            }
        )
    return {
        "temporal_repetition_version": 1,
        "trials_per_cell": trials,
        "threshold": 1000,
        "request_amount": 600,
        "cells": rows,
        "results": {
            "same_session_allow_then_deny": trials,
            "fresh_sessions_allow_then_allow": trials,
            "concurrent_exactly_one_allow": trials,
            "concurrent_intervals_overlapped": trials,
        },
        "concurrency_verdict": (
            "no double-allow observed under synchronized two-request load; this is a "
            "negative result, not proof of serialization for all loads"
        ),
    }


def _updates(raw: dict[str, Any]) -> dict[str, Any]:
    trials = raw.get("trials")
    updates = raw.get("updates")
    if not isinstance(trials, int) or not isinstance(updates, list) or len(updates) != trials:
        raise ValueError("update trials do not match the trial count")
    rows = []
    for index, item in enumerate(updates):
        stale = item["reused_session"]["response"].get("error", {})
        row = {
            "trial": index,
            "before_threshold": item["before_threshold"],
            "after_threshold": item["after_threshold"],
            "no_update_control": _outcomes(item["no_update_control"]),
            "before_update": item["before_update"]["outcome"],
            "update_to_active_ms": round(item["revision"]["elapsed_ms"], 6),
            "update_status": item["revision"]["update_status"],
            "final_status": item["revision"]["final_status"],
            "final_statement_matches": item["revision"]["final_statement_matches"],
            "old_session": {
                "outcome": "stale-session-rejected",
                "error_code": stale.get("code"),
                "message": stale.get("message"),
            },
            "fresh_recovery_session": item["recovered_session"]["outcome"],
        }
        if (
            row["no_update_control"] != ["allow", "deny"]
            or row["before_update"] != "allow"
            or row["update_status"] != "UPDATING"
            or row["final_status"] != "ACTIVE"
            or row["final_statement_matches"] is not True
            or row["old_session"]["error_code"] != -32005
            or "Policy session is stale" not in str(row["old_session"]["message"])
            or row["fresh_recovery_session"] != "allow"
        ):
            raise ValueError(f"update trial {index} does not match the reviewed outcomes")
        rows.append(row)
    timings = [row["update_to_active_ms"] for row in rows]
    return {
        "temporal_update_version": 1,
        "trials": trials,
        "request_amount": 600,
        "alternating_thresholds": [1000, 1001],
        "updates": rows,
        "results": {
            "no_update_allow_then_deny": trials,
            "old_session_rejected_as_stale": trials,
            "fresh_recovery_allowed": trials,
            "recovery_aggregate_across_revisions": 1200,
            "update_to_active_ms": {
                "minimum": min(timings),
                "median": round(statistics.median(timings), 6),
                "maximum": max(timings),
            },
        },
        "interpretation": (
            "policy revision invalidated the old session; following the managed error's "
            "fresh-session recovery reset cumulative history"
        ),
    }


def _bindings(raw: dict[str, Any]) -> dict[str, Any]:
    trials = raw.get("trials")
    if not isinstance(trials, list) or not trials:
        raise ValueError("binding trials are missing")
    rows = []
    for index, item in enumerate(trials):
        calls = [call["outcome"] for call in item["calls"]]
        local = [control["outcome"] for control in item["local_controls"]]
        if calls != ["allow", "deny", "allow"] or local != [
            "rejected-before-network",
            "rejected-before-network",
        ]:
            raise ValueError(f"binding trial {index} does not match the reviewed outcomes")
        rows.append(
            {
                "trial": index,
                "same_binding_separate_processes": calls[:2],
                "different_binding": calls[2],
                "tampered_binding": local[0],
                "expired_binding": local[1],
            }
        )
    return {
        "binding_repetition_version": 1,
        "trials": len(rows),
        "request_amount": 600,
        "cells": rows,
        "results": {
            "same_binding_allow_then_deny": len(rows),
            "different_binding_allowed": len(rows),
            "tampered_rejected_before_network": len(rows),
            "expired_rejected_before_network": len(rows),
        },
        "trust_boundary": "exclusive credential-holding adapter; Gateway did not verify binding",
    }


def _latency(raw: dict[str, Any]) -> dict[str, Any]:
    records = raw.get("records")
    if raw.get("pairs") != 30 or not isinstance(records, list) or len(records) != 30:
        raise ValueError("paired latency requires exactly 30 pairs")
    if any(item[mode]["outcome"] != "allow" for item in records for mode in ("bound", "unbound")):
        raise ValueError("paired latency contains a non-allow outcome")
    return {
        "binding_paired_latency_version": 1,
        "pairs": 30,
        "random_seed": raw["random_seed"],
        "records": records,
        "bound_ms": raw["bound_ms"],
        "unbound_ms": raw["unbound_ms"],
        "paired_difference_ms": raw["paired_difference_ms"],
        "claim_boundary": raw["claim_boundary"],
    }


def capture(raw: Path, output: Path) -> None:
    """Validate raw live results and write only sanitized projections."""
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "temporal-repetition.json": _summary(_read(raw / "round1-probe.raw.json")),
        "temporal-update-repetition.json": _updates(_read(raw / "round1-update.raw.json")),
        "binding-repetition.json": _bindings(_read(raw / "round1-binding.raw.json")),
        "binding-paired-latency.json": _latency(
            _read(raw / "round1-paired-latency.raw.json")
        ),
        "temporal-repetition-corrections.json": {
            "corrections_version": 1,
            "corrections": [
                {
                    "id": "temporal-repetition-001",
                    "class": "extractor defect",
                    "description": (
                        "The first parent process classified a child envelope as a native "
                        "MCP response. The failed projection was retained outside the repository; "
                        "the classifier was corrected before the ten reviewed trials."
                    ),
                    "failed_outcomes_entered_result": False,
                }
            ],
        },
        "temporal-repetition-cleanup.json": {
            "cdk_bootstrap": "retained",
            "gateway": "absent",
            "policy_engine": "absent",
            "policies": "absent",
            "lambda": "absent",
            "lambda_role": "absent",
            "lambda_log_group": "absent",
        },
    }
    for name, value in artifacts.items():
        _write(output / name, value)
    pinned = {
        *artifacts,
        "capture_temporal_repetition.py",
        "temporal-repetition-policy-1000.dogwood",
        "temporal-repetition-policy-1001.dogwood",
        "temporal-repetition-procedure.md",
    }
    sources = []
    for name in sorted(pinned):
        content = (output / name).read_bytes()
        sources.append({"locator": name, "content_sha256": hashlib.sha256(content).hexdigest()})
    _write(
        output / "temporal-repetition-index.json",
        {
            "capture_version": 1,
            "capture_date": "2026-08-30",
            "region": "us-east-1",
            "provider": "AWS AgentCore Gateway Policy ENFORCE",
            "sources": sources,
            "raw_artifacts_committed": False,
            "raw_artifact_policy": (
                "live identifiers, URLs, signatures, session IDs, and service timestamps "
                "remained in temporary files and were deleted after projection"
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    capture(args.raw, args.output)


if __name__ == "__main__":
    main()
