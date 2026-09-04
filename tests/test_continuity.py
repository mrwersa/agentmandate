from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

import agentmandate._continuity as continuity
from agentmandate._continuity import (
    AgentCoreContinuity,
    AnthropicContinuity,
    ContinuityAlignment,
    ContinuityAnalysis,
    ContinuityBinding,
    ContinuityEvidence,
    ContinuityFormatError,
    _agentcore_controls,
    _anthropic_axes,
    _anthropic_controls,
    _boolean,
    _captured,
    _date,
    _digest,
    _evidence,
    _integer,
    _load,
    _migration_sources,
    _path,
    _profile_digest,
    _record,
    _safe_continuation,
    _sources,
    _string,
    _strings,
    _transition_claims,
    _utc,
    _validate_continuity_profile,
    _verify_sources,
    analyse_continuity,
    migrate_agentcore_binding,
    migrate_agentcore_continuity,
    migrate_anthropic_continuity,
)
from agentmandate._ir import AuthorityIR, IRFormatError, _analyse_ir
from agentmandate.manifest import load
from agentmandate.reach import analyse

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
AGENTCORE = ROOT / "docs" / "evidence" / "agentcore-refund-policy"
ANTHROPIC = ROOT / "docs" / "evidence" / "anthropic-managed-budget"


def _contents(paths: list[Path]) -> dict[str, bytes]:
    return {str(path.relative_to(ROOT)): path.read_bytes() for path in paths}


def _binding_contents() -> dict[str, bytes]:
    return _contents(
        [
            AGENTCORE / "mandate-binding.json",
            AGENTCORE / "mandate-binding-result.json",
            AGENTCORE / "binding-public-key.pem",
        ]
    )


def _agentcore_contents() -> dict[str, bytes]:
    return _contents(
        [
            AGENTCORE / "temporal-repetition.json",
            AGENTCORE / "temporal-transition-confirmation-summary.json",
            AGENTCORE / "temporal-update-repetition.json",
            AGENTCORE / "binding-repetition.json",
            AGENTCORE / "binding-policy-revision-repetition.json",
        ]
    )


def _anthropic_contents() -> dict[str, bytes]:
    return _contents(
        [
            ANTHROPIC / "protocol.json",
            ANTHROPIC / "confirmation.json",
            ANTHROPIC / "multiagent-protocol.json",
            ANTHROPIC / "multiagent-confirmation.json",
        ]
    )


@pytest.mark.parametrize(
    ("migrate", "contents", "reader", "fixture"),
    [
        (
            migrate_agentcore_binding,
            _binding_contents,
            ContinuityBinding,
            "continuity-binding-v1.json",
        ),
        (
            migrate_agentcore_continuity,
            _agentcore_contents,
            AgentCoreContinuity,
            "agentcore-continuity-v1.json",
        ),
        (
            migrate_anthropic_continuity,
            _anthropic_contents,
            AnthropicContinuity,
            "anthropic-continuity-v1.json",
        ),
    ],
)
def test_canonical_migrations_are_byte_stable(migrate, contents, reader, fixture):
    migrated = migrate(contents())
    expected = (FIXTURES / fixture).read_text()
    assert migrated.to_json() == expected
    assert reader.from_json(expected).to_json() == expected
    migrated.verify_sources(contents())


def test_migrations_preserve_provider_specific_unknowns_and_controls():
    agentcore = migrate_agentcore_continuity(_agentcore_contents())
    anthropic = migrate_anthropic_continuity(_anthropic_contents())

    assert len(agentcore.controls) == 10
    assert next(
        item for item in agentcore.controls if item.id == "equivalent-revision"
    ).outcomes == (
        "allow",
        "stale_session",
        "allow",
        "deny",
    )
    assert next(
        item for item in agentcore.controls if item.id == "whitespace-revision"
    ).same_mandate
    assert (
        next(item for item in agentcore.controls if item.id == "description-revision").trials == 1
    )
    assert next(item for item in agentcore.controls if item.id == "signed-binding").mediation == (
        "exclusive_adapter"
    )
    assert (
        next(item for item in agentcore.controls if item.id == "fresh-sessions").same_mandate
        is None
    )
    assert next(item for item in agentcore.controls if item.id == "binding-revision").same_mandate
    assert len(anthropic.controls) == 6
    assert next(item for item in anthropic.controls if item.id == "two-children").final_costs == (
        2,
        2,
        2,
        3,
        2,
        2,
        2,
        2,
        2,
        2,
    )
    assert (
        next(item for item in anthropic.controls if item.id == "fresh-sessions").consumed_before
        == (1,) * 10
    )
    assert next(item for item in anthropic.controls if item.id == "four-children").child_count == 4
    assert not hasattr(agentcore, "final_costs")
    assert not hasattr(anthropic, "revision_changed")


