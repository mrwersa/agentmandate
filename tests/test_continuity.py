from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

import agentmandate._continuity as continuity
from agentmandate._continuity import (
    AgentCoreContinuity,
    AnthropicContinuity,
    ContinuityBinding,
    ContinuityFormatError,
    _agentcore_controls,
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
    _sources,
    _string,
    _strings,
    _utc,
    _validate_continuity_profile,
    _verify_sources,
    migrate_agentcore_binding,
    migrate_agentcore_continuity,
    migrate_anthropic_continuity,
)
from agentmandate._ir import AuthorityIR, IRFormatError, _analyse_ir

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
            AGENTCORE / "temporal-semantic-noop-repetition.json",
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

    assert len(agentcore.controls) == 8
    assert next(
        item for item in agentcore.controls if item.id == "equivalent-revision"
    ).outcomes == (
        "allow",
        "stale_session",
        "allow",
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
    assert (len(agentcore.entities), len(agentcore.facts), len(agentcore.edges)) == (45, 187, 52)
    assert (len(anthropic.entities), len(anthropic.facts), len(anthropic.edges)) == (25, 111, 30)
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
        "agentcore-continuity": "4962f850b8b3736f1614385316f02f217a3f716d1d75ef894742fb0d717d1db9",
        "anthropic-continuity": "260cf8b10c0fb70b600db5cb101a79211c4aaf957ccc35ec7b68a40b345955bc",
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
            "temporal-semantic-noop-repetition.json",
            lambda raw: raw["results"].update(distinct_active_revision=9),
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
