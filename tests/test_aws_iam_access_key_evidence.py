from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agentmandate import analyse, check, load, propose, render

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "aws-iam-access-keys"


def _json(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_catalogue_is_the_pinned_full_server_inventory() -> None:
    catalogue = _json("catalogue.json")
    tools = {tool["name"]: tool for tool in catalogue["tools"]}

    assert len(tools) == 29
    assert "create_access_key" in tools
    assert tools["create_access_key"]["inputSchema"]["required"] == ["user_name"]
    assert tools["create_access_key"]["outputSchema"]["required"] == ["result"]


def test_scan_skeleton_is_the_exact_scanner_output() -> None:
    assert (EVIDENCE / "scan-skeleton.yaml").read_text(encoding="utf-8") == render(
        propose(_json("catalogue.json")), "iam-key-agent"
    )


def test_live_capture_proves_two_bindings_and_exhaustion() -> None:
    capture = _json("capture.json")

    assert capture["producer"] == {
        "mcp_version": "1.23.3",
        "package": "awslabs.iam-mcp-server",
        "package_version": "1.0.11",
        "wheel_sha256": "e48d688f8e338098f410fcabfbedec304f65e63c179bb19001e5b80a2523de16",
    }
    assert capture["quota"] == {
        "adjustable": False,
        "kind": "access_keys_per_user",
        "maximum": 2,
    }
    assert capture["outcomes"] == [
        {
            "attempt": 1,
            "authenticated": True,
            "binding": "access-key-1",
            "outcome": "created",
            "status": "Active",
        },
        {
            "attempt": 2,
            "authenticated": True,
            "binding": "access-key-2",
            "outcome": "created",
            "status": "Active",
        },
        {"attempt": 3, "error_code": "LimitExceeded", "outcome": "rejected"},
    ]
    assert capture["identity"] == {"principal_kind": "iam-user", "same_principal": True}
    assert capture["cleanup"] == {"access_keys": 0, "user_absent": True}
    assert capture["sanitization"] == {
        "committed_live_identifiers": False,
        "committed_secret_material": False,
        "raw_credentials_written_to_disk": False,
    }


def test_capture_and_catalogue_digests_are_pinned() -> None:
    assert hashlib.sha256((EVIDENCE / "capture.json").read_bytes()).hexdigest() == (
        "199f47e9bc87d39ab129bcd01ab69200326d759e1621cfdc5c5abfa9511fb3c8"
    )
    assert hashlib.sha256((EVIDENCE / "catalogue.json").read_bytes()).hexdigest() == (
        "6ad70d0ecf3d05e8e9e2b08a52e7d2b8099954b586f52c6bd68bc3d99e5cff3c"
    )


def test_committed_live_result_contains_no_aws_identity_or_secret() -> None:
    content = (EVIDENCE / "capture.json").read_text(encoding="utf-8")

    assert not re.search(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", content)
    assert "arn:aws" not in content.lower()
    assert not re.search(r"\b\d{12}\b", content)
    assert not re.search(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        content,
        flags=re.IGNORECASE,
    )


def test_reviewed_graph_exposes_only_the_false_third_binding_path() -> None:
    mandate = load(EVIDENCE / "mandate.yaml")
    authority = analyse(mandate)

    assert mandate.tool_names == ("create_access_key",)
    assert mandate.tools[0].produces == "access_key"
    assert mandate.tools[0].unbounded is True
    assert authority.reachable_tools == frozenset({"create_access_key"})
    assert len(authority.breaches) == 1
    assert authority.breaches[0].kind == "effect_count"
    assert authority.breaches[0].subject == "write"
    assert [step.binding for step in authority.breaches[0].path] == [
        "access_key#1",
        "access_key#2",
        "access_key#3",
    ]
    assert analyse(mandate, depth=2).breaches == ()
    assert [(finding.rule, finding.subject) for finding in check(mandate)] == [
        ("identity.service-principal", "create_access_key")
    ]
