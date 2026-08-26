from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from agentmandate import analyse, load, loads
from agentmandate._conditions import Evidence, Grant, _profile_digest
from agentmandate._delegation import (
    DELEGATION_ADAPTER,
    DELEGATION_ADAPTER_VERSION,
    DELEGATION_ATTACHMENT_ADAPTER,
    DELEGATION_ATTACHMENT_ADAPTER_VERSION,
    DelegationAttachment,
    DelegationChain,
    DelegationFormatError,
    _validate_attachment_profile,
    _validate_delegation_profile,
)
from agentmandate._delegation import (
    analyse_delegations as _analyse_delegations,
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
ATTACHMENT = FIXTURES / "delegation-attachment-v2.json"
REVIEW = Evidence("exact", "accepted", "evidence-review", "2027-08-25")


def authorizer_chain() -> DelegationChain:
    return DelegationChain.from_authorizer_capture(AUTHORIZER.read_text(encoding="utf-8"), REVIEW)


def raw_chain() -> dict:
    return authorizer_chain().as_dict()


def parse(raw: dict) -> DelegationChain:
    return DelegationChain.from_json(json.dumps(raw))


def attachment() -> DelegationAttachment:
    return DelegationAttachment.from_json(ATTACHMENT.read_text(encoding="utf-8"))


def mandate():
    return loads(
        json.dumps(
            {
                "version": 1,
                "agent": "export-agent",
                "tools": [
                    {
                        "name": "export_records",
                        "effect": "read",
                        "requires": ["openid"],
                    }
                ],
            }
        )
    )


def analyzable_chain() -> DelegationChain:
    raw = raw_chain()
    for hop in raw["hops"]:
        hop["validity"] = {
            "kind": "window",
            "issued_at": "2026-08-25T00:00:00Z",
            "expires_at": "2026-08-26T00:00:00Z",
        }
        for dimension, members in {
            "tools": ["export_records"],
            "effects": ["read"],
        }.items():
            surface = hop["surface"][dimension]
            surface.update(
                domain="demo",
                basis="deployment_policy",
                completeness="complete",
                members=members,
                evidence=hop["evidence"],
                source=hop["source"],
            )
    return parse(raw)


def analyse_delegations(*args, **kwargs):
    kwargs.setdefault("target_source", "deploy/agent.py")
    kwargs.setdefault("target_binding", "agent")
    return _analyse_delegations(*args, **kwargs)


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


def test_attachment_reader_and_profile_are_canonical_and_standalone():
    value = attachment()
    graph = value.to_ir()

    assert value.to_json() == ATTACHMENT.read_text(encoding="utf-8")
    assert DelegationAttachment.from_json(value.to_json()) == value
    assert AuthorityIR.from_json(graph.to_json()).to_json() == graph.to_json()
    assert graph.sources[0].adapter == DELEGATION_ATTACHMENT_ADAPTER
    assert graph.sources[0].adapter_version == DELEGATION_ATTACHMENT_ADAPTER_VERSION
    assert {edge.relation for edge in graph.edges} == {
        "acts_as",
        "at_hop",
        "uses_delegation",
    }
    with pytest.raises(IRFormatError, match="analyzable manifest-v1 profile"):
        _analyse_ir(graph)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(principal_version=1),
        lambda d: d.update(extra=True),
        lambda d: d["principal"].update(kind="service"),
        lambda d: d["principal"].pop("hop"),
    ],
)
def test_attachment_reader_rejects_unsupported_shapes(mutate):
    raw = attachment().as_dict()
    mutate(raw)
    with pytest.raises(DelegationFormatError):
        DelegationAttachment.from_json(json.dumps(raw))


def test_attachment_profile_rejects_semantic_tampering_after_rehash():
    graph = attachment().to_ir()
    principal = next(entity for entity in graph.entities if entity.kind == "principal")
    kind = next(
        fact for fact in graph.facts if fact.subject == principal.id and fact.predicate == "kind"
    )
    changed = replace(kind, value="fixed_user_credential")
    tampered = replace(
        graph,
        facts=tuple(changed if fact.id == kind.id else fact for fact in graph.facts),
    )
    with pytest.raises(DelegationFormatError, match="invalid kind"):
        _validate_attachment_profile(rehash(tampered))

    tool = next(entity for entity in graph.entities if entity.kind == "tool")
    target = next(
        fact for fact in graph.facts if fact.subject == tool.id and fact.predicate == "target"
    )
    changed_target = replace(target, value={**target.value, "tool": "other"})
    tampered_target = replace(
        graph,
        facts=tuple(
            changed_target if fact.id == target.id else fact for fact in graph.facts
        ),
    )
    with pytest.raises(DelegationFormatError, match="target does not match"):
        _validate_attachment_profile(rehash(tampered_target))

    extra = Entity(_entity_id("principal", "extra"), "principal", "extra")
    name = Fact(
        _fact_id(extra.id, "name"), extra.id, "name", "extra", graph.facts[0].evidence
    )
    with pytest.raises(DelegationFormatError, match="unsupported entities"):
        _validate_attachment_profile(
            rehash(replace(graph, entities=(*graph.entities, extra), facts=(*graph.facts, name)))
        )