@pytest.mark.parametrize(
    ("reader", "fixture"),
    [
        (ContinuityBinding, "continuity-binding-v1.json"),
        (AgentCoreContinuity, "agentcore-continuity-v1.json"),
        (AnthropicContinuity, "anthropic-continuity-v1.json"),
    ],
)
def test_canonical_readers_normalize_set_like_order(reader, fixture):
    expected = (FIXTURES / fixture).read_text()
    raw = json.loads(expected)
    raw["sources"].reverse()
    if "controls" in raw:
        raw["controls"].reverse()
        for control in raw["controls"]:
            control["sources"].reverse()
    assert reader.from_json(json.dumps(raw)).to_json() == expected


def _projected_profiles():
    return (
        migrate_agentcore_binding(_binding_contents()).to_ir(),
        migrate_agentcore_continuity(_agentcore_contents()).to_ir(),
        migrate_anthropic_continuity(_anthropic_contents()).to_ir(),
    )


def _profile_contract(graph: AuthorityIR) -> tuple[str, str]:
    source = graph.sources[0]
    return source.kind, source.adapter


def test_continuity_profiles_project_registered_relations_and_round_trip():
    binding, agentcore, anthropic = _projected_profiles()
    assert (len(binding.entities), len(binding.facts), len(binding.edges)) == (3, 9, 2)
    assert (len(agentcore.entities), len(agentcore.facts), len(agentcore.edges)) == (60, 249, 69)
    assert (len(anthropic.entities), len(anthropic.facts), len(anthropic.edges)) == (25, 113, 30)
    assert {edge.relation for edge in binding.edges} == {"binds_mandate", "binds_boundary"}
    provider_relations = {
        "after_state",
        "before_state",
        "observes_decision",
        "state_of",
    }
    assert {edge.relation for edge in agentcore.edges} == provider_relations
    assert {edge.relation for edge in anthropic.edges} == provider_relations
    assert {
        graph.sources[0].kind: graph.sources[0].semantic_sha256
        for graph in (binding, agentcore, anthropic)
    } == {
        "continuity-binding": "1d1d3593d78fb58185b6846262c7c6f21b82af744e6cefa6450a69056c150af7",
        "agentcore-continuity": "501d39993027fe13a61cf6984df64203a7200aa1d7d4c8769c786fcb95d1f54d",
        "anthropic-continuity": "4cdfba617447605f183c35bd7c3af4ceaf0b3b8735862f6c4e59b304a92ecdbd",
    }
    for graph in (binding, agentcore, anthropic):
        encoded = graph.to_json()
        decoded = AuthorityIR.from_json(encoded)
        assert decoded.to_json() == encoded
        assert {item.review for fact in graph.facts for item in fact.evidence} == {"unreviewed"}
        with pytest.raises(IRFormatError, match="analyzable manifest-v1 profile"):
            _analyse_ir(graph)


def test_provider_projection_preserves_distinct_state_shapes():
    _, agentcore, anthropic = _projected_profiles()
    agentcore_predicates = {fact.predicate for fact in agentcore.facts}
    anthropic_predicates = {fact.predicate for fact in anthropic.facts}
    assert "completed_values" not in agentcore_predicates
    assert "completed_values" in anthropic_predicates
    assert sum(fact.predicate == "completed_values" for fact in anthropic.facts) == 8
    assert any(
        fact.predicate == "control" and fact.value["same_mandate"] is None
        for fact in agentcore.facts
    )
    assert not any(
        "revision_changed" in fact.value for fact in anthropic.facts if isinstance(fact.value, dict)
    )


def _rehash(graph: AuthorityIR) -> AuthorityIR:
    source = graph.sources[0]
    return replace(
        graph,
        sources=(
            replace(
                source,
                semantic_sha256=_profile_digest(graph.entities, graph.facts, graph.edges),
            ),
        ),
    )


def test_profile_validator_rejects_structural_source_and_digest_failures():
    graph = migrate_agentcore_continuity(_agentcore_contents()).to_ir()
    kind, adapter = _profile_contract(graph)
    cases = (
        replace(graph, edges=graph.edges[:-1]),
        replace(
            graph,
            sources=graph.sources + (replace(graph.sources[0], id="source:extra"),),
        ),
        replace(graph, sources=(replace(graph.sources[0], adapter="wrong"),)),
        replace(graph, sources=(replace(graph.sources[0], locator="memory:wrong"),)),
        replace(graph, sources=(replace(graph.sources[0], semantic_sha256="0" * 64),)),
        replace(graph, sources=(replace(graph.sources[0], producer_version="wrong"),)),
    )
    for changed in cases:
        with pytest.raises(ContinuityFormatError):
            _validate_continuity_profile(changed, kind, adapter)
    with pytest.raises(ContinuityFormatError, match="kind is not supported"):
        _validate_continuity_profile(graph, "other", adapter)


