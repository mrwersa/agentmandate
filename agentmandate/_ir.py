"""Experimental, private authority IR records and the manifest adapter.

Nothing in this module is exported from :mod:`agentmandate`.  The records are
the first implementation gate for the contract in ``docs/authority-ir.md``;
they can change while the four evidence graphs exercise the format.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from .manifest import SCHEMA_VERSION, Limits, Mandate, Money, Tool

IR_VERSION = 1
MANIFEST_ADAPTER = "agentmandate.manifest"
MANIFEST_ADAPTER_VERSION = 2
MANIFEST_DEFAULTS_ADAPTER = "agentmandate.manifest-defaults"
MANIFEST_DEFAULTS_ADAPTER_VERSION = 1
_NO_DEFAULT = object()
_MANIFEST_V1_DEFAULTS = {
    "agent.identity": None,
    "agent.roles": [],
    "limits.depth": 8,
    "limits.effects": {},
    "limits.total": None,
    "tool.ceiling": None,
    "tool.principal": "caller",
    "tool.produces": None,
    "tool.requires": [],
    "tool.requires_approval": False,
    "tool.scope_key": None,
    "tool.unbounded": False,
    "tool.value_arg": None,
}


class IRFormatError(ValueError):
    """Raised when an experimental IR snapshot cannot be read safely."""


@dataclass(frozen=True)
class Relation:
    source_kind: str
    target_kind: str
    cardinality: str
    merge: str
    predicate: str


RELATIONS = {
    "acts_as": Relation("tool", "principal", "one", "single", "principal"),
    "ceiling_on": Relation("tool", "scope", "one", "single", "scope_key"),
    "produces": Relation("tool", "scope", "one", "single", "produces"),
    "requires": Relation("tool", "scope", "many", "union", "requires"),
    "role_contains": Relation("role", "tool", "many", "union", "members"),
}


@dataclass(frozen=True)
class Evidence:
    source: str
    location: str
    confidence: str = "exact"
    review: str = "accepted"

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "location": self.location,
            "confidence": self.confidence,
            "review": self.review,
        }


@dataclass(frozen=True)
class Source:
    id: str
    kind: str
    locator: str
    format_version: int
    producer_version: str | None
    semantic_sha256: str
    adapter: str
    adapter_version: int
    content_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "locator": self.locator,
            "format_version": self.format_version,
            "producer_version": self.producer_version,
            "semantic_sha256": self.semantic_sha256,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
        }
        if self.content_sha256 is not None:
            result["content_sha256"] = self.content_sha256
        return result


@dataclass(frozen=True)
class Entity:
    id: str
    kind: str
    name: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "kind": self.kind, "name": self.name}


@dataclass(frozen=True)
class Fact:
    id: str
    subject: str
    predicate: str
    value: Any
    evidence: tuple[Evidence, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "value": self.value,
            "evidence": [
                item.as_dict()
                for item in sorted(
                    self.evidence,
                    key=lambda item: (
                        item.source,
                        item.location,
                        item.confidence,
                        item.review,
                    ),
                )
            ],
        }


@dataclass(frozen=True)
class Edge:
    id: str
    source: str
    relation: str
    target: str
    support: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "relation": self.relation,
            "target": self.target,
            "support": sorted(self.support),
        }


@dataclass(frozen=True)
class AuthorityIR:
    ir_version: int
    sources: tuple[Source, ...]
    entities: tuple[Entity, ...]
    facts: tuple[Fact, ...]
    edges: tuple[Edge, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ir_version": self.ir_version,
            "sources": [item.as_dict() for item in sorted(self.sources, key=lambda item: item.id)],
            "entities": [
                item.as_dict() for item in sorted(self.entities, key=lambda item: item.id)
            ],
            "facts": [item.as_dict() for item in sorted(self.facts, key=lambda item: item.id)],
            "edges": [item.as_dict() for item in sorted(self.edges, key=lambda item: item.id)],
        }

    def to_json(self) -> str:
        """Return canonical JSON suitable for hashing and committed fixtures."""
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def validate(self) -> None:
        """Reject graph ambiguity before an analysis can consume IR edges."""
        if self.ir_version != IR_VERSION:
            raise IRFormatError(f"unsupported authority IR version {self.ir_version!r}")

        tables = {
            "source": self.sources,
            "entity": self.entities,
            "edge": self.edges,
        }
        for table, records in tables.items():
            identifiers = [item.id for item in records]
            if len(identifiers) != len(set(identifiers)):
                raise IRFormatError(f"authority IR has a duplicate {table} id")

        sources = {item.id for item in self.sources}
        entities = {item.id: item for item in self.entities}
        facts = {item.id: item for item in self.facts}
        predicates: set[tuple[str, str]] = set()
        for entity in self.entities:
            if entity.id != _entity_id(entity.kind, entity.name):
                raise IRFormatError(f"authority IR entity id does not match {entity.name!r}")
        for fact in self.facts:
            if fact.id != _fact_id(fact.subject, fact.predicate):
                raise IRFormatError(f"authority IR fact id does not match {fact.subject}")
            if fact.subject not in entities:
                raise IRFormatError(f"authority IR fact has unknown subject {fact.subject!r}")
            key = (fact.subject, fact.predicate)
            if key in predicates:
                raise IRFormatError(
                    f"authority IR has conflicting facts for {fact.subject}.{fact.predicate}"
                )
            predicates.add(key)
            for evidence in fact.evidence:
                if evidence.source not in sources:
                    raise IRFormatError(
                        f"authority IR evidence has unknown source {evidence.source!r}"
                    )
                if evidence.confidence not in {"exact", "heuristic", "unknown"}:
                    raise IRFormatError(
                        f"authority IR has unknown confidence {evidence.confidence!r}"
                    )
                if evidence.review not in {"unreviewed", "accepted", "contested"}:
                    raise IRFormatError(f"authority IR has unknown review {evidence.review!r}")

        actual_edges = {(edge.source, edge.relation, edge.target) for edge in self.edges}
        for edge in self.edges:
            expected_id = _edge_id(edge.source, edge.relation, edge.target)
            if edge.id != expected_id:
                raise IRFormatError(f"authority IR edge id does not match {expected_id!r}")
            relation = RELATIONS.get(edge.relation)
            if relation is None:
                raise IRFormatError(f"authority IR has unknown relation {edge.relation!r}")
            source = entities.get(edge.source)
            target = entities.get(edge.target)
            if source is None or target is None:
                raise IRFormatError(f"authority IR edge {edge.id!r} has an unknown endpoint")
            if source.kind != relation.source_kind or target.kind != relation.target_kind:
                raise IRFormatError(f"authority IR edge {edge.id!r} has invalid endpoint kinds")
            if not edge.support:
                raise IRFormatError(f"authority IR edge {edge.id!r} has no support")
            establishes_relation = False
            for support_id in edge.support:
                support = facts.get(support_id)
                if support is None:
                    raise IRFormatError(
                        f"authority IR edge {edge.id!r} has unknown support {support_id!r}"
                    )
                if support.subject != edge.source:
                    raise IRFormatError(
                        f"authority IR edge {edge.id!r} cites support from another entity"
                    )
                targets = support.value if isinstance(support.value, list) else [support.value]
                if support.predicate == relation.predicate and edge.target in targets:
                    establishes_relation = True
            if not establishes_relation:
                raise IRFormatError(
                    f"authority IR edge {edge.id!r} is not established by its support"
                )
        for fact in self.facts:
            for relation_name, relation in RELATIONS.items():
                if fact.predicate != relation.predicate:
                    continue
                targets = fact.value if isinstance(fact.value, list) else [fact.value]
                for target in (item for item in targets if item is not None):
                    if (fact.subject, relation_name, target) not in actual_edges:
                        raise IRFormatError(
                            f"authority IR is missing {relation_name} edge from {fact.subject}"
                        )

    @classmethod
    def from_json(cls, text: str) -> AuthorityIR:
        raw = json.loads(text)
        version = raw.get("ir_version")
        if isinstance(version, bool) or version != IR_VERSION:
            raise IRFormatError(
                f"unsupported authority IR version {version!r}; this build reads {IR_VERSION}"
            )
        snapshot = cls(
            ir_version=version,
            sources=tuple(_source_from_dict(item) for item in raw["sources"]),
            entities=tuple(Entity(**item) for item in raw["entities"]),
            facts=tuple(_fact_from_dict(item) for item in raw["facts"]),
            edges=tuple(_edge_from_dict(item) for item in raw["edges"]),
        )
        snapshot.validate()
        return snapshot


def _source_from_dict(raw: dict[str, Any]) -> Source:
    return Source(
        id=raw["id"],
        kind=raw["kind"],
        locator=raw["locator"],
        format_version=raw["format_version"],
        producer_version=raw["producer_version"],
        semantic_sha256=raw["semantic_sha256"],
        adapter=raw["adapter"],
        adapter_version=raw["adapter_version"],
        content_sha256=raw.get("content_sha256"),
    )


def _fact_from_dict(raw: dict[str, Any]) -> Fact:
    return Fact(
        id=raw["id"],
        subject=raw["subject"],
        predicate=raw["predicate"],
        value=raw["value"],
        evidence=tuple(Evidence(**item) for item in raw["evidence"]),
    )


def _edge_from_dict(raw: dict[str, Any]) -> Edge:
    return Edge(
        id=raw["id"],
        source=raw["source"],
        relation=raw["relation"],
        target=raw["target"],
        support=tuple(raw["support"]),
    )


def _entity_id(kind: str, name: str) -> str:
    return f"{kind}:{quote(name, safe='')}"


def _fact_id(subject: str, predicate: str) -> str:
    return f"fact:{subject}:{quote(predicate, safe='')}"


def _edge_id(source: str, relation: str, target: str) -> str:
    return f"edge:{source}:{quote(relation, safe='')}:{target}"


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _semantic_payload(
    entities: tuple[Entity, ...], facts: tuple[Fact, ...], edges: tuple[Edge, ...]
) -> dict[str, Any]:
    return {
        "adapter": MANIFEST_ADAPTER,
        "adapter_version": MANIFEST_ADAPTER_VERSION,
        "entities": [item.as_dict() for item in entities],
        "facts": [item.as_dict() for item in facts],
        "edges": [item.as_dict() for item in edges],
    }


def _from_mandate(mandate: Mandate, content: bytes | None = None) -> AuthorityIR:
    """Project a parsed v1 mandate into the experimental canonical records."""
    source_id = "source:mandate"
    defaults_source_id = "source:manifest-v1"
    entities: dict[str, Entity] = {}
    facts: list[Fact] = []
    edges: dict[str, Edge] = {}

    def entity(kind: str, name: str, location: str) -> str:
        identifier = _entity_id(kind, name)
        candidate = Entity(id=identifier, kind=kind, name=name)
        entities.setdefault(identifier, candidate)
        fact(identifier, "name", name, location)
        return identifier

    def fact(
        subject: str,
        predicate: str,
        value: Any,
        location: str,
        default: Any = _NO_DEFAULT,
        default_name: str | None = None,
    ) -> str:
        identifier = _fact_id(subject, predicate)
        evidence_items = [Evidence(source=source_id, location=location)]
        if default is not _NO_DEFAULT and value == default:
            evidence_items.append(
                Evidence(
                    source=defaults_source_id,
                    location=f"manifest:v1#/defaults/{default_name}",
                )
            )
        candidate = Fact(
            id=identifier,
            subject=subject,
            predicate=predicate,
            value=value,
            evidence=tuple(evidence_items),
        )
        existing = next(
            ((index, item) for index, item in enumerate(facts) if item.id == identifier), None
        )
        if existing is not None:
            index, previous = existing
            if previous.value != value:
                raise IRFormatError(f"conflicting values for {subject}.{predicate}")
            combined = set(previous.evidence + tuple(evidence_items))
            facts[index] = Fact(
                id=previous.id,
                subject=previous.subject,
                predicate=previous.predicate,
                value=previous.value,
                evidence=tuple(
                    sorted(
                        combined,
                        key=lambda item: item.location,
                    )
                ),
            )
            return identifier
        facts.append(candidate)
        return identifier

    def edge(source: str, relation: str, target: str, support: tuple[str, ...]) -> None:
        identifier = _edge_id(source, relation, target)
        candidate = Edge(identifier, source, relation, target, tuple(sorted(support)))
        edges.setdefault(identifier, candidate)

    agent_id = entity("agent", mandate.agent, "/agent")
    tool_ids: list[str] = []
    for index, tool in enumerate(mandate.tools):
        base = f"/tools/{index}"
        tool_id = entity("tool", tool.name, f"{base}/name")
        tool_ids.append(tool_id)
        fact(tool_id, "effect", tool.effect, f"{base}/effect")
        principal_id = entity("principal", tool.principal, f"{base}/principal")
        principal = fact(
            tool_id,
            "principal",
            principal_id,
            f"{base}/principal",
            _entity_id("principal", "caller"),
            "tool.principal",
        )
        edge(tool_id, "acts_as", principal_id, (principal,))

        required_ids = [
            entity("scope", name, f"{base}/requires/{required_index}")
            for required_index, name in enumerate(tool.requires)
        ]
        required = fact(
            tool_id, "requires", required_ids, f"{base}/requires", [], "tool.requires"
        )
        for scope_id in set(required_ids):
            edge(tool_id, "requires", scope_id, (required,))

        produces_id = (
            entity("scope", tool.produces, f"{base}/produces") if tool.produces else None
        )
        produces = fact(
            tool_id, "produces", produces_id, f"{base}/produces", None, "tool.produces"
        )
        if produces_id is not None:
            edge(tool_id, "produces", produces_id, (produces,))

        fact(
            tool_id,
            "unbounded",
            tool.unbounded,
            f"{base}/unbounded",
            False,
            "tool.unbounded",
        )
        fact(
            tool_id,
            "value_arg",
            tool.value_arg,
            f"{base}/value_arg",
            None,
            "tool.value_arg",
        )
        ceiling_value = (
            None
            if tool.ceiling is None
            else {"amount": str(tool.ceiling.amount), "currency": tool.ceiling.currency}
        )
        ceiling = fact(
            tool_id, "ceiling", ceiling_value, f"{base}/ceiling", None, "tool.ceiling"
        )
        scope_key_id = (
            entity("scope", tool.scope_key, f"{base}/scope_key") if tool.scope_key else None
        )
        scope_key = fact(
            tool_id, "scope_key", scope_key_id, f"{base}/scope_key", None, "tool.scope_key"
        )
        if scope_key_id is not None:
            edge(tool_id, "ceiling_on", scope_key_id, (scope_key, ceiling))
        fact(
            tool_id,
            "requires_approval",
            tool.requires_approval,
            f"{base}/requires_approval",
            False,
            "tool.requires_approval",
        )
        # Effect is deliberately a fact rather than an edge: it is a closed,
        # single-valued predicate whose conflicts must stop analysis.

    fact(agent_id, "tools", tool_ids, "/tools")
    fact(agent_id, "identity", mandate.identity, "/identity", None, "agent.identity")

    role_ids: list[str] = []
    for role_name, members in mandate.roles.items():
        role_pointer = f"/roles/{_pointer_token(role_name)}"
        role_id = entity("role", role_name, role_pointer)
        role_ids.append(role_id)
        member_ids = [_entity_id("tool", member) for member in members]
        membership = fact(role_id, "members", member_ids, role_pointer)
        for member_id in set(member_ids):
            edge(role_id, "role_contains", member_id, (membership,))
    fact(agent_id, "roles", role_ids, "/roles", [], "agent.roles")

    limits_id = entity("constraint", "run", "/limits")
    total = (
        None
        if mandate.limits.total is None
        else {
            "amount": str(mandate.limits.total.amount),
            "currency": mandate.limits.total.currency,
        }
    )
    fact(limits_id, "total", total, "/limits/total", None, "limits.total")
    fact(limits_id, "depth", mandate.limits.depth, "/limits/depth", 8, "limits.depth")
    fact(
        limits_id,
        "effects",
        dict(sorted(mandate.limits.effects.items())),
        "/limits/effects",
        {},
        "limits.effects",
    )

    ordered_entities = tuple(sorted(entities.values(), key=lambda item: item.id))
    ordered_facts = tuple(sorted(facts, key=lambda item: item.id))
    ordered_edges = tuple(sorted(edges.values(), key=lambda item: item.id))
    semantic = hashlib.sha256(
        _canonical_bytes(_semantic_payload(ordered_entities, ordered_facts, ordered_edges))
    ).hexdigest()
    source = Source(
        id=source_id,
        kind="mandate-semantic",
        locator=mandate.source or "memory:mandate",
        format_version=SCHEMA_VERSION,
        producer_version=None,
        semantic_sha256=semantic,
        adapter=MANIFEST_ADAPTER,
        adapter_version=MANIFEST_ADAPTER_VERSION,
        content_sha256=hashlib.sha256(content).hexdigest() if content is not None else None,
    )
    defaults_source = Source(
        id=defaults_source_id,
        kind="manifest-schema",
        locator="agentmandate:manifest/v1",
        format_version=SCHEMA_VERSION,
        producer_version=None,
        semantic_sha256=hashlib.sha256(_canonical_bytes(_MANIFEST_V1_DEFAULTS)).hexdigest(),
        adapter=MANIFEST_DEFAULTS_ADAPTER,
        adapter_version=MANIFEST_DEFAULTS_ADAPTER_VERSION,
    )
    snapshot = AuthorityIR(
        IR_VERSION,
        (source, defaults_source),
        ordered_entities,
        ordered_facts,
        ordered_edges,
    )
    snapshot.validate()
    return snapshot


def _to_mandate(snapshot: AuthorityIR) -> Mandate:
    """Rebuild a mandate from records emitted by the v1 manifest adapter."""
    snapshot.validate()
    entities = {item.id: item for item in snapshot.entities}
    facts = {(item.subject, item.predicate): item.value for item in snapshot.facts}

    def only(kind: str) -> Entity:
        candidates = [item for item in snapshot.entities if item.kind == kind]
        if len(candidates) != 1:
            raise IRFormatError(f"authority IR needs exactly one {kind} entity")
        return candidates[0]

    def value(subject: str, predicate: str) -> Any:
        try:
            return facts[(subject, predicate)]
        except KeyError as exc:
            raise IRFormatError(f"authority IR is missing {subject}.{predicate}") from exc

    def name(identifier: str, kind: str) -> str:
        candidate = entities.get(identifier)
        if candidate is None or candidate.kind != kind:
            raise IRFormatError(f"authority IR has no {kind} entity {identifier!r}")
        return candidate.name

    agent = only("agent")
    tools: list[Tool] = []
    for tool_id in value(agent.id, "tools"):
        tool_name = name(tool_id, "tool")
        ceiling_raw = value(tool_id, "ceiling")
        ceiling = (
            None
            if ceiling_raw is None
            else Money(Decimal(ceiling_raw["amount"]), ceiling_raw["currency"])
        )
        tools.append(
            Tool(
                name=tool_name,
                effect=value(tool_id, "effect"),
                principal=name(value(tool_id, "principal"), "principal"),
                requires=tuple(name(item, "scope") for item in value(tool_id, "requires")),
                produces=(
                    None
                    if value(tool_id, "produces") is None
                    else name(value(tool_id, "produces"), "scope")
                ),
                unbounded=value(tool_id, "unbounded"),
                value_arg=value(tool_id, "value_arg"),
                ceiling=ceiling,
                scope_key=(
                    None
                    if value(tool_id, "scope_key") is None
                    else name(value(tool_id, "scope_key"), "scope")
                ),
                requires_approval=value(tool_id, "requires_approval"),
            )
        )

    roles = {
        name(role_id, "role"): tuple(
            name(tool_id, "tool") for tool_id in value(role_id, "members")
        )
        for role_id in value(agent.id, "roles")
    }
    limits_entity = only("constraint")
    total_raw = value(limits_entity.id, "total")
    total = (
        None
        if total_raw is None
        else Money(Decimal(total_raw["amount"]), total_raw["currency"])
    )
    source = next((item for item in snapshot.sources if item.kind == "mandate-semantic"), None)
    locator = None if source is None or source.locator == "memory:mandate" else source.locator
    return Mandate(
        agent=agent.name,
        tools=tuple(tools),
        identity=value(agent.id, "identity"),
        limits=Limits(
            total=total,
            depth=value(limits_entity.id, "depth"),
            effects=value(limits_entity.id, "effects"),
        ),
        roles=roles,
        source=locator,
    )
