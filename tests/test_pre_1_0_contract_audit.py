from __future__ import annotations

import ast
import json
from pathlib import Path

import agentmandate

AUDIT = Path(__file__).resolve().parents[1] / "docs" / "pre-1.0-consolidation-audit.md"
ROOT = AUDIT.parents[1]


def test_audit_lists_every_public_python_name() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    missing = sorted(name for name in agentmandate.__all__ if f"`{name}`" not in source)

    assert not missing, f"pre-1.0 audit omits public Python names: {', '.join(missing)}"


def test_historical_audit_lists_baseline_top_level_cli_commands() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    # The fixed historical audit cannot acquire every new command. Current
    # declarations are checked separately against the live contract inventory.
    path = ROOT / "tests/fixtures/current-contract-inventory-v0.22.json"
    baseline = json.loads(path.read_text())
    commands = {
        path.split()[1] for path in baseline["cli"] if len(path.split()) == 2
    }
    missing = sorted(name for name in commands if f"`{name}`" not in source)

    assert not missing, f"historical audit omits baseline CLI commands: {', '.join(missing)}"


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


def test_reviewed_baseline_pins_release_and_replay_tools() -> None:
    source = AUDIT.read_text(encoding="utf-8")
    # This audit records the historical baseline, not each subsequent release.
    assert "released as `0.17.0`" in source

    replay_tools = (
        "scripts/migrate_continuity_evidence.py",
        "scripts/migrate_producer_evidence.py",
        "scripts/migrate_delegation_evidence.py",
        "scripts/replay_principal_v1.py",
        "scripts/replay_cedar_bundle_v1.py",
    )
    missing = [path for path in replay_tools if f"`{path}`" not in source]

    assert not missing, f"reviewed baseline omits replay tools: {', '.join(missing)}"