def test_profile_validator_rejects_invalid_and_rehashed_record_tampering():
    graph = migrate_anthropic_continuity(_anthropic_contents()).to_ir()
    kind, adapter = _profile_contract(graph)
    root = next(entity for entity in graph.entities if entity.kind == "enforcement_boundary")
    record = next(
        fact for fact in graph.facts if fact.subject == root.id and fact.predicate == "record"
    )

    invalid_value = deepcopy(record.value)
    invalid_value["provider"] = "other"
    invalid_fact = replace(record, value=invalid_value)
    invalid = replace(
        graph,
        facts=tuple(invalid_fact if fact.id == record.id else fact for fact in graph.facts),
    )
    with pytest.raises(ContinuityFormatError, match="record fact is invalid"):
        _validate_continuity_profile(_rehash(invalid), kind, adapter)

    valid_value = deepcopy(record.value)
    valid_value["controls"][0]["cap_after"] = 3
    changed_fact = replace(record, value=valid_value)
    changed = replace(
        graph,
        facts=tuple(changed_fact if fact.id == record.id else fact for fact in graph.facts),
    )
    with pytest.raises(ContinuityFormatError, match="source identity"):
        _validate_continuity_profile(_rehash(changed), kind, adapter)

    state_fact = next(fact for fact in graph.facts if fact.predicate == "provider_limit")
    altered_fact = replace(state_fact, value=state_fact.value + 1)
    altered = replace(
        graph,
        facts=tuple(altered_fact if fact.id == state_fact.id else fact for fact in graph.facts),
    )
    with pytest.raises(ContinuityFormatError, match="does not match its record"):
        _validate_continuity_profile(_rehash(altered), kind, adapter)

    missing_record = replace(
        graph,
        facts=tuple(fact for fact in graph.facts if fact.id != record.id),
    )
    with pytest.raises(ContinuityFormatError, match="record root"):
        _validate_continuity_profile(_rehash(missing_record), kind, adapter)


def test_profile_validator_checks_content_digest_after_regeneration():
    graph = migrate_agentcore_binding(_binding_contents()).to_ir()
    kind, adapter = _profile_contract(graph)
    changed = replace(
        graph,
        sources=(replace(graph.sources[0], content_sha256="0" * 64),),
    )
    with pytest.raises(ContinuityFormatError, match="content digest"):
        _validate_continuity_profile(changed, kind, adapter)


def _reviewed(record):
    # A synthetic acceptance state exercises Gate 3 without retrospectively
    # upgrading the canonical migrated evidence, which remains unreviewed.
    return replace(
        record,
        evidence=ContinuityEvidence("exact", "accepted", "reviewer", "2027-08-30"),
    )


def _evaluation_time() -> datetime:
    return datetime(2026, 8, 29, 12, tzinfo=timezone.utc)


def _agentcore_analysis(**changes) -> ContinuityAnalysis:
    path = AGENTCORE / "mandate.yaml"
    mandate = load(path)
    arguments = {
        "provider": _reviewed(migrate_agentcore_continuity(_agentcore_contents())),
        "source_bytes": _agentcore_contents(),
        "as_of": _evaluation_time(),
        "binding": _reviewed(migrate_agentcore_binding(_binding_contents())),
        "binding_source_bytes": _binding_contents(),
        "mandate_bytes": path.read_bytes(),
    }
    arguments.update(changes)
    return analyse_continuity(mandate, **arguments)


def _anthropic_analysis(**changes) -> ContinuityAnalysis:
    path = AGENTCORE / "mandate.yaml"
    arguments = {
        "provider": _reviewed(migrate_anthropic_continuity(_anthropic_contents())),
        "source_bytes": _anthropic_contents(),
        "as_of": _evaluation_time(),
    }
    arguments.update(changes)
    return analyse_continuity(load(path), **arguments)


