from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from agentmandate._conditions import Evidence, Grant, _profile_digest
from agentmandate._delegation import (
    DELEGATION_ADAPTER,
    DELEGATION_ADAPTER_VERSION,
    DelegationChain,
    DelegationFormatError,
    _validate_delegation_profile,
)
from agentmandate._ir import (
    AuthorityIR,
    Entity,
    Fact,
    IRFormatError,
    _analyse_ir,
    _entity_id,
    _fact_id,
)

FIXTURES = Path(__file__).parent / "fixtures"
GRANT = FIXTURES / "delegation-grant-v1.json"
GRANT_CAPTURE = FIXTURES / "delegation-grant-capture.json"
MIGRATED_GRANT = FIXTURES / "delegation-chain-migrated-v1.json"
MIGRATED_AUTHORIZER = FIXTURES / "delegation-chain-authorizer-v1.json"
AUTHORIZER = (
    Path(__file__).parents[1] / "docs" / "evidence" / "authorizer-delegation" / "capture.json"
)
REVIEW = Evidence("exact", "accepted", "evidence-review", "2027-08-25")


def authorizer_chain() -> DelegationChain:
    return DelegationChain.from_authorizer_capture(AUTHORIZER.read_text(encoding="utf-8"), REVIEW)


def raw_chain() -> dict:
    return authorizer_chain().as_dict()


def parse(raw: dict) -> DelegationChain:
    return DelegationChain.from_json(json.dumps(raw))


def test_authorizer_projection_preserves_all_four_hops_without_policy_invention():
    chain = authorizer_chain()
    capture = json.loads(AUTHORIZER.read_text(encoding="utf-8"))

    assert chain.subject == capture["subject"]["alias"]
    assert len(chain.hops) == 4
    assert chain.actor_history_complete
    assert chain.actor_history_unresolved_hops == ()
    for hop, observed in zip(chain.hops, capture["hops"], strict=True):
        assert list(hop.actors) == observed["actor_chain"]
        assert hop.audience == observed["audience"]
        assert list(hop.scopes.members) == sorted(observed["scopes"])
        assert hop.scopes.completeness == "complete"
        assert hop.validity.kind == "duration"
        assert hop.validity.ttl_seconds == 300
        assert not hop.validity.attenuation_eligible
        assert hop.tools.completeness == hop.effects.completeness == "unknown"
        assert not hop.tools.members and not hop.effects.members


def test_authorizer_projection_is_canonical_and_verifies_its_source():
    chain = authorizer_chain()
    encoded = chain.to_json()

    assert encoded == MIGRATED_AUTHORIZER.read_text(encoding="utf-8")
    assert DelegationChain.from_json(encoded).to_json() == encoded
    chain.verify_sources({chain.hops[0].source.locator: AUTHORIZER.read_bytes()})

    with pytest.raises(DelegationFormatError, match=chain.hops[0].source.locator):
        chain.verify_sources({chain.hops[0].source.locator: b"{}"})
    with pytest.raises(DelegationFormatError, match=chain.hops[0].source.locator):
        chain.verify_sources({})
    with pytest.raises(DelegationFormatError, match=chain.hops[0].source.locator):
        chain.verify_sources({chain.hops[0].source.locator: "bad"})  # type: ignore[dict-item]
    with pytest.raises(DelegationFormatError, match="unexpected locator"):
        chain.verify_sources(
            {
                chain.hops[0].source.locator: AUTHORIZER.read_bytes(),
                "capture/undeclared.json": b"{}",
            }
        )


def test_grant_v1_migrates_without_precision_or_evidence_upgrade():
    old = Grant.from_json(GRANT.read_text(encoding="utf-8"))
    chain = DelegationChain.from_grant_v1(old)
    hop = chain.hops[0]

    assert chain.id == old.id and chain.subject == old.subject
    assert hop.actors == (old.actor,)
    assert hop.validity.kind == "date_window"
    assert not hop.validity.attenuation_eligible
    assert hop.evidence == old.evidence
    assert hop.scopes.members == old.scopes
    assert hop.tools.members == old.tools
    assert hop.effects.members == old.effects
    assert {hop.scopes.basis, hop.tools.basis, hop.effects.basis} == {"deployment_policy"}
    assert chain.to_json() == MIGRATED_GRANT.read_text(encoding="utf-8")
    chain.verify_sources({hop.source.locator: GRANT_CAPTURE.read_bytes()})


