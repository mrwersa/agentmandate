"""Project private Managed Agents continuation captures into identifier-free evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL = HERE / "continuation-protocol.json"
REFUSAL = "budget.max_list_cost must be greater than the session's consumed list cost"
IDENTIFIER = re.compile(r"\b(?:sesn|agent|env|evt|sevt|sthr|wrkspc|depl|drun)_[A-Za-z0-9]+\b")
CELLS = (
    "lowered_cap_carries_spend",
    "cap_at_or_below_spend_refused",
    "agent_update_leaves_live_session",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scrub(text: str | None) -> str | None:
    return None if text is None else IDENTIFIER.sub("<managed-identifier>", text)


def _units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "work_unit": unit["work_unit"],
            "started_utc": unit["started"]["utc"],
            "finished_utc": unit["finished"]["utc"],
            "duration_ns": unit["finished"]["monotonic_ns"] - unit["started"]["monotonic_ns"],
            "list_cost_minor_units": unit["list_cost_minor_units"],
            "idle_reason": unit["idle_reason"],
            "session_status": unit["session_status"],
        }
        for unit in units
    ]


def _normalised(message: str | None) -> str:
    return (message or "").replace("`", "")


def _classify(record: dict[str, Any], protocol: dict[str, Any]) -> str | None:
    if not record.get("conforming"):
        return None
    cell, result = record["cell"], record["result"]
    if cell == "lowered_cap_carries_spend":
        reached = record["after_update"][-1]["idle_reason"] == "budget_reached"
        if reached and result["added_cents"] <= 3:
            return "carry"
        return "reset" if result["added_cents"] >= 5 else "indeterminate"
    if cell == "cap_at_or_below_spend_refused":
        refusal = result["refusal"]
        cap = protocol["cells"][cell]["create_cap_cents"]
        refused = (
            refusal is not None
            and refusal["status_code"] == 400
            and REFUSAL in _normalised(refusal["message"])
            and result["retrieved_cap"] == cap
        )
        return "refused" if refused else "not_refused"
    update = record["agent_update"]
    pinned = (
        update["session_version_after_update"] == update["original_version"]
        and result["session_version_at_budget"] == update["original_version"]
    )
    if pinned and result["final_reported_cents"] <= 7:
        return "pinned_and_retained"
    return "reset" if result["final_reported_cents"] >= 8 else "indeterminate"


def _trial(record: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    reviewed: dict[str, Any] = {
        "order": record["order"],
        "cell": record["cell"],
        "trial": record["trial"],
        "started_utc": record["started"]["utc"],
        "finished_utc": record["finished"]["utc"],
        "conforming": record["conforming"],
        "classification": _classify(record, protocol),
    }
    if not record["conforming"]:
        reviewed["error"] = {
            "type": record["error"]["type"],
            "message": _scrub(record["error"]["message"]),
        }
    if "before_update" in record:
        reviewed["before_update"] = _units(record["before_update"])
    if "after_update" in record:
        reviewed["after_update"] = _units(record["after_update"])
    if "update" in record:
        update = record["update"]
        reviewed["cap_update"] = {
            "reported_cents": update["reported_cents"],
            "requested_cap": update["requested_cap"],
            "response_cap": update["response_cap"],
            "retrieved_cap": update["retrieved_cap"],
            "requested_utc": update["requested"]["utc"],
            "completed_utc": update["completed"]["utc"],
        }
    if "agent_update" in record:
        update = record["agent_update"]
        reviewed["agent_update"] = {
            key: update[key]
            for key in (
                "reported_cents",
                "original_version",
                "updated_version",
                "session_version_after_update",
            )
        }
    if "post_budget_refusal" in record:
        refusal = record["post_budget_refusal"]
        reviewed["post_budget_refusal"] = {
            "error_type": refusal["error_type"],
            "status_code": refusal["status_code"],
            "message": _scrub(refusal["message"]),
        }
    if "result" in record:
        result = dict(record["result"])
        result.pop("classification", None)
        for key in ("requested", "completed"):
            if key in result:
                result[f"{key}_utc"] = result.pop(key)["utc"]
        if result.get("refusal"):
            result["refusal"] = {
                **result["refusal"],
                "message": _scrub(result["refusal"]["message"]),
            }
        reviewed["result"] = result
    return reviewed


def project(source: Path, output: Path) -> dict[str, Any]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    run = json.loads((source / "run.json").read_text(encoding="utf-8"))
    if run["protocol_sha256"] != _sha256(PROTOCOL):
        raise ValueError("capture did not use the committed continuation protocol")
    trial_paths = sorted(source.glob("trial-*.json"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in trial_paths]
    counts = {cell: sum(record["cell"] == cell for record in records) for cell in CELLS}
    cleanup = json.loads((source / "cleanup.json").read_text(encoding="utf-8"))
    pilot = json.loads((source / "pilot.json").read_text(encoding="utf-8"))
    trials = [_trial(record, protocol) for record in sorted(records, key=lambda r: r["order"])]
    results: dict[str, Any] = {}
    for cell in CELLS:
        rows = [row for row in trials if row["cell"] == cell]
        classes: dict[str, int] = {}
        for row in rows:
            key = row["classification"] or "nonconforming"
            classes[key] = classes.get(key, 0) + 1
        results[cell] = {"trials": len(rows), "classifications": dict(sorted(classes.items()))}
    evidence = {
        "continuation_evidence_version": 1,
        "protocol_sha256": run["protocol_sha256"],
        "model": run.get("model"),
        "stopped": run["stopped"],
        "spent_reported_cents": run["spent_reported_cents"],
        "trials_per_cell_observed": counts,
        "pilot": {
            "excluded_from_results": True,
            "median_units_per_reported_cent": pilot["median_units_per_reported_cent"],
            "continue": pilot["continue"],
            "units_per_cent": [run_["units_per_cent"] for run_ in pilot["runs"]],
        },
        "documentation": [
            {"url": item["url"], "sha256": item["sha256"], "fetched_utc": item["fetched"]["utc"]}
            for item in json.loads((source / "documentation.json").read_text(encoding="utf-8"))
        ],
        "trials": trials,
        "cleanup": {
            "sessions_deleted_and_verified_absent": sum(
                item["kind"] == "session" and item.get("verified_absent", False) for item in cleanup
            ),
            "agents_archived": sum(
                item["kind"] == "agent" and item.get("archived", False) for item in cleanup
            ),
            "environment_deleted": any(
                item["kind"] == "environment" and item.get("deleted") for item in cleanup
            ),
            "complete": run["cleanup_complete"],
        },
        "raw_capture_sha256": {
            path.name: _sha256(path)
            for path in sorted(source.iterdir())
            if path.is_file() and path.suffix == ".json"
        },
    }
    summary = {
        "continuation_summary_version": 1,
        "framing": protocol["framing"],
        "model": run.get("model"),
        "stopped": run["stopped"],
        "results": results,
        "claim_boundary": (
            "single-thread sessions on one model, prompt, and environment; whole-cent reported "
            "list cost with the documented one-request overshoot; provider cost is not "
            "application authority"
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("continuation-confirmation.json", evidence),
        ("continuation-summary.json", summary),
    ):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    print(json.dumps(project(args.source, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
