from __future__ import annotations

import json
from pathlib import Path

from agentmandate import analyse, check, load, propose, render

EVIDENCE = (
    Path(__file__).resolve().parents[1] / "docs" / "evidence" / "aws-postgres-mcp"
)


def test_catalogue_and_reviewed_manifest_cover_the_same_tools() -> None:
    catalogue = json.loads((EVIDENCE / "catalogue.json").read_text(encoding="utf-8"))
    mandate = load(EVIDENCE / "mandate.yaml")

    assert len(catalogue["tools"]) == 7
    assert {tool["name"] for tool in catalogue["tools"]} == set(mandate.tool_names)


def test_scan_misses_the_write_enabled_query_and_connection_state() -> None:
    catalogue = json.loads((EVIDENCE / "catalogue.json").read_text(encoding="utf-8"))
    proposals = {proposal.name: proposal for proposal in propose(catalogue)}

    assert proposals["run_query"].effect == "read"
    assert proposals["connect_to_database"].effect == "irreversible"
    assert proposals["is_database_connected"].effect == "irreversible"


def test_scan_skeleton_is_the_preserved_cli_output() -> None:
    catalogue = json.loads((EVIDENCE / "catalogue.json").read_text(encoding="utf-8"))

    assert (EVIDENCE / "scan-skeleton.yaml").read_text(encoding="utf-8") == render(
        propose(catalogue), "aws-postgres-agent"
    )


def test_reviewed_graph_exposes_the_effect_budget_counterexample() -> None:
    mandate = load(EVIDENCE / "mandate.yaml")
    authority = analyse(mandate)
    breach = next(item for item in authority.breaches if item.kind == "effect_count")

    assert authority.reachable_tools == frozenset(mandate.tool_names)
    assert breach.subject == "irreversible"
    assert [step.tool for step in breach.path] == [
        "connect_to_database",
        "run_query",
        "run_query",
    ]


def test_reviewed_graph_keeps_service_principal_findings_visible() -> None:
    findings = check(load(EVIDENCE / "mandate.yaml"))

    assert len(findings) == 7
    assert {finding.rule for finding in findings} == {"identity.service-principal"}
