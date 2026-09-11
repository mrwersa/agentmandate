"""Sanitize and verify the live completed-request retransmission capture."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GATEWAY = "<reviewed-retry-continuity-gateway>"
ENGINE = "<reviewed-retry-continuity-policy-engine>"
BUDGET = "<reviewed-retry-budget-policy>"
MANDATE = "examples/continuity-refund/manifest.json"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
FILES = (
    "capture_retry_continuity.py",
    "retry-continuity-budget.dogwood",
    "retry-continuity-cleanup.json",
    "retry-continuity-contract.json",
    "retry-continuity-corrections.json",
    "retry-continuity-deployment.json",
    "retry-continuity-events.json",
    "retry-continuity-lambda.py.txt",
    "retry-continuity-permit.cedar",
    "retry-continuity-procedure.md",
    "retry-continuity-summary.json",
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("retry-continuity timestamp is not canonical UTC")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError("retry-continuity timestamp is not canonical UTC") from error
    if parsed.tzinfo != timezone.utc:
        raise ValueError("retry-continuity timestamp is not canonical UTC")
    return value


def _request(raw: Any, expected_amount: int) -> dict[str, Any]:
    if not isinstance(raw, str):
        raise ValueError("retry-continuity request bytes are absent")
    value = json.loads(raw)
    if (
        value.get("jsonrpc") != "2.0"
        or value.get("method") != "tools/call"
        or value.get("params", {}).get("name") != "RetryTarget___process_refund"
        or value.get("params", {}).get("arguments") != {"amount": expected_amount}
        or not isinstance(value.get("id"), str)
    ):
        raise ValueError("retry-continuity request does not match the reviewed call")
    return value


def _call(
    raw: dict[str, Any],
    expected_amount: int,
    marker_aliases: dict[str, str],
    budget_id: str,
) -> dict[str, Any]:
    request = _request(raw.get("request_bytes"), expected_amount)
    response = raw.get("response")
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
        raise ValueError("retry-continuity response is not exact JSON-RPC")
    if response.get("id") != request["id"]:
        raise ValueError("retry-continuity response does not match its request")
    duration = raw.get("duration_ms")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError("retry-continuity call duration is invalid")

    reviewed_response: dict[str, Any]
    execution_alias: str | None = None
    if "result" in response and response["result"].get("isError") is False:
        content = response["result"].get("content")
        if not isinstance(content, list) or len(content) != 1:
            raise ValueError("retry-continuity allow lacks one target result")
        payload = json.loads(content[0].get("text", ""))
        marker = payload.get("execution_marker")
        if (
            payload.get("processed") is not True
            or payload.get("amount") != expected_amount
            or not isinstance(marker, str)
            or UUID.fullmatch(marker) is None
        ):
            raise ValueError("retry-continuity target execution result is invalid")
        execution_alias = marker_aliases.setdefault(marker, f"execution-{len(marker_aliases) + 1}")
        reviewed_response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "processed": True,
                                "amount": expected_amount,
                                "execution_marker": execution_alias,
                            },
                            separators=(",", ":"),
                        ),
                    }
                ],
                "isError": False,
            },
        }
        outcome = "allow"
    else:
        error = response.get("error")
        if (
            not isinstance(error, dict)
            or error.get("code") != -32002
            or budget_id not in str(error.get("message"))
            or "Tool Execution Denied" not in str(error.get("message"))
        ):
            raise ValueError("retry-continuity deny lacks the managed policy diagnostic")
        reviewed_response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {
                "code": -32002,
                "message": (
                    "Tool Execution Denied: Tool call not allowed due to policy enforcement "
                    f"[Policy evaluation denied due to {BUDGET}]"
                ),
            },
        }
        outcome = "deny"

    return {
        "started_at": _timestamp(raw.get("started_at")),
        "finished_at": _timestamp(raw.get("finished_at")),
        "duration_ms": round(float(duration), 6),
        "http_status": raw.get("http_status"),
        "request": request,
        "request_bytes": raw["request_bytes"],
        "request_sha256": hashlib.sha256(raw["request_bytes"].encode()).hexdigest(),
        "response": reviewed_response,
        "outcome": outcome,
        "execution_alias": execution_alias,
    }


def events(raw: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    boundary = raw.get("boundary", {})
    gateway_arn = boundary.get("gateway_arn")
    engine_arn = boundary.get("engine_arn")
    principal = raw.get("principal_arn")
    policies = raw.get("policies")
    if (
        raw.get("retry_capture_raw_version") != 1
        or raw.get("region") != "us-east-1"
        or raw.get("random_seed") != 20260911
        or raw.get("trials_per_arm") != 10
        or not isinstance(gateway_arn, str)
        or not gateway_arn.startswith("arn:")
        or not isinstance(engine_arn, str)
        or not engine_arn.startswith("arn:")
        or not isinstance(principal, str)
        or not principal.startswith("arn:")
        or not isinstance(policies, list)
        or len(policies) != 2
    ):
        raise ValueError("retry-continuity capture boundary is incomplete")
    budget = next((row for row in policies if row.get("name") == "RetryCaptureBudget"), None)
    permit = next((row for row in policies if row.get("name") == "RetryCapturePermit"), None)
    if budget is None or permit is None:
        raise ValueError("retry-continuity policies are absent")
    inactive = any(
        row.get("status") != "ACTIVE" or row.get("enforcementMode") != "ACTIVE"
        for row in policies
    )
    if inactive:
        raise ValueError("retry-continuity policies are not ACTIVE")

    expected_order = ["same_id"] * 10 + ["fresh_id"] * 10
    random.Random(20260911).shuffle(expected_order)
    if raw.get("trial_order") != expected_order:
        raise ValueError("retry-continuity trial order is not the reviewed shuffle")
    trials = raw.get("trials")
    if not isinstance(trials, list) or len(trials) != 20:
        raise ValueError("retry-continuity trials are incomplete")

    marker_aliases: dict[str, str] = {}
    seen_sessions: set[str] = set()
    reviewed_trials = []
    arm_counts = {"same_id": 0, "fresh_id": 0}
    for row, expected_arm in zip(trials, expected_order, strict=True):
        arm = row.get("arm")
        session = row.get("session_id")
        raw_calls = row.get("calls")
        if (
            arm != expected_arm
            or arm not in arm_counts
            or not isinstance(session, str)
            or UUID.fullmatch(session) is None
            or session in seen_sessions
            or row.get("retry_delay_ms") != 250.0
            or not isinstance(raw_calls, list)
            or len(raw_calls) != 3
        ):
            raise ValueError("retry-continuity trial identity is invalid")
        seen_sessions.add(session)
        arm_counts[arm] += 1
        calls = [
            _call(raw_calls[0], 400, marker_aliases, budget["policyId"]),
            _call(raw_calls[1], 400, marker_aliases, budget["policyId"]),
            _call(raw_calls[2], 300, marker_aliases, budget["policyId"]),
        ]
        if [call["outcome"] for call in calls] != ["allow", "allow", "deny"]:
            raise ValueError("retry-continuity reviewed outcomes have drifted")
        first_id, retry_id, probe_id = [call["request"]["id"] for call in calls]
        if probe_id in {first_id, retry_id}:
            raise ValueError("retry-continuity probe identifier is not fresh")
        if arm == "same_id":
            if retry_id != first_id or calls[1]["request_bytes"] != calls[0]["request_bytes"]:
                raise ValueError("same-ID retransmission is not byte-identical")
        elif retry_id == first_id:
            raise ValueError("fresh-ID control reused its request identifier")
        first_without_id = {key: value for key, value in calls[0]["request"].items() if key != "id"}
        retry_without_id = {key: value for key, value in calls[1]["request"].items() if key != "id"}
        if first_without_id != retry_without_id:
            raise ValueError("retry-continuity payload changed with its identifier")
        if calls[0]["execution_alias"] == calls[1]["execution_alias"]:
            raise ValueError("retry-continuity retransmission reused an execution marker")
        reviewed_trials.append(
            {
                "arm": arm,
                "index": row.get("index"),
                "session_alias": f"{arm}-{arm_counts[arm]}",
                "retry_delay_ms": 250,
                "calls": calls,
            }
        )

    controls = raw.get("controls")
    if not isinstance(controls, list) or len(controls) != 2:
        raise ValueError("retry-continuity single-request controls are absent")
    reviewed_controls = []
    for row, amount, expected in zip(controls, (500, 1000), ("allow", "deny"), strict=True):
        call = _call(row.get("call", {}), amount, marker_aliases, budget["policyId"])
        if row.get("amount") != amount or call["outcome"] != expected:
            raise ValueError("retry-continuity single-request control failed")
        reviewed_controls.append({"amount": amount, "outcome": expected, "call": call})

    retry_contract = raw.get("retry_contract")
    if retry_contract != {
        "provider_data_plane_idempotency_token": "not documented",
        "json_rpc_id_role": "correlation identifier candidate",
        "completed_response_before_retransmission": True,
        "sdk_retries": 0,
        "transport_retries": 0,
        "fixed_retry_delay_ms": 250.0,
    }:
        raise ValueError("retry-continuity transport boundary has drifted")
    state = raw.get("provider_state")
    if state != {
        "configured_limit": 1000,
        "consumed": "unavailable",
        "remaining": "unavailable",
        "reserved": "unavailable",
        "in_flight": "unavailable",
        "completed": "unavailable",
    }:
        raise ValueError("retry-continuity provider state must retain unknown fields")

    mandate = repo_root / MANDATE
    return {
        "retry_continuity_events_version": 1,
        "provider": "AWS AgentCore Gateway Policy",
        "region": "us-east-1",
        "capture_started_at": _timestamp(raw.get("capture_started_at")),
        "capture_finished_at": _timestamp(raw.get("capture_finished_at")),
        "mandate_sha256": hashlib.sha256(mandate.read_bytes()).hexdigest(),
        "mandate_binding": "external experiment invariant; Gateway did not inspect it",
        "principal": "temporary-iam-principal",
        "gateway": GATEWAY,
        "policy_engine": ENGINE,
        "provider_session_scope": "one fresh UUID per three-call trial",
        "retry_contract": retry_contract,
        "provider_state": state,
        "random_seed": 20260911,
        "trial_order": expected_order,
        "controls": reviewed_controls,
        "trials": reviewed_trials,
    }


def deployment(raw: dict[str, Any]) -> dict[str, Any]:
    gateway = raw.get("gateway", {})
    target = raw.get("target", {})
    correction = raw.get("gateway_role_correction", {})
    versions = raw.get("versions")
    if (
        gateway.get("status") != "READY"
        or gateway.get("authorizerType") != "AWS_IAM"
        or gateway.get("protocolType") != "MCP"
        or gateway.get("exceptionLevel") != "DEBUG"
        or gateway.get("policyEngineConfiguration", {}).get("mode") != "ENFORCE"
        or target.get("status") != "READY"
        or target.get("name") != "RetryTarget"
        or raw.get("temporary_principal_after_capture") != "absent"
        or not isinstance(versions, dict)
    ):
        raise ValueError("retry-continuity deployment boundary is incomplete")
    resources = correction.get("resources")
    if (
        correction.get("action") != "bedrock-agentcore:GetWorkloadAccessToken"
        or not isinstance(resources, list)
        or len(resources) != 2
        or any(not isinstance(value, str) or not value.startswith("arn:") for value in resources)
    ):
        raise ValueError("retry-continuity workload permission is not exact")
    inventory: dict[str, int] = {}
    for row in raw.get("stack_resources", []):
        kind = row.get("resource_type")
        if not isinstance(kind, str) or row.get("status") != "CREATE_COMPLETE":
            raise ValueError("retry-continuity stack resource is incomplete")
        inventory[kind] = inventory.get(kind, 0) + 1
    expected_inventory = {
        "AWS::BedrockAgentCore::Gateway": 1,
        "AWS::BedrockAgentCore::GatewayTarget": 1,
        "AWS::BedrockAgentCore::PolicyEngine": 1,
        "AWS::CDK::Metadata": 1,
        "AWS::IAM::Policy": 1,
        "AWS::IAM::Role": 2,
        "AWS::Lambda::Function": 1,
        "AWS::Logs::LogGroup": 1,
    }
    if inventory != expected_inventory:
        raise ValueError("retry-continuity stack inventory has drifted")
    return {
        "retry_continuity_deployment_version": 1,
        "provider": "AWS AgentCore Gateway Policy",
        "region": "us-east-1",
        "versions": versions,
        "gateway": {
            "alias": "retry-continuity-gateway",
            "status": "READY",
            "authorizer": "AWS_IAM",
            "protocol": "MCP",
            "exception_level": "DEBUG",
            "policy_engine_mode": "ENFORCE",
        },
        "target": {"alias": "retry-target", "status": "READY", "type": "LAMBDA"},
        "policy_engine": {"alias": "retry-policy-engine", "status": "ACTIVE"},
        "policies": [
            {"name": "RetryCaptureBudget", "status": "ACTIVE", "enforcement_mode": "ACTIVE"},
            {"name": "RetryCapturePermit", "status": "ACTIVE", "enforcement_mode": "ACTIVE"},
        ],
        "gateway_role_correction": {
            "action": "bedrock-agentcore:GetWorkloadAccessToken",
            "resources": ["default-workload-directory", "exact-gateway-workload-identity"],
            "wildcard": False,
        },
        "stack_inventory": inventory,
        "temporary_principals_after_capture": 0,
    }


def cleanup(raw: dict[str, Any]) -> dict[str, Any]:
    checks = raw.get("checks")
    if (
        raw.get("cleanup_raw_version") != 1
        or raw.get("policies_deleted_before_engine") != 2
        or raw.get("cdk_bootstrap") != "retained"
        or not isinstance(checks, list)
        or len(checks) != 8
    ):
        raise ValueError("retry-continuity cleanup is incomplete")
    reviewed = []
    counts: dict[str, int] = {}
    for row in checks:
        kind = row.get("resource")
        outcome = row.get("outcome")
        expected_kinds = {
            "stack",
            "gateway",
            "policy_engine",
            "lambda",
            "log_group",
            "iam_role",
            "temporary_principal",
        }
        if kind not in expected_kinds:
            raise ValueError("retry-continuity cleanup resource is unknown")
        if outcome not in {"not_found", "deleted_residual"}:
            raise ValueError("retry-continuity cleanup outcome is invalid")
        counts[kind] = counts.get(kind, 0) + 1
        reviewed.append({"resource": f"{kind}-{counts[kind]}", "outcome": outcome})
    return {
        "retry_continuity_cleanup_version": 1,
        "checks": reviewed,
        "policies_deleted_before_engine": 2,
        "cdk_bootstrap": "retained",
    }


def summary(value: dict[str, Any]) -> dict[str, Any]:
    trials = value.get("trials", [])
    same = [row for row in trials if row.get("arm") == "same_id"]
    fresh = [row for row in trials if row.get("arm") == "fresh_id"]
    if len(same) != 10 or len(fresh) != 10:
        raise ValueError("retry-continuity reviewed trial counts have drifted")
    def outcomes(row: dict[str, Any]) -> list[Any]:
        return [call.get("outcome") for call in row.get("calls", [])]

    if any(outcomes(row) != ["allow", "allow", "deny"] for row in trials):
        raise ValueError("retry-continuity reviewed outcomes have drifted")
    allowed = [call for row in trials for call in row["calls"] if call["outcome"] == "allow"]
    aliases = [call["execution_alias"] for call in allowed]
    if len(aliases) != 40 or len(set(aliases)) != 40:
        raise ValueError("retry-continuity execution markers have drifted")
    return {
        "retry_continuity_summary_version": 1,
        "trials_per_arm": 10,
        "managed_requests": 62,
        "trial_allowed_target_executions": 40,
        "same_id": {
            "allow_allow_deny": 10,
            "byte_identical_retransmissions": 10,
            "distinct_second_executions": 10,
        },
        "fresh_id": {
            "allow_allow_deny": 10,
            "identifier_only_changes": 10,
            "distinct_second_executions": 10,
        },
        "conclusion": (
            "completed byte-identical retransmission with the same JSON-RPC identifier was "
            "executed and accumulated again in every reviewed trial"
        ),
        "claim_limit": (
            "completed-response retransmission only; no ambiguous timeout, interceptor retry, "
            "transport retry, or application idempotency key was tested"
        ),
    }


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index(root: Path) -> dict[str, Any]:
    return {
        "retry_continuity_index_version": 1,
        "provider": "AWS AgentCore Gateway Policy",
        "region": "us-east-1",
        "sources": [{"locator": name, "content_sha256": _digest(root / name)} for name in FILES],
    }


def project(raw_root: Path, output: Path, repo_root: Path) -> None:
    raw = _read(raw_root / "retry-capture.raw.json")
    reviewed_events = events(raw, repo_root)
    _write(output / "retry-continuity-events.json", reviewed_events)
    _write(output / "retry-continuity-deployment.json", deployment(raw))
    _write(output / "retry-continuity-summary.json", summary(reviewed_events))
    raw_cleanup = _read(raw_root / "retry-cleanup.raw.json")
    _write(output / "retry-continuity-cleanup.json", cleanup(raw_cleanup))
    gateway_arn = raw["boundary"]["gateway_arn"]
    statements = raw["policy_statements"]
    (output / "retry-continuity-budget.dogwood").write_text(
        statements["RetryCaptureBudget"].replace(gateway_arn, GATEWAY) + "\n",
        encoding="utf-8",
    )
    (output / "retry-continuity-permit.cedar").write_text(
        statements["RetryCapturePermit"].replace(gateway_arn, GATEWAY) + "\n",
        encoding="utf-8",
    )
    handler = (raw_root / "app/retry_target/handler.py").read_text(encoding="utf-8")
    if "context.aws_request_id" not in handler:
        raise ValueError("retry-continuity target lacks a per-execution marker")
    (output / "retry-continuity-lambda.py.txt").write_text(handler, encoding="utf-8")
    _write(output / "retry-continuity-index.json", _index(output))


def verify(output: Path, repo_root: Path) -> None:
    reviewed_events = _read(output / "retry-continuity-events.json")
    if hashlib.sha256((repo_root / MANDATE).read_bytes()).hexdigest() != reviewed_events.get(
        "mandate_sha256"
    ):
        raise ValueError("retry-continuity mandate digest has drifted")
    if summary(reviewed_events) != _read(output / "retry-continuity-summary.json"):
        raise ValueError("retry-continuity summary does not match its events")
    if _index(output) != _read(output / "retry-continuity-index.json"):
        raise ValueError("retry-continuity index does not match committed evidence")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_root", nargs="?", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    if args.raw_root is None:
        verify(args.output, args.repo_root)
        print("retry-continuity evidence: committed bundle verifies")
    else:
        project(args.raw_root, args.output, args.repo_root)
        verify(args.output, args.repo_root)
        print("retry-continuity evidence: live capture projected")


if __name__ == "__main__":
    main()