def test_agentcore_reconciliation_preserves_reviewed_control_matrix():
    result = _agentcore_analysis()
    outcomes = {
        item.transition: (item.state, item.authority_change, item.admission)
        for item in result.outcomes
    }
    assert outcomes == {
        "binding-revision": ("reset", "widens", "overshot"),
        "byte-identical-write": ("preserved", "stable", "within_bound"),
        "concurrent-session": ("preserved", "stable", "within_bound"),
        "description-revision": ("unresolved", "stable", "overshot"),
        "equivalent-revision": ("unresolved", "stable", "overshot"),
        "fresh-sessions": ("unresolved", "stable", "unresolved"),
        "limit-revision": ("unresolved", "widens", "unresolved"),
        "same-session": ("preserved", "stable", "within_bound"),
        "signed-binding": ("preserved", "stable", "within_bound"),
        "whitespace-revision": ("unresolved", "stable", "overshot"),
    }
    assert {
        item.transition: (item.comparability, item.issuer_amendment) for item in result.outcomes
    } == {
        "binding-revision": ("unresolved", "unresolved"),
        "byte-identical-write": ("established", "not_required"),
        "concurrent-session": ("established", "not_required"),
        "description-revision": ("unresolved", "unresolved"),
        "equivalent-revision": ("unresolved", "unresolved"),
        "fresh-sessions": ("unresolved", "unresolved"),
        "limit-revision": ("unresolved", "unresolved"),
        "same-session": ("established", "not_required"),
        "signed-binding": ("established", "not_required"),
        "whitespace-revision": ("unresolved", "unresolved"),
    }
    assert {item.safe_continuation for item in result.outcomes} == {"unresolved"}
    signed = next(item for item in result.outcomes if item.transition == "signed-binding")
    assert signed.kind == "same_boundary"
    assert (
        signed.dimension,
        signed.unit,
        signed.limit_before,
        signed.limit_after,
        signed.completed_values,
    ) == ("tool_argument.process_refund.amount", "integer", 1000, 1000, (600,))
    assert {item.check: item.status for item in signed.alignments} == {
        "continuity": "established",
        "derivation_integrity": "established",
        "isolation": "conditional",
        "complete_mediation": "conditional",
    }
    assert signed.assumptions == (
        "continuity is conditional on the adapter being the exclusive path",
    )
    relations = {
        edge.id: edge.relation
        for edge in _reviewed(migrate_agentcore_continuity(_agentcore_contents())).to_ir().edges
    }
    signed_relations = {relations[item] for item in signed.support if item in relations}
    assert signed_relations == {
        "after_state",
        "before_state",
        "observes_decision",
    }
    assert any(item.startswith("capture:") for item in signed.support)
    assert any(item.startswith("edge:continuity_binding:") for item in signed.support)
    unbound = next(item for item in result.outcomes if item.transition == "same-session")
    assert not any(item.startswith("edge:continuity_binding:") for item in unbound.support)
    assert (
        next(item for item in unbound.alignments if item.check == "complete_mediation").strength
        == "unestablished"
    )
    concurrent = next(item for item in result.outcomes if item.transition == "concurrent-session")
    assert concurrent.assumptions == (
        "completed decisions do not prove reservation of in-flight work",
    )
    assert {item.code for item in result.findings} >= {
        "continuity.state-reset",
        "continuity.authority-widens",
        "continuity.admission-overshot",
        "continuity.state-unresolved",
        "continuity.complete-mediation-unresolved",
    }
    assert result.authority == analyse(load(AGENTCORE / "mandate.yaml"))
    assert not result.clean


def test_anthropic_reconciliation_keeps_reset_widening_and_overshoot_separate():
    result = _anthropic_analysis()
    outcomes = {
        item.transition: (item.state, item.authority_change, item.admission)
        for item in result.outcomes
    }
    assert outcomes == {
        "cap-increase": ("preserved", "widens", "within_bound"),
        "four-children": ("preserved", "stable", "overshot"),
        "fresh-sessions": ("reset", "stable", "overshot"),
        "one-child": ("preserved", "stable", "overshot"),
        "sequential": ("preserved", "stable", "within_bound"),
        "two-children": ("preserved", "stable", "overshot"),
    }
    assert {item.transition: item.comparability for item in result.outcomes} == {
        "cap-increase": "unresolved",
        "four-children": "unresolved",
        "fresh-sessions": "unresolved",
        "one-child": "unresolved",
        "sequential": "established",
        "two-children": "unresolved",
    }
    assert {item.safe_continuation for item in result.outcomes} == {"unresolved"}
    children = next(item for item in result.outcomes if item.transition == "four-children")
    assert (
        children.dimension,
        children.unit,
        children.limit_before,
        children.limit_after,
        children.completed_values,
    ) == ("session_cost", "minor_currency_unit", 1, 1, (4,) * 10)
    fresh = next(item for item in result.outcomes if item.transition == "fresh-sessions")
    assert fresh.completed_values == (2,) * 10
    assert children.assumptions == ("completed session cost does not prove in-flight reservation",)
    assert {item.code for item in result.findings} >= {
        "continuity.state-reset",
        "continuity.authority-widens",
        "continuity.admission-overshot",
        "continuity.derivation-integrity-unresolved",
        "continuity.complete-mediation-unresolved",
    }
    assert result.authority == analyse(load(AGENTCORE / "mandate.yaml"))


