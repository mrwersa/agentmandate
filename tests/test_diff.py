import json

import pytest

from agentmandate import Mandate, compare, loads
from agentmandate.cli import main
from agentmandate.diff import NARROWING, NEUTRAL, WIDENING

V1 = """
agent: dispute
limits:
  total: { amount: 500, currency: GBP }
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

# The whole change is one read-only tool.
V2 = V1.replace(
    "tools:\n",
    "tools:\n  - name: search_cases\n    effect: read\n"
    "    produces: case\n    unbounded: true\n",
)


def test_an_unchanged_manifest_is_neutral():
    delta = compare(loads(V1), loads(V1))
    assert delta.direction == NEUTRAL
    assert delta.widened is False
    assert delta.changes == ()


def test_a_read_only_addition_is_reported_as_widening():
    """The headline case. Two lines of config, a new reachable breach."""
    delta = compare(loads(V1), loads(V2))
    assert delta.widened is True
    kinds = {change.kind for change in delta.changes}
    assert "tool" in kinds
    assert "extractable value" in kinds
    assert "reachable breach" in kinds


def test_removing_a_tool_narrows_authority():
    delta = compare(loads(V2), loads(V1))
    assert delta.direction == NARROWING
    assert delta.widened is False
    assert any(c.detail == "lost search_cases" for c in delta.changes)


def test_extractable_value_change_is_quantified():
    delta = compare(loads(V1), loads(V2))
    change = next(c for c in delta.changes if c.kind == "extractable value")
    assert change.detail.startswith("500 -> ")
    assert change.detail.endswith("GBP")


def test_removing_an_approval_requirement_is_widening():
    relaxed = V1.replace("    requires_approval: true\n", "")
    delta = compare(loads(V1), loads(relaxed))
    assert delta.widened is True
    assert any(c.kind == "ungated irreversible" for c in delta.changes)


def test_switching_to_a_service_principal_is_widening():
    swapped = V1.replace(
        "  - name: issue_refund\n    effect: irreversible\n",
        "  - name: issue_refund\n    effect: irreversible\n    principal: service\n",
    )
    delta = compare(loads(V1), loads(swapped))
    assert any(c.kind == "service principal" for c in delta.changes)
    assert delta.widened is True


def test_an_effect_reaching_a_new_scope_is_widening():
    extended = V1 + (
        "  - name: open_ledger\n    effect: read\n    produces: ledger\n"
        "  - name: post_entry\n    effect: irreversible\n    requires: [ledger]\n"
    )
    delta = compare(loads(V1), loads(extended))
    assert any(
        c.kind == "effect" and c.detail == "gained irreversible on ledger"
        for c in delta.changes
    )


def test_another_tool_with_an_existing_effect_and_scope_adds_no_effect_change():
    """A second irreversible tool on `case` is a new tool, not new authority
    over that scope. The tool change is still reported."""
    extended = V1 + "  - name: shred\n    effect: irreversible\n    requires: [case]\n"
    delta = compare(loads(V1), loads(extended))
    assert not any(c.kind == "effect" for c in delta.changes)
    assert any(c.detail == "gained shred" for c in delta.changes)


def test_depth_is_passed_through_to_both_sides():
    delta = compare(loads(V1), loads(V2), depth=2)
    assert delta.before.depth == 2
    assert delta.after.depth == 2


def test_render_labels_both_sides_and_states_the_verdict():
    rendered = compare(loads(V1), loads(V2)).render("v1.yaml", "v2.yaml")
    assert "v1.yaml -> v2.yaml" in rendered
    assert "verdict: WIDENING" in rendered
    assert "needs named review" in rendered


def test_render_says_so_when_nothing_changed():
    rendered = compare(loads(V1), loads(V1)).render()
    assert "no change in effective authority" in rendered
    assert "verdict: NEUTRAL" in rendered


def test_delta_serialises_both_sides():
    payload = compare(loads(V1), loads(V2)).as_dict()
    assert payload["direction"] == WIDENING
    assert "search_cases" in payload["after"]["reachable_tools"]
    assert "search_cases" not in payload["before"]["reachable_tools"]
    assert payload["changes"]


def test_change_render_marks_direction():
    delta = compare(loads(V1), loads(V2))
    assert any(c.render().strip().startswith("+") for c in delta.changes)
    assert compare(loads(V2), loads(V1)).changes[0].render().strip().startswith("-")


def test_the_change_record_names_the_agent_and_the_verdict():
    record = compare(loads(V1), loads(V2)).record("v1.yaml", "v2.yaml")
    assert "# Agent authority change record" in record
    assert "**Agent:** dispute" in record
    assert "**Verdict:** WIDENING" in record
    assert "`v1.yaml` against `v2.yaml`" in record


def test_the_change_record_separates_gained_from_removed():
    record = compare(loads(V1), loads(V2)).record()
    gained = record.split("## Authority gained")[1].split("## Authority removed")[0]
    removed = record.split("## Authority removed")[1].split("## Reachable breaches")[0]
    assert "gained search_cases" in gained
    assert "none" in removed


def test_the_change_record_asks_for_a_named_reviewer_when_widening():
    assert "named reviewer" in compare(loads(V1), loads(V2)).record()


def test_the_change_record_says_so_when_nothing_widened():
    record = compare(loads(V1), loads(V1)).record()
    assert "does not widen" in record
    assert "none within the search depth" in record


def test_the_change_record_carries_the_caveat_about_unchanged_manifests():
    """The record is evidence about the manifest, not about the deployment."""
    assert "unchanged manifest does not prove" in compare(loads(V1), loads(V2)).record()


def test_raising_the_run_limit_is_widening_even_when_the_graph_is_unchanged():
    raised = V1.replace("total: { amount: 500", "total: { amount: 1000")
    delta = compare(loads(V1), loads(raised))
    assert delta.widened is True
    assert any(
        change.kind == "run limit" and "500 -> 1000 GBP" in change.detail
        for change in delta.changes
    )


def test_removing_the_run_limit_is_widening():
    removed = V1.replace("limits:\n  total: { amount: 500, currency: GBP }\n", "")
    delta = compare(loads(V1), loads(removed))
    assert delta.widened is True
    assert any(
        change.kind == "run limit" and "removed limit" in change.detail
        for change in delta.changes
    )


def test_cross_currency_amounts_are_not_compared_numerically():
    changed = V1.replace("500, currency: GBP", "1, currency: USD")
    delta = compare(loads(V1), loads(changed))
    assert delta.widened is True
    assert any(
        "amounts are not comparable" in change.detail for change in delta.changes
    )


def test_removing_a_required_scope_is_widening():
    relaxed = V1.replace("    requires: [case]\n", "")
    delta = compare(loads(V1), loads(relaxed))
    assert delta.widened is True
    assert any(
        change.kind == "precondition" and "removed required scope case" in change.detail
        for change in delta.changes
    )


def test_adding_a_required_scope_is_narrowing_not_widening():
    restricted = V1.replace("    requires: [case]\n", "    requires: [case, approval]\n")
    # Give the released and proposed graphs the binding so the tool remains
    # reachable and only the contract change is under comparison.
    seed = "  - name: grant_approval\n    effect: read\n    produces: approval\n"
    before = V1.replace("tools:\n", f"tools:\n{seed}")
    after = restricted.replace("tools:\n", f"tools:\n{seed}")
    delta = compare(loads(before), loads(after))
    assert delta.direction == NARROWING
    assert any(
        change.kind == "precondition" and "added required scope approval" in change.detail
        for change in delta.changes
    )


def test_removing_approval_from_a_write_tool_is_widening():
    gated = V1 + (
        "  - name: note_case\n"
        "    effect: write\n"
        "    requires: [case]\n"
        "    requires_approval: true\n"
    )
    relaxed = gated.replace(
        "    effect: write\n    requires: [case]\n    requires_approval: true\n",
        "    effect: write\n    requires: [case]\n",
    )
    delta = compare(loads(gated), loads(relaxed))
    assert delta.widened is True
    assert any(
        change.kind == "approval" and "note_case: approval removed" in change.detail
        for change in delta.changes
    )


def test_lowering_the_default_search_depth_cannot_hide_authority():
    deep = V2.replace(
        "  total: { amount: 500, currency: GBP }\n",
        "  total: { amount: 500, currency: GBP }\n  depth: 8\n",
    )
    shallow = deep.replace("  depth: 8", "  depth: 1")
    delta = compare(loads(deep), loads(shallow))
    assert delta.before.depth == 8
    assert delta.after.depth == 8
    assert delta.widened is True
    assert any(change.kind == "analysis depth" for change in delta.changes)


def test_comparison_uses_the_larger_default_depth_on_both_sides():
    shallow = V1.replace(
        "  total: { amount: 500, currency: GBP }\n",
        "  total: { amount: 500, currency: GBP }\n  depth: 2\n",
    )
    delta = compare(loads(shallow), loads(V1))
    assert delta.before.depth == 8
    assert delta.after.depth == 8


def test_different_agents_are_not_comparable():
    with pytest.raises(ValueError, match="cannot compare different agents"):
        compare(loads(V1), loads(V1.replace("agent: dispute", "agent: another")))


def test_removing_or_changing_workload_identity_needs_review():
    identified = V1.replace("agent: dispute\n", "agent: dispute\nidentity: spiffe://a\n")
    removed = compare(loads(identified), loads(V1))
    changed = compare(
        loads(identified),
        loads(identified.replace("spiffe://a", "spiffe://b")),
    )
    assert removed.widened is True
    assert changed.widened is True
    assert any(change.kind == "workload identity" for change in removed.changes)
    assert any(change.kind == "workload identity" for change in changed.changes)


def test_changing_the_value_argument_needs_review():
    changed = V1.replace("    value_arg: amount", "    value_arg: refund_amount")
    delta = compare(loads(V1), loads(changed))
    assert delta.widened is True
    assert any(change.kind == "value argument" for change in delta.changes)


# The controls below are the reason this PR exists, so each direction is
# pinned. An untested widening rule is a gate that might not be there.

BASE = """
agent: a
limits: {total: {amount: 500, currency: GBP}}
tools:
  - name: seed
    effect: read
    produces: case
  - name: act
    effect: read
    requires: [case]
