"""Sanitise and verify the live mandate-binding evaluation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mandate_binding import BindingError, verify_and_derive

HERE = Path(__file__).resolve().parent
TOOL = "TemporalBindingTarget___process_refund"
AMOUNT = 600
THRESHOLD = 1000
POLICIES = {"TemporalBindingBudget", "TemporalBindingPermit"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _allowed(response: dict[str, Any], identifier: str) -> dict[str, Any]:
    if response.get("jsonrpc") != "2.0" or response.get("id") != identifier:
        raise ValueError(f"{identifier}: response does not match the reviewed request")
    result = response.get("result")
    if not isinstance(result, dict) or result.get("isError") is not False:
        raise ValueError(f"{identifier}: managed outcome is not allow")
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise ValueError(f"{identifier}: managed result shape is not exact")
    payload = json.loads(content[0].get("text", ""))
    if payload != {"processed": True, "amount": AMOUNT}:
        raise ValueError(f"{identifier}: Lambda result does not match the request")
    return response


def _denied(response: dict[str, Any], identifier: str) -> dict[str, Any]:
    if response.get("jsonrpc") != "2.0" or response.get("id") != identifier:
        raise ValueError(f"{identifier}: response does not match the reviewed request")
    error = response.get("error")
    message = error.get("message", "") if isinstance(error, dict) else ""
    if (
        not isinstance(error, dict)
        or error.get("code") != -32002
        or "Policy evaluation denied due to TemporalBindingBudget-" not in message
    ):
        raise ValueError(f"{identifier}: managed outcome is not the temporal-policy deny")
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {
            "code": -32002,
            "message": (
                "Tool Execution Denied: Tool call not allowed due to policy enforcement "
                "[Policy evaluation denied due to <reviewed-binding-policy>]"
            ),
        },
    }


def _request(identifier: str, mandate_alias: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": TOOL, "arguments": {"amount": AMOUNT}},
        "reviewed_binding": {
            "mandate_alias": mandate_alias,
            "session_identifier": "derived-after-signature-verification-not-retained",
        },
    }


def _policy(resource: str) -> str:
    return (
        "forbid (\n"
        "  principal is AgentCore::IamEntity,\n"
        f'  action == AgentCore::Action::"{TOOL}",\n'
        f'  resource == AgentCore::Gateway::"{resource}"\n'
        ")\n"
        "when temporal {\n"
        "  exists (total: Long).\n"
        "    (sum amt for (amt: Long), (t: Timepoint).\n"
        f'      where (formerly within 1h (AgentCore::Action::"{TOOL}"::request{{\n'
        "        eventResource: resource, input.amount: amt\n"
        "      } && tp(t)))) == total\n"
        f"    && total >= {THRESHOLD}\n"
        "};\n"
    )


def _validate_deployment(raw_root: Path) -> dict[str, Any]:
    status = _read_json(raw_root / "deployment-status.raw")
    resources = {
        (item.get("resourceType"), item.get("name"), item.get("deploymentState"))
        for item in status.get("resources", [])
    }
    if (
        status.get("success") is not True
        or status.get("projectName") != "TemporalMandate"
        or status.get("targetRegion") != "us-east-1"
        or resources
        != {
            ("gateway", "TemporalBindingGateway", "deployed"),
            ("policy-engine", "TemporalBindingPolicyEngine", "deployed"),
            ("policy", "TemporalBindingBudget", "deployed"),
            ("policy", "TemporalBindingPermit", "deployed"),
        }
    ):
        raise ValueError("deployment does not match the reviewed binding boundary")
    gateway = _read_json(raw_root / "gateway-state.raw")
    if (
        gateway.get("status") != "READY"
        or gateway.get("authorizerType") != "AWS_IAM"
        or gateway.get("protocolType") != "MCP"
        or gateway.get("policyEngineConfiguration", {}).get("mode") != "ENFORCE"
        or not gateway.get("workloadIdentityDetails", {}).get("workloadIdentityArn")
    ):
        raise ValueError("Gateway is not eligible for the binding evaluation")
    inventory = _read_json(raw_root / "policy-inventory.raw").get("policies", [])
    active = {item.get("name"): item for item in inventory if item.get("status") == "ACTIVE"}
    if set(active) != POLICIES or any(
        item.get("enforcementMode") != "ACTIVE" for item in active.values()
    ):
        raise ValueError("policy inventory is not the exact active pair")
    statements = {
        name: item.get("definition", {}).get("policy", {}).get("statement", "")
        for name, item in active.items()
    }
    if (
        TOOL not in statements["TemporalBindingPermit"]
        or "sum amt" not in statements["TemporalBindingBudget"]
        or "total >= 1000" not in statements["TemporalBindingBudget"]
    ):
        raise ValueError("policy statements do not match the reviewed binding boundary")
    return {
        "capture_date": "2026-08-29",
        "region": "us-east-1",
        "gateway": {
            "binding": "agentcore-temporal-bound-mandate-gateway",
            "authorizer_type": "AWS_IAM",
            "policy_engine_mode": "ENFORCE",
            "protocol_type": "MCP",
            "status": "READY",
            "workload_identity_present": True,
        },
        "active_policy_inventory": sorted(POLICIES),
        "tool_inventory": [TOOL],
        "sanitisation": {
            "omitted": [
                "account identifiers",
                "Amazon Resource Names",
                "generated resource identifiers",
                "resource URLs",
                "service timestamps",
                "derived policy session identifiers",
                "signed request headers",
            ],
            "deny_message_policy_identifier_replaced": True,
        },
    }


def capture(raw_root: Path, output: Path = HERE) -> dict[str, Any]:
    """Create the reviewed binding fixture from temporary live outputs."""
    output.mkdir(parents=True, exist_ok=True)
    state = _validate_deployment(raw_root)
    tools = _read_json(raw_root / "tools-list.raw")
    listed = tools.get("result", {}).get("tools", [])
    if tools.get("id") != "binding-tools-list" or [item.get("name") for item in listed] != [TOOL]:
        raise ValueError("tools/list does not establish one exact binding tool")

    public_key = (raw_root / "binding-public.raw").read_bytes()
    binding_a = _read_json(raw_root / "binding-a.raw")
    binding_b = _read_json(raw_root / "binding-b.raw")
    as_of = datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc)
    session_a_first = verify_and_derive(
        binding_a, public_key, as_of=as_of, expected_principal="caller"
    )
    session_a_second = verify_and_derive(
        binding_a, public_key, as_of=as_of, expected_principal="caller"
    )
    session_b = verify_and_derive(
        binding_b, public_key, as_of=as_of, expected_principal="caller"
    )
    if session_a_first != session_a_second or session_a_first == session_b:
        raise ValueError("binding derivation does not establish continuity and isolation")

    tampered = dict(binding_a)
    tampered["mandate_sha256"] = "0" * 64
    rejections = []
    for name, binding, evaluation_time in (
        ("tampered-binding", tampered, as_of),
        ("expired-binding", binding_a, datetime(2026, 8, 30, tzinfo=timezone.utc)),
    ):
        try:
            verify_and_derive(
                binding,
                public_key,
                as_of=evaluation_time,
                expected_principal="caller",
            )
        except BindingError as error:
            rejections.append(
                {"case": name, "result": "rejected-before-network", "reason": str(error)}
            )
        else:
            raise ValueError(f"{name} did not fail closed")

    responses = {
        "bound-first": _allowed(_read_json(raw_root / "bound-first.raw"), "bound-first"),
        "bound-second": _denied(_read_json(raw_root / "bound-second.raw"), "bound-second"),
        "isolated-first": _allowed(
            _read_json(raw_root / "isolated-first.raw"), "isolated-first"
        ),
    }
    for identifier, mandate_alias in (
        ("bound-first", "mandate-a"),
        ("bound-second", "mandate-a"),
        ("isolated-first", "mandate-b"),
    ):
        _write_json(
            output / f"binding-{identifier}-request.json",
            _request(identifier, mandate_alias),
        )
        _write_json(output / f"binding-{identifier}-response.json", responses[identifier])

    (output / "binding-public-key.pem").write_bytes(public_key)
    _write_json(output / "mandate-binding.json", binding_a)
    _write_json(output / "isolation-binding.json", binding_b)
    _write_json(output / "binding-managed-state.json", state)
    _write_json(output / "binding-tools-list-response.json", tools)
    _write_json(
        output / "binding-local-rejections.json",
        {"network_requests": 0, "cases": rejections},
    )
    benchmark = _read_json(raw_root / "benchmark.raw")
    if (
        benchmark.get("binding_benchmark_version") != 1
        or benchmark.get("repetitions") != 200
        or not isinstance(benchmark.get("median_ms"), (int, float))
    ):
        raise ValueError("binding benchmark does not match the reviewed measurement")
    _write_json(output / "binding-benchmark.json", benchmark)
    preflight = _read_json(raw_root / "preflight-failure.raw")
    debug = preflight.get("result", {}).get("_meta", {}).get("debug", {}).get("text", "")
    if (
        preflight.get("result", {}).get("isError") is not True
        or "bedrock-agentcore:GetWorkloadAccessToken" not in debug
        or "not authorized to perform" not in debug
    ):
        raise ValueError("preflight failure does not establish the corrected workload permission")
    _write_json(
        output / "binding-deployment-correction.json",
        {
            "classification": "deployment policy",
            "initial_result": "Gateway target returned an internal error before execution",
            "diagnosis": (
                "the generated Gateway role lacked the workload-token permission required "
                "for policy-session evaluation"
            ),
            "correction": (
                "add GetWorkloadAccessToken for the default directory and this Gateway's "
                "workload identity only"
            ),
            "evidence_boundary": "the failed call is excluded from the evaluated sequence",
        },
    )
    (output / "binding-policy.dogwood").write_text(
        _policy("<reviewed-gateway-binding>"), encoding="utf-8"
    )

    result = {
        "mandate_binding_evaluation_version": 1,
        "scheme": (
            "Ed25519 signature over canonical binding fields; "
            "UUID-shaped session from SHA-256"
        ),
        "threshold": THRESHOLD,
        "request_amount": AMOUNT,
        "same_signed_mandate": {
            "separate_client_processes": 2,
            "derived_session_ids_equal": True,
            "calls": [
                {"id": "bound-first", "outcome": "allow"},
                {"id": "bound-second", "outcome": "deny"},
            ],
        },
        "different_signed_mandate": {
            "derived_session_id_distinct": True,
            "calls": [{"id": "isolated-first", "outcome": "allow"}],
        },
        "local_controls": rejections,
        "median_adapter_ms": benchmark["median_ms"],
        "claim_boundary": (
            "the trusted adapter held the Gateway credential and verified the binding before "
            "deriving the session; the managed Gateway did not verify the binding itself"
        ),
    }
    _write_json(output / "mandate-binding-result.json", result)
    locators = sorted(
        [path.name for path in output.glob("binding-*") if path.name != "binding-index.json"]
        + ["mandate-binding.json", "isolation-binding.json", "mandate-binding-result.json"]
        + ["capture_binding.py", "mandate_binding.py", "benchmark_binding.py"]
    )
    _write_json(
        output / "binding-index.json",
        {
            "binding_capture_version": 1,
            "capture_date": "2026-08-29",
            "region": "us-east-1",
            "raw_retention": (
                "live identifiers, derived session IDs, resource URLs, and signed request "
                "headers remained in temporary files and were deleted after projection"
            ),
            "cleanup": {
                "gateway": "absent",
                "policy_engine": "absent",
                "lambda": "absent",
                "iam_role": "absent",
                "log_group": "absent",
                "cdk_bootstrap": "retained",
            },
            "sources": [
                {
                    "kind": "capture_script" if locator.endswith(".py") else "reviewed_artifact",
                    "locator": locator,
                    "content_sha256": _sha256(
                        (HERE if locator.endswith(".py") else output) / locator
                    ),
                }
                for locator in locators
            ],
        },
    )
    return result
