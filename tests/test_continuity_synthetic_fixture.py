import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from agentmandate._continuity import (
    AgentCoreContinuity,
    ContinuityBinding,
    analyse_continuity,
)
from agentmandate.manifest import load
from agentmandate.reach import analyse

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "continuity-accepted-synthetic"
BINDING_SOURCE = "tests/fixtures/continuity-accepted-synthetic/binding-verification.json"
POLICY_SOURCE = "tests/fixtures/continuity-accepted-synthetic/policy.json"
PROVIDER_SOURCE = "tests/fixtures/continuity-accepted-synthetic/provider-control.json"


def _inputs():
    mandate_path = FIXTURE / "manifest.json"
    mandate = load(mandate_path)
    binding_text = (FIXTURE / "binding.json").read_text()
    provider_text = (FIXTURE / "provider.json").read_text()
    binding = ContinuityBinding.from_json(binding_text)
    provider = AgentCoreContinuity.from_json(provider_text)
    return mandate_path, mandate, binding_text, provider_text, binding, provider


def test_synthetic_continuity_fixture_reaches_one_complete_satisfied_path():
    mandate_path, mandate, binding_text, provider_text, binding, provider = _inputs()
    policy_bytes = (FIXTURE / "policy.json").read_bytes()
    binding_sources = {
        BINDING_SOURCE: (FIXTURE / "binding-verification.json").read_bytes(),
        POLICY_SOURCE: policy_bytes,
    }
    provider_sources = {PROVIDER_SOURCE: (FIXTURE / "provider-control.json").read_bytes()}

    assert binding.to_json() == binding_text
    assert provider.to_json() == provider_text
    binding.verify_sources(binding_sources)
    provider.verify_sources(provider_sources)
    assert binding.evidence.reviewer == "synthetic-fixture-reviewer"
    assert provider.evidence.reviewer == "synthetic-fixture-reviewer"
    assert binding.policy_sha256 == hashlib.sha256(policy_bytes).hexdigest()

    result = analyse_continuity(
        mandate,
        provider,
        provider_sources,
        as_of=datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
        binding=binding,
        binding_source_bytes=binding_sources,
        mandate_bytes=mandate_path.read_bytes(),
    )

    assert result.findings == ()
    assert result.clean
    assert result.authority == analyse(mandate)
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert (
        outcome.state,
        outcome.authority_change,
        outcome.admission,
        outcome.comparability,
        outcome.issuer_amendment,
        outcome.safe_continuation,
    ) == (
        "preserved",
        "stable",
        "within_bound",
        "established",
        "not_required",
        "satisfied",
    )
    assert {item.status for item in outcome.alignments} == {"established"}
    assert {
        item.strength
        for item in outcome.alignments
        if item.check in {"isolation", "complete_mediation"}
    } == {"platform_verified"}
    assert any(item.startswith("edge:continuity_binding:") for item in outcome.support)
    assert any(item.startswith("capture:") for item in outcome.support)


def test_synthetic_fixture_rejects_mismatched_binding_and_control_mediation():
    mandate_path, mandate, _, _, binding, provider = _inputs()
    control = replace(provider.controls[0], mediation="exclusive_adapter")
    mismatched = replace(provider, controls=(control,))
    result = analyse_continuity(
        mandate,
        mismatched,
        {PROVIDER_SOURCE: (FIXTURE / "provider-control.json").read_bytes()},
        as_of=datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
        binding=binding,
        binding_source_bytes={
            BINDING_SOURCE: (FIXTURE / "binding-verification.json").read_bytes(),
            POLICY_SOURCE: (FIXTURE / "policy.json").read_bytes(),
        },
        mandate_bytes=mandate_path.read_bytes(),
    )

    assert not result.clean
    assert result.outcomes[0].safe_continuation == "unresolved"
    assert "continuity.derivation-integrity-unresolved" in {
        item.code for item in result.findings
    }