def test_unreviewed_or_tampered_profiles_fail_closed_with_full_authority():
    path = AGENTCORE / "mandate.yaml"
    mandate = load(path)
    unreviewed = analyse_continuity(
        mandate,
        migrate_agentcore_continuity(_agentcore_contents()),
        _agentcore_contents(),
        as_of=_evaluation_time(),
    )
    assert {item.state for item in unreviewed.outcomes} == {"unresolved"}
    assert {item.authority_change for item in unreviewed.outcomes} == {"unresolved"}
    assert {item.admission for item in unreviewed.outcomes} == {"unresolved"}
    assert {item.comparability for item in unreviewed.outcomes} == {"unresolved"}
    assert {item.issuer_amendment for item in unreviewed.outcomes} == {"unresolved"}
    assert {item.safe_continuation for item in unreviewed.outcomes} == {"unresolved"}
    assert {item.code for item in unreviewed.findings} == {"continuity.evidence-untrusted"}
    assert unreviewed.authority == analyse(mandate)

    contents = _agentcore_contents()
    contents["docs/evidence/agentcore-refund-policy/temporal-repetition.json"] = b"changed"
    tampered = _agentcore_analysis(source_bytes=contents)
    assert {item.state for item in tampered.outcomes} == {"unresolved"}
    assert "continuity.source-untrusted" in {item.code for item in tampered.findings}
    assert tampered.authority == analyse(mandate)


def test_binding_failures_never_establish_cross_boundary_reset():
    path = AGENTCORE / "mandate.yaml"
    mandate = load(path)
    bad_binding = replace(
        _reviewed(migrate_agentcore_binding(_binding_contents())),
        mandate_sha256="0" * 64,
    )
    result = _agentcore_analysis(binding=bad_binding)
    revision = next(item for item in result.outcomes if item.transition == "binding-revision")
    assert revision.state == "unresolved"
    assert "continuity.binding-untrusted" in {item.code for item in result.findings}
    assert result.authority == analyse(mandate)

    result = _agentcore_analysis(binding_source_bytes={})
    assert "continuity.binding-untrusted" in {item.code for item in result.findings}

    no_binding = _agentcore_analysis(
        binding=None,
        binding_source_bytes=None,
        mandate_bytes=None,
    )
    signed = next(item for item in no_binding.outcomes if item.transition == "signed-binding")
    assert (signed.state, signed.authority_change, signed.admission) == (
        "unresolved",
        "unresolved",
        "unresolved",
    )
    assert (
        next(item for item in signed.alignments if item.check == "derivation_integrity").status
        == "unresolved"
    )


