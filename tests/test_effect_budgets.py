"""A declared budget bounds how many calls of an effect class a run may make.

Two real graphs asked for non-monetary effect budgets: `Limits` carried only a
`Money` ceiling, so every cumulative question the search could ask was a
question about currency, and a graph with no currency got "no reachable breach"
on an agent that can write a workflow, run it with secrets, and delete the logs.

See DESIGN.md, "Counting effects, not only value".
"""

import pytest

from agentmandate import analyse, loads
from agentmandate.manifest import ManifestError

# `wipe` neither mints a scope nor spends against a ceiling. Before budgets
# existed the walk skipped it as reaching no new state, so a path could never
# contain it twice. That is the trap this feature had to avoid shipping into.
DESTRUCTIVE = """
agent: janitor
limits:
  depth: 8
  effects:
    irreversible: 3
tools:
  - name: look
    effect: read
  - name: wipe
    effect: irreversible
    requires_approval: true
"""

NO_BUDGET = DESTRUCTIVE.replace("  effects:\n    irreversible: 3\n", "")


def test_a_budget_is_exceeded_by_repeating_one_tool():
    """The case the search could not previously represent at all."""
    authority = analyse(loads(DESTRUCTIVE))
    breaches = [b for b in authority.breaches if b.kind == "effect_count"]

    assert breaches, "a fourth irreversible call is above a budget of three"
    assert "reach 4" in breaches[0].detail
    assert [step.tool for step in breaches[0].path] == ["wipe"] * 4


def test_without_a_budget_nothing_changes():
    """Declared only. An absent class is unbounded, not zero.

    Inventing a ceiling is the same mistake as inventing a reversibility
    label, and this model already refuses that one.
    """
    authority = analyse(loads(NO_BUDGET))

    assert not [b for b in authority.breaches if b.kind == "effect_count"]
    assert "wipe" in authority.reachable_tools


def test_a_budget_of_zero_forbids_the_class_outright():
    authority = analyse(loads(DESTRUCTIVE.replace("irreversible: 3", "irreversible: 0")))
    breaches = [b for b in authority.breaches if b.kind == "effect_count"]

    assert breaches
    assert [step.tool for step in breaches[0].path] == ["wipe"]


def test_a_budget_bounds_the_class_and_not_one_tool():
    """Two different irreversible tools share one budget.

    A per-tool count is a rate limit and belongs at the tool. What a reviewer
    bounds here is the blast radius of a class.
    """
    two_tools = DESTRUCTIVE + """  - name: purge
    effect: irreversible
    requires_approval: true
"""
    authority = analyse(loads(two_tools))
    breaches = [b for b in authority.breaches if b.kind == "effect_count"]

    assert breaches
    assert len(breaches[0].path) == 4


def test_a_budget_on_one_class_leaves_the_others_alone():
    """Reads are unbounded here, so they must not consume the budget."""
    reads = DESTRUCTIVE.replace("irreversible: 3", "write: 1")
    authority = analyse(loads(reads))

    assert not [b for b in authority.breaches if b.kind == "effect_count"]


@pytest.mark.parametrize(
    ("declared", "message"),
    [
        ("effects:\n    destructive: 3", "unknown effect class"),
        ("effects:\n    irreversible: -1", "whole number of calls"),
        ("effects:\n    irreversible: true", "whole number of calls"),
        ("effects:\n    irreversible: 1.5", "whole number of calls"),
        ("effects: []", "expected a mapping"),
    ],
)
def test_a_budget_it_cannot_honour_is_refused(declared, message):
    """Refused when the manifest loads, before any search runs."""
    source = DESTRUCTIVE.replace("effects:\n    irreversible: 3", declared)

    with pytest.raises(ManifestError, match=message):
        loads(source)


def test_the_money_ceiling_still_works_beside_a_budget():
    """The axes are independent, and neither disables the other."""
    both = """
agent: both
limits:
  total: { amount: 100, currency: GBP }
  depth: 8
  effects:
    irreversible: 99
tools:
  - name: open_case
    effect: read
    produces: case
    unbounded: true
  - name: refund
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: { amount: 100, currency: GBP }
    requires_approval: true
"""
    kinds = {b.kind for b in analyse(loads(both)).breaches}

    assert "cumulative_value" in kinds


def test_two_classes_over_budget_are_reported_once_each():
    """The dedup keys on the subject, not on how the message is worded.

    It matched a prefix of `detail` while every message happened to open with
    the effect name. A reworded message would have produced one breach per
    extra call, and nothing would have failed to say so.
    """
    both = """
agent: two
limits:
  depth: 8
  effects:
    write: 1
    irreversible: 1
tools:
  - name: edit
    effect: write
  - name: wipe
    effect: irreversible
    requires_approval: true
"""
    breaches = [b for b in analyse(loads(both)).breaches if b.kind == "effect_count"]

    assert sorted(b.subject for b in breaches) == ["irreversible", "write"]
    assert len(breaches) == 2, "one per class, however many calls exceeded it"


def test_the_json_contract_is_unchanged():
    """`subject` is how the search decides it has already spoken, not a
    finding. The published shape stays kind, detail and path."""
    authority = analyse(loads(DESTRUCTIVE))

    payload = authority.as_dict()["breaches"][0]

    assert sorted(payload) == ["detail", "kind", "path"]
