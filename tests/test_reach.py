from decimal import Decimal

import pytest

from agentmandate import analyse, loads
from agentmandate.reach import Step

CAPPED = """
agent: capped
limits:
  total: { amount: 500, currency: GBP }
  depth: 8
tools:
  - name: open_case
    effect: read
    produces: case
  - name: issue_refund
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: { amount: 500, currency: GBP }
    requires_approval: true
"""

# Identical, except the agent can mint cases at will.
UNBOUNDED = CAPPED.replace(
    "    produces: case\n", "    produces: case\n    unbounded: true\n"
)


def test_a_bounded_scope_keeps_the_ceiling_meaningful():
    authority = analyse(loads(CAPPED))
    assert authority.breaches == ()
    assert authority.max_extractable.amount == Decimal(500)


def test_an_unbounded_scope_makes_the_ceiling_unenforceable():
    """The point of the whole package: each call is legal, the sequence is not."""
    authority = analyse(loads(UNBOUNDED))
    assert len(authority.breaches) == 1
    breach = authority.breaches[0]
    assert breach.kind == "cumulative_value"
    assert "exceeds limit 500 GBP" in breach.detail
    assert authority.max_extractable.amount > Decimal(500)


def test_a_breach_reports_the_call_sequence_that_produces_it():
    breach = analyse(loads(UNBOUNDED)).breaches[0]
    called = [step.tool for step in breach.path]
    assert called.count("open_case") >= 2
    assert called.count("issue_refund") >= 2
    spent = sum(s.spent for s in breach.path if s.spent is not None)
    assert spent > Decimal(500)


def test_the_counterexample_is_the_shortest_one_found():
    breach = analyse(loads(UNBOUNDED)).breaches[0]
    # Two mints and two refunds is the minimum that can exceed a 500 limit
    # when each refund is itself capped at 500.
    assert len(breach.path) == 4


def test_depth_bounds_the_search_and_is_reported():
    authority = analyse(loads(UNBOUNDED), depth=2)
    assert authority.breaches == ()
    assert authority.truncated is True
    assert authority.depth == 2


def test_depth_argument_overrides_the_manifest():
    assert analyse(loads(UNBOUNDED), depth=3).depth == 3
    assert analyse(loads(UNBOUNDED)).depth == 8


def test_unreachable_tools_are_not_reported_as_reachable():
    mandate = loads(
        """
        agent: a
        tools:
          - name: needs_a_scope_nobody_makes
            effect: write
            requires: [ghost]
          - name: plain
            effect: read
            produces: case
        """
    )
    authority = analyse(mandate)
    assert "plain" in authority.reachable_tools
    assert "needs_a_scope_nobody_makes" not in authority.reachable_tools


def test_ungated_irreversible_and_service_principal_are_surfaced():
    mandate = loads(
        """
        agent: a
        tools:
          - name: seed
            effect: read
            produces: case
          - name: wipe
            effect: irreversible
            requires: [case]
          - name: ledger
            effect: write
            principal: service
            requires: [case]
        """
    )
    authority = analyse(mandate)
    assert authority.ungated_irreversible == frozenset({"wipe"})
    assert authority.service_principal_tools == frozenset({"ledger"})


def test_authority_serialises_to_plain_json_types():
    payload = analyse(loads(UNBOUNDED)).as_dict()
    assert payload["max_extractable"]["currency"] == "GBP"
    assert payload["breaches"][0]["kind"] == "cumulative_value"
    assert isinstance(payload["breaches"][0]["path"], list)
    assert payload["depth"] == 8


def test_max_extractable_is_absent_when_no_currency_is_declared():
    authority = analyse(loads("agent: a\ntools:\n  - name: t\n    effect: read\n"))
    assert authority.max_extractable is None


def test_currency_is_inferred_from_a_sole_ceiling_without_a_run_limit():
    mandate = loads(
        """
        agent: a
        tools:
          - name: seed
            effect: read
            produces: case
          - name: pay
            effect: irreversible
            requires: [case]
            value_arg: amount
            scope_key: case
            ceiling: { amount: 40, currency: USD }
            requires_approval: true
        """
    )
    authority = analyse(mandate)
    assert authority.breaches == ()
    assert authority.max_extractable.currency == "USD"
    assert authority.max_extractable.amount == Decimal(40)


def test_a_breach_renders_a_numbered_sequence():
    rendered = analyse(loads(UNBOUNDED)).breaches[0].render()
    assert rendered.startswith("BREACH ")
    assert "\n  1. " in rendered
    assert "\n  2. " in rendered


def test_step_render_covers_each_field_combination():
    assert Step("t").render() == "t"
    assert Step("t", binding="case#1").render() == "t(case#1)"
    assert (
        Step("t", binding="case#1", spent=Decimal(5), currency="GBP").render()
        == "t(case#1, 5 GBP)"
    )


def test_a_read_only_addition_can_widen_reach():
    """A tool that writes nothing can still make a money bound unenforceable."""
    before = analyse(loads(CAPPED))
    after = analyse(
        loads(
            CAPPED.replace(
                "tools:\n",
                "tools:\n  - name: search_cases\n    effect: read\n"
                "    produces: case\n    unbounded: true\n",
            )
        )
    )
    assert before.breaches == ()
    assert after.breaches != ()


UNGATED = """
agent: a
tools:
  - name: open_case
    effect: read
    produces: case
  - name: shred_case
    effect: irreversible
    requires: [case]
"""


def test_an_ungated_irreversible_effect_is_reported_with_the_path_to_it():
    """Knowing the tool exists is lint. Knowing the agent can get to it, and
    how, is what decides whether it matters."""
    authority = analyse(loads(UNGATED))
    breach = next(b for b in authority.breaches if b.kind == "ungated_effect")
    assert breach.path[-1].tool == "shred_case"
    assert [s.tool for s in breach.path] == ["open_case", "shred_case"]
    assert "reachable in 2 call(s)" in breach.detail


def test_an_unreachable_ungated_effect_produces_no_breach():
    mandate = loads(
        """
        agent: a
        tools:
          - name: shred
            effect: irreversible
            requires: [never_minted]
        """
    )
    authority = analyse(mandate)
    assert authority.breaches == ()
    assert authority.ungated_irreversible == frozenset()


def test_each_ungated_tool_is_reported_once():
    mandate = loads(UNGATED + "  - name: purge\n    effect: irreversible\n    requires: [case]\n")
    kinds = [b for b in analyse(mandate).breaches if b.kind == "ungated_effect"]
    assert {b.path[-1].tool for b in kinds} == {"shred_case", "purge"}
    assert len(kinds) == 2


def test_a_gated_irreversible_effect_is_not_a_breach():
    gated = UNGATED + "    requires_approval: true\n"
    assert analyse(loads(gated)).breaches == ()


def test_a_non_positive_depth_is_rejected():
    with pytest.raises(ValueError, match="depth must be a positive integer"):
        analyse(loads(CAPPED), depth=0)