def test_grant_v1_without_digest_cannot_be_upgraded_during_migration():
    raw = json.loads(GRANT.read_text(encoding="utf-8"))
    del raw["source"]["content_sha256"]

    with pytest.raises(DelegationFormatError, match="digest-pinned"):
        DelegationChain.from_grant_v1(Grant.from_json(json.dumps(raw)))


def test_partial_actor_history_taints_every_chain_derived_decision():
    raw = raw_chain()
    raw["hops"][1]["actor_history"] = "partial"
    chain = parse(raw)

    assert not chain.actor_history_complete
    assert chain.actor_history_unresolved_hops == tuple(hop.id for hop in chain.hops)


def test_partial_history_still_requires_the_prior_current_actor_prefix():
    raw = raw_chain()
    raw["hops"][1]["actor_history"] = "partial"
    raw["hops"][2]["actors"][1] = "agent:other"

    with pytest.raises(DelegationFormatError, match="continuity"):
        parse(raw)


def test_validity_union_is_discriminated_and_only_window_is_eligible():
    raw = raw_chain()
    raw["hops"] = [raw["hops"][0]]
    cases = (
        ({"kind": "duration", "ttl_seconds": 300}, False),
        ({"kind": "date_window", "issued": "2026-08-01", "expires": "2026-08-02"}, False),
        (
            {
                "kind": "window",
                "issued_at": "2026-08-01T00:00:00Z",
                "expires_at": "2026-08-01T00:05:00Z",
            },
            True,
        ),
    )
    for validity, eligible in cases:
        raw["hops"][0]["validity"] = validity
        parsed = parse(raw).hops[0].validity
        assert parsed.kind == validity["kind"]
        assert parsed.attenuation_eligible is eligible
        assert parsed.as_dict() == validity


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(delegation_version=2),
        lambda d: d.update(delegation_version=True),
        lambda d: d.update(extra=True),
        lambda d: d.update(hops=[]),
        lambda d: d["hops"].append(d["hops"][0]),
        lambda d: d["hops"][1].update(actors=["agent:research-agent", "agent:wrong"]),
        lambda d: d["hops"][2].update(actors=["agent:crm-reader", "agent:research-agent"]),
        lambda d: d["hops"][0].update(actor_history="maybe"),
        lambda d: d["hops"][0].update(actors=["agent:x", "agent:x"]),
        lambda d: d["hops"][0].update(actors="agent:x"),
        lambda d: d["hops"][0].update(actors=[""]),
        lambda d: d["hops"][0]["validity"].update(ttl_seconds=0),
        lambda d: d["hops"][0].update(validity={"kind": "duration", "ttl_seconds": True}),
        lambda d: d["hops"][0].update(
            validity={
                "kind": "window",
                "issued_at": "2026-08-01",
                "expires_at": "2026-08-02T00:00:00Z",
            }
        ),
        lambda d: d["hops"][0].update(
            validity={
                "kind": "window",
                "issued_at": "2026-08-02T00:00:00Z",
                "expires_at": "2026-08-01T00:00:00Z",
            }
        ),
        lambda d: d["hops"][0].update(
            validity={"kind": "date_window", "issued": "20260801", "expires": "2026-08-02"}
        ),
        lambda d: d["hops"][0].update(
            validity={"kind": "date_window", "issued": "2026-08-03", "expires": "2026-08-02"}
        ),
        lambda d: d["hops"][0].update(
            validity={
                "kind": "window",
                "issued_at": "2026-13-01T00:00:00Z",
                "expires_at": "2027-08-01T00:00:00Z",
            }
        ),
        lambda d: d["hops"][0].update(
            validity={"kind": "date_window", "issued": "2026-13-01", "expires": "2027-08-02"}
        ),
        lambda d: d["hops"][0].update(
            validity={"kind": "duration", "ttl_seconds": 300, "expires": "2026-08-02"}
        ),
        lambda d: d["hops"][0]["source"].update(location="hops/0"),
        lambda d: d["hops"][0]["source"].update(location="/hops/~2"),
        lambda d: d["hops"][0]["source"].update(location=4),
        lambda d: d["hops"][0]["source"].update(content_sha256="bad"),
        lambda d: d["hops"][0]["surface"]["tools"].update(members=["invented"]),
        lambda d: d["hops"][0]["surface"]["tools"].update(domain="x"),
        lambda d: d["hops"][0]["surface"]["scopes"].update(domain=None),
        lambda d: d["hops"][0]["surface"]["scopes"].pop("evidence"),
        lambda d: d["hops"][0]["surface"]["scopes"].update(completeness="partial", members=[]),
        lambda d: d["hops"][0]["surface"]["tools"].update(
            domain="x",
            basis="issuer",
            completeness="complete",
            members=["x"],
            evidence=d["hops"][0]["evidence"],
            source=d["hops"][0]["source"],
        ),
        lambda d: d["hops"][0]["surface"]["effects"].update(
            domain="x",
            basis="deployment_policy",
            completeness="complete",
            members=["execute"],
            evidence=d["hops"][0]["evidence"],
            source=d["hops"][0]["source"],
        ),
    ],
)
def test_strict_reader_rejects_malformed_or_semantically_unsafe_chains(mutate):
    raw = raw_chain()
    mutate(raw)

    with pytest.raises(DelegationFormatError):
        parse(raw)


