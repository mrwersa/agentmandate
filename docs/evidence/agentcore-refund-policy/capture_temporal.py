"""Sanitise and verify the managed temporal-policy session experiment for issue 134."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TOOL = "TemporalTarget___process_refund"
BINDING = "agentcore-temporal-mandate-gateway"
THRESHOLD = 1000
AMOUNT = 600
ACTIVE_POLICIES = {"TemporalMandateBudgetActive", "TemporalMandatePermitActive"}
FAILED_POLICIES = {"TemporalMandateBudget", "TemporalMandatePermit"}


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
        or "Policy evaluation denied due to TemporalMandateBudgetActive-" not in message
    ):
        raise ValueError(f"{identifier}: managed outcome is not the temporal-policy deny")
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "error": {
            "code": -32002,
            "message": (
                "Tool Execution Denied: Tool call not allowed due to policy enforcement "
                "[Policy evaluation denied due to <reviewed-temporal-policy>]"
            ),
        },
    }


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
            ("gateway", "TemporalMandateGateway", "deployed"),
            ("policy-engine", "TemporalPolicyEngine", "deployed"),
        }
    ):
        raise ValueError("deployed status does not match the reviewed temporal boundary")
    deployed = status["deployedState"]["targets"]["default"]["resources"]
    gateway = deployed["mcp"]["gateways"].get("TemporalMandateGateway", {})
    if (
        set(gateway.get("targets", {})) != {"TemporalTarget"}
        or set(deployed.get("policyEngines", {})) != {"TemporalPolicyEngine"}
    ):
        raise ValueError("deployed temporal inventory is not complete")

    gateway_state = _read_json(raw_root / "gateway-state.raw")
    if (
        gateway_state.get("status") != "READY"
        or gateway_state.get("authorizerType") != "AWS_IAM"
        or gateway_state.get("protocolType") != "MCP"
        or gateway_state.get("policyEngineConfiguration", {}).get("mode") != "ENFORCE"
        or not gateway_state.get("workloadIdentityDetails", {}).get("workloadIdentityArn")
    ):
        raise ValueError("Gateway state is not eligible for temporal enforcement")

    inventory = _read_json(raw_root / "policy-inventory.raw").get("policies", [])
    active = {item["name"]: item for item in inventory if item.get("status") == "ACTIVE"}
    failed = {item["name"]: item for item in inventory if item.get("status") == "CREATE_FAILED"}
    if (
        set(active) != ACTIVE_POLICIES
        or set(failed) != FAILED_POLICIES
        or any(item.get("enforcementMode") != "ACTIVE" for item in active.values())
    ):
        raise ValueError("policy inventory does not contain the reviewed active and failed sets")
    budget_statement = active["TemporalMandateBudgetActive"]["definition"]["policy"][
        "statement"
    ]
    permit_statement = active["TemporalMandatePermitActive"]["definition"]["cedar"][
        "statement"
    ]
    if (
        "sum amt" not in budget_statement
        or "total >= 1000" not in budget_statement
        or TOOL not in budget_statement
        or TOOL not in permit_statement
    ):
        raise ValueError("active policy statements do not match the reviewed sum boundary")
    reasons = {name: " ".join(item.get("statusReasons", [])) for name, item in failed.items()}
    if (
        "Overly Restrictive" not in reasons["TemporalMandateBudget"]
        or "Overly Permissive" not in reasons["TemporalMandatePermit"]
    ):
        raise ValueError("failed authoring controls do not preserve their native findings")
    return {
        "capture_date": "2026-08-29",
        "region": "us-east-1",
        "gateway": {
            "binding": BINDING,
            "authorizer_type": "AWS_IAM",
            "policy_engine_mode": "ENFORCE",
            "protocol_type": "MCP",
            "status": "READY",
            "workload_identity_present": True,
        },
        "policy_engine": {"deployment_state": "deployed"},
        "active_policy_inventory": sorted(ACTIVE_POLICIES),
        "failed_authoring_inventory": sorted(FAILED_POLICIES),
        "tool_inventory": [TOOL],
        "sanitisation": {
            "omitted": [
                "account identifiers",
                "Amazon Resource Names",
                "generated resource identifiers",
                "resource URLs",
                "service timestamps",
                "policy session identifiers",
                "signed request headers",
            ],
            "deny_message_policy_identifier_replaced": True,
        },
    }


def _request(identifier: str, session: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": TOOL, "arguments": {"amount": AMOUNT}},
        "reviewed_header": {
            "name": "x-amzn-bedrock-agentcore-policy-session-id",
            "value_alias": session,
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


def capture(raw_root: Path, output: Path = HERE) -> dict[str, Any]:
    """Create the reviewed temporal-session fixture from temporary live outputs."""
    output.mkdir(parents=True, exist_ok=True)
    state = _validate_deployment(raw_root)
    tools = _read_json(raw_root / "tools-list.raw")
    listed = tools.get("result", {}).get("tools", [])
    if tools.get("id") != "tools-list" or [item.get("name") for item in listed] != [TOOL]:
        raise ValueError("tools/list does not establish one exact temporal tool")

    shape = _read_json(raw_root / "session-shape.raw")
    if shape != {
        "session_aliases": ["same", "fresh-a", "fresh-b"],
        "same_session_calls": ["same-first", "same-second"],
        "distinct_session_calls": ["fresh-first", "fresh-second"],
        "session_ids_generated_as": "independent UUIDv4 values retained in memory only",
    }:
        raise ValueError("session aliases do not prove the reviewed equality boundary")

    outcomes: dict[str, str] = {}
    for identifier, session, expected in (
        ("same-first", "same", "allow"),
        ("same-second", "same", "deny"),
        ("fresh-first", "fresh-a", "allow"),
        ("fresh-second", "fresh-b", "allow"),
    ):
        response = _read_json(raw_root / f"{identifier}.raw")
        reviewed = _allowed(response, identifier) if expected == "allow" else _denied(
            response, identifier
        )
        _write_json(output / f"temporal-{identifier}-request.json", _request(identifier, session))
        _write_json(output / f"temporal-{identifier}-response.json", reviewed)
        outcomes[identifier] = expected

    _write_json(output / "temporal-tools-list-response.json", tools)
    _write_json(output / "temporal-managed-state.json", state)
    (output / "temporal-policy.dogwood").write_text(
        _policy("<reviewed-gateway-binding>"), encoding="utf-8"
    )
    (output / "temporal-lambda.py.txt").write_text(
        "def handler(event, context):\n"
        "    del context\n"
        '    arguments = event.get("arguments", event)\n'
        "    return {\n"
        '        "processed": True,\n'
        '        "amount": arguments.get("amount"),\n'
        "    }\n",
        encoding="utf-8",
    )
    _write_json(
        output / "temporal-authoring-refusal.json",
        {
            "requested_validation_mode": "FAIL_ON_ANY_FINDINGS",
            "budget_policy": {"status": "CREATE_FAILED", "finding": "Overly Restrictive"},
            "permit_policy": {"status": "CREATE_FAILED", "finding": "Overly Permissive"},
            "active_recapture_validation_mode": "IGNORE_ALL_FINDINGS",
            "claim_boundary": (
                "native schema validation accepted the active policies; the failed semantic "
                "findings are preserved and no successful semantic-validation claim is made"
            ),
        },
    )
    result = {
        "temporal_session_version": 1,
        "threshold": THRESHOLD,
        "request_amount": AMOUNT,
        "same_session": {
            "session_alias": "same",
            "calls": [
                {"id": "same-first", "outcome": outcomes["same-first"]},
                {"id": "same-second", "outcome": outcomes["same-second"]},
            ],
            "attempted_aggregate": AMOUNT * 2,
            "permitted_aggregate": AMOUNT,
        },
        "fresh_sessions": {
            "session_aliases": ["fresh-a", "fresh-b"],
            "calls": [
                {"id": "fresh-first", "outcome": outcomes["fresh-first"]},
                {"id": "fresh-second", "outcome": outcomes["fresh-second"]},
            ],
            "aggregate_across_sessions": AMOUNT * 2,
        },
        "conformance": {
            "within_session_accumulation": "observed",
            "fresh_session_reset": "observed",
            "authenticated_principal_binding": "configured-not-adversarially-tested",
            "multi_hop_continuity": "documented-not-live-tested",
        },
        "finding": (
            "the managed sum is correct within one policy session, while fresh caller-selected "
            "sessions reset the technical accounting boundary"
        ),
    }
    _write_json(output / "temporal-session-result.json", result)
    locators = sorted(
        [path.name for path in output.glob("temporal-*") if path.name != "temporal-index.json"]
        + ["capture_temporal.py"]
    )
    _write_json(
        output / "temporal-index.json",
        {
            "temporal_capture_version": 1,
            "capture_date": "2026-08-29",
            "region": "us-east-1",
            "raw_retention": (
                "live identifiers, session UUIDs, resource URLs, and signed headers remained "
                "in temporary files and were deleted after reviewed projection"
            ),
            "discarded_attempts": [
                {
                    "id": "combined-statements",
                    "classification": "source ambiguity",
                    "result": "the managed create operation accepts exactly one statement",
                },
                {
                    "id": "semantic-validation",
                    "classification": "source ambiguity",
                    "result": (
                        "the separate permit and temporal forbid triggered overly permissive "
                        "and overly restrictive findings; schema-only active recapture followed"
                    ),
                },
            ],
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
                    "kind": (
                        "capture_script"
                        if locator == "capture_temporal.py"
                        else "reviewed_artifact"
                    ),
                    "locator": locator,
                    "content_sha256": _sha256(
                        (HERE if locator == "capture_temporal.py" else output) / locator
                    ),
                }
                for locator in locators
            ],
        },
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args(argv)
    capture(args.raw_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
