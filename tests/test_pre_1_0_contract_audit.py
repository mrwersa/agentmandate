from __future__ import annotations

import ast
from pathlib import Path

import agentmandate
from agentmandate.cli import build_parser

AUDIT = Path(__file__).resolve().parents[1] / "docs" / "pre-1.0-consolidation-audit.md"
ROOT = AUDIT.parents[1]


def test_audit_lists_every_public_python_name() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    missing = sorted(name for name in agentmandate.__all__ if f"`{name}`" not in source)

    assert not missing, f"pre-1.0 audit omits public Python names: {', '.join(missing)}"


def test_audit_lists_every_top_level_cli_command() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    commands = {
        name for action in build_parser()._subparsers._group_actions for name in action.choices
    }
    missing = sorted(name for name in commands if f"`{name}`" not in source)

    assert not missing, f"pre-1.0 audit omits CLI commands: {', '.join(missing)}"


def test_audit_pins_every_evidence_converter_during_relocation() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    converters = {
        "DelegationChain.from_grant_v1",
        "DelegationChain.from_authorizer_capture",
    }
    for directory in (ROOT / "agentmandate", ROOT / "scripts"):
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            converters.update(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name.startswith("migrate_")
            )
    missing = sorted(name for name in converters if f"`{name}`" not in source)

    assert not missing, f"pre-1.0 audit omits evidence converters: {', '.join(missing)}"
