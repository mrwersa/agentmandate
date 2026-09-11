"""Sanitise and verify the live principal-continuity counterfactual."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TOOL = "PrincipalTarget___process_refund"
GATEWAY = "<reviewed-principal-continuity-gateway>"
MANDATE = Path("examples/continuity-refund/manifest.json")
POLICIES = {
    "PrincipalPolicyEngine/PrincipalPermit": "principal-continuity-permit.cedar",
    "PrincipalPolicyEngine/PrincipalBudget": "principal-continuity-budget.dogwood",
}
UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _live_arn(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("arn:" + "aws")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _instant(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("principal-continuity timestamp is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("principal-continuity timestamp is not canonical UTC") from error
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        raise ValueError("principal-continuity timestamp is not canonical UTC")
    return parsed


def _sanitise_response(call: dict[str, Any], amount: int, expected: str) -> dict[str, Any]:
    response = call.get("response")
    identifier = call.get("request", {}).get("id")
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
        raise ValueError("principal-continuity response is not exact JSON-RPC")
    if response.get("id") != identifier or call.get("http_status") != 200:
        raise ValueError("principal-continuity response does not match its request")
    if expected == "allow":
        result = response.get("result")
        content = result.get("content") if isinstance(result, dict) else None
        if (
            not isinstance(result, dict)
            or result.get("isError") is not False
            or not isinstance(content, list)
            or len(content) != 1
            or content[0].get("type") != "text"
            or json.loads(content[0].get("text", ""))
            != {"processed": True, "amount": amount}
        ):
            raise ValueError("principal-continuity allow lacks the inert Lambda result")
        return response
    error = response.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    if (
        not isinstance(error, dict)
        or error.get("code") != -32002
        or not isinstance(message, str)
        or "Policy evaluation denied due to PrincipalBudget-" not in message
    ):
        raise ValueError("principal-continuity deny lacks the managed policy diagnostic")
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {
            "code": -32002,
            "message": (
                "Tool Execution Denied: Tool call not allowed due to policy enforcement "
                "[Policy evaluation denied due to <reviewed-principal-budget-policy>]"
            ),
        },
    }


def _call(call: dict[str, Any], alias: str, amount: int, expected: str) -> dict[str, Any]:
    request = call.get("request")
    if (
        call.get("principal_alias") != alias
        or call.get("outcome") != expected
        or not isinstance(request, dict)
        or request.get("method") != "tools/call"
        or request.get("params")
        != {"name": TOOL, "arguments": {"amount": amount}}
        or not isinstance(request.get("id"), str)
    ):
        raise ValueError("principal-continuity call does not match the reviewed request")
    started_at = _instant(call.get("started_at"))
    finished_at = _instant(call.get("finished_at"))
    started_ns, finished_ns = call.get("started_ns"), call.get("finished_ns")
    if (
        not isinstance(started_ns, int)
        or not isinstance(finished_ns, int)
        or started_ns > finished_ns
    ):
        raise ValueError("principal-continuity call interval is invalid")
    response = _sanitise_response(call, amount, expected)
    return {
        "principal_alias": alias.lower(),
        "started_at": call["started_at"],
        "finished_at": call["finished_at"],
        "duration_ms": round((finished_ns - started_ns) / 1_000_000, 6),
        "wall_clock_delta_ms": round((finished_at - started_at).total_seconds() * 1000, 6),
        "request": request,
        "response": response,
        "outcome": expected,
    }


def events(raw: dict[str, Any], mandate: bytes) -> dict[str, Any]:
    trials = raw.get("trials")
    controls = raw.get("controls")
    identities = raw.get("principal_arns")
    if (
        raw.get("capture_version") != 1
        or raw.get("provider") != "AWS AgentCore Gateway Policy"
        or raw.get("protocol") != "MCP 2025-03-26"
        or raw.get("region") != "us-east-1"
        or raw.get("tool") != TOOL
        or raw.get("retry") != {"sdk_max_attempts": 0, "application_retries": 0}
        or raw.get("random_seed") != 20260911
        or raw.get("principal_identity_distinct") is not True
        or not isinstance(identities, dict)
        or set(identities) != {"A", "B"}
        or identities["A"] == identities["B"]
        or not all(_live_arn(value) for value in identities.values())
        or not isinstance(trials, list)
        or len(trials) != 20
        or not isinstance(controls, list)
        or len(controls) != 4
    ):
        raise ValueError("principal-continuity capture root is incomplete")
    if _instant(raw.get("capture_started_at")) > _instant(raw.get("capture_finished_at")):
        raise ValueError("principal-continuity capture interval is invalid")

    expected_order = [("same", index) for index in range(10)] + [
        ("changed", index) for index in range(10)
    ]
    random.Random(20260911).shuffle(expected_order)
    if [(row.get("arm"), row.get("trial")) for row in trials] != expected_order:
        raise ValueError("principal-continuity pair order is not the reviewed shuffle")

    seen_sessions: set[str] = set()
    rows = []
    for row in trials:
        arm, index = row["arm"], row["trial"]
        first, second = row.get("first"), row.get("second")
        expected_principals = (
            (("A", "A") if index % 2 == 0 else ("B", "B"))
            if arm == "same"
            else (("A", "B") if index % 2 == 0 else ("B", "A"))
        )
        calls = row.get("calls")
        if (first, second) != expected_principals or not isinstance(calls, list) or len(calls) != 2:
            raise ValueError(f"principal-continuity trial {arm}-{index} has invalid identities")
        sessions = [call.get("session_id") for call in calls]
        if (
            sessions[0] != sessions[1]
            or not isinstance(sessions[0], str)
            or UUID.fullmatch(sessions[0]) is None
            or sessions[0] in seen_sessions
        ):
            raise ValueError(f"principal-continuity trial {arm}-{index} has invalid session reuse")
        seen_sessions.add(sessions[0])
        expected_outcomes = ("allow", "deny") if arm == "same" else ("allow", "allow")
        reviewed = [
            _call(call, alias, 600, expected)
            for call, alias, expected in zip(
                calls, expected_principals, expected_outcomes, strict=True
            )
        ]
        if calls[0]["finished_ns"] > calls[1]["started_ns"]:
            raise ValueError(f"principal-continuity trial {arm}-{index} is not sequential")
        rows.append(
            {
                "arm": arm,
                "trial": index,
                "session_alias": f"{arm}-{index}",
                "principal_sequence": [alias.lower() for alias in expected_principals],
                "calls": reviewed,
            }
        )

    reviewed_controls = []
    for index, (alias, amount, expected) in enumerate(
        (("A", 500, "allow"), ("A", 1000, "deny"), ("B", 500, "allow"), ("B", 1000, "deny"))
    ):
        call = controls[index]
        session = call.get("session_id")
        if (
            not isinstance(session, str)
            or UUID.fullmatch(session) is None
            or session in seen_sessions
        ):
            raise ValueError("principal-continuity control session is not independent")
        seen_sessions.add(session)
        reviewed_controls.append(
            {
                "session_alias": f"control-{alias.lower()}-{amount}",
                **_call(call, alias, amount, expected),
            }
        )

    expected_state = {
        "configured_limit": 1000,
        "consumed": "unavailable",
        "remaining": "unavailable",
        "reserved": "unavailable",
        "in_flight": "unavailable",
        "completed": "unavailable",
    }
    if raw.get("provider_state") != expected_state:
        raise ValueError("principal-continuity provider state must retain unknown fields")
    return {
        "principal_continuity_events_version": 1,
        "capture_started_at": raw["capture_started_at"],
        "capture_finished_at": raw["capture_finished_at"],
        "provider": raw["provider"],
        "region": raw["region"],
        "protocol": raw["protocol"],
        "tool": TOOL,
        "mandate_sha256": hashlib.sha256(mandate).hexdigest(),
        "mandate_binding": "external experiment invariant; Gateway did not inspect it",
        "principal_identity": {
            "aliases": ["a", "b"],
            "authenticated_by": "AWS_IAM",
            "proof": "distinct STS GetCallerIdentity results validated before trials",
            "raw_identifiers_retained": False,
        },
        "random_seed": 20260911,
        "retry": raw["retry"],
        "sdk": raw["sdk"],
        "provider_state": expected_state,
        "trials": rows,
        "controls": reviewed_controls,
        "sanitisation": {
            "omitted": [
                "AWS account identifier",
                "Amazon Resource Names",
                "access keys",
                "Gateway URL",
                "live policy identifiers",
                "provider session identifiers",
            ],
            "raw_live_files_deleted_after_projection": True,
        },
    }


def deployment(raw: dict[str, Any], policy_text: dict[str, str]) -> dict[str, Any]:
    gateway, engine = raw.get("gateway", {}), raw.get("policy_engine", {})
    targets, policies = raw.get("targets", {}).get("items"), raw.get("policies")
    if (
        raw.get("capture_version") != 1
        or gateway.get("status") != "READY"
        or gateway.get("protocolType") != "MCP"
        or gateway.get("authorizerType") != "AWS_IAM"
        or gateway.get("exceptionLevel") != "DEBUG"
        or gateway.get("protocolConfiguration") != {"mcp": {"searchType": "SEMANTIC"}}
        or gateway.get("policyEngineConfiguration", {}).get("mode") != "ENFORCE"
        or engine.get("status") != "ACTIVE"
        or not isinstance(targets, list)
        or len(targets) != 1
        or {key: targets[0].get(key) for key in ("name", "status", "targetType")}
        != {"name": "PrincipalTarget", "status": "READY", "targetType": "LAMBDA"}
        or not isinstance(policies, dict)
        or set(policies) != set(POLICIES)
        or raw.get("temporary_users_after_capture") != []
    ):
        raise ValueError("principal-continuity deployment boundary is incomplete")

    reviewed_policies = []
    gateway_arn = gateway.get("gatewayArn")
    if not _live_arn(gateway_arn):
        raise ValueError("principal-continuity Gateway ARN is absent")
    for logical, filename in POLICIES.items():
        value = policies[logical]
        definition = value.get("definition", {}).get("policy", {})
        statement = definition.get("statement")
        sanitised = statement.replace(gateway_arn, GATEWAY) if isinstance(statement, str) else None
        if (
            value.get("status") != "ACTIVE"
            or value.get("enforcementMode") != "ACTIVE"
            or sanitised != policy_text[filename].strip()
        ):
            raise ValueError(f"principal-continuity policy {logical} is not exact and ACTIVE")
        reviewed_policies.append(
            {
                "name": value["name"],
                "definition_kind": "policy",
                "enforcement_mode": "ACTIVE",
                "status": "ACTIVE",
                "statement_sha256": hashlib.sha256(policy_text[filename].encode()).hexdigest(),
            }
        )

    correction = raw.get("gateway_role_correction", {}).get("PolicyDocument", {})
    statements = correction.get("Statement")
    resources = (
        statements[0].get("Resource") if isinstance(statements, list) and statements else None
    )
    if (
        correction.get("Version") != "2012-10-17"
        or len(statements) != 1
        or statements[0].get("Effect") != "Allow"
        or statements[0].get("Action") != "bedrock-agentcore:GetWorkloadAccessToken"
        or not isinstance(resources, list)
        or len(resources) != 2
        or not all(_live_arn(item) for item in resources)
        or "/workload-identity/" in resources[0]
        or not resources[1].startswith(f"{resources[0]}/workload-identity/")
    ):
        raise ValueError("principal-continuity Gateway correction is not narrowly scoped")

    inventory: dict[str, int] = {}
    for item in raw.get("stack_resources", []):
        kind = item.get("ResourceType")
        if not isinstance(kind, str):
            raise ValueError("principal-continuity stack resource type is invalid")
        inventory[kind] = inventory.get(kind, 0) + 1
    expected_inventory = {
        "AWS::BedrockAgentCore::Gateway": 1,
        "AWS::BedrockAgentCore::GatewayTarget": 1,
        "AWS::BedrockAgentCore::Policy": 2,
        "AWS::BedrockAgentCore::PolicyEngine": 1,
        "AWS::CDK::Metadata": 1,
        "AWS::IAM::Policy": 1,
        "AWS::IAM::Role": 2,
        "AWS::Lambda::Function": 1,
        "AWS::Logs::LogGroup": 1,
    }
    if inventory != expected_inventory:
        raise ValueError("principal-continuity stack inventory is incomplete")
    operations = raw.get("service_operations")
    if not isinstance(operations, list) or "GetPolicy" not in operations:
        raise ValueError("principal-continuity provider interface is absent")
    continuation = [
        name
        for name in operations
        if any(
            term in name.lower()
            for term in ("migrate", "reauthor", "settle", "transfer", "continuation")
        )
    ]
    return {
        "principal_continuity_deployment_version": 1,
        "provider": "AWS AgentCore Gateway Policy",
        "region": "us-east-1",
        "agentcore_cli": "0.24.2",
        "boto3": raw["boto3"],
        "botocore": raw["botocore"],
        "gateway": {
            "alias": "principal-continuity-gateway",
            "status": "READY",
            "protocol": "MCP",
            "authorizer": "AWS_IAM",
            "policy_engine_mode": "ENFORCE",
            "search_type": "SEMANTIC",
        },
        "target": {"alias": "principal-target", "status": "READY", "type": "LAMBDA"},
        "policy_engine": {"alias": "principal-policy-engine", "status": "ACTIVE"},
        "policies": sorted(reviewed_policies, key=lambda item: item["name"]),
        "stack_inventory": expected_inventory,
        "gateway_role_correction": {
            "action": "bedrock-agentcore:GetWorkloadAccessToken",
            "effect": "Allow",
            "resources": ["default-workload-directory", "exact-gateway-workload-identity"],
            "wildcard": False,
        },
        "temporary_principals_after_capture": 0,
        "state_continuation_operations": continuation,
        "provider_state_snapshot": "unavailable",
    }


def summary(reviewed: dict[str, Any]) -> dict[str, Any]:
    same = [row for row in reviewed["trials"] if row["arm"] == "same"]
    changed = [row for row in reviewed["trials"] if row["arm"] == "changed"]
    same_outcomes = [[call["outcome"] for call in row["calls"]] for row in same]
    changed_outcomes = [[call["outcome"] for call in row["calls"]] for row in changed]
    controls = [call["outcome"] for call in reviewed["controls"]]
    if (
        same_outcomes != [["allow", "deny"]] * 10
        or changed_outcomes != [["allow", "allow"]] * 10
        or controls != ["allow", "deny", "allow", "deny"]
    ):
        raise ValueError("principal-continuity reviewed outcomes have drifted")
    directions = {
        "a_to_b": sum(row["principal_sequence"] == ["a", "b"] for row in changed),
        "b_to_a": sum(row["principal_sequence"] == ["b", "a"] for row in changed),
    }
    if directions != {"a_to_b": 5, "b_to_a": 5}:
        raise ValueError("principal-continuity directions are not balanced")
    durations = [call["duration_ms"] for row in reviewed["trials"] for call in row["calls"]]
    return {
        "principal_continuity_summary_version": 1,
        "mandate_sha256": reviewed["mandate_sha256"],
        "threshold": 1000,
        "request_amount": 600,
        "trials_per_arm": 10,
        "results": {
            "same_principal_allow_then_deny": 10,
            "changed_principal_allow_then_allow": 10,
            "changed_principal_aggregate": 1200,
            "direction_counts": directions,
            "single_request_controls": {
                "principal_a": {"below_500": "allow", "boundary_1000": "deny"},
                "principal_b": {"below_500": "allow", "boundary_1000": "deny"},
            },
            "managed_call_ms": {
                "minimum": min(durations),
                "maximum": max(durations),
            },
        },
        "finding": (
            "under the tested service and policy versions, cumulative history was isolated by "
            "authenticated IAM principal as well as policy-session identifier"
        ),
        "claim_boundary": (
            "ten balanced principal changes under one Gateway and policy revision; allow/deny "
            "outcomes with provider state fields unavailable, not a claim about all identities"
        ),
    }


def _index(output: Path) -> dict[str, Any]:
    names = {
        "capture_principal_continuity.py",
        "principal-continuity-budget.dogwood",
        "principal-continuity-cleanup.json",
        "principal-continuity-corrections.json",
        "principal-continuity-deployment.json",
        "principal-continuity-events.json",
        "principal-continuity-permit.cedar",
        "principal-continuity-procedure.md",
        "principal-continuity-summary.json",
    }
    return {
        "principal_continuity_capture_version": 1,
        "capture_date": "2026-09-11",
        "provider": "AWS AgentCore Gateway Policy ENFORCE",
        "region": "us-east-1",
        "sources": [
            {
                "locator": name,
                "content_sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
            }
            for name in sorted(names)
        ],
        "raw_artifacts_committed": False,
        "raw_artifact_policy": (
            "live account, resource, policy, request and session identifiers remained in "
            "temporary files and were deleted after reviewed projection"
        ),
    }


def capture(raw_path: Path, state_path: Path, output: Path, root: Path) -> None:
    mandate = (root / MANDATE).read_bytes()
    policy_text = {name: (output / name).read_text(encoding="utf-8") for name in POLICIES.values()}
    reviewed_events = events(_read(raw_path), mandate)
    reviewed_deployment = deployment(_read(state_path), policy_text)
    _write(output / "principal-continuity-events.json", reviewed_events)
    _write(output / "principal-continuity-deployment.json", reviewed_deployment)
    _write(output / "principal-continuity-summary.json", summary(reviewed_events))
    _write(output / "principal-continuity-index.json", _index(output))


def verify(output: Path, root: Path) -> None:
    reviewed_events = _read(output / "principal-continuity-events.json")
    mandate_sha256 = hashlib.sha256((root / MANDATE).read_bytes()).hexdigest()
    if reviewed_events.get("mandate_sha256") != mandate_sha256:
        raise ValueError("principal-continuity mandate digest has drifted")
    if summary(reviewed_events) != _read(output / "principal-continuity-summary.json"):
        raise ValueError("principal-continuity summary does not match its events")
    if _index(output) != _read(output / "principal-continuity-index.json"):
        raise ValueError("principal-continuity index does not match committed evidence")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path, default=HERE)
    parser.add_argument("--root", type=Path, default=HERE.parents[2])
    args = parser.parse_args()
    if (args.raw is None) != (args.state is None):
        parser.error("--raw and --state must be supplied together")
    if args.raw is None:
        verify(args.output, args.root)
        print("principal-continuity evidence: committed bundle verifies")
    else:
        capture(args.raw, args.state, args.output, args.root)
        print("principal-continuity evidence: live capture projected")


if __name__ == "__main__":
    main()