@pytest.mark.parametrize(
    "as_of",
    [
        datetime(2026, 8, 29),
        datetime(2026, 8, 29, 12, 0, 0, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
        .astimezone(timezone.utc)
        .replace(tzinfo=None),
    ],
)
def test_continuity_analysis_requires_whole_second_utc_time(as_of):
    with pytest.raises(ContinuityFormatError, match="whole-second UTC"):
        _anthropic_analysis(as_of=as_of)


def test_continuity_clean_uses_the_explicit_safe_continuation_verdict():
    result = _anthropic_analysis()
    safe = replace(
        result.outcomes[0],
        state="preserved",
        authority_change="stable",
        admission="within_bound",
        safe_continuation="satisfied",
    )
    assert replace(result, findings=(), outcomes=(safe,)).clean
    assert not replace(
        result,
        findings=(),
        outcomes=(replace(safe, safe_continuation="unresolved"),),
    ).clean


def test_platform_verified_mediation_can_establish_all_alignment_checks():
    control = next(
        item
        for item in migrate_agentcore_continuity(_agentcore_contents()).controls
        if item.id == "signed-binding"
    )
    _, _, _, alignments, assumptions = continuity._agentcore_axes(
        replace(control, mediation="platform_verified"),
        binding_ready=True,
    )
    assert {item.status for item in alignments} == {"established"}
    assert {
        item.strength for item in alignments if item.check in {"isolation", "complete_mediation"}
    } == {"platform_verified"}
    assert assumptions == ()


def test_transition_claims_require_an_unchanged_reviewed_boundary():
    agentcore = next(
        item
        for item in migrate_agentcore_continuity(_agentcore_contents()).controls
        if item.id == "same-session"
    )
    anthropic = next(
        item
        for item in migrate_anthropic_continuity(_anthropic_contents()).controls
        if item.id == "sequential"
    )
    assert _transition_claims(agentcore, provider_ready=True) == (
        "established",
        "not_required",
    )
    assert _transition_claims(anthropic, provider_ready=True) == (
        "established",
        "not_required",
    )
    assert _transition_claims(agentcore, provider_ready=False) == (
        "unresolved",
        "unresolved",
    )


@pytest.mark.parametrize(
    ("state", "authority", "admission", "comparability", "amendment", "expected"),
    [
        ("preserved", "stable", "within_bound", "established", "not_required", "satisfied"),
        ("preserved", "tightens", "within_bound", "established", "not_required", "satisfied"),
        ("reset", "stable", "within_bound", "established", "not_required", "violated"),
        ("preserved", "widens", "within_bound", "established", "not_required", "violated"),
        ("preserved", "stable", "overshot", "established", "not_required", "violated"),
        ("reset", "widens", "within_bound", "established", "approved", "satisfied"),
        ("preserved", "stable", "overshot", "established", "approved", "violated"),
        ("preserved", "stable", "within_bound", "unresolved", "not_required", "unresolved"),
        ("preserved", "stable", "within_bound", "established", "unknown", "unresolved"),
    ],
)
def test_safe_continuation_keeps_axes_comparability_and_amendment_separate(
    state,
    authority,
    admission,
    comparability,
    amendment,
    expected,
):
    alignments = tuple(
        ContinuityAlignment(check, "established", "observed", ())
        for check in ("continuity", "derivation_integrity", "isolation", "complete_mediation")
    )
    assert (
        _safe_continuation(
            state,
            authority,
            admission,
            comparability,
            amendment,
            alignments,
        )
        == expected
    )
    conditional = replace(alignments[-1], status="conditional")
    assert (
        _safe_continuation(
            state,
            authority,
            admission,
            comparability,
            amendment,
            (*alignments[:-1], conditional),
        )
        == "unresolved"
    )


def test_anthropic_axis_fallbacks_remain_closed():
    control = migrate_anthropic_continuity(_anthropic_contents()).controls[0]
    state, authority, _, _, _ = _anthropic_axes(
        replace(control, transition="configuration_revision", boundary_changed=True)
    )
    assert state == "unresolved"
    assert authority == "widens"
    _, authority, _, _, _ = _anthropic_axes(replace(control, cap_before=2, cap_after=1))
    assert authority == "tightens"


@pytest.mark.parametrize("mandate_bytes", [None, b"\xff"])
def test_missing_or_unreadable_mandate_bytes_do_not_establish_a_binding(mandate_bytes):
    result = _agentcore_analysis(mandate_bytes=mandate_bytes)
    assert "continuity.binding-untrusted" in {item.code for item in result.findings}
    revision = next(item for item in result.outcomes if item.transition == "binding-revision")
    assert revision.state == "unresolved"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{", "not valid JSON"),
        ('{"x":NaN}', "non-canonical"),
    ],
)
def test_json_errors_are_typed(text, message):
    with pytest.raises(ContinuityFormatError, match=message):
        _load(text, "sample")


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: _record([], "x", set()), "must be an object"),
        (lambda: _record({}, "x", {"a"}), "missing field"),
        (lambda: _record({"a": 1}, "x", set()), "unknown field"),
        (lambda: _string("", "x"), "non-empty stripped"),
        (lambda: _string(" x", "x"), "non-empty stripped"),
        (lambda: _integer(True, "x"), "integer"),
        (lambda: _integer(-1, "x"), "integer"),
        (lambda: _boolean(1, "x"), "boolean"),
        (lambda: _digest("0" * 63, "x"), "lowercase SHA-256"),
        (lambda: _date("20260830", "x"), "canonical ISO date"),
        (lambda: _date("2026-02-30", "x"), "real calendar"),
        (lambda: _utc("2026-08-30T00:00:00+00:00", "x"), "canonical UTC"),
        (lambda: _utc("2026-02-30T00:00:00Z", "x"), "real timestamp"),
        (lambda: _path("/absolute", "x"), "repository-relative"),
        (lambda: _path("a\\b", "x"), "repository-relative"),
        (lambda: _path("a/../b", "x"), "repository-relative"),
        (lambda: _strings({}, "x"), "non-empty array"),
        (lambda: _strings(["a", "a"], "x"), "duplicates"),
        (lambda: _strings(["x"], "x", frozenset({"a"})), "invalid value"),
    ],
)
def test_scalar_reader_errors_are_typed(call, message):
    with pytest.raises(ContinuityFormatError, match=message):
        call()


@pytest.mark.parametrize(
    "raw",
    [
        {"confidence": "wrong", "review": "accepted", "reviewer": "r", "expires": "2027-01-01"},
        {"confidence": "exact", "review": "wrong", "reviewer": "r", "expires": "2027-01-01"},
        {"confidence": "exact", "review": "unreviewed", "reviewer": "r", "expires": None},
        {"confidence": "exact", "review": "accepted", "reviewer": None, "expires": "2027-01-01"},
    ],
)
def test_evidence_invariants_fail_closed(raw):
    with pytest.raises(ContinuityFormatError):
        _evidence(raw, "evidence")


def test_unreviewed_evidence_is_archival():
    evidence = _evidence(
        {"confidence": "unknown", "review": "unreviewed", "reviewer": None, "expires": None},
        "evidence",
    )
    assert evidence.as_dict()["reviewer"] is None
    reviewed = _evidence(
        {
            "confidence": "exact",
            "review": "accepted",
            "reviewer": "reviewer",
            "expires": "2027-08-30",
        },
        "evidence",
    )
    assert reviewed.expires == "2027-08-30"


