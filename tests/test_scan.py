import json

import pytest

from agentmandate import loads, propose, render, scan_file

CATALOGUE = {
    "tools": [
        {
            "name": "search_cases",
            "description": "Find dispute cases.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        },
        {
            "name": "issue_refund",
            "description": "Refund against a case.",
            "inputSchema": {
                "type": "object",
                "properties": {"case_id": {"type": "string"}, "amount": {"type": "number"}},
            },
        },
        {
            "name": "update_case_notes",
            "inputSchema": {"type": "object", "properties": {"case_id": {"type": "string"}}},
        },
    ]
}


def by_name(proposals):
    return {p.name: p for p in proposals}


def test_read_verbs_are_recognised_without_guessing():
    proposal = by_name(propose(CATALOGUE))["search_cases"]
    assert proposal.effect == "read"
    assert proposal.guessed_effect is False


def test_write_verbs_are_proposed_as_write_and_marked_as_a_guess():
    proposal = by_name(propose(CATALOGUE))["update_case_notes"]
    assert proposal.effect == "write"
    assert proposal.guessed_effect is True


def test_an_unrecognised_verb_defaults_to_irreversible():
    """Under-calling an effect is the expensive mistake, so the default is strict."""
    proposal = by_name(propose(CATALOGUE))["issue_refund"]
    assert proposal.effect == "irreversible"
    assert proposal.guessed_effect is True


def test_an_id_argument_becomes_a_scope():
    assert by_name(propose(CATALOGUE))["issue_refund"].scope == "case"


def test_a_numeric_amount_argument_is_detected_as_value():
    assert by_name(propose(CATALOGUE))["issue_refund"].value_arg == "amount"


def test_a_bare_list_of_tools_is_accepted():
    assert len(propose(CATALOGUE["tools"])) == 3


def test_snake_case_input_schema_is_accepted():
    proposals = propose(
        [{"name": "pay", "input_schema": {"properties": {"case_id": {"type": "string"}}}}]
    )
    assert proposals[0].scope == "case"


def test_entries_without_a_name_are_skipped():
    assert propose([{"description": "no name"}, {"name": "get_x"}]) != []
    assert len(propose([{"description": "no name"}, {"name": "get_x"}])) == 1


def test_a_payload_that_is_not_a_catalogue_is_rejected():
    with pytest.raises(ValueError, match="tools/list payload"):
        propose({"nope": True})


def test_the_skeleton_marks_every_guess_for_review():
    text = render(propose(CATALOGUE), "dispute-resolver")
    assert "REVIEW: effect guessed from the name" in text
    assert "REVIEW: does this spend the caller's authority" in text
    assert "REVIEW: amount looks like a value argument" in text


def test_the_skeleton_warns_that_no_tool_mints_a_scope():
    """Without a `produces`, every `requires` is unreachable and the analysis
    would silently report nothing."""
    text = render(propose(CATALOGUE), "a")
    assert "no tool was detected as producing a scope" in text
    assert "Scopes referenced: case" in text


def test_an_irreversible_proposal_gets_an_approval_requirement():
    text = render(propose(CATALOGUE), "a")
    assert "requires_approval: true" in text


def test_the_skeleton_is_a_parseable_manifest_once_yaml_reads_it():
    """The comments must not make the output invalid YAML."""
    text = render(propose(CATALOGUE), "dispute-resolver")
    mandate = loads(text)
    assert mandate.agent == "dispute-resolver"
    assert "issue_refund" in mandate.tool_names


def test_scan_file_reads_from_disk(tmp_path):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(CATALOGUE), encoding="utf-8")
    assert 'agent: "x"' in scan_file(path, "x")


def test_a_catalogue_with_no_scopes_omits_the_scope_warning():
    text = render(propose([{"name": "get_status"}]), "a")
    assert "Scopes referenced" not in text


def test_untrusted_catalogue_text_cannot_inject_yaml():
    catalogue = {
        "tools": [
            {
                "name": "get_case: privileged",
                "description": "Safe line\n- name: injected\n  effect: irreversible",
            }
        ]
    }
    text = render(propose(catalogue), "agent: privileged")
    mandate = loads(text)
    assert mandate.agent == "agent: privileged"
    assert mandate.tool_names == ("get_case: privileged",)
    assert "\n  - name: injected" not in text


def test_control_characters_in_tool_names_are_rejected():
    with pytest.raises(ValueError, match="control character"):
        propose([{"name": "get_ok\nprincipal: service"}])


def test_duplicate_tool_names_are_rejected_before_rendering():
    with pytest.raises(ValueError, match="duplicate name"):
        propose([{"name": "get_case"}, {"name": "get_case"}])


def test_an_empty_catalogue_does_not_emit_an_invalid_manifest():
    with pytest.raises(ValueError, match="no named tools"):
        render(propose([]), "a")


def test_a_blank_tool_name_is_skipped():
    assert propose([{"name": "   "}, {"name": "get_x"}]) == propose([{"name": "get_x"}])


@pytest.mark.parametrize("agent", ["", "   "])
def test_a_blank_agent_name_is_rejected(agent):
    with pytest.raises(ValueError, match="agent name must be a non-empty string"):
        render(propose([{"name": "get_x"}]), agent)


def test_an_agent_name_with_a_control_character_is_rejected():
    """The skeleton is rendered as text, so a newline in the agent name would
    let the caller write their own YAML."""
    with pytest.raises(ValueError, match="must not contain control characters"):
        render(propose([{"name": "get_x"}]), "demo\n  effect: read")