"""


def only(changes, kind):
    return [c for c in changes if c.kind == kind]


def test_strengthening_an_effect_class_is_widening():
    after = BASE.replace("  - name: act\n    effect: read", "  - name: act\n    effect: write")
    delta = compare(loads(BASE), loads(after))
    change = only(delta.changes, "effect class")[0]
    assert change.detail == "act: read -> write"
    assert change.direction == WIDENING


def test_weakening_an_effect_class_is_narrowing():
    stronger = BASE.replace("  - name: act\n    effect: read", "  - name: act\n    effect: write")
    change = only(compare(loads(stronger), loads(BASE)).changes, "effect class")[0]
    assert change.direction == NARROWING


def test_letting_a_tool_mint_bindings_is_widening():
    """`unbounded` is the field that decides whether a ceiling means anything,
    so a release that flips it must not pass silently."""
    after = BASE.replace("    produces: case", "    produces: case\n    unbounded: true")
    change = only(compare(loads(BASE), loads(after)).changes, "scope minting")[0]
    assert change.detail == "seed: can now mint fresh bindings"
    assert change.direction == WIDENING


def test_removing_scope_minting_is_narrowing():
    unbounded = BASE.replace("    produces: case", "    produces: case\n    unbounded: true")
    change = only(compare(loads(unbounded), loads(BASE)).changes, "scope minting")[0]
    assert change.detail == "seed: can no longer mint fresh bindings"
    assert change.direction == NARROWING


def test_changing_the_produced_scope_needs_review():
    after = BASE.replace("    produces: case", "    produces: ledger")
    change = only(compare(loads(BASE), loads(after)).changes, "produced scope on seed")[0]
    assert change.direction == WIDENING
    assert "needs review" in change.detail


def test_adding_a_produced_scope_is_widening():
    plain = BASE.replace("    produces: case\n", "")
    change = only(compare(loads(plain), loads(BASE)).changes, "produced scope on seed")[0]
    assert change.direction == WIDENING
    assert change.detail == "added case"


def test_removing_a_produced_scope_is_narrowing():
    plain = BASE.replace("    produces: case\n", "")
    change = only(compare(loads(BASE), loads(plain)).changes, "produced scope on seed")[0]
    assert change.direction == NARROWING


CEILINGED = """
agent: a
limits: {total: {amount: 500, currency: GBP}}
tools:
  - name: seed
    effect: read
    produces: case
  - name: pay
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: {amount: 100, currency: GBP}
    requires_approval: true