def test_source_reader_and_verifier_fail_closed():
    source = {
        "id": "source:a",
        "kind": "capture",
        "locator": "capture.json",
        "content_sha256": "0" * 64,
    }
    with pytest.raises(ContinuityFormatError, match="non-empty array"):
        _sources([], "sources")
    with pytest.raises(ContinuityFormatError, match="duplicate identities"):
        _sources([source, source], "sources")
    parsed = _sources([source], "sources")
    with pytest.raises(ContinuityFormatError, match="locator-to-bytes"):
        _verify_sources(parsed, {"capture.json": "not bytes"})
    with pytest.raises(ContinuityFormatError, match="source set"):
        _verify_sources(parsed, {})
    with pytest.raises(ContinuityFormatError, match="capture.json"):
        _verify_sources(parsed, {"capture.json": b"wrong"})


def _mutate_fixture(name: str, mutate) -> str:
    raw = json.loads((FIXTURES / name).read_text())
    mutate(raw)
    return json.dumps(raw)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(continuity_binding_version=2), "unsupported"),
        (lambda raw: raw["adapter"].update(version=2), "not supported"),
        (lambda raw: raw["mediation"].update(kind="claimed"), "mediation"),
        (lambda raw: raw["signature"].update(algorithm="rsa"), "cryptographic"),
        (lambda raw: raw["validity"].update(expires_at=raw["validity"]["issued_at"]), "half-open"),
    ],
)
def test_binding_reader_rejects_invalid_contracts(mutate, message):
    with pytest.raises(ContinuityFormatError, match=message):
        ContinuityBinding.from_json(_mutate_fixture("continuity-binding-v1.json", mutate))


@pytest.mark.parametrize(
    ("reader", "fixture", "version_field"),
    [
        (AgentCoreContinuity, "agentcore-continuity-v1.json", "agentcore_continuity_version"),
        (AnthropicContinuity, "anthropic-continuity-v1.json", "anthropic_continuity_version"),
    ],
)
def test_provider_readers_reject_future_versions(reader, fixture, version_field):
    text = _mutate_fixture(fixture, lambda raw: raw.update({version_field: 2}))
    with pytest.raises(ContinuityFormatError, match="unsupported"):
        reader.from_json(text)


@pytest.mark.parametrize(
    ("reader", "fixture", "mutate"),
    [
        (
            AgentCoreContinuity,
            "agentcore-continuity-v1.json",
            lambda raw: raw.update(provider="other"),
        ),
        (
            AnthropicContinuity,
            "anthropic-continuity-v1.json",
            lambda raw: raw.update(service="other"),
        ),
    ],
)
def test_provider_readers_reject_other_profiles(reader, fixture, mutate):
    with pytest.raises(ContinuityFormatError, match="not supported"):
        reader.from_json(_mutate_fixture(fixture, mutate))


def test_agentcore_control_reader_rejects_bad_shapes():
    valid = json.loads((FIXTURES / "agentcore-continuity-v1.json").read_text())
    source_ids = {source["id"] for source in valid["sources"]}
    control = valid["controls"][0]
    cases = [
        ([], "must be an array"),
        ([{**control, "transition": "wrong"}], "vocabulary"),
        ([{**control, "provider_limits": []}], "provider_limits"),
        ([{**control, "outcomes": ["wrong"]}], "invalid value"),
        ([{**control, "sources": ["source:missing"]}], "unknown source"),
        ([{**control, "revision_changed": "yes"}], "boolean"),
        ([control, control], "duplicate ids"),
    ]
    for value, message in cases:
        with pytest.raises(ContinuityFormatError, match=message):
            _agentcore_controls(value, source_ids)


def test_anthropic_control_reader_rejects_bad_shapes():
    valid = json.loads((FIXTURES / "anthropic-continuity-v1.json").read_text())
    source_ids = {source["id"] for source in valid["sources"]}
    control = valid["controls"][0]
    cases = [
        ([], "must be an array"),
        ([{**control, "transition": "wrong"}], "invalid value"),
        ([{**control, "final_costs": []}], "final_costs"),
        ([{**control, "consumed_before": {}}], "array or null"),
        ([{**control, "consumed_before": [1]}], "one value per trial"),
        ([{**control, "child_count": 0}], "integer"),
        ([{**control, "topology_complete": "yes"}], "boolean"),
        ([{**control, "final_costs": [1]}], "one value per trial"),
        ([{**control, "child_count": 1}], "child topology together"),
        ([{**control, "sources": ["source:missing"]}], "unknown source"),
        ([control, control], "duplicate ids"),
    ]
    for value, message in cases:
        with pytest.raises(ContinuityFormatError, match=message):
            _anthropic_controls(value, source_ids)