def test_records_are_frozen_and_digest_conflicts_fail_at_read_time():
    chain = authorizer_chain()
    with pytest.raises(FrozenInstanceError):
        chain.subject = "other"  # type: ignore[misc]

    raw = chain.as_dict()
    raw["hops"][0]["surface"]["scopes"]["source"]["content_sha256"] = "0" * 64
    with pytest.raises(DelegationFormatError, match="disagree"):
        parse(raw)

    conflicting_source = replace(chain.hops[0].scopes.source, content_sha256="0" * 64)
    conflicting_scope = replace(chain.hops[0].scopes, source=conflicting_source)
    conflicting_hop = replace(chain.hops[0], scopes=conflicting_scope)
    conflicting_chain = replace(chain, hops=(conflicting_hop, *chain.hops[1:]))
    with pytest.raises(DelegationFormatError, match=chain.hops[0].source.locator):
        conflicting_chain.verify_sources({})


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(capture_version=2),
        lambda d: d["hops"][0].update(actor="agent:wrong"),
        lambda d: d["hops"][0].update(ttl_seconds=0),
    ],
)
def test_authorizer_adapter_rejects_unsupported_or_inconsistent_capture(mutate):
    raw = json.loads(AUTHORIZER.read_text(encoding="utf-8"))
    mutate(raw)
    with pytest.raises(DelegationFormatError):
        DelegationChain.from_authorizer_capture(json.dumps(raw), REVIEW)


def test_projection_digest_is_pinned_for_stability():
    assert hashlib.sha256(authorizer_chain().to_json().encode()).hexdigest() == (
        "62a8df5f204a3ec665ecc7d1d00f2f6945a0e52c8c8afeb26d67188b3f4be764"
    )


@pytest.mark.parametrize(
    ("chain", "projection_sha256"),
    [
        pytest.param(
            authorizer_chain(),
            "b1e8c43497d9408526cb649eecf844bbbf8f6b00afa37aa8703a3f8eeb2346f8",
            id="authorizer",
        ),
        pytest.param(
            DelegationChain.from_grant_v1(Grant.from_json(GRANT.read_text(encoding="utf-8"))),
            "a5b2ad851500cd8f554e9bab124b7b291dee431815812b73ce5345d63066528d",
            id="migrated-grant",
        ),
    ],
)
def test_delegation_ir_projection_is_structural_and_byte_stable(chain, projection_sha256):
    graph = chain.to_ir()

    assert AuthorityIR.from_json(graph.to_json()).to_json() == graph.to_json()
    assert hashlib.sha256(graph.to_json().encode()).hexdigest() == projection_sha256
    assert graph.sources[0].adapter == DELEGATION_ADAPTER
    assert graph.sources[0].adapter_version == DELEGATION_ADAPTER_VERSION
    assert graph.sources[0].content_sha256 == hashlib.sha256(chain.to_json().encode()).hexdigest()
    assert [edge.relation for edge in graph.edges].count("has_hop") == len(chain.hops)
    assert [edge.relation for edge in graph.edges].count("previous_hop") == len(chain.hops) - 1
    assert [edge.relation for edge in graph.edges].count("has_surface") == 3 * len(chain.hops)

    with pytest.raises(IRFormatError, match="analyzable manifest-v1 profile"):
        _analyse_ir(graph)


