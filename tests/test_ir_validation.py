from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from agentmandate import loads
from agentmandate._ir import (
    RELATIONS,
    AuthorityIR,
    Evidence,
    IRFormatError,
    _analyse_ir,
    _edge_id,
    _fact_id,
    _from_mandate,
)

MANIFEST = """
agent: validator
roles:
  reader: [read_case]
tools:
  - name: open_case
    effect: write
    produces: case
  - name: read_case
    effect: read
    requires: [case]
"""


def snapshot() -> AuthorityIR:
    return _from_mandate(loads(MANIFEST))


def duplicate_source(value: AuthorityIR) -> AuthorityIR:
    return replace(value, sources=value.sources + (value.sources[0],))


def duplicate_edge(value: AuthorityIR) -> AuthorityIR:
    return replace(value, edges=value.edges + (value.edges[0],))


def mismatched_entity_id(value: AuthorityIR) -> AuthorityIR:
    changed = replace(value.entities[0], id="agent:not-the-name")
    return replace(value, entities=(changed,) + value.entities[1:])


def mismatched_fact_id(value: AuthorityIR) -> AuthorityIR:
    changed = replace(value.facts[0], id="fact:not-canonical")
    return replace(value, facts=(changed,) + value.facts[1:])


def unknown_fact_subject(value: AuthorityIR) -> AuthorityIR:
    changed = replace(
        value.facts[0],
        id=_fact_id("agent:missing", value.facts[0].predicate),
        subject="agent:missing",
    )
    return replace(value, facts=(changed,) + value.facts[1:])


def conflicting_fact(value: AuthorityIR) -> AuthorityIR:
    original = next(item for item in value.facts if item.predicate == "effect")
    changed = replace(original, value="irreversible")
    return replace(value, facts=value.facts + (changed,))


def unknown_evidence_source(value: AuthorityIR) -> AuthorityIR:
    fact = value.facts[0]
    changed = replace(fact, evidence=(replace(fact.evidence[0], source="source:missing"),))
    return replace(value, facts=(changed,) + value.facts[1:])


def unknown_confidence(value: AuthorityIR) -> AuthorityIR:
    fact = value.facts[0]
    changed = replace(fact, evidence=(replace(fact.evidence[0], confidence="maybe"),))
    return replace(value, facts=(changed,) + value.facts[1:])


def unknown_review(value: AuthorityIR) -> AuthorityIR:
    fact = value.facts[0]
    changed = replace(fact, evidence=(replace(fact.evidence[0], review="rubber-stamped"),))
    return replace(value, facts=(changed,) + value.facts[1:])


def mismatched_edge_id(value: AuthorityIR) -> AuthorityIR:
    changed = replace(value.edges[0], id="edge:not-canonical")
    return replace(value, edges=(changed,) + value.edges[1:])


def unknown_relation(value: AuthorityIR) -> AuthorityIR:
    edge = value.edges[0]
    changed = replace(
        edge,
        id=_edge_id(edge.source, "invented", edge.target),
        relation="invented",
    )
    return replace(value, edges=(changed,) + value.edges[1:])


def unknown_endpoint(value: AuthorityIR) -> AuthorityIR:
    edge = value.edges[0]
    changed = replace(
        edge,
        id=_edge_id(edge.source, edge.relation, "tool:missing"),
        target="tool:missing",
    )
    return replace(value, edges=(changed,) + value.edges[1:])


def invalid_endpoint_kind(value: AuthorityIR) -> AuthorityIR:
    edge = next(item for item in value.edges if item.relation == "acts_as")
    changed = replace(
        edge,
        id=_edge_id(edge.source, edge.relation, "agent:validator"),
        target="agent:validator",
    )
    edges = tuple(changed if item == edge else item for item in value.edges)
    return replace(value, edges=edges)


def unsupported_edge(value: AuthorityIR) -> AuthorityIR:
    edge = value.edges[0]
    changed = replace(edge, support=())
    return replace(value, edges=(changed,) + value.edges[1:])


def unknown_support(value: AuthorityIR) -> AuthorityIR:
    edge = value.edges[0]
    changed = replace(edge, support=("fact:missing",))
    return replace(value, edges=(changed,) + value.edges[1:])


def support_from_another_entity(value: AuthorityIR) -> AuthorityIR:
    edge = value.edges[0]
    other = next(item for item in value.facts if item.subject != edge.source)
    changed = replace(edge, support=(other.id,))
    return replace(value, edges=(changed,) + value.edges[1:])


def support_does_not_establish_relation(value: AuthorityIR) -> AuthorityIR:
    edge = value.edges[0]
    name = next(
        item
        for item in value.facts
        if item.subject == edge.source and item.predicate == "name"
    )
    changed = replace(edge, support=(name.id,))
    return replace(value, edges=(changed,) + value.edges[1:])


