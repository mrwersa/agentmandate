from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agentmandate import loads
from agentmandate.drift import compare_source
from agentmandate.inventory import InventoryError

MANIFEST = """
version: 1
agent: dispute-resolver
limits:
  total: { amount: 500, currency: GBP }
  depth: 8
tools:
  - name: open_case
    effect: read
    principal: caller
    produces: case
  - name: issue_refund
    effect: irreversible
    principal: caller
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: { amount: 500, currency: GBP }
    requires_approval: true
"""

SOURCE = '''
from decimal import Decimal

from strands import Agent, tool


@tool
def open_case(customer_id: str) -> str:
    """Open a case."""


@tool("issue_refund")
def refund(case_id: str, amount: Decimal, currency: str) -> str:
    """Refund a case."""


agent = Agent(tools=[open_case, refund])
'''


def write(tmp_path: Path, source: str = SOURCE) -> Path:
    path = tmp_path / "agent.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


def test_a_matching_manifest_and_source_report_no_drift(tmp_path: Path) -> None:
    drift = compare_source(loads(MANIFEST), write(tmp_path))

    assert drift.clean
    assert drift.declared == ("issue_refund", "open_case")
    assert drift.discovered == ("issue_refund", "open_case")
    assert "still describes the implementation" in drift.render()


def test_a_tool_the_agent_has_and_the_mandate_omits(tmp_path: Path) -> None:
    # The dangerous direction. Every clean reach report before this one was
    # about a smaller graph than the real system.
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        '''@tool
def issue_credit_note(case_id: str, amount: Decimal) -> str:
    """Never added to the mandate."""


agent = Agent(tools=[open_case, refund, issue_credit_note])''',
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert [(f.kind, f.tool) for f in drift.findings] == [
        ("undeclared", "issue_credit_note")
    ]
    assert "smaller graph than the real one" in drift.findings[0].message


def test_a_ceiling_counted_against_an_argument_that_no_longer_exists(
    tmp_path: Path,
) -> None:
    # The quiet one. The manifest still parses, `reach` still runs, and the
    # ceiling counts against nothing.
    source = SOURCE.replace(
        "def refund(case_id: str, amount: Decimal, currency: str)",
        "def refund(case_id: str, total: Decimal, currency: str)",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert [(f.kind, f.tool) for f in drift.findings] == [("argument", "issue_refund")]
    assert "value_arg names 'amount'" in drift.findings[0].message
    assert "case_id, total, currency" in drift.findings[0].message


def test_a_scope_key_carried_by_an_argument_is_not_drift(tmp_path: Path) -> None:
    # `scope_key: case` is a manifest concept. `case_id` carries it, so this
    # must not be reported: a false drift finding on every well-formed
    # manifest would make the command useless.
    drift = compare_source(loads(MANIFEST), write(tmp_path))

    assert not any(f.kind == "argument" for f in drift.findings)


def test_a_scope_key_nothing_carries_is_drift(tmp_path: Path) -> None:
    source = SOURCE.replace(
        "def refund(case_id: str, amount: Decimal, currency: str)",
        "def refund(ticket: str, amount: Decimal, currency: str)",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert [f.kind for f in drift.findings] == ["argument"]
    assert "scope_key names 'case'" in drift.findings[0].message


def test_a_tool_the_mandate_declares_and_the_agent_lost(tmp_path: Path) -> None:
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "agent = Agent(tools=[open_case])",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert [(f.kind, f.tool) for f in drift.findings] == [("removed", "issue_refund")]
    assert "gets switched off" in drift.findings[0].message


def test_an_unenumerable_tool_list_refuses_to_report_no_drift(
    tmp_path: Path,
) -> None:
    # Fail closed. Reporting a clean comparison from evidence that could not
    # see the whole list is the false assurance this package exists to stop.
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "agent = Agent(tools=[open_case, refund, *load_partner_tools()])",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert not drift.clean
    assert [f.kind for f in drift.findings] == ["unresolved"]
    assert "cannot establish that nothing is missing" in drift.findings[0].message


def test_a_tool_declared_outside_the_scanned_path_is_not_a_clean_pass(
    tmp_path: Path,
) -> None:
    source = SOURCE.replace(
        "from strands import Agent, tool",
        "from partner_kit import lookup_partner\nfrom strands import Agent, tool",
    ).replace(
        "agent = Agent(tools=[open_case, refund])",
        "agent = Agent(tools=[open_case, refund, lookup_partner])",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert [(f.kind, f.tool) for f in drift.findings] == [
        ("unresolved", "lookup_partner")
    ]
    assert "Widen --source" in drift.findings[0].message


def test_findings_are_ordered_by_how_much_they_matter(tmp_path: Path) -> None:
    source = SOURCE.replace(
        "def refund(case_id: str, amount: Decimal, currency: str)",
        "def refund(case_id: str, total: Decimal, currency: str)",
    ).replace(
        "agent = Agent(tools=[open_case, refund])",
        '''@tool
def wipe(case_id: str) -> None:
    """Undeclared."""


agent = Agent(tools=[refund, wipe])''',
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    # Authority the mandate does not describe first: it invalidates every
    # other answer the analysis has given.
    assert [f.kind for f in drift.findings] == ["undeclared", "argument", "removed"]


def test_a_tool_with_no_arguments_is_not_argument_drift(tmp_path: Path) -> None:
    source = SOURCE.replace(
        'def refund(case_id: str, amount: Decimal, currency: str) -> str:',
        "def refund() -> str:",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert not any(f.kind == "argument" for f in drift.findings)


def test_the_json_shape_carries_both_inventories(tmp_path: Path) -> None:
    drift = compare_source(loads(MANIFEST), write(tmp_path))
    payload = drift.as_dict()

    assert payload["clean"] is True
    assert payload["declared"] == ["issue_refund", "open_case"]
    assert payload["discovered"] == ["issue_refund", "open_case"]
    assert payload["findings"] == []


def test_selecting_one_agent_when_the_source_builds_several(tmp_path: Path) -> None:
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "triage = Agent(tools=[open_case])\nresolver = Agent(tools=[open_case, refund])",
    )
    root = write(tmp_path, source)

    with pytest.raises(InventoryError, match="more than one agent"):
        compare_source(loads(MANIFEST), root)

    assert compare_source(loads(MANIFEST), root, binding="resolver").clean
    assert compare_source(loads(MANIFEST), root, union=True).clean
