from __future__ import annotations

from dataclasses import replace

import pytest

import agentmandate._ir as ir
from agentmandate import analyse, loads
from agentmandate._ir import (
    RELATIONS,
    AuthorityIR,
    Entity,
    IRFormatError,
    _analyse_ir,
    _edge_id,
    _entity_id,
    _fact_id,
    _from_mandate,
    _path_is_enabling,
    _to_mandate,
)
from agentmandate.reach import Step

COMPOUND = """
agent: compound
limits:
  total: {amount: 500, currency: GBP}
  depth: 8
  effects: {irreversible: 1}
tools:
  - name: open_case
    effect: read
    produces: case
    unbounded: true
  - name: issue_refund
    effect: irreversible
    requires: [case]
    value_arg: amount
    scope_key: case
    ceiling: {amount: 500, currency: GBP}
"""


def test_ir_reachability_preserves_authority_and_adds_only_derived_records() -> None:
    mandate = loads(COMPOUND)
    source = _from_mandate(mandate)
    result = _analyse_ir(source)
    derived = [edge for edge in result.graph.edges if RELATIONS[edge.relation].derived]

    assert result.authority == analyse(mandate)
    assert _to_mandate(result.graph) == mandate
    assert {edge.relation for edge in derived} == {
        "can_reach",
        "has_breach",
        "has_effect",
        "transitions_to",
    }
    assert not any(RELATIONS[edge.relation].derived for edge in source.edges)
    assert result.graph.facts == source.facts
    result.graph.validate()
    assert AuthorityIR.from_json(result.graph.to_json()) == result.graph


def test_derived_edges_cite_reach_effect_transition_and_limit_support() -> None:
    result = _analyse_ir(_from_mandate(loads(COMPOUND)))
    edges = {edge.id: edge for edge in result.graph.edges}
    facts = {fact.id for fact in result.graph.facts}
    input_edges = {
        edge.id for edge in result.graph.edges if not RELATIONS[edge.relation].derived
    }

    refund_reach = edges[
        _edge_id("agent:compound", "can_reach", "tool:issue_refund")
    ]
    refund_effect = edges[
        _edge_id("tool:issue_refund", "has_effect", "scope:case")
    ]
    assert _fact_id("agent:compound", "tools") in refund_reach.support
    assert _fact_id("tool:issue_refund", "requires") in refund_reach.support
    assert _edge_id("tool:open_case", "produces", "scope:case") in refund_reach.support
    assert set(refund_effect.support) == {
        refund_reach.id,
        _fact_id("tool:issue_refund", "effect"),
        _edge_id("tool:issue_refund", "requires", "scope:case"),
    }

    breach_edges = [edge for edge in edges.values() if edge.relation == "has_breach"]
    by_kind = {
        next(entity.name for entity in result.graph.entities if entity.id == edge.target).split(
            ":", maxsplit=1
        )[0]: edge
        for edge in breach_edges
    }
    cumulative = by_kind["cumulative_value"]
    effect_count = by_kind["effect_count"]
    ungated = by_kind["ungated_effect"]
    assert _fact_id("constraint:run", "total") in cumulative.support
    assert _fact_id("constraint:run", "effects") in effect_count.support
    assert _fact_id("tool:issue_refund", "requires_approval") in ungated.support

    for breach in result.authority.breaches:
        edge = by_kind[breach.kind]
        expected_transitions = {
            _edge_id(
                f"tool:{previous.tool}",
                "transitions_to",
                f"tool:{current.tool}",
            )
            for previous, current in zip(breach.path, breach.path[1:], strict=False)
        }
        assert expected_transitions <= set(edge.support)

    known_support = facts | input_edges | set(edges)
    assert all(set(edge.support) <= known_support for edge in breach_edges)


def test_retained_paths_replay_the_same_enabling_preconditions() -> None:
    mandate = loads(COMPOUND)

    assert _path_is_enabling(
        mandate,
        (Step("open_case", "case#1"), Step("issue_refund", "case#1")),
    )
    assert not _path_is_enabling(mandate, (Step("issue_refund", "case#1"),))
    assert not _path_is_enabling(mandate, (Step("missing"),))
    assert not _path_is_enabling(mandate, ())


@pytest.mark.parametrize(
    ("relation", "missing", "message"),
    [
        ("can_reach", "fact:agent:compound:tools", "reachable support"),
        ("has_effect", "fact:tool:issue_refund:effect", "effect support"),
        (
            "transitions_to",
            "edge:agent:compound:can_reach:tool:issue_refund",
            "transition support",
        ),
        ("has_breach", "fact:constraint:run:total", "breach support"),
    ],
)
def test_each_derived_relation_rejects_missing_semantic_support(
    relation: str, missing: str, message: str
) -> None:
    graph = _analyse_ir(_from_mandate(loads(COMPOUND))).graph
    candidate = next(
        edge
        for edge in graph.edges
        if edge.relation == relation
        and (relation != "has_breach" or "cumulative_value" in edge.target)
        and missing in edge.support
    )
    changed = replace(
        candidate,
        support=tuple(identifier for identifier in candidate.support if identifier != missing),
    )
    tampered = replace(
        graph,
        edges=tuple(changed if edge == candidate else edge for edge in graph.edges),
    )

    with pytest.raises(IRFormatError, match=message):
        tampered.validate()


