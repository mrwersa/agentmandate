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


def test_the_output_names_which_tool_list_it_compared_against(
    tmp_path: Path,
) -> None:
    # `diff` refuses to compare two different agents. This cannot: nothing in
    # source states the agent's declared name, so identity cannot be
    # established. Naming the binding is what lets a reader see that the
    # comparison was against the agent they meant.
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "resolver = Agent(tools=[open_case, refund])",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert "(resolver)" in drift.source
    assert "source inventory taken from" in drift.render()
    assert drift.as_dict()["source"] == drift.source


def test_no_binding_at_all_says_the_comparison_is_unnarrowed(
    tmp_path: Path,
) -> None:
    source = SOURCE.replace("agent = Agent(tools=[open_case, refund])", "")

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert drift.source == ""
    assert "no agent binding was found in source" in drift.render()


def test_a_list_the_read_cannot_enumerate_suppresses_removals(
    tmp_path: Path,
) -> None:
    # A removal is a claim that a tool is absent from the agent's list, and
    # that claim cannot be made from a list the read could not enumerate: the
    # tool may be in the part it could not see. Reporting both `unresolved`
    # and `removed` asserted something positive from evidence already flagged
    # as unreadable.
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "agent = Agent(tools=[open_case] if flag else [open_case, refund])",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert [f.kind for f in drift.findings] == ["unresolved"]
    assert not drift.clean


def test_a_readable_list_still_reports_a_genuine_removal(tmp_path: Path) -> None:
    # The suppression must not swallow the real case, which is the whole
    # reason `removed` exists.
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "agent = Agent(tools=[open_case])",
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert [f.kind for f in drift.findings] == ["removed"]


def test_an_undeclared_tool_survives_an_unreadable_list(tmp_path: Path) -> None:
    # A tool seen bound and not declared is real whatever else the read
    # missed, so this direction is not suppressed.
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        '''@tool
def wipe(case_id: str) -> None:
    """Undeclared."""


agent = Agent(tools=[open_case, refund, wipe, *load_more()])''',
    )

    drift = compare_source(loads(MANIFEST), write(tmp_path, source))

    assert {f.kind for f in drift.findings} == {"undeclared", "unresolved"}


def test_a_tool_bound_outside_the_scan_is_not_reported_removed(
    tmp_path: Path,
) -> None:
    # The manifest declares fetch_case and the source binds it from a module
    # the scan never saw. Reporting that as `removed` would contradict the
    # `unresolved` finding beside it: the tool is given to the agent, the scan
    # just never read the file that declares it. An absent declaration is not
    # an absent tool.
    manifest = MANIFEST + """
  - name: fetch_case
    effect: read
"""
    source = SOURCE.replace(
        "from strands import Agent, tool",
        "from partner_kit import fetch_case\nfrom strands import Agent, tool",
    ).replace(
        "agent = Agent(tools=[open_case, refund])",
        "agent = Agent(tools=[open_case, refund, fetch_case])",
    )

    drift = compare_source(loads(manifest), write(tmp_path, source))

    assert [(f.kind, f.tool) for f in drift.findings] == [
        ("unresolved", "fetch_case")
    ]
    assert "Widen --source" in drift.findings[0].message


def test_a_union_of_several_agents_names_itself_as_the_source(
    tmp_path: Path,
) -> None:
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "triage = Agent(tools=[open_case])\nresolver = Agent(tools=[open_case, refund])",
    )
    root = write(tmp_path, source)

    drift = compare_source(loads(MANIFEST), root, union=True)

    assert drift.clean
    assert "union of every agent's tool list" in drift.source
    assert "union of every agent's tool list" in drift.render()


def test_a_single_agent_under_union_flags_still_names_its_binding(
    tmp_path: Path,
) -> None:
    # `--union-bindings` with one agent in source selects that agent, so the
    # report must name it rather than claim no binding was found.
    source = SOURCE.replace(
        "agent = Agent(tools=[open_case, refund])",
        "resolver = Agent(tools=[open_case, refund])",
    )
    root = write(tmp_path, source)

    drift = compare_source(loads(MANIFEST), root, union=True)

    assert drift.clean
    assert "(resolver)" in drift.source
    assert "no agent binding" not in drift.render()
