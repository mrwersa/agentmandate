"""A small agent, written the way agents are usually written.

Run `mandate scan --source examples/refund_agent.py --agent refunds` against
this file to see what a static read can and cannot establish. Nothing here is
imported or executed by that command, and the frameworks it names do not need
to be installed.
"""

from decimal import Decimal

from strands import Agent, tool


@tool
def search_cases(query: str) -> list[dict]:
    """Find support cases matching a free-text query.

    Returns summaries only. The second paragraph of a docstring is left out of
    the manifest comment, because a manifest is not documentation.
    """


@tool
def open_case(customer_id: str) -> str:
    """Open a support case for a customer."""


@tool("issue_refund")
async def refund(case_id: str, amount: Decimal, currency: str) -> str:
    """Return money to the customer for a case."""


@tool
def close_case(case_id: str, note: str) -> None:
    """Close a case."""


@tool
def draft_email(case_id: str, body: str) -> str:
    """Draft a customer email for a human to send.

    This one is never given to the agent below, so it is reported as defined
    but unbound rather than folded into the mandate.
    """


agent = Agent(
    model="claude-sonnet-5",
    tools=[search_cases, open_case, refund, close_case],
)
