import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTCORE = ROOT / "docs" / "evidence" / "agentcore-refund-policy"
ANTHROPIC = ROOT / "docs" / "evidence" / "anthropic-managed-budget"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agentcore_projector = _module(AGENTCORE / "project_continuation.py", "agentcore_continuation")
managed_projector = _module(ANTHROPIC / "project_continuation.py", "managed_continuation")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_managed_agents_classifications_rederive_from_sanitised_trials():
    protocol = _read(ANTHROPIC / "continuation-protocol.json")
    evidence = _read(ANTHROPIC / "continuation-confirmation.json")
    summary = _read(ANTHROPIC / "continuation-summary.json")

    assert evidence["protocol_sha256"] == _sha256(ANTHROPIC / "continuation-protocol.json")
    assert evidence["stopped"] is None
    assert evidence["cleanup"]["complete"] is True
    assert evidence["trials_per_cell_observed"] == dict.fromkeys(managed_projector.CELLS, 10)
    counts: dict[str, dict[str, int]] = {cell: {} for cell in managed_projector.CELLS}
    for trial in evidence["trials"]:
        classification = managed_projector._classify(trial, protocol)
        assert classification == trial["classification"]
        key = classification or "nonconforming"
        counts[trial["cell"]][key] = counts[trial["cell"]].get(key, 0) + 1
    assert {cell: result["classifications"] for cell, result in summary["results"].items()} == {
        cell: dict(sorted(values.items())) for cell, values in counts.items()
    }


def test_agentcore_matrix_summary_rederives_from_sanitised_events():
    protocol = _read(AGENTCORE / "continuation-protocol.json")
    events = _read(AGENTCORE / "continuation-events.json")
    summary = _read(AGENTCORE / "continuation-summary.json")

    assert summary["arms"] == agentcore_projector._summary(protocol, events["trials"])
    assert summary["controls"] == {"preflight": True, "postflight": True}
    assert summary["stopped"] is None
    assert len(events["trials"]) == 6 * protocol["trials_per_arm"]


def test_agentcore_recorded_statements_are_pinned_templates():
    protocol = _read(AGENTCORE / "continuation-protocol.json")
    events = _read(AGENTCORE / "continuation-events.json")
    marker = agentcore_projector.MARKER

    def check(statement):
        if statement is None:
            return
        template = (AGENTCORE / statement["template"]).read_text(encoding="utf-8").rstrip("\n")
        assert statement["template"] in protocol["templates"]
        if statement["variant"] == "whitespace":
            template = template.replace(marker, marker + "\n", 1)
        assert hashlib.sha256(template.encode()).hexdigest() == statement["sha256"]

    for trial in events["trials"]:
        for update in (trial.get("reset"), trial.get("update")):
            if update is None:
                continue
            check(update["submitted"]["statement"])
            for snapshot in (update["before"], update["after"], *update["polls"]):
                check(snapshot["statement"])


def test_agentcore_diagnostic_summary_rederives_from_sanitised_blocks():
    diagnostic = _read(AGENTCORE / "continuation-diagnostic-protocol.json")
    events = _read(AGENTCORE / "continuation-diagnostic-events.json")
    summary = _read(AGENTCORE / "continuation-diagnostic-summary.json")

    assert events["diagnostic_protocol_sha256"] == _sha256(
        AGENTCORE / "continuation-diagnostic-protocol.json"
    )
    assert sorted(events["block_order"]) == sorted(diagnostic["configurations"])
    assert summary["configurations"] == agentcore_projector._diagnostic_summary(events["blocks"])


# The tests below assert the published results directly over the event records. They share no
# code with the projectors, so a projector defect cannot make both the summary and its check wrong.


def _response_outcome(call) -> str:
    response = call["response"]
    if "error" not in response and response["result"]["isError"] is False:
        return "allow"
    code = response["error"]["code"]
    if code == -32005:
        assert "Policy session is stale" in response["error"]["message"]
        return "stale_session"
    assert code == -32002
    return "deny"


