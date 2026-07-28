from agentmandate import compare, loads
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
