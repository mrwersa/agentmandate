from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from agentmandate._cedar import _mapping
from agentmandate._managed_cedar import ManagedOracle, compare_managed_cedar
from agentmandate.manifest import load
from agentmandate.reach import analyse

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "agentcore-refund-policy"

_spec = importlib.util.spec_from_file_location(
    "measure_analysis", EVIDENCE / "measure_analysis.py"
)
assert _spec is not None and _spec.loader is not None
measure_analysis = importlib.util.module_from_spec(_spec)
sys.modules["measure_analysis"] = measure_analysis
_spec.loader.exec_module(measure_analysis)

_controls_spec = importlib.util.spec_from_file_location(
    "capture_controls", EVIDENCE / "capture_controls.py"
)
assert _controls_spec is not None and _controls_spec.loader is not None
capture_controls = importlib.util.module_from_spec(_controls_spec)
sys.modules["capture_controls"] = capture_controls
_controls_spec.loader.exec_module(capture_controls)

_temporal_spec = importlib.util.spec_from_file_location(
    "capture_temporal", EVIDENCE / "capture_temporal.py"
)
assert _temporal_spec is not None and _temporal_spec.loader is not None
capture_temporal = importlib.util.module_from_spec(_temporal_spec)
sys.modules["capture_temporal"] = capture_temporal
_temporal_spec.loader.exec_module(capture_temporal)

_binding_spec = importlib.util.spec_from_file_location(
    "mandate_binding", EVIDENCE / "mandate_binding.py"
)
assert _binding_spec is not None and _binding_spec.loader is not None
mandate_binding = importlib.util.module_from_spec(_binding_spec)
sys.modules["mandate_binding"] = mandate_binding
_binding_spec.loader.exec_module(mandate_binding)

_binding_capture_spec = importlib.util.spec_from_file_location(
    "capture_binding", EVIDENCE / "capture_binding.py"
)
assert _binding_capture_spec is not None and _binding_capture_spec.loader is not None
capture_binding = importlib.util.module_from_spec(_binding_capture_spec)
sys.modules["capture_binding"] = capture_binding
_binding_capture_spec.loader.exec_module(capture_binding)