def test_authorizer_ir_preserves_chain_order_validity_and_unknown_policy_surfaces():
    graph = authorizer_chain().to_ir()
    facts = {(fact.subject, fact.predicate): fact.value for fact in graph.facts}
    root = next(entity for entity in graph.entities if entity.kind == "delegation")
    hops = facts[(root.id, "hops")]

    assert len(hops) == 4
    for index, hop in enumerate(hops):
        assert facts[(hop, "previous")] == (hops[index - 1] if index else None)
        assert facts[(hop, "validity")] == {"kind": "duration", "ttl_seconds": 300}
        assert facts[(hop, "actor_history")] == "complete"
        surfaces = facts[(hop, "surfaces")]
        by_dimension = {facts[(surface, "dimension")]: surface for surface in surfaces}
        assert facts[(by_dimension["tools"], "completeness")] == "unknown"
        assert facts[(by_dimension["tools"], "members")] == []
        assert facts[(by_dimension["effects"], "completeness")] == "unknown"
        assert facts[(by_dimension["effects"], "members")] == []


def rehash(graph: AuthorityIR) -> AuthorityIR:
    return replace(
        graph,
        sources=(
            replace(
                graph.sources[0],
                semantic_sha256=_profile_digest(graph.entities, graph.facts, graph.edges),
            ),
        ),
    )


def replace_fact_value(
    graph: AuthorityIR, subject: str, predicate: str, value: object
) -> AuthorityIR:
    fact = next(
        item for item in graph.facts if item.subject == subject and item.predicate == predicate
    )
    changed = replace(fact, value=value)
    return replace(
        graph,
        facts=tuple(changed if item.id == fact.id else item for item in graph.facts),
    )


def test_delegation_ir_profile_rejects_semantic_tampering_after_rehash():
    graph = authorizer_chain().to_ir()
    root = next(entity for entity in graph.entities if entity.kind == "delegation")
    hops = next(
        fact for fact in graph.facts if fact.subject == root.id and fact.predicate == "hops"
    )
    changed = replace(hops, value=list(reversed(hops.value)))
    tampered = replace(
        graph,
        facts=tuple(changed if fact.id == hops.id else fact for fact in graph.facts),
    )

    with pytest.raises(DelegationFormatError, match="hop order"):
        _validate_delegation_profile(rehash(tampered))


def test_delegation_ir_profile_requires_uniform_evidence_state():
    graph = authorizer_chain().to_ir()
    fact = graph.facts[-1]
    changed = replace(
        fact,
        evidence=(replace(fact.evidence[0], review="contested"),),
    )
    tampered = replace(
        graph,
        facts=(*graph.facts[:-1], changed),
    )

    with pytest.raises(DelegationFormatError, match="disagree on evidence state"):
        _validate_delegation_profile(rehash(tampered))


def test_delegation_ir_profile_rejects_unsupported_entities_and_hop_sets():
    graph = authorizer_chain().to_ir()
    extra_id = _entity_id("mystery", "extra")
    extra = Entity(extra_id, "mystery", "extra")
    evidence = graph.facts[0].evidence
    extra_fact = Fact(_fact_id(extra_id, "name"), extra_id, "name", "extra", evidence)
    with pytest.raises(DelegationFormatError, match="unsupported entities"):
        _validate_delegation_profile(
            rehash(
                replace(
                    graph,
                    entities=(*graph.entities, extra),
                    facts=(*graph.facts, extra_fact),
                )
            )
        )

    root = next(entity for entity in graph.entities if entity.kind == "delegation")
    hops = next(
        fact for fact in graph.facts if fact.subject == root.id and fact.predicate == "hops"
    )
    duplicated = replace(hops, value=[*hops.value, hops.value[-1]])
    with pytest.raises(DelegationFormatError, match="hops do not match"):
        _validate_delegation_profile(
            rehash(
                replace(
                    graph,
                    facts=tuple(duplicated if fact.id == hops.id else fact for fact in graph.facts),
                )
            )
        )


