"""Replay repository-only principal observations, not a runtime continuity profile."""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from agentmandate._continuity import ContinuityFormatError
from scripts.migrate_continuity_evidence import (
    _captured,
    _migration_evidence,
    _migration_sources,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = "docs/evidence/agentcore-refund-policy/"
FIXTURE = ROOT / "tests/fixtures/agentcore-principal-observations-v1.json"
PINS = {
    "principal-continuity-index.json": (
        "81972ff6288675709e202cf1d4c39b980c076837c689080b787ef01ce871fbb4"
    ),
    "capture_principal_continuity.py": (
        "7468b28691d794285cecd666c2712a2f1d69b6dd4af922cca6278fc4aaf0bb64"
    ),
    "principal-continuity-budget.dogwood": (
        "a587948f683c16736f41da33f675d90a618ff2ef3235e783d7ba3c57d000ca0f"
    ),
    "principal-continuity-cleanup.json": (
        "3ea96cfec12201c649364dc0232e5248a5e1049ea51c5c970c1ee531f83a63f4"
    ),
    "principal-continuity-corrections.json": (
        "151bff97016809fac3caed3ce6742f542848cfafa9bed32aa9d8f4c02e4afcc7"
    ),
    "principal-continuity-deployment.json": (
        "31adf3af0bf4bd6ac868284703628ab2807cf0ce1d33892cb783d3f0918ec5bb"
    ),
    "principal-continuity-events.json": (
        "07a203e38d15bae630fa6029591c899633a06a3ec9c654856903fc5f527ca09d"
    ),
    "principal-continuity-permit.cedar": (
        "567afddbd8ab86303c8f8d23db3f4c9fa32593302ea12e3c18a98edcb0c958a2"
    ),
    "principal-continuity-procedure.md": (
        "20508f920079233b9876a9c3a116b9662c7589e9bb94b5ef9e0bcb18ab5a2cc3"
    ),
    "principal-continuity-summary.json": (
        "a0ac8836aa03a9608d9f9703abcf8443dd120ec13012e2164fefd49d283fd229"
    ),
}


def _call(raw: dict[str, Any], principal: str, amount: int, outcome: str) -> dict[str, Any]:
    request, response = raw["request"], raw["response"]
    if (
        raw["principal_alias"] != principal
        or raw["outcome"] != outcome
        or request
        != {
            "id": request["id"],
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"arguments": {"amount": amount}, "name": "PrincipalTarget___process_refund"},
        }
        or not isinstance(request["id"], str)
        or not request["id"]
        or response["id"] != request["id"]
        or response["jsonrpc"] != "2.0"
    ):
        raise ContinuityFormatError("principal projection call identity differs")
    if outcome == "allow":
        result = response.get("result", {})
        content = result.get("content", [])
        if (
            "error" in response
            or result.get("isError") is not False
            or len(content) != 1
            or content[0].get("type") != "text"
            or json.loads(content[0]["text"]) != {"processed": True, "amount": amount}
        ):
            raise ContinuityFormatError("principal projection native allow differs")
    elif (
        "result" in response
        or response.get("error", {}).get("code") != -32002
        or "<reviewed-principal-budget-policy>" not in response["error"].get("message", "")
    ):
        raise ContinuityFormatError("principal projection native denial differs")
    start, finish = (
        datetime.fromisoformat(raw[key].replace("Z", "+00:00"))
        for key in ("started_at", "finished_at")
    )
    # Preserve a negative wall-clock delta. The monotonic endpoints were not
    # retained, so a positive recorded duration cannot independently prove order.
    if (
        round((finish - start).total_seconds() * 1000, 6) != raw["wall_clock_delta_ms"]
        or not isinstance(raw["duration_ms"], (int, float))
        or raw["duration_ms"] <= 0
    ):
        raise ContinuityFormatError("principal projection recorded clocks differ")
    return {
        "principal_alias": principal,
        "request_amount": amount,
        "outcome": outcome,
        "started_at": raw["started_at"],
        "finished_at": raw["finished_at"],
        "recorded_duration_ms": raw["duration_ms"],
        "wall_clock_delta_ms": raw["wall_clock_delta_ms"],
    }


