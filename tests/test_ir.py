from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

import agentmandate._ir as ir
from agentmandate import analyse, loads
from agentmandate._ir import (
    IR_VERSION,
    AuthorityIR,
    IRFormatError,
    _from_mandate,
    _to_mandate,
)

RICH = """
version: 1
agent: operations/team
identity: spiffe://example/agents/operations
limits:
  total: {amount: 75.50, currency: gbp}
  depth: 5
  effects:
    irreversible: 2
roles:
  operator/team: [open_case, issue_refund]
tools:
  - name: open_case
    effect: write
    produces: case
    unbounded: true
  - name: issue_refund
    effect: irreversible
    principal: service
    requires: [case]
    value_arg: amount
    ceiling: {amount: 50, currency: GBP}
    scope_key: case
    requires_approval: true
"""


def test_manifest_round_trips_through_canonical_json_without_semantic_change() -> None:
    mandate = loads(RICH, source="policies/operations.yaml")
    snapshot = _from_mandate(mandate, RICH.encode())
    encoded = snapshot.to_json()
    restored_snapshot = AuthorityIR.from_json(encoded)
    restored_mandate = _to_mandate(restored_snapshot)

    assert restored_snapshot == snapshot
    assert restored_snapshot.to_json() == encoded
    assert encoded.endswith("\n")
    assert restored_mandate == mandate
    assert analyse(restored_mandate).as_dict() == analyse(mandate).as_dict()


def test_records_preserve_entity_fact_edge_and_source_provenance() -> None:
    snapshot = _from_mandate(loads(RICH), RICH.encode())
    entities = {item.id: item for item in snapshot.entities}
    facts = {item.id: item for item in snapshot.facts}
    sources = {item.id: item for item in snapshot.sources}
    source = sources["source:mandate"]

    assert snapshot.ir_version == IR_VERSION
    assert entities["agent:operations%2Fteam"].name == "operations/team"
    assert {item.relation for item in snapshot.edges} == {
        "acts_as",
        "ceiling_on",
        "produces",
        "requires",
        "role_contains",
    }
    assert all(set(edge.support) <= set(facts) for edge in snapshot.edges)
    assert all(
        evidence.source in sources
        and evidence.confidence == "exact"
        and evidence.review == "accepted"
        for fact in snapshot.facts
        for evidence in fact.evidence
    )
    scope_name = facts["fact:scope:case:name"]
    assert {item.location for item in scope_name.evidence} == {
        "/tools/0/produces",
        "/tools/1/requires/0",
        "/tools/1/scope_key",
    }
    role_name = facts["fact:role:operator%2Fteam:name"]
    assert role_name.evidence[0].location == "/roles/operator~1team"
    assert source.content_sha256 == hashlib.sha256(RICH.encode()).hexdigest()
    assert source.adapter == "agentmandate.manifest"
    assert source.adapter_version == 2
    assert sources["source:manifest-v1"].adapter == "agentmandate.manifest-defaults"
    assert sources["source:manifest-v1"].adapter_version == 1


def test_canonical_json_orders_tables_evidence_and_edge_support() -> None:
    snapshot = _from_mandate(loads(RICH))
    facts = tuple(
        replace(item, evidence=tuple(reversed(item.evidence))) for item in reversed(snapshot.facts)
    )
    edges = tuple(
        replace(item, support=tuple(reversed(item.support))) for item in reversed(snapshot.edges)
    )
    reordered = replace(
        snapshot,
        sources=tuple(reversed(snapshot.sources)),
        entities=tuple(reversed(snapshot.entities)),
        facts=facts,
        edges=edges,
    )

    assert reordered.to_json() == snapshot.to_json()


def test_content_digest_is_optional_and_independent_of_semantic_projection() -> None:
    mandate = loads("agent: a\ntools: [{name: read_x, effect: read}]\n")
    without_content = _from_mandate(mandate)
    first = _from_mandate(mandate, b"first representation")
    second = _from_mandate(mandate, b"second representation")

    assert "content_sha256" not in without_content.sources[0].as_dict()
    assert first.sources[0].semantic_sha256 == second.sources[0].semantic_sha256
    assert first.sources[0].content_sha256 != second.sources[0].content_sha256
    assert _to_mandate(without_content) == mandate


@pytest.mark.parametrize("version", [True, 2])
def test_reader_rejects_an_unsupported_ir_version(version: object) -> None:
    payload = _from_mandate(loads("agent: a\ntools: [{name: t, effect: read}]\n")).as_dict()
    payload["ir_version"] = version

    with pytest.raises(IRFormatError, match="unsupported authority IR version"):
        AuthorityIR.from_json(json.dumps(payload))


def test_mandate_adapter_rejects_a_snapshot_from_another_ir_version() -> None:
    snapshot = _from_mandate(loads("agent: a\ntools: [{name: t, effect: read}]\n"))

    with pytest.raises(IRFormatError, match="unsupported authority IR version"):
        _to_mandate(replace(snapshot, ir_version=2))


def test_mandate_adapter_requires_one_agent_and_every_required_fact() -> None:
    snapshot = _from_mandate(loads("agent: a\ntools: [{name: t, effect: read}]\n"))
    without_agent = replace(
        snapshot,
        entities=tuple(item for item in snapshot.entities if item.kind != "agent"),
        facts=tuple(item for item in snapshot.facts if item.subject != "agent:a"),
    )
    without_identity = replace(
        snapshot,
        facts=tuple(item for item in snapshot.facts if item.predicate != "identity"),
    )

    with pytest.raises(IRFormatError, match="exactly one agent"):
        _to_mandate(without_agent)
    with pytest.raises(IRFormatError, match="complete analyzable manifest-v1 predicate set"):
        _to_mandate(without_identity)


def test_mandate_adapter_fails_closed_on_conflicting_single_valued_facts() -> None:
    snapshot = _from_mandate(loads("agent: a\ntools: [{name: t, effect: read}]\n"))
    effect = next(item for item in snapshot.facts if item.predicate == "effect")
    conflict = replace(effect, value="irreversible")

    with pytest.raises(IRFormatError, match=r"facts\[\d+\].id has conflicting facts"):
        _to_mandate(replace(snapshot, facts=snapshot.facts + (conflict,)))


def test_manifest_projection_refuses_an_internal_id_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ir._entity_id

    def collide_scopes(kind: str, name: str) -> str:
        return "scope:collision" if kind == "scope" else original(kind, name)

    monkeypatch.setattr(ir, "_entity_id", collide_scopes)
    mandate = loads(
        "agent: a\ntools:\n  - name: t\n    effect: read\n    requires: [first, second]\n"
    )

    with pytest.raises(IRFormatError, match="conflicting values for scope:collision.name"):
        _from_mandate(mandate)


def test_mandate_adapter_rejects_a_reference_to_the_wrong_entity_kind() -> None:
    snapshot = _from_mandate(
        loads("agent: a\ntools: [{name: t, effect: read, produces: case}]\n")
    )
    facts = tuple(
        replace(item, value=["scope:case"])
        if item.subject == "agent:a" and item.predicate == "tools"
        else item
        for item in snapshot.facts
    )

    with pytest.raises(IRFormatError, match="manifest profile schema tool_refs"):
        _to_mandate(replace(snapshot, facts=facts))
