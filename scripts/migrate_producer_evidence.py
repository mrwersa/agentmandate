"""Regenerate the canonical producer artifact from committed IAM evidence.

This repository tool owns evidence-specific conversion. The installed runtime
owns the strict boundary reader, IR projection, and analysis only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agentmandate._producer import (
    PRODUCER_BOUNDARY_ADAPTER,
    PRODUCER_BOUNDARY_ADAPTER_VERSION,
    PRODUCER_BOUNDARY_VERSION,
    AcceptedControl,
    ExhaustedControl,
    ProducerBoundary,
    ProducerBoundaryFormatError,
    ProducerCapacity,
    ProducerControls,
    ProducerEvidence,
    ProducerOutput,
    ProducerPartition,
    ProducerRunBoundary,
    ProducerSource,
    ProducerTarget,
    _load,
)

_IAM_BASE = "docs/evidence/aws-iam-access-keys/"
_IAM_SOURCES = {
    _IAM_BASE + "catalogue.json": (
        "tool-catalogue",
        "upstream-inventory",
        "6ad70d0ecf3d05e8e9e2b08a52e7d2b8099954b586f52c6bd68bc3d99e5cff3c",
    ),
    _IAM_BASE + "capture.json": (
        "producer-outcomes",
        "capacity-controls",
        "199f47e9bc87d39ab129bcd01ab69200326d759e1621cfdc5c5abfa9511fb3c8",
    ),
    _IAM_BASE + "capture.py": (
        "capture-adapter",
        "selected-run-boundary",
        "ace01427863ddeb8880ed1f42ed8e1a8dd6a6cc1fbaeb7c856967708120d0b88",
    ),
}


def _migration_sources(contents: Mapping[str, bytes]) -> tuple[ProducerSource, ...]:
    if not isinstance(contents, Mapping) or any(
        not isinstance(locator, str) for locator in contents
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary migration requires locator-to-bytes sources"
        )
    if set(contents) != set(_IAM_SOURCES):
        missing = sorted(set(_IAM_SOURCES) - set(contents))
        detail = f"; missing locator {missing[0]}" if missing else ""
        raise ProducerBoundaryFormatError(
            f"producer boundary migration source set differs{detail}"
        )
    result = []
    for locator, (kind, role, expected_digest) in _IAM_SOURCES.items():
        content = contents[locator]
        if not isinstance(content, bytes):
            raise ProducerBoundaryFormatError(
                "producer boundary migration source contents must be bytes"
            )
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_digest:
            raise ProducerBoundaryFormatError(
                f"producer boundary migration source bytes do not match reviewed locator {locator}"
            )
        result.append(ProducerSource(f"source:{role}", kind, role, locator, digest))
    return tuple(sorted(result, key=lambda source: source.id))


def _captured(contents: Mapping[str, bytes], locator: str) -> dict[str, Any]:
    content = contents[locator]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProducerBoundaryFormatError(
            f"producer boundary source {locator} is not UTF-8"
        ) from exc
    value = _load(text, f"producer boundary source {locator}")
    if not isinstance(value, dict):
        raise ProducerBoundaryFormatError(
            f"producer boundary source {locator} must contain an object"
        )
    return value


def migrate_aws_iam_access_key_boundary(
    contents: Mapping[str, bytes],
) -> ProducerBoundary:
    """Migrate the digest-pinned IAM access-key capture into boundary v1."""

    sources = _migration_sources(contents)
    catalogue = _captured(contents, _IAM_BASE + "catalogue.json")
    capture = _captured(contents, _IAM_BASE + "capture.json")
    tools = catalogue.get("tools")
    if not isinstance(tools, list):
        raise ProducerBoundaryFormatError(
            "producer boundary migration catalogue tools must be an array"
        )
    selected = [
        tool
        for tool in tools
        if isinstance(tool, dict) and tool.get("name") == "create_access_key"
    ]
    selected_tool = selected[0] if len(selected) == 1 else {}
    input_schema = selected_tool.get("inputSchema")
    output_schema = selected_tool.get("outputSchema")
    if (
        len(tools) != 29
        or len(selected) != 1
        or not isinstance(input_schema, dict)
        or input_schema.get("required") != ["user_name"]
        or not isinstance(output_schema, dict)
        or output_schema.get("required") != ["result"]
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary migration catalogue does not match the selected producer"
        )
    expected_outcomes = [
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
    producer = capture.get("producer")
    quota = capture.get("quota")
    if (
        capture.get("capture_version") != 1
        or capture.get("adapter")
        != {"name": "agentmandate.aws-iam-access-key-capture", "version": 1}
        or capture.get("capture_date") != "2026-08-29"
        or capture.get("outcomes") != expected_outcomes
        or capture.get("identity") != {"principal_kind": "iam-user", "same_principal": True}
        or capture.get("cleanup") != {"access_keys": 0, "user_absent": True}
        or capture.get("sanitization")
        != {
            "committed_live_identifiers": False,
            "committed_secret_material": False,
            "raw_credentials_written_to_disk": False,
        }
        or capture.get("deployment")
        != {
            "attached_policies": [],
            "region": "us-east-1",
            "user_path": "/agentmandate-evidence/",
        }
        or producer
        != {
            "mcp_version": "1.23.3",
            "package": "awslabs.iam-mcp-server",
            "package_version": "1.0.11",
            "wheel_sha256": (
                "e48d688f8e338098f410fcabfbedec304f65e63c179bb19001e5b80a2523de16"
            ),
        }
        or quota
        != {"adjustable": False, "kind": "access_keys_per_user", "maximum": 2}
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary migration controls do not match the reviewed evidence"
        )
    outcome_source = "source:capacity-controls"
    migrated = ProducerBoundary(
        PRODUCER_BOUNDARY_VERSION,
        "producer-boundaries/iam-user-access-keys",
        PRODUCER_BOUNDARY_ADAPTER,
        PRODUCER_BOUNDARY_ADAPTER_VERSION,
        ProducerTarget(
            _IAM_BASE + "capture.py",
            "create_access_key",
            producer["package"],
            producer["package_version"],
        ),
        ProducerPartition("user_name", "reviewed-iam-user"),
        ProducerOutput("access_key", ProducerCapacity("concurrent", quota["maximum"])),
        ProducerRunBoundary(("create_access_key",), "complete", (), "complete"),
        ProducerControls(
            AcceptedControl(2, outcome_source, "/outcomes/1"),
            ExhaustedControl(3, "capacity_exhausted", outcome_source, "/outcomes/2"),
        ),
        sources,
        ProducerEvidence("exact", "unreviewed", None, None),
    )
    return ProducerBoundary.from_json(migrated.to_json())


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "producer-boundary-iam-v1.json"


def _contents() -> dict[str, bytes]:
    return {locator: (ROOT / locator).read_bytes() for locator in _IAM_SOURCES}


def verify_fixture() -> None:
    contents = _contents()
    migrated = migrate_aws_iam_access_key_boundary(contents)
    expected = FIXTURE.read_text(encoding="utf-8")
    if migrated.to_json() != expected:
        raise ProducerBoundaryFormatError(
            "producer migration no longer reproduces canonical IAM fixture"
        )
    migrated.verify_sources(contents)


def main() -> None:
    verify_fixture()
    print("producer evidence migration: canonical IAM fixture matches source evidence")


if __name__ == "__main__":
    main()
