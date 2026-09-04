import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agentmandate._continuity import (
    AgentCoreContinuity,
    ContinuityBinding,
    ContinuityFinding,
    ContinuityFormatError,
    ContinuityResult,
    analyse_continuity,
)
from agentmandate.manifest import loads
from agentmandate.reach import analyse

ROOT = Path(__file__).parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "continuity-accepted-synthetic"
BINDING_SOURCE = "tests/fixtures/continuity-accepted-synthetic/binding-verification.json"
POLICY_SOURCE = "tests/fixtures/continuity-accepted-synthetic/policy.json"
PROVIDER_SOURCE = "tests/fixtures/continuity-accepted-synthetic/provider-control.json"
RESULT_FIXTURES = FIXTURE.parent


def _inputs():
    mandate_path = FIXTURE / "manifest.json"
    mandate = loads(
        mandate_path.read_text(),
        source=str(mandate_path.relative_to(ROOT)),
    )
    binding_text = (FIXTURE / "binding.json").read_text()
    provider_text = (FIXTURE / "provider.json").read_text()
    binding = ContinuityBinding.from_json(binding_text)
    provider = AgentCoreContinuity.from_json(provider_text)
    return mandate_path, mandate, binding_text, provider_text, binding, provider


def _analysis():
    mandate_path, mandate, _, _, binding, provider = _inputs()
    return analyse_continuity(
        mandate,
        provider,
        {PROVIDER_SOURCE: (FIXTURE / "provider-control.json").read_bytes()},
        as_of=datetime(2026, 9, 3, 12, tzinfo=timezone.utc),
        binding=binding,
        binding_source_bytes={
            BINDING_SOURCE: (FIXTURE / "binding-verification.json").read_bytes(),
            POLICY_SOURCE: (FIXTURE / "policy.json").read_bytes(),
        },
        mandate_bytes=mandate_path.read_bytes(),
    )


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def _rehash(value):
    body = deepcopy(value)
    body.pop("result_sha256", None)
    value["result_sha256"] = hashlib.sha256(_encoded(body).rstrip("\n").encode()).hexdigest()
    return _encoded(value)


def _result_cases():
    analyzed = _analysis().to_result()
    outcome = replace(
        analyzed.outcomes[0],
        alignments=tuple(replace(item, support=()) for item in analyzed.outcomes[0].alignments),
        support=(),
    )
    satisfied = replace(analyzed, outcomes=(outcome,))
    transition = outcome.transition

    def result_with(changed, code=None, message=None, *, authority=None):
        findings = (
            ()
            if code is None
            else (ContinuityFinding(code, transition, message, ()),)
        )
        return replace(
            satisfied,
            authority=satisfied.authority if authority is None else authority,
            outcomes=(changed,),
            findings=findings,
        )

    unresolved_alignment = replace(outcome.alignments[0], status="unresolved")
    unresolved = replace(
        outcome,
        state="unresolved",
        safe_continuation="unresolved",
        alignments=(unresolved_alignment, *outcome.alignments[1:]),
    )
    untrusted = replace(
        unresolved,
        authority_change="unresolved",
        admission="unresolved",
        comparability="unresolved",
        issuer_amendment="unresolved",
    )
    truncated_authority = {**satisfied.authority, "depth": 1, "truncated": True}
    return {
        "satisfied": satisfied,
        "reset": result_with(
            replace(outcome, state="reset", safe_continuation="violated"),
            "continuity.state-reset",
            "consumed authority did not survive the transition",
        ),
        "widened": result_with(
            replace(outcome, authority_change="widens", safe_continuation="violated"),
            "continuity.authority-widens",
            "remaining authority increased without a cited successor approval",
        ),
        "tightened": result_with(replace(outcome, authority_change="tightens")),
        "overshot": result_with(
            replace(outcome, admission="overshot", safe_continuation="violated"),
            "continuity.admission-overshot",
            "completed usage exceeded the reviewed transition bound",
        ),
        "unresolved": result_with(
            unresolved,
            "continuity.state-unresolved",
            "the capture cannot establish one mandate across the transition",
        ),
        "untrusted": result_with(
            untrusted,
            "continuity.source-untrusted",
            "continuity source bytes failed verification",
        ),
        "truncated": result_with(outcome, authority=truncated_authority),
    }


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


