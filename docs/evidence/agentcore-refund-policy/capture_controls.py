"""Sanitize and verify the managed policy controls captured for issue 132.

The raw root contains signed MCP responses and AgentCore status snapshots with
live identifiers.  This script validates those observations, emits only the
reviewed logical binding, and proves the resulting managed-oracle records with
the same private comparator used by the public Cedar diff command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from agentmandate._managed_cedar import ManagedOracle, compare_managed_cedar
from agentmandate.manifest import load

HERE = Path(__file__).resolve().parent
TOOL = "PaperControlTarget___process_refund"
BINDING = "agentcore-policy-control-gateway"
OMITTED = [
    "account identifiers",
    "Amazon Resource Names",
    "generated resource identifiers",
    "resource URLs",
    "service timestamps",
]
REVISIONS = {
    "baseline": {
        "policy": "PaperBaselinePolicy",
        "condition": "context.input.amount < 1000",
        "outcomes": {500: "allow", 2000: "deny"},
    },
    "noop": {
        "policy": "PaperNoOpPolicy",
        "condition": "context.input.amount < 1000 && true",
        "outcomes": {500: "allow", 2000: "deny"},
    },
    "narrow": {
        "policy": "PaperNarrowPolicy",
        "condition": "context.input.amount < 400",
        "outcomes": {500: "deny", 2000: "deny"},
    },
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kind(locator: str) -> str:
    if locator == "capture_controls.py":
        return "capture_script"
    if "managed-oracle" in locator:
        return "managed_oracle"
    if locator.endswith("-request.json"):
        return "request"
    if locator.endswith("-response.json"):
        return "managed_response"
    if locator.endswith("-policy.cedar"):
        return "policy"
    if locator.endswith("-state.json"):
        return "reviewed_managed_state"
    return "reviewed_artifact"


def _status(raw_root: Path, revision: str, policy: str) -> None:
    status = _read_json(raw_root / f"agentmandate-paper-{revision}-status.raw")
    resources = {
        (item.get("resourceType"), item.get("name"), item.get("deploymentState"))
        for item in status.get("resources", [])
    }
    expected = {
        ("gateway", "PaperControlGateway", "deployed"),
        ("policy-engine", "PaperControlEngine", "deployed"),
        ("policy", policy, "deployed"),
    }
    if (
        status.get("success") is not True
        or status.get("projectName") != "AuthorityControls"
        or status.get("targetRegion") != "us-east-1"
        or resources != expected
    ):
        raise ValueError(f"{revision}: deployed status does not match the reviewed boundary")
    deployed = status["deployedState"]["targets"]["default"]["resources"]
    if (
        set(deployed["mcp"]["gateways"]) != {"PaperControlGateway"}
        or set(deployed["mcp"]["gateways"]["PaperControlGateway"]["targets"])
        != {"PaperControlTarget"}
        or set(deployed["policyEngines"]) != {"PaperControlEngine"}
        or set(deployed["policies"]) != {f"PaperControlEngine/{policy}"}
    ):
        raise ValueError(f"{revision}: deployed inventory is not complete")


def _response(raw_root: Path, name: str, expected_id: str, outcome: str) -> dict[str, Any]:
    response = _read_json(raw_root / name)
    if response.get("jsonrpc") != "2.0" or response.get("id") != expected_id:
        raise ValueError(f"{name}: response does not match the request")
    allowed = (
        isinstance(response.get("result"), dict)
        and response["result"].get("isError") is False
        and response.get("error") is None
    )
    error = response.get("error")
    denied = (
        isinstance(error, dict)
        and error.get("code") == -32002
        and "denied by default" in str(error.get("message", "")).lower()
    )
    if (outcome == "allow" and not allowed) or (outcome == "deny" and not denied):
        raise ValueError(f"{name}: managed outcome is not {outcome}")
    return response


def _request(identifier: str, amount: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": TOOL, "arguments": {"amount": amount}},
    }


def _policy(condition: str) -> str:
    return (
        "permit(\n"
        "  principal is AgentCore::IamEntity,\n"
        f'  action == AgentCore::Action::"{TOOL}",\n'
        '  resource == AgentCore::Gateway::"<reviewed-gateway-binding>"\n'
        ")\n"
        f"when {{ {condition} }};\n"
    )


def _mapping() -> dict[str, Any]:
    return {
        "mapping_version": 1,
        "source": "controls-mapping.json",
        "target": {"source": "controls-mandate.yaml", "agent": "policy-control-agent"},
        "principal": {
            "cedar_types": ["AgentCore::IamEntity"],
            "mandate_principal": "caller",
        },
        "actions": [{"cedar": f'AgentCore::Action::"{TOOL}"', "tool": "process_refund"}],
        "resources": [{"cedar_type": "AgentCore::Gateway", "binding": BINDING}],
        "request_domain": {
            "completeness": "representative",
            "evidence": {
                "confidence": "exact",
                "review": "accepted",
                "reviewer": "paper-study-review",
                "expires": "2027-08-29",
            },
        },
    }


def _managed_state(policy: str) -> dict[str, Any]:
    return {
        "capture_date": "2026-08-29",
        "gateway": {
            "authorizer_type": "AWS_IAM",
            "policy_engine_mode": "ENFORCE",
            "protocol_type": "MCP",
            "status": "READY",
        },
        "policy": {
            "enforcement_mode": "ACTIVE",
            "inventory_count": 1,
            "name": policy,
            "requested_validation_mode": "FAIL_ON_ANY_FINDINGS",
            "status": "ACTIVE",
        },
        "policy_engine": {"status": "ACTIVE"},
        "sanitization": {
            "omitted": OMITTED,
            "decision_messages_changed": False,
            "policy_resource_replaced_with_binding": True,
        },
        "tool_inventory_complete": True,
    }


def _oracle(output: Path, revision: str, policy: str, outcomes: dict[int, str]) -> ManagedOracle:
    decisions = []
    for amount in sorted(outcomes):
        identifier = f"{revision}-{amount}"
        outcome = outcomes[amount]
        decisions.append(
            {
                "id": identifier,
                "request": f"controls-{identifier}-request.json",
                "response": f"controls-{identifier}-response.json",
                "outcome": outcome,
                "reason": "managed_allow" if outcome == "allow" else "default_deny",
                "method": "tools/call",
                "tool": TOOL,
                "arguments": {"amount": amount},
            }
        )
    locators = {
        "controls-tools-list-request.json": "tool_inventory_request",
        "controls-tools-list-response.json": "tool_inventory_response",
        "controls-tool-schema.json": "tool_schema",
        "controls-mandate.yaml": "manifest",
        "controls-mapping.json": "deployment_mapping",
        "lambda.py.txt": "handler_source",
        f"controls-{revision}-state.json": "managed_state",
        f"controls-{revision}-policy.cedar": "policy",
    }
    for item in decisions:
        locators[item["request"]] = "decision_request"
        locators[item["response"]] = "decision_response"
    sources = [
        {
            "kind": kind,
            "locator": locator,
            "content_sha256": _sha256(output / locator),
        }
        for locator, kind in sorted(locators.items())
    ]
    mapping = _mapping()
    payload = {
        "managed_oracle_version": 1,
        "provider": {
            "name": "aws-agentcore",
            "region": "us-east-1",
            "protocol": "MCP",
            "protocol_version": "2025-03-26",
        },
        "adapter": {"name": "agentmandate.agentcore-managed-capture", "version": 1},
        "capture_date": "2026-08-29",
        "sources": sources,
        "state": {
            "authorizer_type": "AWS_IAM",
            "gateway_status": "READY",
            "policy_engine_status": "ACTIVE",
            "policy_engine_mode": "ENFORCE",
            "requested_validation_mode": "FAIL_ON_ANY_FINDINGS",
            "source": f"controls-{revision}-state.json",
        },
        "tool_inventory": {
            "complete": True,
            "members": [TOOL],
            "source": "controls-tools-list-response.json",
        },
        "policy_inventory": {
            "complete": True,
            "members": [{"name": policy, "status": "ACTIVE", "enforcement_mode": "ACTIVE"}],
            "source": f"controls-{revision}-state.json",
        },
        "mapping": mapping,
        "decisions": decisions,
        "sanitization": {
            "source": f"controls-{revision}-state.json",
            "omitted": OMITTED,
            "decision_messages_changed": False,
            "aliases": [
                {
                    "cedar_type": "AgentCore::Gateway",
                    "binding": BINDING,
                    "placeholder": "<reviewed-gateway-binding>",
                }
            ],
        },
    }
    return ManagedOracle.from_json(json.dumps(payload))


def capture(raw_root: Path, output: Path = HERE) -> dict[str, Any]:
    """Create reviewed control artifacts and return their verified outcomes."""
    output.mkdir(parents=True, exist_ok=True)
    tools = _read_json(raw_root / "agentmandate-paper-controls-tools-list.raw")
    listed = tools.get("result", {}).get("tools", [])
    if tools.get("id") != "tools-list" or [item.get("name") for item in listed] != [TOOL]:
        raise ValueError("tools/list does not establish one exact tool")
    schema = _read_json(HERE / "tool-schema.json")
    _write_json(output / "controls-tool-schema.json", schema)
    (output / "lambda.py.txt").write_bytes((HERE / "lambda.py.txt").read_bytes())
    _write_json(output / "controls-tools-list-request.json", {
        "jsonrpc": "2.0", "id": "tools-list", "method": "tools/list", "params": {}
    })
    _write_json(output / "controls-tools-list-response.json", tools)
    (output / "controls-mandate.yaml").write_text(
        "version: 1\nagent: policy-control-agent\ntools:\n"
        "  - name: process_refund\n    effect: read\n    principal: caller\n"
        "    requires: []\n    requires_approval: false\n    unbounded: false\n",
        encoding="utf-8",
    )
    _write_json(output / "controls-mapping.json", _mapping())

    oracles = {}
    for revision, spec in REVISIONS.items():
        _status(raw_root, revision, spec["policy"])
        (output / f"controls-{revision}-policy.cedar").write_text(
            _policy(spec["condition"]), encoding="utf-8"
        )
        _write_json(output / f"controls-{revision}-state.json", _managed_state(spec["policy"]))
        for amount, outcome in spec["outcomes"].items():
            identifier = f"{revision}-{amount}"
            _write_json(
                output / f"controls-{identifier}-request.json",
                _request(identifier, amount),
            )
            response = _response(
                raw_root,
                f"agentmandate-paper-{revision}-{amount}.raw",
                identifier,
                outcome,
            )
            _write_json(output / f"controls-{identifier}-response.json", response)
        oracle = _oracle(output, revision, spec["policy"], spec["outcomes"])
        contents = {item.locator: (output / item.locator).read_bytes() for item in oracle.sources}
        oracle.verify_sources(contents)
        (output / f"controls-{revision}-managed-oracle-v1.json").write_text(
            oracle.to_json(), encoding="utf-8"
        )
        oracles[revision] = (oracle, contents)

    sequence_calls = []
    for suffix in ("a", "b"):
        identifier = f"sequence-600-{suffix}"
        request = _request(identifier, 600)
        response = _response(
            raw_root,
            f"agentmandate-paper-sequence-600-{suffix}.raw",
            identifier,
            "allow",
        )
        _write_json(output / f"controls-{identifier}-request.json", request)
        _write_json(output / f"controls-{identifier}-response.json", response)
        sequence_calls.append({"id": identifier, "amount": 600, "outcome": "allow"})
    sequence = {
        "sequence_version": 1,
        "policy_revision": "PaperBaselinePolicy",
        "per_request_threshold": 1000,
        "calls": sequence_calls,
        "aggregate_amount": 1200,
        "claim_boundary": (
            "the managed policy enforces each request; it does not claim cumulative accounting"
        ),
    }
    _write_json(output / "controls-permitted-sequence.json", sequence)

    mandate = load(output / "controls-mandate.yaml")
    comparisons = {}
    for candidate in ("noop", "narrow"):
        result = compare_managed_cedar(
            mandate,
            oracles["baseline"][0],
            oracles["baseline"][1],
            oracles[candidate][0],
            oracles[candidate][1],
            as_of=date(2026, 8, 29),
        )
        if result.findings:
            raise ValueError(f"{candidate}: comparison is not trusted")
        comparisons[candidate] = [item.classification for item in result.changes]
    expected = {
        "noop": ["stable_deny", "stable_allow"],
        "narrow": ["stable_deny", "tightens"],
    }
    if comparisons != expected:
        raise ValueError("managed controls do not reproduce their expected classifications")
    result = {
        "controls_version": 1,
        "comparisons": comparisons,
        "sequence": sequence,
        "status_proof": (
            "each raw AgentCore status contained exactly one deployed gateway, target, engine, "
            "and policy; managed responses prove the configured policy was enforcing"
        ),
    }
    _write_json(output / "controls-result.json", result)
    locators = sorted(
        [path.name for path in output.glob("controls-*") if path.name != "controls-index.json"]
        + ["capture_controls.py"]
    )
    index = {
        "controls_capture_version": 1,
        "capture_date": "2026-08-29",
        "region": "us-east-1",
        "raw_retention": (
            "live identifiers remained in temporary status and deployment outputs and were "
            "deleted after reviewed projection"
        ),
        "discarded_attempts": [
            {
                "id": "comment-noop",
                "classification": "extractor defect",
                "result": (
                    "native validation rejected a literal backslash-n before policy activation; "
                    "no managed decision was captured from that attempt"
                ),
            }
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
                "kind": _kind(locator),
                "locator": locator,
                "content_sha256": _sha256(
                    (HERE if locator == "capture_controls.py" else output) / locator
                ),
            }
            for locator in locators
        ],
    }
    _write_json(output / "controls-index.json", index)
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