"""


LEDGER_SCOPED = """
agent: a
limits: {total: {amount: 500, currency: GBP}}
tools:
  - name: seed
    effect: read
    produces: case
  - name: seed_ledger
    effect: read
    produces: ledger
  - name: pay
    effect: irreversible
    requires: [ledger]
    value_arg: amount
    scope_key: ledger
    ceiling: {amount: 100, currency: GBP}
    requires_approval: true
"""


def test_changing_the_ceiling_scope_makes_limits_incomparable():
    """Two ceilings of 100 measured against different scopes are not the same
    control, so the amounts must not be compared as if they were."""
    change = only(compare(loads(CEILINGED), loads(LEDGER_SCOPED)).changes, "ceiling scope")[0]
    assert change.direction == WIDENING
    assert "not comparable" in change.detail


# scope_key is kept on both sides so the comparison isolates the ceiling.
# Dropping it too would route to the "ceiling scope" rule above instead.
UNCAPPED = CEILINGED.replace(
    "    value_arg: amount\n    scope_key: case\n"
    "    ceiling: {amount: 100, currency: GBP}\n",
    "    scope_key: case\n",
)


def test_removing_a_ceiling_is_widening():
    change = only(compare(loads(CEILINGED), loads(UNCAPPED)).changes, "ceiling on pay")[0]
    assert change.direction == WIDENING
    assert "removed limit" in change.detail


def test_adding_a_ceiling_is_narrowing():
    change = only(compare(loads(UNCAPPED), loads(CEILINGED)).changes, "ceiling on pay")[0]
    assert change.direction == NARROWING
    assert "added limit" in change.detail


def test_an_effect_reaching_a_newly_reachable_scope_is_reported():
    after = BASE + "  - name: post\n    effect: write\n    requires: [case]\n"
    changes = compare(loads(BASE), loads(after)).changes
    assert any(c.kind == "effect" and c.detail == "gained write on case" for c in changes)


def test_an_effect_lost_with_its_tool_is_reported():
    richer = BASE + "  - name: post\n    effect: write\n    requires: [case]\n"
    changes = compare(loads(richer), loads(BASE)).changes
    assert any(c.kind == "effect" and c.detail == "lost write on case" for c in changes)


def test_comparing_different_agents_is_refused():
    """Pointing diff at the wrong file produces a meaningless verdict, so it
    fails rather than reporting noise."""
    with pytest.raises(ValueError, match="cannot compare different agents"):
        compare(loads(BASE), loads(BASE.replace("agent: a", "agent: b")))


NO_MONEY = """
agent: a
tools:
  - name: seed
    effect: read
    produces: case