def test_authorizer_analysis_is_unresolved_only_and_preserves_authority():
    result = analyse_delegations(
        mandate(),
        [attachment()],
        [authorizer_chain()],
        {authorizer_chain().hops[0].source.locator: AUTHORIZER.read_bytes()},
        as_of="2026-08-25T12:00:00Z",
    )

    assert result.authority.as_dict() == analyse_delegations(
        mandate(), [], [], {}, as_of="2026-08-25T12:00:00Z"
    ).authority.as_dict()
    assert not result.clean and not result.attenuated
    assert "delegation.validity-unresolved" in {finding.code for finding in result.findings}
    assert "delegation.surface-unresolved" in {finding.code for finding in result.findings}
    assert "delegation.widens" not in {finding.code for finding in result.findings}
    assert all(finding.support for finding in result.findings)


def test_complete_monotonic_chain_attenuates_and_rewidening_is_detected():
    chain = analyzable_chain()
    contents = {chain.hops[0].source.locator: AUTHORIZER.read_bytes()}
    clean = analyse_delegations(
        mandate(),
        [attachment()],
        [chain],
        contents,
        as_of="2026-08-25T00:00:00Z",
    )
    assert clean.clean
    assert len(clean.attenuated) == 1
    assert any(item.startswith("fact:") for item in clean.attenuated[0].support)
    assert any(item.startswith("edge:") for item in clean.attenuated[0].support)

    raw = chain.as_dict()
    raw["hops"][2]["surface"]["scopes"]["members"].append("mail:send")
    widened = analyse_delegations(
        mandate(),
        [attachment()],
        [parse(raw)],
        contents,
        as_of="2026-08-25T00:00:00Z",
    )
    finding = next(item for item in widened.findings if item.code == "delegation.widens")
    assert finding.hop == "hop-3" and finding.dimension == "scopes"
    assert finding.support
    assert not widened.attenuated


def test_expiry_is_exclusive_and_partial_history_taints_the_whole_chain():
    chain = analyzable_chain()
    contents = {chain.hops[0].source.locator: AUTHORIZER.read_bytes()}
    expired = analyse_delegations(
        mandate(),
        [attachment()],
        [chain],
        contents,
        as_of="2026-08-26T00:00:00Z",
    )
    assert all(item.code == "delegation.validity-unresolved" for item in expired.findings)

    raw = chain.as_dict()
    raw["hops"][1]["actor_history"] = "partial"
    partial = analyse_delegations(
        mandate(),
        [attachment()],
        [parse(raw)],
        contents,
        as_of="2026-08-25T12:00:00Z",
    )
    assert any(item.code == "delegation.actor-history-unresolved" for item in partial.findings)
    assert not partial.attenuated


def test_analysis_names_missing_locator_and_rejects_noncanonical_time():
    chain = analyzable_chain()
    result = analyse_delegations(
        mandate(),
        [attachment()],
        [chain],
        {},
        as_of="2026-08-25T12:00:00Z",
    )
    source = next(item for item in result.findings if item.code == "delegation.source-unresolved")
    assert chain.hops[0].source.locator in source.message

    with pytest.raises(DelegationFormatError, match="canonical UTC timestamp"):
        analyse_delegations(
            mandate(), [], [], {}, as_of="2026-08-25T12:00:00+00:00"
        )


@pytest.mark.parametrize(
    "path",
    [
        "agentkit/mandate.yaml",
        "github-mcp-server/mandate.yaml",
        "aws-postgres-mcp/mandate.yaml",
        "sentry-mcp/mandate.yaml",
    ],
)
def test_empty_delegation_inputs_preserve_all_four_evidence_graphs(path):
    value = load(Path(__file__).parents[1] / "docs" / "evidence" / path)
    result = analyse_delegations(value, [], [], {}, as_of="2026-08-25T12:00:00Z")

    assert result.authority.as_dict() == analyse(value).as_dict()
    assert result.clean and not result.attenuated