@pytest.mark.parametrize(
    ("predicate", "relation", "message"),
    [
        ("actors", "acts_under", "invalid actors"),
        ("surfaces", "has_surface", "invalid surfaces"),
    ],
)
def test_delegation_ir_profile_rejects_empty_hop_members(predicate, relation, message):
    graph = authorizer_chain().to_ir()
    hop = next(entity for entity in graph.entities if entity.kind == "hop")
    member_fact = next(
        fact for fact in graph.facts if fact.subject == hop.id and fact.predicate == predicate
    )
    changed = replace(member_fact, value=[])
    tampered = replace(
        graph,
        facts=tuple(changed if fact.id == member_fact.id else fact for fact in graph.facts),
        edges=tuple(
            edge
            for edge in graph.edges
            if not (edge.source == hop.id and edge.relation == relation)
        ),
    )

    with pytest.raises(DelegationFormatError, match=message):
        _validate_delegation_profile(rehash(tampered))


def test_delegation_ir_profile_rejects_invalid_hop_semantics():
    graph = authorizer_chain().to_ir()
    hops = [entity for entity in graph.entities if entity.kind == "hop"]

    invalid_history = replace_fact_value(graph, hops[0].id, "actor_history", "invented")
    with pytest.raises(DelegationFormatError, match="actor history"):
        _validate_delegation_profile(rehash(invalid_history))

    actors = next(
        fact for fact in graph.facts if fact.subject == hops[1].id and fact.predicate == "actors"
    ).value
    broken = replace_fact_value(graph, hops[1].id, "actors", list(reversed(actors)))
    with pytest.raises(DelegationFormatError, match="broken actor continuity"):
        _validate_delegation_profile(rehash(broken))

    actors = next(
        fact for fact in graph.facts if fact.subject == hops[2].id and fact.predicate == "actors"
    ).value
    incomplete = replace_fact_value(graph, hops[2].id, "actors", actors[:2])
    incomplete = replace(
        incomplete,
        edges=tuple(
            edge
            for edge in incomplete.edges
            if not (
                edge.source == hops[2].id
                and edge.relation == "acts_under"
                and edge.target == actors[2]
            )
        ),
    )
    with pytest.raises(DelegationFormatError, match="incomplete actor continuity"):
        _validate_delegation_profile(rehash(incomplete))

    invalid_validity = replace_fact_value(graph, hops[0].id, "validity", "duration")
    with pytest.raises(DelegationFormatError, match="invalid validity"):
        _validate_delegation_profile(rehash(invalid_validity))


def test_delegation_ir_profile_rejects_invalid_surface_semantics():
    graph = authorizer_chain().to_ir()
    surfaces = [entity for entity in graph.entities if entity.kind == "surface"]
    by_dimension = {
        next(
            fact
            for fact in graph.facts
            if fact.subject == surface.id and fact.predicate == "dimension"
        ).value: surface
        for surface in surfaces[:3]
    }

    duplicate = replace_fact_value(graph, by_dimension["effects"].id, "dimension", "tools")
    with pytest.raises(DelegationFormatError, match="invalid surface dimensions"):
        _validate_delegation_profile(rehash(duplicate))

    invalid_state = replace_fact_value(graph, by_dimension["scopes"].id, "completeness", "maybe")
    with pytest.raises(DelegationFormatError, match="invalid surface state"):
        _validate_delegation_profile(rehash(invalid_state))

    unknown_claim = replace_fact_value(graph, by_dimension["tools"].id, "basis", "issuer")
    with pytest.raises(DelegationFormatError, match="invalid unknown surface"):
        _validate_delegation_profile(rehash(unknown_claim))

    incomplete_claim = replace_fact_value(graph, by_dimension["scopes"].id, "domain", None)
    with pytest.raises(DelegationFormatError, match="invalid claimed surface"):
        _validate_delegation_profile(rehash(incomplete_claim))
