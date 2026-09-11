"""Verify the sanitized AgentCore deployment-continuity refusal evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FILES = (
    "capture_deployment_continuity_refusal.py",
    "deployment-continuity-candidate-action-type.dogwood",
    "deployment-continuity-candidate-tool-specific.dogwood",
    "deployment-continuity-candidate-unconstrained.dogwood",
    "deployment-continuity-cleanup.json",
    "deployment-continuity-corrections.json",
    "deployment-continuity-procedure.md",
    "deployment-continuity-refusal.json",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index(root: Path) -> dict[str, Any]:
    return {
        "deployment_continuity_refusal_index_version": 1,
        "provider": "AWS AgentCore Gateway Policy",
        "region": "us-east-1",
        "sources": [
            {"locator": name, "content_sha256": _digest(root / name)} for name in FILES
        ],
    }


def verify(root: Path) -> None:
    refusal = _read(root / "deployment-continuity-refusal.json")
    attempts = refusal.get("attempts")
    if (
        refusal.get("deployment_continuity_refusal_version") != 1
        or refusal.get("accepted_data_plane_requests") != 0
        or refusal.get("result") != "one-factor experiment refused before data-plane trials"
        or refusal.get("raw_identifiers_retained") is not False
        or refusal.get("state_snapshot") != "unavailable"
        or not isinstance(attempts, list)
        or len(attempts) != 3
    ):
        raise ValueError("deployment-continuity refusal boundary has drifted")

    expected = {
        "deployment-continuity-candidate-tool-specific.dogwood": (
            "an exact tool action cannot be paired with a Gateway-type resource scope"
        ),
        "deployment-continuity-candidate-action-type.dogwood": (
            "the action-type form cannot remove the exact-action constraint"
        ),
        "deployment-continuity-candidate-unconstrained.dogwood": (
            "the remaining valid action scope cannot define a cross-Gateway temporal predicate"
        ),
    }
    observed = {row.get("candidate"): row.get("reason") for row in attempts}
    rejected = all(row.get("outcome") == "create-policy rejected" for row in attempts)
    if observed != expected or not rejected:
        raise ValueError("deployment-continuity refusal sequence has drifted")

    candidates = {name: (root / name).read_text(encoding="utf-8") for name in expected}
    if "action == AgentCore::Action" not in candidates[
        "deployment-continuity-candidate-tool-specific.dogwood"
    ]:
        raise ValueError("tool-specific refusal candidate has drifted")
    if "action is AgentCore::Action" not in candidates[
        "deployment-continuity-candidate-action-type.dogwood"
    ]:
        raise ValueError("action-type refusal candidate has drifted")
    unconstrained = candidates["deployment-continuity-candidate-unconstrained.dogwood"]
    if "\n  action,\n" not in unconstrained or "eventResource" in unconstrained:
        raise ValueError("unconstrained refusal candidate has drifted")
    if any("eventResource" in text for text in candidates.values()):
        raise ValueError("refusal candidates already partition history by Gateway")

    corrections = _read(root / "deployment-continuity-corrections.json")
    if (
        corrections.get("correction_log_version") != 1
        or corrections.get("excluded_data_plane_requests") != 0
        or len(corrections.get("entries", [])) != 4
    ):
        raise ValueError("deployment-continuity correction log has drifted")

    cleanup = _read(root / "deployment-continuity-cleanup.json")
    checks = cleanup.get("checks")
    if (
        cleanup.get("cleanup_version") != 1
        or not isinstance(checks, list)
        or len(checks) != 7
        or any(row.get("outcome") not in {"not_found", "empty_result"} for row in checks)
    ):
        raise ValueError("deployment-continuity cleanup is incomplete")

    if _index(root) != _read(root / "deployment-continuity-refusal-index.json"):
        raise ValueError("deployment-continuity refusal index does not match committed evidence")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    args = parser.parse_args()
    verify(args.evidence_root)
    print("deployment-continuity refusal evidence: committed bundle verifies")


if __name__ == "__main__":
    main()