def test_analysis_reports_attachment_join_failures_without_omission():
    chain = analyzable_chain()
    contents = {chain.hops[0].source.locator: AUTHORIZER.read_bytes()}
    base = attachment()
    cases = [
        (replace(base, target=replace(base.target, tool="missing")), [chain], "target tool"),
        (base, [], "chain is missing"),
        (replace(base, hop="missing"), [chain], "hop is missing"),
        (replace(base, evidence=replace(base.evidence, review="contested")), [chain], "not exact"),
        (replace(base, evidence=replace(base.evidence, expires="2025-01-01")), [chain], "expired"),
    ]
    for item, chains, message in cases:
        result = analyse_delegations(
            mandate(), [item], chains, contents, as_of="2026-08-25T12:00:00Z"
        )
        assert any(message in finding.message for finding in result.findings)
        assert not result.attenuated

    duplicate = analyse_delegations(
        mandate(), [base, base], [chain], contents, as_of="2026-08-25T12:00:00Z"
    )
    assert any("more than once" in finding.message for finding in duplicate.findings)

    ambiguous = analyse_delegations(
        mandate(), [base], [chain, chain], contents, as_of="2026-08-25T12:00:00Z"
    )
    assert any("ambiguous" in finding.message for finding in ambiguous.findings)

    foreign = analyse_delegations(
        mandate(),
        [base],
        [chain],
        contents,
        as_of="2026-08-25T12:00:00Z",
        target_binding="other",
    )
    assert any("selected source binding" in finding.message for finding in foreign.findings)


def test_analysis_requires_current_reviewed_hops_and_surfaces():
    chain = analyzable_chain()
    contents = {chain.hops[0].source.locator: AUTHORIZER.read_bytes()}
    contested = Evidence("exact", "contested", "reviewer", "2027-08-25")
    contested_hops = tuple(
        replace(
            hop,
            evidence=contested,
            scopes=replace(hop.scopes, evidence=contested),
            tools=replace(hop.tools, evidence=contested),
            effects=replace(hop.effects, evidence=contested),
        )
        for hop in chain.hops
    )
    result = analyse_delegations(
        mandate(),
        [attachment()],
        [replace(chain, hops=contested_hops)],
        contents,
        as_of="2026-08-25T12:00:00Z",
    )
    assert any("hop evidence" in finding.message for finding in result.findings)
    assert not any(finding.code == "delegation.widens" for finding in result.findings)

    expired = Evidence("exact", "accepted", "reviewer", "2025-01-01")
    first = chain.hops[0]
    expired_first = replace(
        first,
        evidence=expired,
        scopes=replace(first.scopes, evidence=expired),
        tools=replace(first.tools, evidence=expired),
        effects=replace(first.effects, evidence=expired),
    )
    result = analyse_delegations(
        mandate(),
        [attachment()],
        [replace(chain, hops=(expired_first, *chain.hops[1:]))],
        contents,
        as_of="2026-08-25T12:00:00Z",
    )
    assert any("hop review is expired" in finding.message for finding in result.findings)
    assert any("surface evidence" in finding.message for finding in result.findings)


def test_analysis_distinguishes_domain_and_tool_widening_and_distrust():
    chain = analyzable_chain()
    contents = {chain.hops[0].source.locator: AUTHORIZER.read_bytes()}
    third = chain.hops[2]
    changed_domain = replace(third, scopes=replace(third.scopes, domain="other"))
    result = analyse_delegations(
        mandate(),
        [attachment()],
        [replace(chain, hops=(*chain.hops[:2], changed_domain, chain.hops[3]))],
        contents,
        as_of="2026-08-25T12:00:00Z",
    )
    assert any("incomparable domains" in finding.message for finding in result.findings)

    foreign_attachment = replace(attachment(), tool_domain="other")
    result = analyse_delegations(
        mandate(),
        [foreign_attachment],
        [chain],
        contents,
        as_of="2026-08-25T12:00:00Z",
    )
    assert any("tool attachment" in finding.message for finding in result.findings)

    last = chain.hops[-1]
    narrowed = replace(last, tools=replace(last.tools, members=()))
    widened_chain = replace(chain, hops=(*chain.hops[:-1], narrowed))
    result = analyse_delegations(
        mandate(),
        [attachment()],
        [widened_chain],
        contents,
        as_of="2026-08-25T12:00:00Z",
    )
    assert any("tool authority exceeds" in finding.message for finding in result.findings)

    unverified = analyse_delegations(
        mandate(),
        [attachment()],
        [widened_chain],
        {last.source.locator: b"wrong"},
        as_of="2026-08-25T12:00:00Z",
    )
    assert any(finding.code == "delegation.source-unresolved" for finding in unverified.findings)
    assert not any(finding.code == "delegation.widens" for finding in unverified.findings)
