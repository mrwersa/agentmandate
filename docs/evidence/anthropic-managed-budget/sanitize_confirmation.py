"""Reduce private Managed Agents captures to reviewable, identifier-free evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _unit(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_unit": unit["work_unit"],
        "list_cost_minor_units": unit["list_cost_minor_units"],
        "idle_reason": unit["idle_reason"],
    }


def _trial(record: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "trial": record["trial"],
        "order": record["order"],
        "cell": record["cell"],
    }
    if record["cell"] == "sequential_control":
        result["work_units"] = [_unit(item) for item in record["work_units"]]
        refusal = record["post_budget_refusal"]
        result["post_budget_refusal"] = {
            "error_type": refusal["error_type"],
            "api_error_type": refusal["body"]["error"]["type"],
        }
    elif record["cell"] == "fresh_session_replication":
        result["sessions"] = [
            {
                "replica": session["replica"],
                "work_units": [_unit(item) for item in session["work_units"]],
            }
            for session in record["sessions"]
        ]
    elif record["cell"] == "cap_revision_control":
        result["before_revision"] = [_unit(item) for item in record["before_revision"]]
        result["revision"] = record["revision"]
        result["after_revision"] = [_unit(item) for item in record["after_revision"]]
    else:
        raise ValueError("unexpected confirmation cell")
    return result


def sanitize(source: Path, protocol: Path) -> dict[str, Any]:
    trial_paths = sorted(source.glob("trial-*.json"))
    if len(trial_paths) != 30:
        raise ValueError("confirmation must contain exactly 30 trial files")
    records = [json.loads(path.read_text()) for path in trial_paths]
    cells = {name: sum(record["cell"] == name for record in records) for name in {
        "sequential_control",
        "fresh_session_replication",
        "cap_revision_control",
    }}
    if cells != dict.fromkeys(cells, 10):
        raise ValueError("confirmation must contain ten trials per cell")

    cleanup_path = source / "cleanup.json"
    cleanup = json.loads(cleanup_path.read_text())
    sessions = [item for item in cleanup if item["kind"] == "session"]
    agents = [item for item in cleanup if item["kind"] == "agent"]
    environments = [item for item in cleanup if item["kind"] == "environment"]
    if not (
        len(sessions) == 40
        and all(item.get("deleted") and item.get("verified_absent") for item in sessions)
        and agents == [{"kind": "agent", "archived": True}]
        and environments == [{"kind": "environment", "deleted": True}]
    ):
        raise ValueError("capture cleanup is incomplete")

    raw_paths = [source / "cell-order.json", *trial_paths, cleanup_path]
    return {
        "evidence_version": 1,
        "protocol_sha256": _sha256(protocol),
        "raw_capture_sha256": {path.name: _sha256(path) for path in raw_paths},
        "trials": [_trial(record) for record in sorted(records, key=lambda item: item["order"])],
        "cleanup": {
            "sessions_deleted_and_verified_absent": len(sessions),
            "agent_archived": True,
            "environment_deleted": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("protocol.json"))
    args = parser.parse_args()
    print(json.dumps(sanitize(args.source, args.protocol), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
