from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from agentmandate._cedar import _mapping
from agentmandate._managed_cedar import ManagedOracle, compare_managed_cedar
from agentmandate.manifest import load
from agentmandate.reach import analyse

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "agentcore-refund-policy"


def read_json(name: str) -> Any:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_capture_index_pins_every_operational_artifact() -> None:
    index = read_json("capture-index.json")
    indexed = {source["locator"] for source in index["sources"]}
    committed = {
        path.name
        for path in EVIDENCE.iterdir()
        if path.is_file()
        and path.name not in {"README.md", "capture-index.json", "corrections.json"}
    }

    assert index["capture_version"] == 1
    assert index["agentcore_cli"] == {
        "package_integrity": (
            "sha512-lkgudEhogNezM0w70eGE0sW9+a9yU79X46kkBTJpFkpUjBS7pAZVqd/"
            "kz5TvXXdp9wNai4zlubuB2edQ4Od3Ag=="
        ),
        "version": "0.28.1",
    }
    assert index["mcp_protocol"] == "2025-03-26"
    assert indexed == committed
    for source in index["sources"]:
        content = (EVIDENCE / source["locator"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["content_sha256"]


def test_tool_inventory_mapping_and_manifest_are_exactly_joined() -> None:
    schema = read_json("tool-schema.json")
    listed = read_json("tools-list-response.json")["result"]["tools"]
    mapping = _mapping(read_json("mapping.json"))
    mandate = load(EVIDENCE / "mandate.yaml")

    assert [tool["name"] for tool in schema] == ["process_refund"]
    assert schema[0]["outputSchema"]["required"] == ["processed", "amount"]
    assert [tool["name"] for tool in listed] == ["RefundIamTarget___process_refund"]
    assert [(item.cedar, item.tool) for item in mapping.actions] == [
        ('AgentCore::Action::"RefundIamTarget___process_refund"', "process_refund")
    ]
    assert mandate.agent == mapping.target.agent == "refund-evidence-agent"
    assert mandate.tool_names == tuple(item.tool for item in mapping.actions)
    assert mapping.principal.cedar_types == ("AgentCore::IamEntity",)
    assert mapping.principal.mandate_principal == "caller"
    assert mapping.request_domain.completeness == "representative"
    assert mapping.request_domain.evidence.review == "accepted"
    authority = analyse(mandate)
    assert authority.reachable_tools == {"process_refund"}
    assert authority.breaches == ()


def test_live_enforce_controls_preserve_opposite_decisions() -> None:
    allow_request = read_json("allow-request.json")
    allow_response = read_json("allow-response.json")
    deny_request = read_json("deny-request.json")
    deny_response = read_json("deny-response.json")
    state = read_json("managed-state.json")

    assert allow_request["params"]["name"] == deny_request["params"]["name"]
    assert allow_request["params"]["arguments"] == {"amount": 500}
    assert deny_request["params"]["arguments"] == {"amount": 2000}
    assert allow_response["result"]["isError"] is False
    assert json.loads(allow_response["result"]["content"][0]["text"]) == {
        "amount": 500,
        "processed": True,
    }
    assert deny_response["error"]["code"] == -32002
    assert "policy enforcement" in deny_response["error"]["message"]
    assert "denied by default" in deny_response["error"]["message"]
    assert state["gateway"] == {
        "authorizer_type": "AWS_IAM",
        "policy_engine_mode": "ENFORCE",
        "protocol_type": "MCP",
        "status": "READY",
    }
    assert state["policy_engine"] == {"status": "ACTIVE"}
    assert state["policy"]["inventory_count"] == 1
    assert state["policy"]["status"] == "ACTIVE"
    assert state["policy"]["enforcement_mode"] == "ACTIVE"
    assert state["policy"]["requested_validation_mode"] == "FAIL_ON_ANY_FINDINGS"
    assert state["tool_inventory_complete"] is True


def test_live_candidate_preserves_the_boundary_and_widens_the_exact_request() -> None:
    baseline = ManagedOracle.from_json(
        (EVIDENCE / "managed-oracle-v1.json").read_text(encoding="utf-8")
    )
    candidate = ManagedOracle.from_json(
        (EVIDENCE / "candidate-managed-oracle-v1.json").read_text(encoding="utf-8")
    )

    def contents(oracle: ManagedOracle) -> dict[str, bytes]:
        return {item.locator: (EVIDENCE / item.locator).read_bytes() for item in oracle.sources}

    baseline_contents = contents(baseline)
    candidate_contents = contents(candidate)
    baseline.verify_sources(baseline_contents)
    candidate.verify_sources(candidate_contents)
    assert baseline.to_json() == (EVIDENCE / "managed-oracle-v1.json").read_text(
        encoding="utf-8"
    )
    assert candidate.to_json() == (EVIDENCE / "candidate-managed-oracle-v1.json").read_text(
        encoding="utf-8"
    )

    result = compare_managed_cedar(
        load(EVIDENCE / "mandate.yaml"),
        baseline,
        baseline_contents,
        candidate,
        candidate_contents,
        as_of=date(2026, 8, 29),
    )

    assert result.findings == ()
    assert [(item.baseline, item.candidate, item.classification) for item in result.changes] == [
        ("allow", "allow", "stable_allow"),
        ("deny", "allow", "widens"),
    ]
    assert all(len(item.support) == 6 for item in result.changes)
    assert read_json("candidate-allow-request.json") == read_json("allow-request.json")
    assert read_json("candidate-widen-request.json") == read_json("deny-request.json")
    assert read_json("candidate-tools-list-request.json") == read_json(
        "tools-list-request.json"
    )
    assert read_json("candidate-tools-list-response.json") == read_json(
        "tools-list-response.json"
    )
    widen_text = read_json("candidate-widen-response.json")["result"]["content"][0]["text"]
    assert json.loads(widen_text) == {
        "amount": 2000,
        "processed": True,
    }
    baseline_policy = (EVIDENCE / "policy.cedar").read_text(encoding="utf-8")
    candidate_policy = (EVIDENCE / "candidate-policy.cedar").read_text(encoding="utf-8")
    assert baseline_policy.replace("amount < 1000", "amount < 3000") == candidate_policy


def test_protocol_correction_is_preserved() -> None:
    refusal = read_json("protocol-refusal.json")

    assert refusal["error"]["code"] == -32600
    assert refusal["error"]["data"] == {
        "requested": "2025-11-25",
        "supported": ["2025-03-26"],
    }


def test_committed_evidence_contains_no_live_aws_identity_or_credential() -> None:
    forbidden = re.compile(
        r"(?:\b\d{12}\b|arn:aws|https://[a-z0-9-]+\.gateway\.bedrock-agentcore|"
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|eyJ[A-Za-z0-9_-]+\.|"
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})",
        re.IGNORECASE,
    )
    for path in EVIDENCE.iterdir():
        if path.is_file():
            assert forbidden.search(path.read_text(encoding="utf-8")) is None, path

    policy = (EVIDENCE / "policy.cedar").read_text(encoding="utf-8")
    state = read_json("managed-state.json")
    assert '<reviewed-gateway-binding>' in policy
    assert state["sanitization"] == {
        "decision_messages_changed": False,
        "omitted": [
            "account identifiers",
            "Amazon Resource Names",
            "generated resource identifiers",
            "resource URLs",
            "service timestamps",
        ],
        "policy_resource_replaced_with_binding": True,
    }