def project_principal_observations(contents: dict[str, bytes]) -> dict[str, Any]:
    """Preserve principal and session axes without asserting shared-mandate consumption."""
    sources = _migration_sources(
        contents,
        {BASE + name: "principal-capture" for name in PINS},
        {BASE + name: digest for name, digest in PINS.items()},
    )
    index = _captured(contents, BASE + "principal-continuity-index.json")
    events = _captured(contents, BASE + "principal-continuity-events.json")
    deployment = _captured(contents, BASE + "principal-continuity-deployment.json")
    summary = _captured(contents, BASE + "principal-continuity-summary.json")
    expected_index = {
        name: digest for name, digest in PINS.items() if name != "principal-continuity-index.json"
    }
    if (
        len(index["sources"]) != len(expected_index)
        or {s["locator"]: s["content_sha256"] for s in index["sources"]} != expected_index
        or events["principal_continuity_events_version"] != 1
        or deployment["principal_continuity_deployment_version"] != 1
        or events["mandate_sha256"] != summary["mandate_sha256"]
        or events["mandate_sha256"]
        != "f8aa99a6d889db19002c193801cd84bce36e10219d343804eb717f61b5236326"
        or events["mandate_binding"] != "external experiment invariant; Gateway did not inspect it"
        or events["principal_identity"]
        != {
            "aliases": ["a", "b"],
            "authenticated_by": "AWS_IAM",
            "proof": "distinct STS GetCallerIdentity results validated before trials",
            "raw_identifiers_retained": False,
        }
        or events["retry"] != {"application_retries": 0, "sdk_max_attempts": 0}
        or events["protocol"] != "MCP 2025-03-26"
        or events["random_seed"] != 20260911
        or events["region"] != deployment["region"]
        or deployment["gateway"]
        != {
            "alias": "principal-continuity-gateway",
            "authorizer": "AWS_IAM",
            "policy_engine_mode": "ENFORCE",
            "protocol": "MCP",
            "search_type": "SEMANTIC",
            "status": "READY",
        }
        or events["provider_state"]
        != {
            "configured_limit": 1000,
            "consumed": "unavailable",
            "remaining": "unavailable",
            "reserved": "unavailable",
            "in_flight": "unavailable",
            "completed": "unavailable",
        }
    ):
        raise ContinuityFormatError("principal projection source join or configuration differs")
    expected_policies = {
        "PrincipalBudget": hashlib.sha256(
            contents[BASE + "principal-continuity-budget.dogwood"]
        ).hexdigest(),
        "PrincipalPermit": hashlib.sha256(
            contents[BASE + "principal-continuity-permit.cedar"]
        ).hexdigest(),
    }
    if (
        len(deployment["policies"]) != 2
        or {p["name"]: p["statement_sha256"] for p in deployment["policies"]} != expected_policies
        or any(
            p["status"] != "ACTIVE" or p["enforcement_mode"] != "ACTIVE"
            for p in deployment["policies"]
        )
    ):
        raise ContinuityFormatError("principal projection policy join differs")
    expected_order = [(arm, trial) for arm in ("same", "changed") for trial in range(10)]
    random.Random(20260911).shuffle(expected_order)
    trials = events["trials"]
    if [(t["arm"], t["trial"]) for t in trials] != expected_order:
        raise ContinuityFormatError("principal projection trial identities or order differ")
    observations = []
    request_ids = []
    for source_index, trial in enumerate(trials):
        changed = trial["arm"] == "changed"
        first = "a" if trial["trial"] % 2 == 0 else "b"
        second = ("b" if first == "a" else "a") if changed else first
        if (
            trial["principal_sequence"] != [first, second]
            or len(trial["calls"]) != 2
            or trial["session_alias"] != f"{trial['arm']}-{trial['trial']}"
        ):
            raise ContinuityFormatError(
                "principal projection principal or session relation differs"
            )
        outcomes = ("allow", "allow" if changed else "deny")
        calls = [
            _call(raw, principal, 600, outcome)
            for raw, principal, outcome in zip(
                trial["calls"], (first, second), outcomes, strict=True
            )
        ]
        request_ids.extend(raw["request"]["id"] for raw in trial["calls"])
        completed = {
            principal: sum(
                call["request_amount"]
                for call in calls
                if call["principal_alias"] == principal and call["outcome"] == "allow"
            )
            for principal in sorted({first, second})
        }
        observations.append(
            {
                "id": trial["session_alias"],
                "source_pointer": f"/trials/{source_index}",
                "principal_sequence": [first, second],
                "session_alias": trial["session_alias"],
                "session_relation": "recorded_same",
                "calls": calls,
                "observed_completed_by_principal": completed,
                "observed_completed_across_principals": sum(completed.values()),
            }
        )
    expected_controls = (
        ("a", 500, "allow"),
        ("a", 1000, "deny"),
        ("b", 500, "allow"),
        ("b", 1000, "deny"),
    )
    if len(events["controls"]) != 4:
        raise ContinuityFormatError("principal projection single-request controls differ")
    controls = []
    for i, (raw, (principal, amount, outcome)) in enumerate(
        zip(events["controls"], expected_controls, strict=True)
    ):
        if raw["session_alias"] != f"control-{principal}-{amount}":
            raise ContinuityFormatError("principal projection control session differs")
        controls.append(
            {
                "source_pointer": f"/controls/{i}",
                "session_alias": raw["session_alias"],
                **_call(raw, principal, amount, outcome),
            }
        )
        request_ids.append(raw["request"]["id"])
    if len(set(request_ids)) != 44:
        raise ContinuityFormatError("principal projection request identities are not distinct")
    durations = [call["recorded_duration_ms"] for row in observations for call in row["calls"]]
    if (
        summary["principal_continuity_summary_version"] != 1
        or summary["request_amount"] != 600
        or summary["threshold"] != 1000
        or summary["trials_per_arm"] != 10
        or summary["results"]
        != {
            "same_principal_allow_then_deny": 10,
            "changed_principal_allow_then_allow": 10,
            "changed_principal_aggregate": 1200,
            "direction_counts": {"a_to_b": 5, "b_to_a": 5},
            "managed_call_ms": {"minimum": min(durations), "maximum": max(durations)},
            "single_request_controls": {
                "principal_a": {"below_500": "allow", "boundary_1000": "deny"},
                "principal_b": {"below_500": "allow", "boundary_1000": "deny"},
            },
        }
    ):
        raise ContinuityFormatError("principal projection summary differs from events")
    return {
        "principal_observations_version": 1,
        "scope": "repository-only observations; not a runtime continuity profile",
        "sources": [source.as_dict() for source in sources],
        "events_locator": BASE + "principal-continuity-events.json",
        "evidence": _migration_evidence().as_dict(),
        "mandate_sha256": events["mandate_sha256"],
        "same_mandate": None,
        "mediation": "unestablished",
        "protocol": events["protocol"],
        "recorded_gateway": deployment["gateway"]["alias"],
        "recorded_policy_statements": expected_policies,
        "principal_identity_claim": events["principal_identity"],
        "provider_state": events["provider_state"],
        "monotonic_endpoints_retained": False,
        "ordering_basis": "original sanitizer checked raw monotonic endpoints; not replayable here",
        "trials": sorted(observations, key=lambda item: item["id"]),
        "single_request_controls": controls,
    }


def canonical_json(observations: dict[str, Any]) -> str:
    return json.dumps(observations, sort_keys=True, separators=(",", ":")) + "\n"


def verify_fixture() -> None:
    contents = {BASE + name: (ROOT / BASE / name).read_bytes() for name in PINS}
    projected = canonical_json(project_principal_observations(contents))
    if projected != FIXTURE.read_text(encoding="utf-8"):
        raise ContinuityFormatError(
            "principal projection no longer reproduces canonical observations"
        )


if __name__ == "__main__":
    verify_fixture()
    print("principal observations: canonical fixture matches pinned sources; no continuity verdict")
