from __future__ import annotations

import json
from pathlib import Path

from agentmandate import analyse, check, load, propose, render

EVIDENCE = Path(__file__).resolve().parents[1] / "docs" / "evidence" / "sentry-mcp"


def catalogue() -> dict:
    return json.loads((EVIDENCE / "catalogue.json").read_text(encoding="utf-8"))


def test_catalogue_and_reviewed_manifest_cover_the_same_visible_tools() -> None:
    mandate = load(EVIDENCE / "mandate.yaml")

    assert len(catalogue()["tools"]) == 8
    assert {tool["name"] for tool in catalogue()["tools"]} == set(mandate.tool_names)


def test_scan_confuses_bearer_ids_and_result_limits_with_authority() -> None:
    proposals = {proposal.name: proposal for proposal in propose(catalogue())}

    assert proposals["update_issue"].scope == "issue"
    assert proposals["search_issues"].scope == "projectslugor"
    assert proposals["search_issues"].value_arg == "limit"
    assert proposals["execute_sentry_tool"].effect == "irreversible"


def test_scan_skeleton_is_the_exact_scanner_output() -> None:
    generated = render(propose(catalogue()), "sentry-operations-agent")

    assert (EVIDENCE / "scan-skeleton.yaml").read_text(encoding="utf-8") == generated


def test_reviewed_graph_exposes_the_meta_tool_budget_counterexample() -> None:
    mandate = load(EVIDENCE / "mandate.yaml")
    authority = analyse(mandate)
    breach = next(item for item in authority.breaches if item.kind == "effect_count")

    assert authority.reachable_tools == frozenset(mandate.tool_names)
    assert breach.subject == "irreversible"
    assert [step.tool for step in breach.path] == [
        "execute_sentry_tool",
        "execute_sentry_tool",
    ]


def test_reviewed_graph_keeps_fixed_token_findings_visible() -> None:
    findings = check(load(EVIDENCE / "mandate.yaml"))

    assert len(findings) == 8
    assert {finding.rule for finding in findings} == {"identity.service-principal"}


def test_capture_lock_pins_the_reviewed_package_and_integrity() -> None:
    lock = json.loads((EVIDENCE / "package-lock.json").read_text(encoding="utf-8"))
    package = lock["packages"]["node_modules/@sentry/mcp-server"]

    assert package["version"] == "0.37.0"
    assert package["integrity"] == (
        "sha512-agZ4KMeYVlTzl4topI6ED6gTmZDtmWZJV4n/nSuoXjNv4i+PNhdx1qJEtTdJdjEh8lPXu1"
        "SziEk7zgRCQ4FYbg=="
    )
