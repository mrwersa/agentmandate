from __future__ import annotations

import json
from pathlib import Path

from agentmandate import analyse, check, load, propose, render

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "initiative-mcp"


def catalogue() -> dict:
    return json.loads((EVIDENCE / "catalogue.json").read_text(encoding="utf-8"))


def test_catalogue_and_reviewed_manifest_cover_the_same_tools() -> None:
    mandate = load(EVIDENCE / "mandate.yaml")

    assert len(catalogue()["tools"]) == 25
    assert {tool["name"] for tool in catalogue()["tools"]} == set(mandate.tool_names)


def test_scan_confuses_bearer_ids_and_result_shapes_with_authority() -> None:
    proposals = {proposal.name: proposal for proposal in propose(catalogue())}

    assert proposals["list_task_statuses_api_v1_g"].scope == "guild"
    assert proposals["create_comment_api_v1_g"].scope == "calendar"
    assert proposals["autocomplete_tasks_api_v1_g"].value_arg == "limit"
    assert proposals["update_task_api_v1_g"].value_arg == "property_values"


def test_scan_skeleton_is_the_exact_scanner_output() -> None:
    generated = render(propose(catalogue()), "initiative-agent")

    assert (EVIDENCE / "scan-skeleton.yaml").read_text(encoding="utf-8") == generated


def test_reviewed_graph_keeps_the_real_move_finding() -> None:
    mandate = load(EVIDENCE / "mandate.yaml")
    authority = analyse(mandate)

    assert authority.reachable_tools == frozenset(mandate.tool_names)
    assert len(authority.breaches) == 1
    assert authority.breaches[0].kind == "ungated_effect"
    assert [step.tool for step in authority.breaches[0].path] == [
        "move_task_api_v1_g"
    ]
    findings = check(mandate)
    assert [(finding.rule, finding.subject) for finding in findings] == [
        ("effect.ungated-irreversible", "move_task_api_v1_g")
    ]


def test_relationship_inputs_remain_visible_in_the_raw_catalogue() -> None:
    tools = {tool["name"]: tool for tool in catalogue()["tools"]}
    status_properties = tools["list_task_statuses_api_v1_g"]["inputSchema"]["properties"]
    create_properties = tools["create_task_api_v1_g"]["inputSchema"]["properties"]

    assert "project_id" in status_properties
    assert {"project_id", "task_status_id"} <= set(create_properties)
