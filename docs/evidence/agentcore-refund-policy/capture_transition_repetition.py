"""Verify sanitised policy-transition events and derive the reviewed summary."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("transition timestamp is not canonical UTC") from exc
    canonical = parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value != canonical:
        raise ValueError("transition timestamp is not canonical UTC")
    return parsed


def _ordered(label: str, *values: str) -> None:
    instants = tuple(_instant(value) for value in values)
    if any(before > after for before, after in zip(instants, instants[1:], strict=False)):
        raise ValueError(f"{label} timestamps are not causally ordered")


def _call(value: dict[str, Any], expected: str) -> None:
    request = value.get("request", {})
    response = value.get("response", {})
    if (
        request.get("method") != "tools/call"
        or request.get("params", {}).get("arguments") != {"amount": 600}
        or value.get("derived_outcome") != expected
        or value.get("http_status") != 200
        or _instant(value["started_at"]) > _instant(value["finished_at"])
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


def _update(
    value: dict[str, Any], changed: bool, before_text: str, after_text: str
) -> dict[str, Any]:
    before, after = value.get("before", {}), value.get("after", {})
    polls = value.get("polls")
    submitted, managed = value.get("submitted_request", {}), value.get("managed_response", {})
    before_hash = hashlib.sha256(before_text.encode()).hexdigest()
    after_hash = hashlib.sha256(after_text.encode()).hexdigest()
    if (
        value.get("revision_changed") is not changed
        or before.get("status") != "ACTIVE"
        or after.get("status") != "ACTIVE"
        or before.get("enforcement_mode") != "ACTIVE"
        or after.get("enforcement_mode") != "ACTIVE"
        or not isinstance(polls, list)
        or not polls
        or any(poll.get("poll_index") != index for index, poll in enumerate(polls))
        or polls[-1] != {"poll_index": len(polls) - 1, **after}
        or submitted.get("operation") != "UpdatePolicy"
        or submitted.get("definition", {}).get("policy", {}).get("statement") != after_text
        or submitted.get("validation_mode") != "IGNORE_ALL_FINDINGS"
        or submitted.get("enforcement_mode") != "ACTIVE"
        or managed.get("status") != "UPDATING"
        or managed.get("enforcement_mode") != "ACTIVE"
        or managed.get("statement_sha256") != after_hash
        or before.get("statement_sha256") != before_hash
        or after.get("statement_sha256") != after_hash
        or _instant(value["requested_at"]) > _instant(value["completed_at"])
    ):
        raise ValueError("transition update does not match the reviewed submitted policy")
    _ordered(
        "transition update",
        value["requested_at"],
        *(poll["observed_at"] for poll in polls),
        value["completed_at"],
    )
    if _instant(before["observed_at"]) > _instant(value["completed_at"]):
        raise ValueError("transition update before-state observation follows completion")
    aliases_differ = before.get("revision_alias") != after.get("revision_alias")
    if aliases_differ is not changed or (not changed and before_hash != after_hash):
        raise ValueError("transition revision and statement identity disagree")
    return {
        "revision_changed": changed,
        "before_revision": before["revision_alias"],
        "after_revision": after["revision_alias"],
        "before_statement_sha256": before_hash,
        "after_statement_sha256": after_hash,
        "polls_to_active": len(polls),
    }


def _transition(
    trial: dict[str, Any], index: int, before_text: str, after_text: str
) -> dict[str, Any]:
    _call(trial["before_call"], "allow")
    _call(trial["predecessor_after_call"], "stale_session")
    _call(trial["recovery_call"], "allow")
    _call(trial["recovery_after_call"], "deny")
    _ordered(
        f"transition trial {index}",
        trial["before_call"]["started_at"],
        trial["before_call"]["finished_at"],
        trial["update"]["requested_at"],
        trial["update"]["completed_at"],
        trial["predecessor_after_call"]["started_at"],
        trial["predecessor_after_call"]["finished_at"],
        trial["recovery_call"]["started_at"],
        trial["recovery_call"]["finished_at"],
        trial["recovery_after_call"]["started_at"],
        trial["recovery_after_call"]["finished_at"],
    )
    predecessor = trial["before_call"]["session_alias"]
    successor = trial["recovery_call"]["session_alias"]
    if (
        predecessor != trial["predecessor_after_call"]["session_alias"]
        or predecessor == successor
        or successor != trial["recovery_after_call"]["session_alias"]
    ):
        raise ValueError(f"transition trial {index} has invalid session continuity")
    elapsed = (
        _instant(trial["recovery_after_call"]["finished_at"])
        - _instant(trial["before_call"]["started_at"])
    ).total_seconds()
    if not 0 <= elapsed < 3600:
        raise ValueError(f"transition trial {index} exceeds the temporal window")
    return {
        "trial": index,
        "before_update": "allow",
        "update": _update(trial["update"], True, before_text, after_text),
        "predecessor_session_after_update": "stale_session",
        "fresh_recovery_session": ["allow", "deny"],
        "elapsed_seconds": elapsed,
    }


def _metadata(value: dict[str, Any], statement: str) -> dict[str, Any]:
    update = value.get("update", {})
    before, after, polls = update.get("before", {}), update.get("after", {}), update.get("polls")
    digest = hashlib.sha256(statement.encode()).hexdigest()
    if (
        value.get("capture_version") != 1
        or value.get("changed_field") != "description"
        or value.get("revision_changed") is not True
        or value.get("statement_changed") is not False
        or update.get("submitted_request")
        != {
            "changed_field": "description",
            "definition_supplied": False,
            "operation": "UpdatePolicy",
        }
        or update.get("managed_status") != "UPDATING"
        or not isinstance(polls, list)
        or not polls
        or any(poll.get("poll_index") != index for index, poll in enumerate(polls))
        or polls[-1] != {"poll_index": len(polls) - 1, **after}
        or before.get("revision_alias") == after.get("revision_alias")
        or before.get("statement_sha256") != digest
        or after.get("statement_sha256") != digest
    ):
        raise ValueError("metadata-only update does not preserve the reviewed statement")
    _call(value["before_call"], "allow")
    _call(value["predecessor_after_call"], "stale_session")
    _call(value["recovery_call"], "allow")
    _call(value["recovery_after_call"], "deny")
    _ordered(
        "metadata-only transition",
        before["observed_at"],
        value["capture_started_at"],
        value["before_call"]["started_at"],
        value["before_call"]["finished_at"],
        update["requested_at"],
        *(poll["observed_at"] for poll in polls),
        value["predecessor_after_call"]["started_at"],
        value["predecessor_after_call"]["finished_at"],
        value["recovery_call"]["started_at"],
        value["recovery_call"]["finished_at"],
        value["recovery_after_call"]["started_at"],
        value["recovery_after_call"]["finished_at"],
        value["capture_finished_at"],
    )
    predecessor = value["before_call"]["session_alias"]
    successor = value["recovery_call"]["session_alias"]
    elapsed = (
        _instant(value["recovery_after_call"]["finished_at"])
        - _instant(value["before_call"]["started_at"])
    ).total_seconds()
    if (
        predecessor != value["predecessor_after_call"]["session_alias"]
        or predecessor == successor
        or successor != value["recovery_after_call"]["session_alias"]
        or not 0 <= elapsed < 3600
    ):
        raise ValueError("metadata-only transition has invalid session continuity")
    return {
        "trial": 0,
        "before_update": "allow",
        "predecessor_session_after_update": "stale_session",
        "fresh_recovery_session": ["allow", "deny"],
        "elapsed_seconds": elapsed,
        "update": {
            "revision_changed": True,
            "statement_changed": False,
            "before_revision": before["revision_alias"],
            "after_revision": after["revision_alias"],
            "statement_sha256": digest,
            "polls_to_active": len(polls),
        },
    }


def summary(
    value: dict[str, Any], forms: dict[str, str], metadata: dict[str, Any]
) -> dict[str, Any]:
    byte_trials = value.get("byte_identical_trials")
    rename_trials = value.get("alpha_equivalent_trials")
    whitespace_trials = value.get("whitespace_only_trials")
    trial_sets = (byte_trials, rename_trials, whitespace_trials)
    if (
        value.get("capture_version") != 2
        or value.get("provider") != "AWS AgentCore Gateway Policy"
        or value.get("protocol") != "MCP 2025-03-26"
        or value.get("validation_mode") != "IGNORE_ALL_FINDINGS"
        or value.get("enforcement_mode") != "ACTIVE"
        or value.get("request_domain") != "representative"
        or value.get("amount_per_call") != 600
        or value.get("temporal_threshold") != 1000
        or not isinstance(value.get("mandate_sha256"), str)
        or len(value["mandate_sha256"]) != 64
        or any(not isinstance(rows, list) or len(rows) != 10 for rows in trial_sets)
        or _instant(value["capture_started_at"]) > _instant(value["capture_finished_at"])
    ):
        raise ValueError("transition event root does not match the reviewed capture")

    byte_rows = []
    for index, trial in enumerate(byte_trials):
        style = "a" if index % 2 == 0 else "b"
        if trial.get("trial") != index or trial.get("style") != style:
            raise ValueError(f"byte-identical trial {index} has invalid identity")
        _call(trial["before_call"], "allow")
        _call(trial["after_call"], "deny")
        _ordered(
            f"byte-identical trial {index}",
            trial["before_call"]["started_at"],
            trial["before_call"]["finished_at"],
            trial["update"]["requested_at"],
            trial["update"]["completed_at"],
            trial["after_call"]["started_at"],
            trial["after_call"]["finished_at"],
        )
        if trial["before_call"]["session_alias"] != trial["after_call"]["session_alias"]:
            raise ValueError(f"byte-identical trial {index} changed session")
        byte_rows.append(
            {
                "trial": index,
                "policy_form": style,
                "before_write": "allow",
                "update": _update(trial["update"], False, forms[style], forms[style]),
                "same_session_after_write": "deny",
            }
        )

    rename_rows = []
    for index, trial in enumerate(rename_trials):
        after_style = "b" if index % 2 == 0 else "a"
        before_style = "a" if after_style == "b" else "b"
        if trial.get("trial") != index or trial.get("style") != after_style:
            raise ValueError(f"alpha-equivalent trial {index} has invalid identity")
        row = _transition(trial, index, forms[before_style], forms[after_style])
        row["alpha_equivalent_form"] = after_style
        rename_rows.append(row)

    for index, (byte_trial, rename_trial) in enumerate(
        zip(byte_trials, rename_trials, strict=True)
    ):
        schedule = [
            byte_trial["before_call"]["started_at"],
            byte_trial["after_call"]["finished_at"],
            rename_trial["before_call"]["started_at"],
            rename_trial["recovery_after_call"]["finished_at"],
        ]
        if index + 1 < len(byte_trials):
            schedule.append(byte_trials[index + 1]["before_call"]["started_at"])
        _ordered(f"interleaved trial pair {index}", *schedule)

    compact = forms["a"]
    spaced = compact.replace("when temporal {\n", "when temporal {\n\n", 1)
    whitespace_rows = []
    for index, trial in enumerate(whitespace_trials):
        variant = "spaced" if index % 2 == 0 else "compact"
        before_text, after_text = (compact, spaced) if variant == "spaced" else (spaced, compact)
        if trial.get("trial") != index or trial.get("variant") != variant:
            raise ValueError(f"whitespace-only trial {index} has invalid identity")
        row = _transition(trial, index, before_text, after_text)
        row["variant"] = variant
        whitespace_rows.append(row)

    _ordered(
        "capture window",
        value["capture_started_at"],
        byte_trials[0]["before_call"]["started_at"],
        rename_trials[-1]["recovery_after_call"]["finished_at"],
        whitespace_trials[0]["before_call"]["started_at"],
        whitespace_trials[-1]["recovery_after_call"]["finished_at"],
        value["capture_finished_at"],
    )

    metadata_row = _metadata(metadata, compact)
    transitions = [*rename_rows, *whitespace_rows, metadata_row]
    return {
        "transition_confirmation_version": 3,
        "mandate_sha256": value["mandate_sha256"],
        "request_amount": 600,
        "threshold": 1000,
        "byte_identical_trials": byte_rows,
        "alpha_equivalent_trials": rename_rows,
        "whitespace_only_trials": whitespace_rows,
        "description_only_trial": metadata_row,
        "results": {
            "byte_identical_revision_unchanged": sum(
                not row["update"]["revision_changed"] for row in byte_rows
            ),
            "byte_identical_second_request_denied": sum(
                row["same_session_after_write"] == "deny" for row in byte_rows
            ),
            "alpha_equivalent_revision_changed": sum(
                row["update"]["revision_changed"] for row in rename_rows
            ),
            "whitespace_only_revision_changed": sum(
                row["update"]["revision_changed"] for row in whitespace_rows
            ),
            "description_only_revision_changed": metadata_row["update"]["revision_changed"],
            "description_only_statement_changed": metadata_row["update"]["statement_changed"],
            "predecessor_session_rejected_as_stale": sum(
                row["predecessor_session_after_update"] == "stale_session" for row in transitions
            ),
            "fresh_successor_allow_then_deny": sum(
                row["fresh_recovery_session"] == ["allow", "deny"] for row in transitions
            ),
            "maximum_transition_seconds": max(row["elapsed_seconds"] for row in transitions),
        },
        "interpretation": (
            "byte-identical writes preserved the revision and cumulative enforcement. "
            "Bound-variable renaming, whitespace-only rewriting, and a description-only "
            "update with an unchanged statement each created a revision. Each predecessor "
            "session then became stale, while the fresh successor enforced the same bound "
            "from an empty history"
        ),
    }


def capture(events: Path, output: Path, metadata: Path | None = None) -> None:
    """Derive the canonical reviewed summary from sanitised provider events."""
    forms = {
        style: (events.parent / f"temporal-transition-policy-{style}.dogwood")
        .read_text(encoding="utf-8")
        .rstrip("\n")
        for style in ("a", "b")
    }
    metadata_path = metadata or events.parent / "temporal-transition-metadata-events.json"
    _write(output, summary(_read(events), forms, _read(metadata_path)))


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
        "temporal-transition-metadata-events.json",
        "temporal-transition-policy-a.dogwood",
        "temporal-transition-policy-b.dogwood",
        "temporal-transition-procedure.md",
        "temporal-transition-validation-refusal.json",
    }
    sources = [
        {"locator": name, "content_sha256": hashlib.sha256((root / name).read_bytes()).hexdigest()}
        for name in sorted(pinned)
    ]
    _write(
        root / "temporal-transition-index.json",
        {
            "capture_version": 3,
            "capture_date": "2026-09-04",
            "provider": "AWS AgentCore Gateway Policy ENFORCE",
            "region": "us-east-1",
            "mcp_protocol": "2025-03-26",
            "sources": sources,
            "raw_artifacts_committed": False,
            "raw_artifact_policy": (
                "account identifiers, URLs, and live session identifiers remained in temporary "
                "storage. Committed events retain UTC timestamps, provider responses, request "
                "bodies, hashes, and stable aliases"
            ),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--index-root", type=Path)
    args = parser.parse_args()
    capture(args.events, args.output, args.metadata)
    if args.index_root is not None:
        build_index(args.index_root)


if __name__ == "__main__":
    main()
