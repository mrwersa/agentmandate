from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agentmandate.inventory import InventoryError, collect, notes_for
from agentmandate.scan import scan_source

STRANDS_AGENT = '''
from decimal import Decimal

from strands import Agent, tool


@tool
def search_cases(query: str) -> list:
    """Find support cases matching a query.

    A second paragraph that should not reach the manifest.
    """


@tool("issue_refund")
async def refund(case_id: str, amount: Decimal, currency: str) -> str:
    """Move money back to the customer."""


@tool
def draft_email(case_id: str, body: str) -> str:
    """Draft an email for a human to send."""


agent = Agent(model="claude-sonnet-5", tools=[search_cases, refund])
'''


def write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def test_a_bound_tool_list_is_the_inventory(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    inventory = collect(tmp_path)

    assert [p.name for p in inventory.proposals] == ["search_cases", "issue_refund"]
    # The mandate covers what the agent was given. A decorated function nobody
    # handed it is not part of its authority.
    assert inventory.unbound == ["draft_email"]


def test_the_decorator_argument_names_the_tool_not_the_function(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    names = [p.name for p in collect(tmp_path).proposals]

    assert "issue_refund" in names
    assert "refund" not in names


def test_a_keyword_name_overrides_the_function_name(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from agents import Agent, function_tool


        @function_tool(name_override="pay_supplier")
        def pay(invoice_id: str, amount: float) -> str:
            """Pay a supplier invoice."""


        agent = Agent(name="ap", tools=[pay])
        ''',
    )

    proposal = collect(tmp_path).proposals[0]

    assert proposal.name == "pay_supplier"
    assert proposal.value_arg == "amount"
    assert proposal.scope == "invoice"


def test_an_annotated_string_is_not_read_as_a_value_argument(tmp_path: Path) -> None:
    # `amount` matches the value hint by name. The annotation is what stops it
    # being proposed as a ceiling argument, which a bare MCP schema could not.
    write(
        tmp_path,
        "agent.py",
        '''
        from agent_framework import ai_function


        @ai_function
        def record_note(case_id: str, amount: str) -> None:
            """Record the amount as free text."""
        ''',
    )

    assert collect(tmp_path).proposals[0].value_arg is None


@pytest.mark.parametrize(
    ("annotation", "detected"),
    [
        ("int", True),
        ("float", True),
        ("Decimal", True),
        ("decimal.Decimal", True),
        ("Optional[float]", True),
        ('"int"', True),
        ('Annotated[float, "gbp"]', True),
        ("int | None", True),
        ("str", False),
        ("bool", False),
        ("SomethingElse", True),
    ],
)
def test_value_detection_follows_the_annotation(
    tmp_path: Path, annotation: str, detected: bool
) -> None:
    # An unrecognised annotation stays untyped, and an untyped argument is
    # still offered as a candidate, because the reviewer decides.
    write(
        tmp_path,
        "agent.py",
        f'''
        from strands import tool


        @tool
        def pay(case_id: str, amount: {annotation}) -> None:
            """Pay."""
        ''',
    )

    assert (collect(tmp_path).proposals[0].value_arg == "amount") is detected


def test_an_unannotated_argument_stays_a_candidate(tmp_path: Path) -> None:
    # No annotation is no evidence either way, and the reviewer decides. The
    # alternative, dropping it, would hide a ceiling argument.
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import tool


        @tool
        def pay(case_id, amount):
            """Pay."""
        ''',
    )

    proposal = collect(tmp_path).proposals[0]

    assert proposal.value_arg == "amount"
    assert proposal.scope == "case"


def test_framework_plumbing_is_not_read_as_agent_input(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from agents import RunContextWrapper, function_tool


        @function_tool
        def close(ctx, tool_context, wrapper: RunContextWrapper, case_id: str) -> None:
            """Close a case."""
        ''',
    )

    # `wrapper` would otherwise have been taken as the scope-bearing argument.
    assert collect(tmp_path).proposals[0].scope == "case"


def test_a_method_tool_ignores_self(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from crewai.tools import tool


        class Support:
            @tool
            def close_case(self, case_id: str) -> None:
                """Close a case."""
        ''',
    )

    assert collect(tmp_path).proposals[0].scope == "case"


def test_only_the_first_docstring_paragraph_becomes_the_comment(
    tmp_path: Path,
) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    described = {p.name: p.description for p in collect(tmp_path).proposals}

    assert described["search_cases"] == "Find support cases matching a query."


def test_a_tool_with_no_docstring_carries_no_description(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        """
        from strands import tool


        @tool
        def ping():
            return None
        """,
    )

    assert collect(tmp_path).proposals[0].description == ""


def test_an_attribute_decorator_is_recognised(tmp_path: Path) -> None:
    # FastMCP registers with `@mcp.tool()`, and the import path differs from
    # every other framework, so matching is on the trailing name.
    write(
        tmp_path,
        "agent.py",
        '''
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("support")


        @mcp.tool()
        def get_case(case_id: str) -> dict:
            """Read a case."""
        ''',
    )

    assert [p.name for p in collect(tmp_path).proposals] == ["get_case"]


def test_a_renamed_import_is_still_recognised(tmp_path: Path) -> None:
    # `from strands import tool as strands_tool` is common when two frameworks
    # are used in one file, and matching the decorator name alone missed the
    # declaration completely.
    write(
        tmp_path,
        "agent.py",
        '''
        from langchain_core.tools import tool as lc_tool
        from strands import tool as strands_tool


        @lc_tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        @strands_tool
        def close_case(case_id: str) -> None:
            """Close a case."""
        ''',
    )

    assert [p.name for p in collect(tmp_path).proposals] == ["get_case", "close_case"]


def test_a_local_name_shadowing_a_decorator_is_not_a_tool(tmp_path: Path) -> None:
    # `from mymod import helper as tool` names something that is not a
    # framework decorator, and resolving the alias is what keeps it out.
    write(
        tmp_path,
        "agent.py",
        '''
        from mymod import helper as tool


        @tool
        def get_case(case_id: str) -> dict:
            """Not a framework tool."""
        ''',
    )

    assert collect(tmp_path).proposals == []


def test_an_unrelated_decorator_declares_nothing(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        import functools


        @functools.cache
        def get_case(case_id: str) -> dict:
            """Not a tool."""
        ''',
    )

    with pytest.raises(ValueError, match="no tool declarations"):
        scan_source(tmp_path, "support")


def test_a_decorator_that_is_not_a_plain_name_is_ignored(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        @registry["tool"]
        def get_case(case_id: str) -> dict:
            """Not matched."""
        ''',
    )

    assert collect(tmp_path).proposals == []


def test_bind_tools_is_read_as_a_binding(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from langchain_core.tools import tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        @tool
        def delete_case(case_id: str) -> None:
            """Delete a case."""


        model = ChatModel().bind_tools([get_case])
        ''',
    )

    inventory = collect(tmp_path)

    assert [p.name for p in inventory.proposals] == ["get_case"]
    assert inventory.unbound == ["delete_case"]


def test_an_explicitly_empty_tool_list_is_refused(tmp_path: Path) -> None:
    # The blocker. Branching on whether any symbol was bound, rather than on
    # whether a list was found, turned `tools=[]` into every declared tool.
    # The agent has no authority and the manifest granted some.
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def refund(case_id: str, amount: float) -> str:
            """Refund."""


        agent = Agent(tools=[])
        ''',
    )

    with pytest.raises(InventoryError, match="is empty"):
        collect(tmp_path)


def test_bind_tools_with_no_argument_lists_nothing(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from langchain_core.tools import tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        model = ChatModel().bind_tools()
        ''',
    )

    # No list at all is not an empty list. Nothing was said about the tools,
    # so every declaration is offered and the note says the list is unnarrowed.
    inventory = collect(tmp_path)

    assert [p.name for p in inventory.proposals] == ["get_case"]
    assert "No agent was found" in " ".join(notes_for(inventory))


def test_an_unenumerable_tool_list_is_reported_rather_than_assumed(
    tmp_path: Path,
) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        second = Agent(tools=[get_case, *extra_tools])
        ''',
    )

    inventory = collect(tmp_path, binding="second")
    notes = " ".join(notes_for(inventory))

    assert "*extra_tools" in notes
    # Silence here would mean the next release diff called those tools new.
    assert "diff would report them as newly added authority" in notes


def test_a_bound_tool_declared_outside_the_scanned_path_is_reported(
    tmp_path: Path,
) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from partner_kit import lookup_partner
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        agent = Agent(tools=[get_case, lookup_partner])
        ''',
    )

    inventory = collect(tmp_path)

    assert inventory.undeclared == ["lookup_partner"]
    assert "Widen --source" in " ".join(notes_for(inventory))


def test_a_dotted_tool_reference_is_resolved_through_its_module(
    tmp_path: Path,
) -> None:
    write(tmp_path, "pkg/tools.py", STRANDS_AGENT)
    write(
        tmp_path,
        "pkg/main.py",
        """
        from strands import Agent

        from . import tools

        agent = Agent(tools=[tools.draft_email])
        """,
    )

    assert "draft_email" in [
        p.name for p in collect(tmp_path, binding="agent").proposals
    ]


def test_more_than_one_agent_is_refused_rather_than_merged(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        @tool
        def delete_case(case_id: str) -> None:
            """Delete a case."""


        triage = Agent(tools=[get_case])
        resolver = Agent(tools=[delete_case])
        ''',
    )

    # A union claims one agent holds every tool in the system, and `reach`
    # would then compose a path across tools that never share a run. A gate
    # reporting breaches nobody can reach is a gate that gets switched off.
    with pytest.raises(InventoryError) as raised:
        collect(tmp_path)

    assert "more than one agent" in str(raised.value)
    assert "triage" in str(raised.value)
    assert "resolver" in str(raised.value)


def test_a_named_binding_selects_one_agent(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        @tool
        def delete_case(case_id: str) -> None:
            """Delete a case."""


        triage = Agent(tools=[get_case])
        resolver = Agent(tools=[delete_case])
        ''',
    )

    inventory = collect(tmp_path, binding="resolver")

    assert [p.name for p in inventory.proposals] == ["delete_case"]
    assert inventory.unbound == ["get_case"]
    assert "resolver" in notes_for(inventory)[0]


def test_a_union_is_available_but_labelled(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        @tool
        def delete_case(case_id: str) -> None:
            """Delete a case."""


        triage = Agent(tools=[get_case])
        resolver = Agent(tools=[delete_case])
        ''',
    )

    inventory = collect(tmp_path, union=True)

    assert [p.name for p in inventory.proposals] == ["get_case", "delete_case"]
    assert "union of every agent" in notes_for(inventory)[0]


def test_an_unknown_binding_name_lists_what_there_is(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    with pytest.raises(InventoryError, match="no tool binding called 'nope'"):
        collect(tmp_path, binding="nope")


def test_no_binding_at_all_says_so(tmp_path: Path) -> None:
    write(
        tmp_path,
        "tools.py",
        '''
        from strands import tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""
        ''',
    )

    inventory = collect(tmp_path)

    assert [p.name for p in inventory.proposals] == ["get_case"]
    assert "No agent was found" in " ".join(notes_for(inventory))


def test_an_unparsable_file_is_named_and_the_rest_survives(tmp_path: Path) -> None:
    write(tmp_path, "good.py", STRANDS_AGENT)
    write(tmp_path, "broken.py", "def oops(:\n")

    inventory = collect(tmp_path)

    assert inventory.files_read == 1
    assert inventory.unreadable == ["broken.py: SyntaxError"]
    assert "Could not parse broken.py" in " ".join(notes_for(inventory))
    assert inventory.proposals


def test_installed_and_generated_directories_are_skipped(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)
    write(
        tmp_path,
        ".venv/lib/vendor.py",
        '''
        from strands import tool


        @tool
        def vendor_tool(x: str) -> str:
            """Not this agent's authority."""
        ''',
    )

    assert "vendor_tool" not in [p.name for p in collect(tmp_path).proposals]


def test_a_single_file_can_be_scanned(tmp_path: Path) -> None:
    path = write(tmp_path, "agent.py", STRANDS_AGENT)

    inventory = collect(path)

    assert inventory.files_read == 1
    assert [p.name for p in inventory.proposals] == ["search_cases", "issue_refund"]


def test_a_duplicate_declaration_keeps_the_first(tmp_path: Path) -> None:
    body = '''
        from strands import tool


        @tool
        def get_case(case_id: str) -> dict:
            """{}"""
        '''
    write(tmp_path, "a.py", body.format("First"))
    write(tmp_path, "b.py", body.format("Second"))

    proposals = collect(tmp_path).proposals

    assert len(proposals) == 1
    assert proposals[0].description == "First"


def test_a_missing_path_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        collect(tmp_path / "absent")


def test_a_directory_with_no_python_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("nothing here", encoding="utf-8")

    with pytest.raises(ValueError, match="no Python files"):
        collect(tmp_path)


def test_scan_source_renders_the_notes_before_the_manifest(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    rendered = scan_source(tmp_path, "refunds")

    notes_end = rendered.index("version: 1")
    assert "Declared but not given to this agent: draft_email" in rendered[:notes_end]
    assert rendered.index("REVIEW") < notes_end
    assert 'agent: "refunds"' in rendered


def test_a_long_note_wraps_without_repeating_the_marker(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    rendered = scan_source(tmp_path, "refunds")
    review_lines = [
        line for line in rendered.splitlines() if line.startswith("# REVIEW:")
    ]

    # A repeated marker on a wrapped line reads as several findings.
    assert len(review_lines) < len(notes_for(collect(tmp_path))) + 4
    assert any(line.startswith("#         ") for line in rendered.splitlines())


def test_the_generated_skeleton_is_a_loadable_manifest_once_reviewed(
    tmp_path: Path,
) -> None:
    from agentmandate import loads

    write(tmp_path, "agent.py", STRANDS_AGENT)
    rendered = scan_source(tmp_path, "refunds")

    # Everything a reviewer must decide is commented out, so what is left has
    # to parse on its own. A skeleton that does not load is not a start.
    mandate = loads(rendered)

    assert mandate.agent == "refunds"
    assert {tool.name for tool in mandate.tools} == {"search_cases", "issue_refund"}


def test_an_ambiguous_name_is_reported_rather_than_guessed(tmp_path: Path) -> None:
    # Two modules declaring `refund`, and the binding names neither. Choosing
    # one would attribute the wrong signature, scope, and ceiling.
    for name, body in [
        ("bank.py", "def refund(case_id: str, amount: float) -> str:"),
        ("support.py", "def refund(ticket_id: str) -> str:"),
    ]:
        write(
            tmp_path,
            name,
            f'''
            from strands import tool


            @tool
            {body}
                """Refund."""
            ''',
        )
    write(
        tmp_path,
        "agent.py",
        """
        from strands import Agent

        agent = Agent(tools=[refund])
        """,
    )

    inventory = collect(tmp_path)

    assert inventory.proposals == []
    assert inventory.ambiguous == ["refund (bank.py:refund, support.py:refund)"]
    assert "wrong signature" in " ".join(notes_for(inventory))


def test_the_importing_module_decides_which_declaration_is_meant(
    tmp_path: Path,
) -> None:
    # The defect this replaced picked whichever file sorted first, so the
    # bank's per-case ceiling was attributed to the support agent's tool.
    write(
        tmp_path,
        "bank.py",
        '''
        from strands import tool


        @tool
        def refund(case_id: str, amount: float) -> str:
            """Bank refund."""
        ''',
    )
    write(
        tmp_path,
        "support.py",
        '''
        from strands import Agent, tool


        @tool
        def refund(ticket_id: str) -> str:
            """Support refund."""


        agent = Agent(tools=[refund])
        ''',
    )

    proposal = collect(tmp_path).proposals[0]

    assert (proposal.scope, proposal.value_arg) == ("ticket", None)
    assert collect(tmp_path).unbound == ["bank.py:refund"]


def test_an_explicit_import_resolves_across_modules(tmp_path: Path) -> None:
    write(
        tmp_path,
        "bank.py",
        '''
        from strands import tool


        @tool
        def refund(case_id: str, amount: float) -> str:
            """Bank refund."""
        ''',
    )
    write(
        tmp_path,
        "support.py",
        '''
        from strands import tool


        @tool
        def refund(ticket_id: str) -> str:
            """Support refund."""
        ''',
    )
    write(
        tmp_path,
        "agent.py",
        """
        from strands import Agent

        from .bank import refund

        agent = Agent(tools=[refund])
        """,
    )

    proposal = collect(tmp_path).proposals[0]

    assert (proposal.scope, proposal.value_arg) == ("case", "amount")


def test_a_tools_keyword_on_a_non_agent_is_not_a_binding(tmp_path: Path) -> None:
    # `render_panel(tools=[...])` previously decided the whole inventory.
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import tool
        from ui import render_panel


        @tool
        def wipe_database(confirm: bool) -> None:
            """Not this agent's authority."""


        render_panel(tools=[wipe_database])
        ''',
    )

    inventory = collect(tmp_path)
    notes = " ".join(notes_for(inventory))

    assert inventory.selected is None
    assert "does not look like an agent" in notes
    assert "--binding" in notes


def test_an_ignored_call_site_can_still_be_selected(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        @tool
        def delete_case(case_id: str) -> None:
            """Delete a case."""


        support = build_my_own_thing(tools=[get_case])
        ''',
    )

    inventory = collect(tmp_path, binding="support")

    assert [p.name for p in inventory.proposals] == ["get_case"]
    assert inventory.unbound == ["delete_case"]


def test_a_decorator_from_an_unknown_module_is_flagged(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from internal_helpers import tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""
        ''',
    )

    notes = " ".join(notes_for(collect(tmp_path)))

    # Re-exported decorators are common, so this is included and questioned
    # rather than dropped.
    assert "does not recognise as an agent framework" in notes
    assert "internal_helpers" in notes


def test_a_framework_decorator_is_not_flagged(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    assert collect(tmp_path).unconfirmed == []


def test_an_import_module_form_is_attributed(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        import strands


        @strands.tool
        def get_case(case_id: str) -> dict:
            """Read a case."""
        ''',
    )

    assert collect(tmp_path).unconfirmed == []


def test_a_binding_can_be_selected_by_location(tmp_path: Path) -> None:
    write(tmp_path, "agent.py", STRANDS_AGENT)

    where = collect(tmp_path).bindings[0].where
    inventory = collect(tmp_path, binding=where)

    assert [p.name for p in inventory.proposals] == ["search_cases", "issue_refund"]


def test_an_unnamed_binding_is_labelled_by_its_callee(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        run(Agent(tools=[get_case]))
        ''',
    )

    binding = collect(tmp_path).bindings[0]
    assert binding.label == f"Agent@{binding.where.split(':')[1]}"


def test_an_annotated_assignment_names_the_binding(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        resolver: Agent = Agent(tools=[get_case])
        ''',
    )

    assert collect(tmp_path).bindings[0].label == "resolver"


def test_a_computed_callee_is_still_recorded(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        FACTORIES[0](tools=[get_case])
        ''',
    )

    assert collect(tmp_path).bindings[0].callee == "<expression>"


def test_a_renamed_plain_import_is_attributed(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        import strands.tools as st


        @st.tool
        def get_case(case_id: str) -> dict:
            """Read a case."""
        ''',
    )

    assert collect(tmp_path).unconfirmed == []


def test_a_tool_list_that_is_a_bare_name_is_reported(tmp_path: Path) -> None:
    write(
        tmp_path,
        "agent.py",
        '''
        from strands import Agent, tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        agent = Agent(tools=TOOLS)
        ''',
    )

    inventory = collect(tmp_path)

    assert inventory.proposals == []
    assert "TOOLS" in " ".join(notes_for(inventory))


def test_one_declaration_across_modules_needs_no_import_to_resolve(
    tmp_path: Path,
) -> None:
    # Only one `refund` exists anywhere, so the reference is unambiguous even
    # though the binding module never imported it in a form this can see.
    write(
        tmp_path,
        "tools.py",
        '''
        from strands import tool


        @tool
        def refund(case_id: str, amount: float) -> str:
            """Refund."""
        ''',
    )
    write(
        tmp_path,
        "agent.py",
        """
        from strands import Agent
        from .tools import *

        agent = Agent(tools=[refund])
        """,
    )

    assert [p.name for p in collect(tmp_path).proposals] == ["refund"]


@pytest.mark.parametrize(
    "callee",
    [
        # Each of these matched the word test that this replaced, and none of
        # them builds an agent.
        "workflow_graph",
        "team_dashboard",
        "agent_metrics_panel",
        "render_swarm_chart",
        "assistant_docs",
    ],
)
def test_a_lookalike_callee_does_not_decide_the_inventory(
    tmp_path: Path, callee: str
) -> None:
    write(
        tmp_path,
        "agent.py",
        f'''
        from strands import tool


        @tool
        def wipe_database(confirm: bool) -> None:
            """Not this agent's authority."""


        {callee}(tools=[wipe_database])
        ''',
    )

    inventory = collect(tmp_path)

    assert inventory.selected is None
    assert [c.callee for c in inventory.candidates] == [callee]


@pytest.mark.parametrize(
    "callee",
    [
        "Agent",
        "create_react_agent",
        "LlmAgent",
        "AssistantAgent",
        "ChatAgent",
        "AgentWorkflow",
        "ToolNode",
        "Crew",
        "Swarm",
    ],
)
def test_a_real_constructor_is_the_binding(tmp_path: Path, callee: str) -> None:
    write(
        tmp_path,
        "agent.py",
        f'''
        from strands import tool


        @tool
        def get_case(case_id: str) -> dict:
            """Read a case."""


        @tool
        def delete_case(case_id: str) -> None:
            """Delete a case."""


        agent = {callee}(tools=[get_case])
        ''',
    )

    inventory = collect(tmp_path)

    assert [p.name for p in inventory.proposals] == ["get_case"]
    assert inventory.unbound == ["delete_case"]