def test_continuity_result_v1_round_trips_the_satisfied_fixture():
    result = _analysis().to_result()
    rendered = result.to_json()
    body = result.as_dict()

    assert body["schema"] == "agentmandate.continuity/v1"
    assert body["result_version"] == 1
    assert body["inputs"]["binding"]["kind"] == "continuity-binding"
    assert body["inputs"]["provider"]["kind"] == "agentcore-continuity"
    assert body["outcomes"][0]["safe_continuation"] == "satisfied"
    assert body["findings"] == []
    assert ContinuityResult.from_json(rendered) == result
    assert ContinuityResult.from_json(rendered).to_json() == rendered


@pytest.mark.parametrize(
    "case",
    [
        "satisfied",
        "reset",
        "widened",
        "tightened",
        "overshot",
        "unresolved",
        "untrusted",
        "truncated",
    ],
)
def test_continuity_result_v1_canonical_fixtures(case):
    result = _result_cases()[case]
    expected = (RESULT_FIXTURES / f"continuity-result-v1-{case}.json").read_text()

    assert result.to_json() == expected
    assert ContinuityResult.from_json(expected) == result


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "not valid JSON"),
        ('{"value":NaN}', "non-canonical value"),
        ("[]", "must be an object"),
        ('{"result_sha256":"' + "0" * 64 + '"}', "missing field"),
    ],
)
def test_continuity_result_rejects_malformed_envelopes(text, message):
    with pytest.raises(ContinuityFormatError, match=message):
        ContinuityResult.from_json(text)


