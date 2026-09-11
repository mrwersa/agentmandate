from __future__ import annotations

from pathlib import Path

import agentmandate
from agentmandate.cli import build_parser

AUDIT = Path(__file__).resolve().parents[1] / "docs" / "pre-1.0-consolidation-audit.md"


def test_audit_lists_every_public_python_name() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    missing = sorted(name for name in agentmandate.__all__ if f"`{name}`" not in source)

    assert not missing, f"pre-1.0 audit omits public Python names: {', '.join(missing)}"


def test_audit_lists_every_top_level_cli_command() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    commands = {
        name
        for action in build_parser()._subparsers._group_actions
        for name in action.choices
    }
    missing = sorted(name for name in commands if f"`{name}`" not in source)

    assert not missing, f"pre-1.0 audit omits CLI commands: {', '.join(missing)}"


def test_audit_pins_every_evidence_converter_before_relocation() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    converters = {
        "DelegationChain.from_grant_v1",
        "DelegationChain.from_authorizer_capture",
        "migrate_aws_iam_access_key_boundary",
        "migrate_agentcore_binding",
        "migrate_agentcore_continuity",
        "migrate_anthropic_continuity",
    }
    missing = sorted(name for name in converters if f"`{name}`" not in source)

    assert not missing, f"pre-1.0 audit omits evidence converters: {', '.join(missing)}"
