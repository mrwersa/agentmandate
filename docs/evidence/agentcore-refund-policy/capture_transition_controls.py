"""Project transition controls into credential-free review artifacts."""

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


def _stale(call: dict[str, Any]) -> dict[str, Any]:
    error = call.get("response", {}).get("error", {})
    if call.get("outcome") != "stale-session-rejected" or error.get("code") != -32005:
        raise ValueError("old session was not rejected with the managed stale-session error")
    if "Policy session is stale" not in str(error.get("message")):
        raise ValueError("old session did not carry the reviewed stale-session diagnostic")
    return {"outcome": "stale-session-rejected", "error_code": -32005}


def _revision(value: dict[str, Any], *, changed: bool) -> dict[str, Any]:
    if (
        value.get("revision_changed") is not changed
        or value.get("final_status") != "ACTIVE"
        or value.get("final_statement_matches") is not True
    ):
        raise ValueError("policy revision does not match the reviewed ACTIVE state")
    return {
        "revision_changed": changed,
        "update_status": value.get("update_status"),
        "final_status": "ACTIVE",
        "final_statement_matches": True,
        "update_to_active_ms": round(value["elapsed_ms"], 6),
    }


def _semantic_noop(raw: dict[str, Any]) -> dict[str, Any]:
    control = raw.get("byte_identical_control")
    trials = raw.get("semantic_noop_trials")
    if raw.get("experiment_version") != 1 or not isinstance(control, dict):
        raise ValueError("transition-control root is invalid")
    if not isinstance(trials, list) or len(trials) != 10:
        raise ValueError("semantic no-op evidence requires ten trials")
    if control["before"].get("outcome") != "allow" or control["reuse"].get("outcome") != "deny":
        raise ValueError("byte-identical control did not preserve cumulative history")
    rows = []
    for index, trial in enumerate(trials):
        if trial.get("trial") != index or trial.get("style") not in {"total", "accumulated"}:
            raise ValueError(f"semantic no-op trial {index} has invalid identity")
        if trial["before"].get("outcome") != "allow" or trial["recovery"].get("outcome") != "allow":
            raise ValueError(f"semantic no-op trial {index} has invalid allow outcomes")
        rows.append(
            {
                "trial": index,
                "alpha_equivalent_form": trial["style"],
                "before_update": "allow",
                "revision": _revision(trial["revision"], changed=True),
                "old_session": _stale(trial["reuse"]),
                "fresh_recovery_session": "allow",
            }
        )
    timings = [row["revision"]["update_to_active_ms"] for row in rows]
    return {
        "semantic_noop_revision_version": 1,
        "trials": 10,
        "threshold": 1000,
        "request_amount": 600,
        "byte_identical_control": {
            "before_write": "allow",
            "revision": _revision(control["revision"], changed=False),
            "same_session_after_write": "deny",
            "interpretation": "the service deduplicated the byte-identical write",
        },
        "semantic_noop_trials": rows,
        "results": {
            "distinct_active_revision": 10,
            "old_session_rejected_as_stale": 10,
            "fresh_recovery_allowed": 10,
            "update_to_active_ms": {
                "minimum": min(timings),
                "median": round(statistics.median(timings), 6),
                "maximum": max(timings),
            },
        },
        "interpretation": (
            "textually different but alpha-equivalent temporal policies invalidated accrued "
            "session history; revision identity, not a changed bound, was sufficient"
        ),
    }


def _binding_revision(raw: dict[str, Any]) -> dict[str, Any]:
    trials = raw.get("binding_revision_trials")
    if not isinstance(trials, list) or len(trials) != 10:
        raise ValueError("binding policy-revision evidence requires ten trials")
    rows = []
    for index, trial in enumerate(trials):
        if trial.get("trial") != index or trial["before"].get("outcome") != "allow":
            raise ValueError(f"binding policy-revision trial {index} has invalid identity")
        if trial["successor_binding_recovery"].get("outcome") != "allow":
            raise ValueError(f"binding policy-revision trial {index} did not recover")
        if not all(
            trial.get(field) is True
            for field in ("same_mandate_digest", "policy_digest_changed", "derived_session_changed")
        ):
            raise ValueError(f"binding policy-revision trial {index} lost its join")
        rows.append(
            {
                "trial": index,
                "before_threshold": trial["before_threshold"],
                "after_threshold": trial["after_threshold"],
                "same_mandate_digest": True,
                "policy_digest_changed": True,
                "derived_session_changed": True,
                "before_update": "allow",
                "revision": _revision(trial["revision"], changed=True),
                "old_binding_session": _stale(trial["old_binding_reuse"]),
                "successor_binding_session": "allow",
            }
        )
    return {
        "binding_policy_revision_version": 1,
        "trials": 10,
        "request_amount": 600,
        "alternating_thresholds": [1000, 1001],
        "cells": rows,
        "results": {
            "old_binding_session_rejected_as_stale": 10,
            "successor_binding_session_allowed": 10,
            "same_mandate_across_revision_aggregate": 1200,
        },
        "trust_boundary": (
            "the exclusive credential-holding adapter verified each signed binding; the "
            "managed Gateway did not verify it"
        ),
        "interpretation": (
            "the binding collapses session continuity into complete mediation but does not "
            "carry consumed authority across a policy revision"
        ),
    }


def capture(raw: Path, output: Path) -> None:
    """Validate one raw live record and write its sanitized projections."""
    value = _read(raw)
    _write(output / "temporal-semantic-noop-repetition.json", _semantic_noop(value))
    _write(output / "binding-policy-revision-repetition.json", _binding_revision(value))
    pinned = {
        "binding-policy-revision-repetition.json",
        "capture_transition_controls.py",
        "temporal-semantic-noop-accumulated.dogwood",
        "temporal-semantic-noop-repetition.json",
        "temporal-semantic-noop-total.dogwood",
        "temporal-transition-cleanup.json",
        "temporal-transition-procedure.md",
    }
    sources = [
        {
            "locator": name,
            "content_sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
        }
        for name in sorted(pinned)
    ]
    _write(
        output / "temporal-transition-index.json",
        {
            "capture_version": 1,
            "capture_date": "2026-08-30",
            "provider": "AWS AgentCore Gateway Policy ENFORCE",
            "region": "us-east-1",
            "sources": sources,
            "raw_artifacts_committed": False,
            "raw_artifact_policy": (
                "account identifiers, URLs, policy IDs, service timestamps, session IDs, "
                "signatures, private keys, and credentials remained in temporary storage"
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
