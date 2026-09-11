"""Project private AgentCore continuation captures into sanitised, reviewable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PROTOCOL = HERE / "continuation-protocol.json"
MARKER = "when temporal {\n"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
PARTITION = "aws"
RESOURCE_NAME = re.compile(rf"arn:{PARTITION}[a-z-]*:[^\s\"'\]\)]+", re.IGNORECASE)
ACCOUNT = re.compile(r"\b\d{12}\b")
GATEWAY_URL = re.compile(r"https://[a-z0-9-]+\.gateway\.bedrock-agentcore[^\s\"']*", re.IGNORECASE)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        value = GATEWAY_URL.sub("<reviewed-gateway-url>", value)
        value = RESOURCE_NAME.sub("<reviewed-resource>", value)
        value = UUID.sub("<reviewed-identifier>", value)
        return ACCOUNT.sub("<reviewed-account>", value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


class Aliases:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.values: dict[str, str] = {}

    def __call__(self, value: str) -> str:
        if value not in self.values:
            self.values[value] = f"{self.prefix}-{len(self.values) + 1:03d}"
        return self.values[value]


def _statement_map(protocol: dict[str, Any], gateway_resource: str) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for name in protocol["templates"]:
        template = (HERE / name).read_text(encoding="utf-8").rstrip("\n")
        live = template.replace(protocol["gateway_placeholder"], gateway_resource)
        mapping[_digest(live)] = {"template": name, "variant": "exact", "sha256": _digest(template)}
        if MARKER in template:
            spaced = template.replace(MARKER, MARKER + "\n", 1)
            mapping[_digest(live.replace(MARKER, MARKER + "\n", 1))] = {
                "template": name,
                "variant": "whitespace",
                "sha256": _digest(spaced),
            }
    return mapping


class Projector:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.protocol = _read(PROTOCOL)
        self.run = _read(source / "run.json")
        if self.run["protocol_sha256"] != _sha256(PROTOCOL):
            raise ValueError("capture did not use the committed continuation protocol")
        self.resources = _read(source / "resources.json")
        self.statements = _statement_map(self.protocol, self.resources.get("gateway_arn", ""))
        self.revisions = Aliases("revision")
        self.sessions = Aliases("session")

    def statement(self, digest: str | None) -> dict[str, str] | None:
        if digest is None:
            return None
        if digest not in self.statements:
            raise ValueError("a captured statement does not match any committed template")
        return self.statements[digest]

    def snapshot(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "observed_utc": value["observed"]["utc"],
            "observed_monotonic_ns": value["observed"]["monotonic_ns"],
            "status": value["status"],
            "status_reasons": _scrub(value["status_reasons"]),
            "revision_alias": self.revisions(value["updated_at"]),
            "description": value["description"],
            "statement": self.statement(value["statement_sha256"]),
            "enforcement_mode": value["enforcement_mode"],
            **({"poll_index": value["poll_index"]} if "poll_index" in value else {}),
        }

    def update(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        submitted = value["submitted"]
        return {
            "requested_utc": value["requested"]["utc"],
            "requested_monotonic_ns": value["requested"]["monotonic_ns"],
            "before": self.snapshot(value["before"]),
            "submitted": {
                "operation": submitted["operation"],
                "definition_supplied": submitted["definition_supplied"],
                "statement": self.statement(submitted["statement_sha256"]),
                "description": submitted["description"],
                "validation_mode": submitted["validation_mode"],
            },
            "managed_response": {
                "status": value["managed_response"]["status"],
                "revision_alias": self.revisions(value["managed_response"]["updated_at"]),
            },
            "polls": [self.snapshot(poll) for poll in value["polls"]],
            "completed_utc": value["completed"]["utc"],
            "completed_monotonic_ns": value["completed"]["monotonic_ns"],
            "after": self.snapshot(value["after"]),
            "revision_changed": value["revision_changed"],
        }

    def call(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_alias": self.sessions(value["session_id"]),
            "started_utc": value["started"]["utc"],
            "started_monotonic_ns": value["started"]["monotonic_ns"],
            "finished_utc": value["finished"]["utc"],
            "finished_monotonic_ns": value["finished"]["monotonic_ns"],
            "http_status": value["http_status"],
            "request": value["request"],
            "response": _scrub(value["response"]),
            "derived_outcome": value["derived_outcome"],
        }

    def controls(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "label": value["label"],
            "reset": self.update(value["reset"]),
            "single_below": self.call(value["single_below"]),
            "single_boundary": self.call(value["single_boundary"]),
            "same_session_pair": [self.call(item) for item in value["same_session_pair"]],
            "matches_prediction": value["matches_prediction"],
        }

    def trial(self, value: dict[str, Any]) -> dict[str, Any]:
        reviewed: dict[str, Any] = {
            "order": value["order"],
            "arm": value["arm"],
            "trial": value["trial"],
            "conforming": value["conforming"],
        }
        if "error" in value:
            reviewed["error"] = _scrub(value["error"])
            return reviewed
        reviewed["reset"] = self.update(value["reset"])
        for key in (
            "before_call",
            "predecessor_after_call",
            "recovery_call",
            "recovery_after_call",
        ):
            if key in value:
                reviewed[key] = self.call(value[key])
        reviewed["update"] = self.update(value["update"])
        reviewed["elapsed_monotonic_seconds"] = value["elapsed_monotonic_seconds"]
        reviewed["nonconforming_reasons"] = value["nonconforming_reasons"]
        return reviewed


def _count(values: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = "-".join(value) if isinstance(value, list) else str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _summary(protocol: dict[str, Any], trials: list[dict[str, Any]]) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm in protocol["arms"]:
        rows = [row for row in trials if row["arm"] == arm]
        scored = [row for row in rows if row["conforming"]]
        entry: dict[str, Any] = {
            "trials": len(rows),
            "nonconforming": len(rows) - len(scored),
            "revision_changed": sum(row["update"]["revision_changed"] for row in scored),
            "predecessor_after_update": _count(
                [row["predecessor_after_call"]["derived_outcome"] for row in scored]
            ),
        }
        successors = [
            [row["recovery_call"]["derived_outcome"], row["recovery_after_call"]["derived_outcome"]]
            for row in scored
            if "recovery_call" in row
        ]
        if successors:
            entry["successor_sequence"] = _count(successors)
        if arm == "tightening_to_700":
            entry["discrimination"] = {
                "reset_admits_first_successor_call": sum(pair[0] == "allow" for pair in successors),
                "carry_refuses_first_successor_call": sum(pair[0] == "deny" for pair in successors),
            }
        if scored:
            entry["maximum_elapsed_seconds"] = max(
                row["elapsed_monotonic_seconds"] for row in scored
            )
        arms[arm] = entry
    return arms


def project(source: Path, output: Path) -> dict[str, Any]:
    projector = Projector(source)
    protocol, run = projector.protocol, projector.run
    records = [_read(path) for path in sorted(source.glob("trial-*.json"))]
    trials = [projector.trial(record) for record in sorted(records, key=lambda r: r["order"])]
    controls = [
        projector.controls(_read(source / name))
        for name in ("preflight.json", "postflight.json")
        if (source / name).exists()
    ]
    validation = [
        {
            "candidate": attempt["candidate"],
            "validated": attempt["validated"],
            "steps": attempt["steps"],
            "error": _scrub(attempt.get("error")),
        }
        for attempt in projector.resources.get("validation", [])
    ]
    cleanup = [
        {
            "kind": item["kind"],
            "verified_absent": item["verified_absent"],
            "error": _scrub(item.get("error")),
        }
        for item in _read(source / "cleanup.json")
    ]
    events = {
        "continuation_events_version": 1,
        "provider": protocol["provider"],
        "region": protocol["region"],
        "mcp_protocol": protocol["mcp_protocol"],
        "mandate_sha256": protocol["mandate"]["sha256"],
        "validation_mode": run.get("validation_mode"),
        "candidate": run.get("candidate"),
        "controls": controls,
        "trials": trials,
    }
    deployment = {
        "continuation_deployment_version": 1,
        "deployment": _scrub(projector.resources.get("deployment")),
        "validation_attempts": validation,
        "cleanup": cleanup,
        "cleanup_complete": run["cleanup_complete"],
        "stopped": _scrub(run["stopped"]),
        "raw_capture_sha256": {
            path.name: _sha256(path)
            for path in sorted(source.iterdir())
            if path.is_file() and path.suffix == ".json"
        },
    }
    summary = {
        "continuation_summary_version": 1,
        "mandate_sha256": protocol["mandate"]["sha256"],
        "validation_mode": run.get("validation_mode"),
        "candidate": run.get("candidate"),
        "stopped": _scrub(run["stopped"]),
        "controls": {item["label"]: item["matches_prediction"] for item in controls},
        "arms": _summary(protocol, trials),
        "provider_state_snapshot": "unavailable",
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("continuation-events.json", events),
        ("continuation-deployment.json", deployment),
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