def test_continuity_result_rejects_unknown_fields_and_bad_checksum():
    raw = _analysis().to_result().as_dict()
    raw["unknown"] = True
    with pytest.raises(ContinuityFormatError, match="unknown field"):
        ContinuityResult.from_json(_encoded(raw))

    raw = _analysis().to_result().as_dict()
    raw["result_sha256"] = "not-a-digest"
    with pytest.raises(ContinuityFormatError, match="lowercase SHA-256"):
        ContinuityResult.from_json(_encoded(raw))

    raw = _analysis().to_result().as_dict()
    raw["as_of"] = "2026-09-03T12:00:01Z"
    with pytest.raises(ContinuityFormatError, match="SHA-256 does not match"):
        ContinuityResult.from_json(_encoded(raw))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(result_version=True), "unsupported continuity result version"),
        (lambda raw: raw.update(schema="other/v1"), "unsupported continuity result schema"),
        (lambda raw: raw.update(as_of="2026-02-30T12:00:00Z"), "real timestamp"),
        (lambda raw: raw["inputs"].update(extra=True), "unknown field"),
        (lambda raw: raw["inputs"].update(manifest=[]), "must be an object"),
        (
            lambda raw: raw["inputs"]["manifest"].update(semantic_sha256="A" * 64),
            "lowercase SHA-256",
        ),
        (lambda raw: raw["inputs"].update(provider=[]), "must be an object"),
        (lambda raw: raw["inputs"]["provider"].update(kind="continuity-binding"), "wrong kind"),
        (lambda raw: raw["inputs"]["provider"].update(kind="unknown"), "unsupported"),
        (lambda raw: raw["inputs"]["provider"].update(id=" "), "non-empty stripped"),
        (
            lambda raw: raw["inputs"].update(binding={**raw["inputs"]["provider"]}),
            "wrong kind",
        ),
        (lambda raw: raw.update(authority=[]), "must be an object"),
        (lambda raw: raw["authority"].update(reachable_tools={}), "must be an array"),
        (
            lambda raw: raw["authority"].update(reachable_tools=["z", "a"]),
            "sorted unique strings",
        ),
        (lambda raw: raw["authority"].update(effects=["write"]), "string pairs"),
        (
            lambda raw: raw["authority"].update(effects=[["z", "a"], ["a", "z"]]),
            "sorted and unique",
        ),
        (
            lambda raw: raw["authority"].update(
                max_extractable={"amount": "not-decimal", "currency": "USD"}
            ),
            "must be decimal",
        ),
        (
            lambda raw: raw["authority"].update(
                max_extractable={"amount": "NaN", "currency": "USD"}
            ),
            "must be canonical",
        ),
        (lambda raw: raw["authority"].update(breaches={}), "must be an array"),
        (
            lambda raw: raw["authority"].update(
                breaches=[{"kind": "effect", "detail": "detail", "path": []}]
            ),
            "must be non-empty",
        ),
        (lambda raw: raw["authority"].update(depth=True), "integer"),
        (lambda raw: raw["authority"].update(truncated=0), "boolean"),
        (lambda raw: raw.update(outcomes={}), "non-empty array"),
        (
            lambda raw: raw["outcomes"][0].update(completed_values=[]),
            "completed_values must be non-empty",
        ),
        (lambda raw: raw["outcomes"][0].update(alignments={}), "must be an array"),
        (lambda raw: raw["outcomes"][0].update(assumptions={}), "must be an array"),
        (
            lambda raw: raw["outcomes"][0].update(assumptions=["z", "a"]),
            "sorted unique strings",
        ),
        (
            lambda raw: raw["outcomes"][0]["alignments"].reverse(),
            "canonical checks",
        ),
        (
            lambda raw: raw["outcomes"][0]["alignments"][0].update(status="unknown"),
            "unsupported alignment state",
        ),
        (
            lambda raw: raw["outcomes"][0]["alignments"][0].update(strength="asserted"),
            "strength is unsupported",
        ),
        (lambda raw: raw["outcomes"][0].update(state="migrated"), "unsupported outcome"),
        (
            lambda raw: raw["outcomes"][0].update(safe_continuation="violated"),
            "safe_continuation is inconsistent",
        ),
        (
            lambda raw: raw["outcomes"][0].update(provider="other-provider"),
            "provider does not match",
        ),
        (
            lambda raw: raw.update(outcomes=raw["outcomes"] * 2),
            "sorted unique transition identities",
        ),
        (lambda raw: raw.update(findings={}), "must be an array"),
    ],
)
def test_continuity_result_strictly_validates_inner_contract(mutate, message):
    raw = _analysis().to_result().as_dict()
    mutate(raw)
    with pytest.raises(ContinuityFormatError, match=message):
        ContinuityResult.from_json(_rehash(raw))


def test_continuity_result_validates_findings_and_optional_binding():
    result = _analysis().to_result()
    finding = ContinuityFinding(
        "continuity.state-reset", result.outcomes[0].transition, "state reset", ()
    )
    without_binding = replace(result, binding=None, findings=(finding,))
    rendered = without_binding.to_json()

    assert ContinuityResult.from_json(rendered) == without_binding

    raw = without_binding.as_dict()
    raw["findings"][0]["code"] = "continuity.unknown"
    with pytest.raises(ContinuityFormatError, match="code is unsupported"):
        ContinuityResult.from_json(_rehash(raw))

    raw = without_binding.as_dict()
    raw["findings"] *= 2
    with pytest.raises(ContinuityFormatError, match="must be unique"):
        ContinuityResult.from_json(_rehash(raw))

    raw = without_binding.as_dict()
    raw["findings"][0]["transition"] = "unknown-transition"
    with pytest.raises(ContinuityFormatError, match="unknown transition"):
        ContinuityResult.from_json(_rehash(raw))


def test_continuity_result_accepts_complete_money_and_breach_authority():
    result = _analysis().to_result()
    authority = {
        **result.authority,
        "max_extractable": {"amount": "1.5", "currency": "USD"},
        "breaches": [{"kind": "effect", "detail": "reviewed breach", "path": ["tool"]}],
    }
    changed = replace(result, authority=authority)

    assert ContinuityResult.from_json(changed.to_json()) == changed


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
