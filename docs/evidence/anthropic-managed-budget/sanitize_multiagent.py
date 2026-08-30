"""Reduce private multiagent captures to reviewable, identifier-free evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _trial(record: dict[str, Any]) -> dict[str, Any]:
    refusal = record["post_budget_refusal"]
    return {
        "trial": record["trial"],
        "order": record["order"],
        "cell": record["cell"],
        "topology": record["topology"],
        "list_cost_minor_units": record["list_cost_minor_units"],
        "idle_reason": record["idle_reason"],
        "post_budget_refusal": None
        if refusal is None
        else {
            "error_type": refusal["error_type"],
            "api_error_type": refusal["body"]["error"]["type"],
        },
    }


def sanitize(source: Path, protocol: Path) -> dict[str, Any]:
    trial_paths = sorted(source.glob("trial-*.json"))
    if len(trial_paths) != 30:
        raise ValueError("multiagent confirmation must contain exactly 30 trial files")
    records = [json.loads(path.read_text()) for path in trial_paths]
    cells = {
        name: sum(record["cell"] == name for record in records)
        for name in {
            "subagent_handoff",
            "concurrent_subagents_2",
            "concurrent_subagents_4",
        }
    }
    if cells != dict.fromkeys(cells, 10):
        raise ValueError("multiagent confirmation must contain ten trials per cell")

    cleanup_path = source / "cleanup.json"
    cleanup = json.loads(cleanup_path.read_text())
    sessions = [item for item in cleanup if item["kind"] == "session"]
    agents = [item for item in cleanup if item["kind"] == "agent"]
    environments = [item for item in cleanup if item["kind"] == "environment"]
    if not (
        len(sessions) == 30
        and all(item.get("deleted") and item.get("verified_absent") for item in sessions)
        and sorted((item.get("role"), item.get("archived")) for item in agents)
        == [("coordinator", True), ("worker", True)]
        and environments == [{"kind": "environment", "deleted": True}]
    ):
        raise ValueError("multiagent capture cleanup is incomplete")

    raw_paths = [source / "cell-order.json", *trial_paths, cleanup_path]
    return {
        "evidence_version": 1,
        "protocol_sha256": _sha256(protocol),
        "raw_capture_sha256": {path.name: _sha256(path) for path in raw_paths},
        "trials": [_trial(record) for record in sorted(records, key=lambda item: item["order"])],
        "cleanup": {
            "sessions_deleted_and_verified_absent": len(sessions),
            "agents_archived": len(agents),
            "environment_deleted": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--protocol", type=Path, default=Path(__file__).with_name("multiagent-protocol.json")
    )
    args = parser.parse_args()
    print(json.dumps(sanitize(args.source, args.protocol), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
