from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from agentmandate._conditions import Evidence, Grant
from agentmandate._delegation import DelegationChain, DelegationFormatError

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

    with pytest.raises(DelegationFormatError, match="reviewed digest"):
        chain.verify_sources({chain.hops[0].source.locator: b"{}"})
    with pytest.raises(DelegationFormatError, match="declared locators"):
        chain.verify_sources({})
    with pytest.raises(DelegationFormatError, match="requires bytes"):
        chain.verify_sources({chain.hops[0].source.locator: "bad"})  # type: ignore[dict-item]


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
    with pytest.raises(DelegationFormatError, match="disagree"):
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