def missing_derived_edge(value: AuthorityIR) -> AuthorityIR:
    return replace(value, edges=value.edges[1:])


CASES: tuple[tuple[Callable[[AuthorityIR], AuthorityIR], str], ...] = (
    (duplicate_source, "duplicate source id"),
    (duplicate_edge, "duplicate edge id"),
    (mismatched_entity_id, "entity id does not match"),
    (mismatched_fact_id, "fact id does not match"),
    (unknown_fact_subject, "unknown subject"),
    (conflicting_fact, "conflicting facts"),
    (unknown_evidence_source, "unknown source"),
    (unknown_confidence, "unknown confidence"),
    (unknown_review, "unknown review"),
    (mismatched_edge_id, "edge id does not match"),
    (unknown_relation, "unknown relation"),
    (unknown_endpoint, "unknown endpoint"),
    (invalid_endpoint_kind, "invalid endpoint kinds"),
    (unsupported_edge, "has no support"),
    (unknown_support, "unknown support"),
    (support_from_another_entity, "support from another entity"),
    (support_does_not_establish_relation, "not established by its support"),
    (missing_derived_edge, "is missing role_contains edge"),
)


@pytest.mark.parametrize(
    ("mutate", "message"), CASES, ids=[mutate.__name__ for mutate, _ in CASES]
)
def test_invalid_graphs_fail_before_analysis(
    mutate: Callable[[AuthorityIR], AuthorityIR], message: str
) -> None:
    with pytest.raises(IRFormatError, match=message):
        mutate(snapshot()).validate()


def test_relation_registry_declares_cardinality_merge_and_support_predicate() -> None:
    assert {
        name: (
            relation.cardinality,
            relation.merge,
            relation.predicate,
            relation.derived,
            relation.support_rule,
        )
        for name, relation in RELATIONS.items()
    } == {
        "acts_as": ("one", "single", "principal", False, "input"),
        "acts_under": ("many", "union", "actors", False, "input"),
        "at_hop": ("one", "single", "hop", False, "input"),
        "can_reach": ("many", "union", None, True, "reachable"),
        "ceiling_on": ("one", "single", "scope_key", False, "input"),
        "contains_policy": ("many", "union", "observed_policies", False, "input"),
        "contains_tool": ("many", "union", "members", False, "input"),
        "constrained_by": ("many", "union", "principals", False, "input"),
        "decides_request": ("one", "single", "request", False, "input"),
        "delegates_for": ("one", "single", "subject", False, "input"),
        "has_breach": ("many", "union", None, True, "breach"),
        "has_effect": ("many", "union", None, True, "effect"),
        "has_condition": ("many", "union", "conditions", False, "input"),
        "has_hop": ("many", "union", "hops", False, "input"),
        "has_surface": ("many", "union", "surfaces", False, "input"),
        "narrows_to": ("one", "single", "effect", False, "input"),
        "produces": ("one", "single", "produces", False, "input"),
        "previous_hop": ("one", "single", "previous", False, "input"),
        "requires": ("many", "union", "requires", False, "input"),
        "role_contains": ("many", "union", "members", False, "input"),
        "transitions_to": ("many", "union", None, True, "transition"),
        "under_grant": ("one", "single", "grant", False, "input"),
        "uses_delegation": ("one", "single", "delegation", False, "input"),
        "uses_context": ("one", "single", "context", False, "input"),
    }


def test_derived_support_must_be_acyclic() -> None:
    value = _analyse_ir(snapshot()).graph
    first, second = (edge for edge in value.edges if edge.relation == "has_effect")
    changed_first = replace(first, support=first.support + (second.id,))
    changed_second = replace(second, support=second.support + (first.id,))
    edges = tuple(
        changed_first
        if edge == first
        else changed_second
        if edge == second
        else edge
        for edge in value.edges
    )

    with pytest.raises(IRFormatError, match="derived support contains a cycle"):
        replace(value, edges=edges).validate()


def test_from_json_validates_the_graph_not_only_the_record_shapes() -> None:
    value = missing_derived_edge(snapshot())

    with pytest.raises(IRFormatError, match="is missing role_contains edge"):
        AuthorityIR.from_json(value.to_json())


def test_evidence_states_accepted_by_the_contract_validate() -> None:
    value = snapshot()
    fact = value.facts[0]
    evidence = (
        Evidence("source:mandate", "/x", "heuristic", "unreviewed"),
        Evidence("source:mandate", "/y", "unknown", "contested"),
    )
    changed = replace(fact, evidence=evidence)

    replace(value, facts=(changed,) + value.facts[1:]).validate()