def test_derived_validation_rejects_unknown_or_irrelevant_provenance() -> None:
    graph = _analyse_ir(_from_mandate(loads(COMPOUND))).graph
    effect = next(edge for edge in graph.edges if edge.relation == "has_effect")
    reachable = next(
        edge
        for edge in graph.edges
        if edge.relation == "can_reach" and edge.target == "tool:issue_refund"
    )

    unknown = replace(effect, support=effect.support + ("fact:missing",))
    with pytest.raises(IRFormatError, match="unknown support"):
        replace(
            graph,
            edges=tuple(unknown if edge == effect else edge for edge in graph.edges),
        ).validate()

    derived_root = replace(reachable, support=reachable.support + (effect.id,))
    with pytest.raises(IRFormatError, match="rooted in source records"):
        replace(
            graph,
            edges=tuple(
                derived_root if edge == reachable else edge for edge in graph.edges
            ),
        ).validate()

    producer = _edge_id("tool:open_case", "produces", "scope:case")
    without_producer = replace(
        reachable,
        support=tuple(identifier for identifier in reachable.support if identifier != producer),
    )
    with pytest.raises(IRFormatError, match="lacks a producer"):
        replace(
            graph,
            edges=tuple(
                without_producer if edge == reachable else edge for edge in graph.edges
            ),
        ).validate()


def test_derived_validation_rejects_inconsistent_entities_and_scope_support() -> None:
    graph = _analyse_ir(_from_mandate(loads(COMPOUND))).graph
    tools = next(
        fact
        for fact in graph.facts
        if fact.subject == "agent:compound" and fact.predicate == "tools"
    )
    without_refund = replace(
        tools, value=[tool for tool in tools.value if tool != "tool:issue_refund"]
    )
    with pytest.raises(IRFormatError, match="targets an undeclared tool"):
        replace(
            graph,
            facts=tuple(without_refund if fact == tools else fact for fact in graph.facts),
        ).validate()

    effect = next(
        edge
        for edge in graph.edges
        if edge.relation == "has_effect" and edge.source == "tool:issue_refund"
    )
    scope_edge = _edge_id("tool:issue_refund", "requires", "scope:case")
    without_scope = replace(
        effect,
        support=tuple(identifier for identifier in effect.support if identifier != scope_edge),
    )
    with pytest.raises(IRFormatError, match="lacks effect scope support"):
        replace(
            graph,
            edges=tuple(without_scope if edge == effect else edge for edge in graph.edges),
        ).validate()

    extra_agent = Entity("agent:other", "agent", "other")
    with pytest.raises(IRFormatError, match="require exactly one agent"):
        replace(graph, entities=graph.entities + (extra_agent,)).validate()


def test_breach_validation_rejects_missing_paths_and_unknown_breach_kinds() -> None:
    graph = _analyse_ir(_from_mandate(loads(COMPOUND))).graph
    cumulative = next(
        edge
        for edge in graph.edges
        if edge.relation == "has_breach" and "cumulative_value" in edge.target
    )
    edges = {edge.id: edge for edge in graph.edges}
    without_path = replace(
        cumulative,
        support=tuple(
            identifier
            for identifier in cumulative.support
            if identifier not in edges or edges[identifier].relation != "can_reach"
        ),
    )
    with pytest.raises(IRFormatError, match="lacks a reachable path"):
        replace(
            graph,
            edges=tuple(
                without_path if edge == cumulative else edge for edge in graph.edges
            ),
        ).validate()

    old_entity = next(entity for entity in graph.entities if entity.id == cumulative.target)
    new_id = _entity_id("breach", "unknown:run")
    new_entity = Entity(new_id, "breach", "unknown:run")
    unknown = replace(
        cumulative,
        id=_edge_id(cumulative.source, cumulative.relation, new_id),
        target=new_id,
    )
    with pytest.raises(IRFormatError, match="unknown breach entity"):
        replace(
            graph,
            entities=tuple(
                new_entity if entity == old_entity else entity for entity in graph.entities
            ),
            edges=tuple(unknown if edge == cumulative else edge for edge in graph.edges),
        ).validate()


def test_analysis_rejects_derived_input_and_a_non_replayable_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _from_mandate(loads(COMPOUND))
    result = _analyse_ir(source)
    with pytest.raises(IRFormatError, match="already contains derived edges"):
        _analyse_ir(result.graph)

    original = ir._analyse_with_trace

    def invalid_trace(mandate, depth=None):
        authority, trace = original(mandate, depth=depth)
        paths = tuple(
            (name, (Step("issue_refund"),)) if name == "issue_refund" else (name, path)
            for name, path in trace.reachable_paths
        )
        return authority, replace(trace, reachable_paths=paths)

    monkeypatch.setattr(ir, "_analyse_with_trace", invalid_trace)
    with pytest.raises(IRFormatError, match="path that does not replay"):
        _analyse_ir(source)


def test_unknown_derived_support_rule_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _analyse_ir(_from_mandate(loads(COMPOUND))).graph
    monkeypatch.setitem(
        RELATIONS,
        "has_effect",
        replace(RELATIONS["has_effect"], support_rule="invented"),
    )

    with pytest.raises(IRFormatError, match="unknown derived support rule"):
        graph.validate()
