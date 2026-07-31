from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agentmandate.inventory import collect, notes_for
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


def test_bind_tools_with_no_argument_binds_nothing(tmp_path: Path) -> None:
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

    inventory = collect(tmp_path)

    # No list means nothing was bound here, so this falls back to listing every
    # declared tool and saying so, which over-lists rather than under-lists.
    assert inventory.bindings == []
    assert [p.name for p in inventory.proposals] == ["get_case"]


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


        agent = Agent(tools=load_tools())
        second = Agent(tools=[get_case, *extra_tools])
        ''',
    )

    inventory = collect(tmp_path)
    notes = " ".join(notes_for(inventory))

    assert "load_tools()" in notes
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


def test_a_dotted_tool_reference_is_resolved_by_its_trailing_name(
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

    assert "draft_email" in [p.name for p in collect(tmp_path).proposals]


def test_more_than_one_binding_is_declared_a_union(tmp_path: Path) -> None:
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

    notes = " ".join(notes_for(collect(tmp_path)))

    # A union of two agents' tools claims one agent can reach both, which is
    # exactly the overstatement `reach` would then act on.
    assert "2 tool bindings" in notes
    assert "union overstates" in notes


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
    assert "No `tools=[...]` binding was found" in " ".join(notes_for(inventory))


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
    assert "Defined but not bound to any agent: draft_email" in rendered[:notes_end]
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