def test_agentcore_matrix_results_hold_in_event_records():
    events = _read(AGENTCORE / "continuation-events.json")
    by_arm: dict[str, list] = {}
    for trial in events["trials"]:
        by_arm.setdefault(trial["arm"], []).append(trial)

    assert {arm: len(trials) for arm, trials in by_arm.items()} == {
        "byte_identical_statement": 10,
        "bound_variable_renaming": 10,
        "whitespace_only": 10,
        "description_only": 10,
        "identical_description": 10,
        "tightening_to_700": 10,
    }
    for arm, trials in by_arm.items():
        for trial in trials:
            update = trial["update"]
            before = trial["before_call"]
            predecessor = trial["predecessor_after_call"]
            assert update["submitted"]["validation_mode"] == "FAIL_ON_ANY_FINDINGS"
            assert update["before"]["revision_alias"] != update["after"]["revision_alias"]
            assert update["after"]["status"] == "ACTIVE"
            assert before["request"]["params"]["arguments"] == {"amount": 600}
            assert _response_outcome(before) == "allow"
            assert predecessor["session_alias"] == before["session_alias"]
            assert _response_outcome(predecessor) == "stale_session"
            if arm == "byte_identical_statement":
                assert "recovery_call" not in trial
                assert update["submitted"]["statement"] == update["before"]["statement"]
                continue
            recovery, refusal = trial["recovery_call"], trial["recovery_after_call"]
            assert recovery["session_alias"] == refusal["session_alias"] != before["session_alias"]
            assert [_response_outcome(recovery), _response_outcome(refusal)] == ["allow", "deny"]
            if arm == "tightening_to_700":
                assert update["after"]["statement"]["template"].endswith("-700.dogwood")
            if arm in ("description_only", "identical_description"):
                assert update["submitted"]["definition_supplied"] is False
                assert update["after"]["statement"] == update["before"]["statement"]

    assert [control["label"] for control in events["controls"]] == ["preflight", "postflight"]
    for control in events["controls"]:
        assert _response_outcome(control["single_below"]) == "allow"
        assert _response_outcome(control["single_boundary"]) == "deny"
        assert [_response_outcome(call) for call in control["same_session_pair"]] == [
            "allow",
            "deny",
        ]


def test_agentcore_diagnostic_results_hold_in_event_records():
    events = _read(AGENTCORE / "continuation-diagnostic-events.json")
    observed = {}
    for block in events["blocks"]:
        outcomes = set()
        for trial in block["trials"]:
            update = trial["update"]
            changed = update["before"]["revision_alias"] != update["after"]["revision_alias"]
            assert (
                trial["predecessor_after_call"]["session_alias"]
                == (trial["before_call"]["session_alias"])
            )
            outcomes.add((changed, _response_outcome(trial["predecessor_after_call"])))
        observed[block["configuration"]] = (
            block["validation_mode"],
            len(block["trials"]),
            outcomes,
        )

    assert observed == {
        "earlier_configuration": ("IGNORE_ALL_FINDINGS", 10, {(False, "deny")}),
        "earlier_without_enforcement_mode": ("IGNORE_ALL_FINDINGS", 10, {(False, "deny")}),
        "current_with_enforcement_mode": ("FAIL_ON_ANY_FINDINGS", 10, {(True, "stale_session")}),
    }


def test_managed_agents_results_hold_in_trial_records():
    evidence = _read(ANTHROPIC / "continuation-confirmation.json")
    added: dict[int, int] = {}
    cells: dict[str, int] = {}
    for trial in evidence["trials"]:
        cells[trial["cell"]] = cells.get(trial["cell"], 0) + 1
        if trial["cell"] == "lowered_cap_carries_spend":
            update, result = trial["cap_update"], trial["result"]
            assert update["requested_cap"] == update["reported_cents"] + 2
            assert update["retrieved_cap"] == update["requested_cap"]
            added_cents = result["final_reported_cents"] - update["reported_cents"]
            assert added_cents == result["added_cents"]
            assert trial["post_budget_refusal"]["status_code"] == 400
            added[result["added_cents"]] = added.get(result["added_cents"], 0) + 1
        elif trial["cell"] == "cap_at_or_below_spend_refused":
            result = trial["result"]
            assert result["attempted_cap"] == result["reported_cents"] - 1
            assert result["refusal"]["status_code"] == 400
            assert result["retrieved_cap"] == 10
        else:
            update, result = trial["agent_update"], trial["result"]
            assert update["updated_version"] == update["original_version"] + 1
            assert update["session_version_after_update"] == update["original_version"]
            assert result["session_version_at_budget"] == update["original_version"]
            assert result["final_reported_cents"] == 6

    assert cells == {
        "lowered_cap_carries_spend": 10,
        "cap_at_or_below_spend_refused": 10,
        "agent_update_leaves_live_session": 10,
    }
    assert added == {2: 9, 3: 1}