def test_migration_source_and_capture_errors_are_named():
    with pytest.raises(ContinuityFormatError, match="differs at locator"):
        _migration_sources({}, {"missing.json": "capture"}, {"missing.json": "0" * 64})
    with pytest.raises(ContinuityFormatError, match="reviewed locator"):
        _migration_sources(
            {"capture.json": b"changed"},
            {"capture.json": "capture"},
            {"capture.json": "0" * 64},
        )
    with pytest.raises(ContinuityFormatError, match="missing source locator"):
        _captured({}, "missing.json")
    with pytest.raises(ContinuityFormatError, match="must be bytes"):
        _captured({"capture.json": "bad"}, "capture.json")
    with pytest.raises(ContinuityFormatError, match="must contain an object"):
        _captured({"capture.json": b"[]"}, "capture.json")


def _replace_json(contents: dict[str, bytes], suffix: str, mutate) -> dict[str, bytes]:
    result = dict(contents)
    locator = next(name for name in result if name.endswith(suffix))
    raw = json.loads(result[locator])
    mutate(raw)
    result[locator] = json.dumps(raw).encode()
    return result


def _allow_rehashed_migration(monkeypatch):
    original = _migration_sources

    def rehashed(contents, kinds, expected):
        del expected
        return original(
            contents,
            kinds,
            {locator: hashlib.sha256(contents[locator]).hexdigest() for locator in kinds},
        )

    monkeypatch.setattr(continuity, "_migration_sources", rehashed)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.update(binding_version=2),
        lambda raw: raw.pop("issuer"),
    ],
)
def test_binding_migration_rejects_changed_transport(mutate, monkeypatch):
    _allow_rehashed_migration(monkeypatch)
    with pytest.raises(ContinuityFormatError):
        migrate_agentcore_binding(
            _replace_json(_binding_contents(), "mandate-binding.json", mutate)
        )


def test_binding_migration_rejects_changed_controls(monkeypatch):
    _allow_rehashed_migration(monkeypatch)
    changed = _replace_json(
        _binding_contents(),
        "mandate-binding-result.json",
        lambda raw: raw["same_signed_mandate"].update(calls=[]),
    )
    with pytest.raises(ContinuityFormatError, match="controls do not match"):
        migrate_agentcore_binding(changed)


@pytest.mark.parametrize(
    ("suffix", "mutate"),
    [
        (
            "temporal-repetition.json",
            lambda raw: raw["results"].update(same_session_allow_then_deny=9),
        ),
        (
            "temporal-transition-confirmation-summary.json",
            lambda raw: raw["results"].update(alpha_equivalent_revision_changed=9),
        ),
        (
            "temporal-update-repetition.json",
            lambda raw: raw["results"].update(old_session_rejected_as_stale=9),
        ),
        (
            "binding-repetition.json",
            lambda raw: raw["results"].update(same_binding_allow_then_deny=9),
        ),
        (
            "binding-policy-revision-repetition.json",
            lambda raw: raw["results"].update(same_mandate_across_revision_aggregate=1199),
        ),
    ],
)
def test_agentcore_migration_rejects_changed_controls(suffix, mutate, monkeypatch):
    _allow_rehashed_migration(monkeypatch)
    with pytest.raises(ContinuityFormatError, match="does not match source"):
        migrate_agentcore_continuity(_replace_json(_agentcore_contents(), suffix, mutate))


def test_anthropic_migration_rejects_bad_joins_and_cells(monkeypatch):
    _allow_rehashed_migration(monkeypatch)
    bad_join = _replace_json(
        _anthropic_contents(), "confirmation.json", lambda raw: raw.update(protocol_sha256="0" * 64)
    )
    with pytest.raises(ContinuityFormatError, match="protocol join"):
        migrate_anthropic_continuity(bad_join)

    bad_trials = _replace_json(
        _anthropic_contents(), "confirmation.json", lambda raw: raw.update(trials={})
    )
    with pytest.raises(ContinuityFormatError, match="trials must be arrays"):
        migrate_anthropic_continuity(bad_trials)

    wrong_count = _replace_json(
        _anthropic_contents(), "confirmation.json", lambda raw: raw["trials"].pop()
    )
    with pytest.raises(ContinuityFormatError, match="trial counts differ"):
        migrate_anthropic_continuity(wrong_count)

    bad_cell = _replace_json(
        _anthropic_contents(),
        "confirmation.json",
        lambda raw: raw["trials"][0].update(cell="other"),
    )
    with pytest.raises(ContinuityFormatError, match="cell fresh_session_replication differs"):
        migrate_anthropic_continuity(bad_cell)

    bad_topology = _replace_json(
        _anthropic_contents(),
        "multiagent-confirmation.json",
        lambda raw: raw["trials"][0]["topology"].update(protocol_conformant=False),
    )
    with pytest.raises(ContinuityFormatError, match="cell concurrent_subagents_2 differs"):
        migrate_anthropic_continuity(bad_topology)