"""

WITH_MONEY = """
agent: a
limits: {total: {amount: 50, currency: GBP}}
tools:
  - name: seed
    effect: read
    produces: case
  - name: pay
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: {amount: 50, currency: GBP}
    requires_approval: true
"""


def test_an_agent_that_could_spend_nothing_and_now_can_is_widening():
    change = only(compare(loads(NO_MONEY), loads(WITH_MONEY)).changes, "extractable value")[0]
    assert change.direction == WIDENING
    assert change.detail == "gained 50 GBP"


def test_an_agent_that_can_no_longer_spend_is_narrowing():
    change = only(compare(loads(WITH_MONEY), loads(NO_MONEY)).changes, "extractable value")[0]
    assert change.direction == NARROWING
    assert change.detail == "removed 50 GBP"


def test_declaring_a_workload_identity_is_narrowing():
    """Naming the identity an agent runs as constrains it, so it is not a
    widening change even though the manifest gained a line."""
    identified = NO_MONEY.replace("agent: a", "agent: a\nidentity: spiffe://bank/agents/a")
    change = only(compare(loads(NO_MONEY), loads(identified)).changes, "workload identity")[0]
    assert change.direction == NARROWING
    assert change.detail == "declared spiffe://bank/agents/a"


def budget_mandate(budgets, *, effect="irreversible", depth=2):
    return Mandate.parse({
        "agent": "budget-regression", "limits": {"depth": depth, "effects": budgets},
        "tools": [{"name": "act", "effect": effect, "requires_approval": True}],
    })


@pytest.mark.parametrize("effect", ["read", "write", "irreversible"])
@pytest.mark.parametrize("previous,proposed,direction,detail", [
    (3, 5, WIDENING, "3 -> 5 calls"),
    (5, 3, NARROWING, "5 -> 3 calls"),
    (None, 3, NARROWING, "added limit 3 calls"),
    (3, None, WIDENING, "removed limit 3 calls"),
    (0, None, WIDENING, "removed limit 0 calls"),
    (None, 0, NARROWING, "added limit 0 calls"),
    (0, 1, WIDENING, "0 -> 1 calls"),
    (1, 0, NARROWING, "1 -> 0 calls"),
    (3, 3, NEUTRAL, None),
    (None, None, NEUTRAL, None),
])
def test_effect_allowance_changes_are_explicit_even_without_a_breach(
    effect, previous, proposed, direction, detail,
):
    before = budget_mandate({} if previous is None else {effect: previous}, effect=effect)
    after = budget_mandate({} if proposed is None else {effect: proposed}, effect=effect)
    delta = compare(before, after)
    allowance = only(delta.changes, "effect budget")
    if detail is None:
        assert not allowance and delta.direction == NEUTRAL
    else:
        assert [(c.direction, c.detail) for c in allowance] == [
            (direction, f"{effect}: {detail}"),
        ]
        if direction == WIDENING:
            assert delta.widened
        if previous in {None, 3, 5} and proposed in {None, 3, 5}:
            assert not delta.before.breaches and not delta.after.breaches
            assert delta.direction == direction


def test_removing_a_budget_is_widening_even_when_its_breach_disappears():
    before = budget_mandate({"irreversible": 3}, depth=8)
    after = budget_mandate({}, depth=8)
    delta = compare(before, after)
    assert {b.kind for b in delta.before.breaches} == {"effect_count"}
    assert not delta.after.breaches
    assert delta.direction == WIDENING
    assert any(c.kind == "reachable breach" and c.direction == NARROWING
               for c in delta.changes)
    assert only(delta.changes, "effect budget")[0].direction == WIDENING


def test_raising_a_budget_is_widening_when_both_releases_still_breach():
    delta = compare(budget_mandate({"irreversible": 3}, depth=8),
                    budget_mandate({"irreversible": 5}, depth=8))
    assert {b.kind for b in delta.before.breaches} == {"effect_count"}
    assert {b.kind for b in delta.after.breaches} == {"effect_count"}
    assert not only(delta.changes, "reachable breach")
    assert delta.direction == WIDENING


def test_mixed_budget_changes_are_not_net_summed_or_hidden_by_a_shared_breach_kind():
    before = budget_mandate({"write": 6, "read": 4, "irreversible": 0})
    after = budget_mandate({"write": 4, "read": 6})
    delta = compare(before, after)
    assert [(c.direction, c.detail) for c in only(delta.changes, "effect budget")] == [
        (WIDENING, "irreversible: removed limit 0 calls"),
        (WIDENING, "read: 4 -> 6 calls"),
        (NARROWING, "write: 6 -> 4 calls"),
    ]
    assert delta.direction == WIDENING
    assert before.limits.effects == {"write": 6, "read": 4, "irreversible": 0}
    assert after.limits.effects == {"write": 4, "read": 6}


def test_tighter_allowance_and_new_breach_remain_separate_review_signals():
    delta = compare(budget_mandate({}), budget_mandate({"irreversible": 0}))
    assert only(delta.changes, "effect budget")[0].direction == NARROWING
    assert only(delta.changes, "reachable breach")[0].direction == WIDENING
    assert delta.widened  # Existing conservative review policy is retained.


@pytest.mark.parametrize("proposed", [5, None])
@pytest.mark.parametrize("output", ["text", "json", "record"])
def test_cli_blocks_budget_relaxation_and_names_the_changed_allowance(
    proposed, output, tmp_path, capsys,
):
    paths = []
    for name, cap in (("before", 3), ("after", proposed)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps({
            "agent": "budget-cli", "limits": {
                "depth": 8, "effects": {} if cap is None else {"irreversible": cap},
            },
            "tools": [{"name": "act", "effect": "irreversible", "requires_approval": True}],
        }))
        paths.append(str(path))
    argv = ["diff", *paths] + ([] if output == "text" else [f"--{output}"])
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert not captured.err
    if output == "json":
        result = json.loads(captured.out)
        assert set(result) == {"direction", "changes", "before", "after"}
        assert result["direction"] == WIDENING
        assert any(c["kind"] == "effect budget" and c["direction"] == WIDENING
                   for c in result["changes"])
    else:
        assert "effect budget: irreversible:" in captured.out
        assert "WIDENING" in captured.out
