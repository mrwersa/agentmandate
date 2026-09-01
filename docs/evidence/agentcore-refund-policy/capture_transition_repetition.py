"""Verify sanitized policy-transition events and derive the reviewed summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _call(value: dict[str, Any], expected: str) -> None:
    request = value.get("request", {})
    response = value.get("response", {})
    if (
        request.get("method") != "tools/call"
        or request.get("params", {}).get("arguments") != {"amount": 600}
        or value.get("derived_outcome") != expected
    ):
        raise ValueError("transition call does not match the reviewed request and outcome")
    if expected == "allow" and response.get("result", {}).get("isError") is not False:
        raise ValueError("allowed transition call lacks the managed success response")
    if expected == "deny" and response.get("error", {}).get("code") != -32002:
        raise ValueError("denied transition call lacks the managed denial code")
    if expected == "stale_session":
        error = response.get("error", {})
        if error.get("code") != -32005 or "Policy session is stale" not in str(
            error.get("message")
        ):
            raise ValueError("stale transition call lacks the managed stale-session diagnostic")


def _update(value: dict[str, Any], changed: bool) -> dict[str, Any]:
    before = value.get("before", {})
    after = value.get("after", {})
    polls = value.get("polls")
    if (
        value.get("revision_changed") is not changed
        or before.get("status") != "ACTIVE"
        or after.get("status") != "ACTIVE"
        or before.get("enforcement_mode") != "ACTIVE"
        or after.get("enforcement_mode") != "ACTIVE"
        or not isinstance(polls, list)
        or not polls
        or polls[-1] != {"poll_index": len(polls) - 1, **after}
    ):
        raise ValueError("transition update does not match the reviewed ACTIVE revision")
    aliases_differ = before.get("revision_alias") != after.get("revision_alias")
    statements_differ = before.get("statement_sha256") != after.get("statement_sha256")
    if aliases_differ is not changed or statements_differ is not changed:
        raise ValueError("transition revision and statement identity disagree")
    return {
        "revision_changed": changed,
        "before_revision": before["revision_alias"],
        "after_revision": after["revision_alias"],
        "before_statement_sha256": before["statement_sha256"],
        "after_statement_sha256": after["statement_sha256"],
        "polls_to_active": len(polls),
    }


def summary(value: dict[str, Any]) -> dict[str, Any]:
    byte_trials = value.get("byte_identical_trials")
    equivalent_trials = value.get("alpha_equivalent_trials")
    if (
        value.get("capture_version") != 1
        or value.get("provider") != "AWS AgentCore Gateway Policy"
        or value.get("protocol") != "MCP 2025-03-26"
        or value.get("validation_mode") != "IGNORE_ALL_FINDINGS"
        or value.get("enforcement_mode") != "ACTIVE"
        or value.get("request_domain") != "representative"
        or value.get("amount_per_call") != 600
        or value.get("temporal_threshold") != 1000
        or not isinstance(value.get("mandate_sha256"), str)
        or len(value["mandate_sha256"]) != 64
        or not isinstance(byte_trials, list)
        or len(byte_trials) != 10
        or not isinstance(equivalent_trials, list)
        or len(equivalent_trials) != 10
    ):
        raise ValueError("transition event root does not match the reviewed capture")

    byte_rows = []
    for index, trial in enumerate(byte_trials):
        if trial.get("trial") != index:
            raise ValueError(f"byte-identical trial {index} has invalid identity")
        _call(trial["before_call"], "allow")
        _call(trial["after_call"], "deny")
        if trial["before_call"].get("session_alias") != trial["after_call"].get(
            "session_alias"
        ):
            raise ValueError(f"byte-identical trial {index} changed session")
        byte_rows.append(
            {
                "trial": index,
                "before_write": "allow",
                "update": _update(trial["update"], False),
                "same_session_after_write": "deny",
            }
        )

    equivalent_rows = []
    for index, trial in enumerate(equivalent_trials):
        if trial.get("trial") != index or trial.get("style") not in {"a", "b"}:
            raise ValueError(f"alpha-equivalent trial {index} has invalid identity")
        _call(trial["before_call"], "allow")
        _call(trial["predecessor_after_call"], "stale_session")
        _call(trial["recovery_call"], "allow")
        predecessor = trial["before_call"].get("session_alias")
        if predecessor != trial["predecessor_after_call"].get("session_alias"):
            raise ValueError(f"alpha-equivalent trial {index} changed predecessor session")
        if predecessor == trial["recovery_call"].get("session_alias"):
            raise ValueError(f"alpha-equivalent trial {index} reused predecessor for recovery")
        equivalent_rows.append(
            {
                "trial": index,
                "alpha_equivalent_form": trial["style"],
                "before_update": "allow",
                "update": _update(trial["update"], True),
                "predecessor_session_after_update": "stale_session",
                "fresh_recovery_session": "allow",
            }
        )

    return {
        "semantic_noop_revision_version": 2,
        "mandate_sha256": value["mandate_sha256"],
        "request_amount": 600,
        "threshold": 1000,
        "byte_identical_trials": byte_rows,
        "alpha_equivalent_trials": equivalent_rows,
        "results": {
            "byte_identical_revision_unchanged": 10,
            "byte_identical_second_request_denied": 10,
            "alpha_equivalent_revision_changed": 10,
            "predecessor_session_rejected_as_stale": 10,
            "fresh_recovery_allowed": 10,
        },
        "interpretation": (
            "under one external mandate digest, byte-identical writes preserved the revision "
            "and cumulative enforcement; alpha-equivalent writes created a new revision, "
            "after which prescribed fresh-session recovery was not constrained by predecessor "
            "history"
        ),
    }


def capture(events: Path, output: Path) -> None:
    """Derive the canonical reviewed summary from sanitized provider events."""
    _write(output, summary(_read(events)))


def build_index(root: Path) -> None:
    """Pin every artifact in the revised transition evidence boundary."""
    pinned = {
        "binding-policy-revision-repetition.json",
        "capture_transition_controls.py",
        "capture_transition_interface.py",
        "capture_transition_repetition.py",
        "temporal-semantic-noop-accumulated.dogwood",
        "temporal-semantic-noop-repetition.json",
        "temporal-semantic-noop-total.dogwood",
        "temporal-transition-cleanup.json",
        "temporal-transition-confirmation-cleanup.json",
        "temporal-transition-confirmation-procedure.md",
        "temporal-transition-confirmation-summary.json",
        "temporal-transition-deployment-correction.json",
        "temporal-transition-events.json",
        "temporal-transition-interface.json",
        "temporal-transition-procedure.md",
        "temporal-transition-validation-refusal.json",
    }
    sources = [
        {
            "locator": name,
            "content_sha256": hashlib.sha256((root / name).read_bytes()).hexdigest(),
        }
        for name in sorted(pinned)
    ]
    _write(
        root / "temporal-transition-index.json",
        {
            "capture_version": 2,
            "capture_date": "2026-09-01",
            "provider": "AWS AgentCore Gateway Policy ENFORCE",
            "region": "us-east-1",
            "mcp_protocol": "2025-03-26",
            "sources": sources,
            "raw_artifacts_committed": False,
            "raw_artifact_policy": (
                "account identifiers, URLs, service timestamps, and live session identifiers "
                "remained in temporary storage; committed events retain provider responses, "
                "request bodies, hashes, and stable aliases"
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--index-root", type=Path)
    args = parser.parse_args()
    capture(args.events, args.output)
    if args.index_root is not None:
        build_index(args.index_root)


if __name__ == "__main__":
    main()