def read_json(name: str) -> Any:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_capture_index_pins_every_operational_artifact() -> None:
    index = read_json("capture-index.json")
    indexed = {source["locator"] for source in index["sources"]}
    controls_index = read_json("controls-index.json")
    controls_indexed = {source["locator"] for source in controls_index["sources"]}
    temporal_index = read_json("temporal-index.json")
    temporal_indexed = {source["locator"] for source in temporal_index["sources"]}
    binding_index = read_json("binding-index.json")
    binding_indexed = {source["locator"] for source in binding_index["sources"]}
    committed = {
        path.name
        for path in EVIDENCE.iterdir()
        if path.is_file()
        and path.name
        not in {
            "README.md",
            "capture-index.json",
            "binding-index.json",
            "controls-index.json",
            "corrections.json",
            "temporal-index.json",
        }
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
    assert indexed.isdisjoint(controls_indexed)
    assert indexed.isdisjoint(temporal_indexed)
    assert controls_indexed.isdisjoint(temporal_indexed)
    assert binding_indexed.isdisjoint(indexed | controls_indexed | temporal_indexed)
    assert indexed | controls_indexed | temporal_indexed | binding_indexed == committed
    for source in (
        *index["sources"],
        *controls_index["sources"],
        *temporal_index["sources"],
        *binding_index["sources"],
    ):
        content = (EVIDENCE / source["locator"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == source["content_sha256"]
    assert controls_index["cleanup"] == {
        "cdk_bootstrap": "retained",
        "gateway": "absent",
        "iam_role": "absent",
        "lambda": "absent",
        "log_group": "absent",
        "policy_engine": "absent",
    }
    assert temporal_index["cleanup"] == controls_index["cleanup"]
    assert binding_index["cleanup"] == controls_index["cleanup"]


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


def test_analysis_measurement_reproduces_the_widening_result(tmp_path: Path) -> None:
    result = measure_analysis.measure(warmups=0, repetitions=1, measured_at="2026-08-29T00:00:00Z")

    assert result["counterexample_length"] == 1
    assert result["analysis_wall_clock_ms"] > 0
    assert result["samples"]["repetitions"] == 1
    assert result["result"] == {
        "classifications": ["stable_allow", "widens"],
        "finding_count": 0,
    }
    output = tmp_path / "measurement.json"
    assert (
        measure_analysis.main(
            [
                "--warmups",
                "0",
                "--repetitions",
                "1",
                "--measured-at",
                "2026-08-29T00:00:00Z",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["measurement_version"] == 1


def test_analysis_measurement_rejects_invalid_sample_counts() -> None:
    for warmups, repetitions in ((-1, 1), (0, 0)):
        with pytest.raises(ValueError, match="warmups must be non-negative"):
            measure_analysis.measure(
                warmups=warmups,
                repetitions=repetitions,
                measured_at="2026-08-29T00:00:00Z",
            )


def _write_control_raw(root: Path) -> None:
    (root / "agentmandate-paper-controls-tools-list.raw").write_bytes(
        (EVIDENCE / "controls-tools-list-response.json").read_bytes()
    )
    policies = {
        "baseline": "PaperBaselinePolicy",
        "noop": "PaperNoOpPolicy",
        "narrow": "PaperNarrowPolicy",
    }
    for revision, policy in policies.items():
        status = {
            "success": True,
            "projectName": "AuthorityControls",
            "targetRegion": "us-east-1",
            "resources": [
                {
                    "resourceType": "gateway",
                    "name": "PaperControlGateway",
                    "deploymentState": "deployed",
                },
                {
                    "resourceType": "policy-engine",
                    "name": "PaperControlEngine",
                    "deploymentState": "deployed",
                },
                {"resourceType": "policy", "name": policy, "deploymentState": "deployed"},
            ],
            "deployedState": {
                "targets": {
                    "default": {
                        "resources": {
                            "mcp": {
                                "gateways": {
                                    "PaperControlGateway": {
                                        "targets": {"PaperControlTarget": {"targetId": "raw-only"}}
                                    }
                                }
                            },
                            "policyEngines": {"PaperControlEngine": {}},
                            "policies": {f"PaperControlEngine/{policy}": {}},
                        }
                    }
                }
            },
        }
        (root / f"agentmandate-paper-{revision}-status.raw").write_text(
            json.dumps(status), encoding="utf-8"
        )
        for amount in (500, 2000):
            (root / f"agentmandate-paper-{revision}-{amount}.raw").write_bytes(
                (EVIDENCE / f"controls-{revision}-{amount}-response.json").read_bytes()
            )
    for suffix in ("a", "b"):
        (root / f"agentmandate-paper-sequence-600-{suffix}.raw").write_bytes(
            (EVIDENCE / f"controls-sequence-600-{suffix}-response.json").read_bytes()
        )


def test_managed_controls_regenerate_and_prove_negative_controls(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "output"
    raw.mkdir()
    _write_control_raw(raw)

    result = capture_controls.capture(raw, output)

    assert result["comparisons"] == {
        "noop": ["stable_deny", "stable_allow"],
        "narrow": ["stable_deny", "tightens"],
    }
    assert result["sequence"]["aggregate_amount"] == 1200
    assert all(item["outcome"] == "allow" for item in result["sequence"]["calls"])
    index = json.loads((output / "controls-index.json").read_text(encoding="utf-8"))
    for source in index["sources"]:
        if source["locator"] != "capture_controls.py":
            assert (output / source["locator"]).read_bytes() == (
                EVIDENCE / source["locator"]
            ).read_bytes()


def test_managed_control_capture_rejects_wrong_outcomes_and_inventory(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_control_raw(raw)
    response = json.loads((raw / "agentmandate-paper-noop-500.raw").read_text(encoding="utf-8"))
    response["id"] = "wrong"
    (raw / "agentmandate-paper-noop-500.raw").write_text(
        json.dumps(response), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="response does not match"):
        capture_controls.capture(raw, tmp_path / "bad-response")

    _write_control_raw(raw)
    status_path = raw / "agentmandate-paper-narrow-status.raw"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["resources"].pop()
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed boundary"):
        capture_controls.capture(raw, tmp_path / "bad-status")


def _write_temporal_raw(root: Path) -> None:
    status = {
        "success": True,
        "projectName": "TemporalMandate",
        "targetRegion": "us-east-1",
        "resources": [
            {
                "resourceType": "gateway",
                "name": "TemporalMandateGateway",
                "deploymentState": "deployed",
            },
            {
                "resourceType": "policy-engine",
                "name": "TemporalPolicyEngine",
                "deploymentState": "deployed",
            },
        ],
        "deployedState": {
            "targets": {
                "default": {
                    "resources": {
                        "mcp": {
                            "gateways": {
                                "TemporalMandateGateway": {
                                    "targets": {"TemporalTarget": {"targetId": "raw-only"}}
                                }
                            }
                        },
                        "policyEngines": {"TemporalPolicyEngine": {}},
                    }
                }
            }
        },
    }
    (root / "deployment-status.raw").write_text(json.dumps(status), encoding="utf-8")
    gateway = {
        "status": "READY",
        "authorizerType": "AWS_IAM",
        "protocolType": "MCP",
        "policyEngineConfiguration": {"mode": "ENFORCE"},
        "workloadIdentityDetails": {"workloadIdentityArn": "raw-only"},
    }
    (root / "gateway-state.raw").write_text(json.dumps(gateway), encoding="utf-8")
    resource = 'AgentCore::Gateway::"raw-only"'
    tool = "TemporalTarget___process_refund"
    policies = {
        "policies": [
            {
                "name": "TemporalMandateBudgetActive",
                "status": "ACTIVE",
                "enforcementMode": "ACTIVE",
                "definition": {
                    "policy": {
                        "statement": (
                            f'forbid (action == AgentCore::Action::"{tool}", resource == '
                            f"{resource}) when temporal {{ sum amt; total >= 1000 }};"
                        )
                    }
                },
            },
            {
                "name": "TemporalMandatePermitActive",
                "status": "ACTIVE",
                "enforcementMode": "ACTIVE",
                "definition": {
                    "cedar": {
                        "statement": (
                            f'permit (action == AgentCore::Action::"{tool}", resource == '
                            f"{resource});"
                        )
                    }
                },
            },
            {
                "name": "TemporalMandateBudget",
                "status": "CREATE_FAILED",
                "statusReasons": ["Overly Restrictive"],
            },
            {
                "name": "TemporalMandatePermit",
                "status": "CREATE_FAILED",
                "statusReasons": ["Overly Permissive"],
            },
        ]
    }
    (root / "policy-inventory.raw").write_text(json.dumps(policies), encoding="utf-8")
    (root / "tools-list.raw").write_bytes(
        (EVIDENCE / "temporal-tools-list-response.json").read_bytes()
    )
    shape = {
        "session_aliases": ["same", "fresh-a", "fresh-b"],
        "same_session_calls": ["same-first", "same-second"],
        "distinct_session_calls": ["fresh-first", "fresh-second"],
        "session_ids_generated_as": "independent UUIDv4 values retained in memory only",
    }
    (root / "session-shape.raw").write_text(json.dumps(shape), encoding="utf-8")
    for identifier in ("same-first", "same-second", "fresh-first", "fresh-second"):
        response = read_json(f"temporal-{identifier}-response.json")
        if identifier == "same-second":
            response["error"]["message"] = (
                "Tool Execution Denied: Tool call not allowed due to policy enforcement "
                "[Policy evaluation denied due to TemporalMandateBudgetActive-raw-only]"
            )
        (root / f"{identifier}.raw").write_text(json.dumps(response), encoding="utf-8")


def test_temporal_session_capture_regenerates_the_live_boundary(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    output = tmp_path / "output"
    raw.mkdir()
    _write_temporal_raw(raw)

    result = capture_temporal.capture(raw, output)

    assert [item["outcome"] for item in result["same_session"]["calls"]] == [
        "allow",
        "deny",
    ]
    assert [item["outcome"] for item in result["fresh_sessions"]["calls"]] == [
        "allow",
        "allow",
    ]
    assert result["same_session"]["attempted_aggregate"] == 1200
    assert result["fresh_sessions"]["aggregate_across_sessions"] == 1200
    index = json.loads((output / "temporal-index.json").read_text(encoding="utf-8"))
    for source in index["sources"]:
        if source["locator"] != "capture_temporal.py":
            assert (output / source["locator"]).read_bytes() == (
                EVIDENCE / source["locator"]
            ).read_bytes()


def test_temporal_capture_rejects_policy_and_decision_mismatch(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_temporal_raw(raw)
    policies = json.loads((raw / "policy-inventory.raw").read_text(encoding="utf-8"))
    policies["policies"][0]["definition"]["policy"]["statement"] = "forbid();"
    (raw / "policy-inventory.raw").write_text(json.dumps(policies), encoding="utf-8")
    with pytest.raises(ValueError, match="sum boundary"):
        capture_temporal.capture(raw, tmp_path / "bad-policy")

    _write_temporal_raw(raw)
    response = json.loads((raw / "fresh-second.raw").read_text(encoding="utf-8"))
    response["result"]["isError"] = True
    (raw / "fresh-second.raw").write_text(json.dumps(response), encoding="utf-8")
    with pytest.raises(ValueError, match="outcome is not allow"):
        capture_temporal.capture(raw, tmp_path / "bad-response")


def _write_binding_raw(root: Path) -> None:
    status = {
        "success": True,
        "projectName": "TemporalMandate",
        "targetRegion": "us-east-1",
        "resources": [
            {
                "resourceType": resource_type,
                "name": name,
                "deploymentState": "deployed",
            }
            for resource_type, name in (
                ("gateway", "TemporalBindingGateway"),
                ("policy-engine", "TemporalBindingPolicyEngine"),
                ("policy", "TemporalBindingBudget"),
                ("policy", "TemporalBindingPermit"),
            )
        ],
    }
    (root / "deployment-status.raw").write_text(json.dumps(status), encoding="utf-8")
    gateway = {
        "status": "READY",
        "authorizerType": "AWS_IAM",
        "protocolType": "MCP",
        "policyEngineConfiguration": {"mode": "ENFORCE"},
        "workloadIdentityDetails": {"workloadIdentityArn": "present-only-in-raw"},
    }
    (root / "gateway-state.raw").write_text(json.dumps(gateway), encoding="utf-8")
    budget = (EVIDENCE / "binding-policy.dogwood").read_text(encoding="utf-8").replace(
        "<reviewed-gateway-binding>", "raw-gateway-resource"
    )
    permit = (
        "permit (principal is AgentCore::IamEntity, "
        'action == AgentCore::Action::"TemporalBindingTarget___process_refund", '
        'resource == AgentCore::Gateway::"raw-gateway-resource");'
    )
    policies = {
        "policies": [
            {
                "name": "TemporalBindingBudget",
                "status": "ACTIVE",
                "enforcementMode": "ACTIVE",
                "definition": {"policy": {"statement": budget}},
            },
            {
                "name": "TemporalBindingPermit",
                "status": "ACTIVE",
                "enforcementMode": "ACTIVE",
                "definition": {"policy": {"statement": permit}},
            },
        ]
    }
    (root / "policy-inventory.raw").write_text(json.dumps(policies), encoding="utf-8")
    for committed, raw in (
        ("binding-tools-list-response.json", "tools-list.raw"),
        ("mandate-binding.json", "binding-a.raw"),
        ("isolation-binding.json", "binding-b.raw"),
        ("binding-public-key.pem", "binding-public.raw"),
        ("binding-benchmark.json", "benchmark.raw"),
        ("binding-bound-first-response.json", "bound-first.raw"),
        ("binding-isolated-first-response.json", "isolated-first.raw"),
    ):
        (root / raw).write_bytes((EVIDENCE / committed).read_bytes())
    denied = read_json("binding-bound-second-response.json")
    denied["error"]["message"] = (
        "Tool Execution Denied: Tool call not allowed due to policy enforcement "
        "[Policy evaluation denied due to TemporalBindingBudget-raw-only]"
    )
    (root / "bound-second.raw").write_text(json.dumps(denied), encoding="utf-8")
    preflight = {
        "result": {
            "isError": True,
            "_meta": {
                "debug": {
                    "text": (
                        "not authorized to perform: "
                        "bedrock-agentcore:GetWorkloadAccessToken"
                    )
                }
            },
        }
    }
    (root / "preflight-failure.raw").write_text(json.dumps(preflight), encoding="utf-8")


def test_signed_mandate_binding_is_stable_fail_closed_and_live(tmp_path: Path) -> None:
    binding = read_json("mandate-binding.json")
    public_key = (EVIDENCE / "binding-public-key.pem").read_bytes()
    as_of = datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc)

    first = mandate_binding.verify_and_derive(
        binding, public_key, as_of=as_of, expected_principal="caller"
    )
    second = mandate_binding.verify_and_derive(
        binding, public_key, as_of=as_of, expected_principal="caller"
    )
    other = mandate_binding.verify_and_derive(
        read_json("isolation-binding.json"),
        public_key,
        as_of=as_of,
        expected_principal="caller",
    )
    assert first == second
    assert first != other
    assert re.fullmatch(r"[0-9a-f-]{36}", first)

    result = read_json("mandate-binding-result.json")
    assert [call["outcome"] for call in result["same_signed_mandate"]["calls"]] == [
        "allow",
        "deny",
    ]
    assert result["same_signed_mandate"]["separate_client_processes"] == 2
    assert result["different_signed_mandate"]["calls"] == [
        {"id": "isolated-first", "outcome": "allow"}
    ]
    assert [case["result"] for case in result["local_controls"]] == [
        "rejected-before-network",
        "rejected-before-network",
    ]
    assert read_json("binding-local-rejections.json")["network_requests"] == 0
    assert result["median_adapter_ms"] == read_json("binding-benchmark.json")["median_ms"]

    tampered = dict(binding)
    tampered["mandate_sha256"] = "0" * 64
    with pytest.raises(mandate_binding.BindingError, match="signature is not valid"):
        mandate_binding.verify_and_derive(
            tampered, public_key, as_of=as_of, expected_principal="caller"
        )
    with pytest.raises(mandate_binding.BindingError, match="not active"):
        mandate_binding.verify_and_derive(
            binding,
            public_key,
            as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
            expected_principal="caller",
        )

    raw = tmp_path / "raw"
    output = tmp_path / "output"
    raw.mkdir()
    _write_binding_raw(raw)
    regenerated = capture_binding.capture(raw, output)
    assert regenerated == result
    index = json.loads((output / "binding-index.json").read_text(encoding="utf-8"))
    for source in index["sources"]:
        if source["kind"] != "capture_script":
            assert (output / source["locator"]).read_bytes() == (
                EVIDENCE / source["locator"]
            ).read_bytes()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(extra=True), "missing or unknown"),
        (lambda value: value.update(binding_version=True), "binding_version"),
        (lambda value: value.update(principal=" caller"), "non-empty stripped"),
        (lambda value: value.update(issued_at="20260829"), "canonical UTC"),
        (lambda value: value.update(expires_at=value["issued_at"]), "increasing"),
        (lambda value: value.update(signature="!"), "base64"),
    ],
)
def test_binding_reader_rejects_malformed_records(mutation: Any, message: str) -> None:
    binding = read_json("mandate-binding.json")
    mutation(binding)
    with pytest.raises(mandate_binding.BindingError, match=message):
        mandate_binding.verify_and_derive(
            binding,
            (EVIDENCE / "binding-public-key.pem").read_bytes(),
            as_of=datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc),
            expected_principal="caller",
        )


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
