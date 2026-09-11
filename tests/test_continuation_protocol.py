import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTCORE = ROOT / "docs" / "evidence" / "agentcore-refund-policy"
ANTHROPIC = ROOT / "docs" / "evidence" / "anthropic-managed-budget"


def _protocol(directory: Path) -> dict:
    return json.loads((directory / "continuation-protocol.json").read_text())


def _cents(expression: str) -> int:
    match = re.fullmatch(r"reported_cents_at_update ([+-]) (\d+)", expression)
    assert match is not None
    return int(match.group(2)) * (1 if match.group(1) == "+" else -1)


def test_agentcore_protocol_pins_templates_and_mandate():
    protocol = _protocol(AGENTCORE)

    assert protocol["status"] == "preregistered_not_executed"
    mandate = ROOT / protocol["mandate"]["path"]
    assert hashlib.sha256(mandate.read_bytes()).hexdigest() == protocol["mandate"]["sha256"]
    for name, digest in protocol["templates"].items():
        assert hashlib.sha256((AGENTCORE / name).read_bytes()).hexdigest() == digest
        assert protocol["gateway_placeholder"] in (AGENTCORE / name).read_text()


def test_agentcore_validation_candidates_use_only_pinned_templates():
    validation = _protocol(AGENTCORE)["validation"]
    templates = _protocol(AGENTCORE)["templates"]

    assert validation["max_candidates"] == len(validation["candidates"]) == 2
    for candidate in validation["candidates"]:
        variants = [candidate["base"], candidate["renamed"], candidate["tightened"]]
        if candidate["companion"] is not None:
            variants.append(candidate["companion"])
        assert set(variants) <= set(templates)


def test_agentcore_tightening_probe_separates_carry_from_reset():
    protocol = _protocol(AGENTCORE)
    amount = protocol["request_amount"]

    assert protocol["trials_per_arm"] == 10
    assert protocol["random_seed"] == 20260912
    assert list(protocol["arms"]) == [
        "byte_identical_statement",
        "bound_variable_renaming",
        "whitespace_only",
        "description_only",
        "identical_description",
        "tightening_to_700",
    ]
    assert amount < protocol["base_threshold"] <= 2 * amount
    assert amount < protocol["tightened_threshold"] <= 2 * amount
    assert protocol["tightened_threshold"] < protocol["base_threshold"]
    assert protocol["eligibility"]["application_retries"] == 0
    assert protocol["eligibility"]["sdk_max_attempts"] == 0


def test_managed_agents_classification_margins_do_not_overlap():
    protocol = _protocol(ANTHROPIC)
    lowered = protocol["cells"]["lowered_cap_carries_spend"]
    refused = protocol["cells"]["cap_at_or_below_spend_refused"]
    pinned = protocol["cells"]["agent_update_leaves_live_session"]

    assert protocol["status"] == "preregistered_not_executed"
    assert protocol["trials_per_cell"] == 10
    assert protocol["random_seed"] == 20260913
    assert _cents(lowered["lowered_cap"]) == 2
    assert lowered["classification"]["carry"].endswith("<= 3")
    assert lowered["classification"]["reset"].endswith(">= 5")
    assert _cents(refused["attempted_cap"]) == -1
    assert pinned["classification"]["pinned_and_retained"].endswith("<= 7")
    assert pinned["classification"]["reset"].endswith(">= 8")
    assert protocol["eligibility"]["concurrent_threads"] == 1


def test_both_protocols_share_the_mandate_and_never_replace_trials():
    agentcore = _protocol(AGENTCORE)
    anthropic = _protocol(ANTHROPIC)

    assert agentcore["mandate"] == anthropic["mandate"]
    for protocol in (agentcore, anthropic):
        assert protocol["eligibility"]["nonconforming_trials"] == (
            "retain and report; never replace or omit"
        )
