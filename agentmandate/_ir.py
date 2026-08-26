"""Experimental, private authority IR records and the manifest adapter.

Nothing in this module is exported from :mod:`agentmandate`.  The records are
the first implementation gate for the contract in ``docs/authority-ir.md``;
they can change while the four evidence graphs exercise the format.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar
from urllib.parse import quote

from .manifest import EFFECTS, PRINCIPALS, SCHEMA_VERSION, Limits, Mandate, Money, Tool
from .reach import (
    Authority,
    Step,
    _analyse_with_trace,
    _enabled,
    _mints,
    _State,
)

IR_VERSION = 1
RESULT_VERSION = 1
MANIFEST_ADAPTER = "agentmandate.manifest"
MANIFEST_ADAPTER_VERSION = 2
MANIFEST_DEFAULTS_ADAPTER = "agentmandate.manifest-defaults"
MANIFEST_DEFAULTS_ADAPTER_VERSION = 1
_NO_DEFAULT = object()
_RecordT = TypeVar("_RecordT")
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
    predicate: str | None
    derived: bool = False
    support_rule: str = "input"


@dataclass(frozen=True)
class ManifestPredicate:
    subject_kind: str
    value_schema: str


MANIFEST_PREDICATES = {
    ("agent", "identity"): ManifestPredicate("agent", "nullable_string"),
    ("agent", "name"): ManifestPredicate("agent", "entity_name"),
    ("agent", "roles"): ManifestPredicate("agent", "role_refs"),
    ("agent", "tools"): ManifestPredicate("agent", "tool_refs"),
    ("constraint", "depth"): ManifestPredicate("constraint", "positive_integer"),
    ("constraint", "effects"): ManifestPredicate("constraint", "effect_limits"),
    ("constraint", "name"): ManifestPredicate("constraint", "entity_name"),
    ("constraint", "total"): ManifestPredicate("constraint", "nullable_money"),
    ("principal", "name"): ManifestPredicate("principal", "entity_name"),
    ("role", "members"): ManifestPredicate("role", "tool_refs"),
    ("role", "name"): ManifestPredicate("role", "entity_name"),
    ("scope", "name"): ManifestPredicate("scope", "entity_name"),
    ("tool", "ceiling"): ManifestPredicate("tool", "nullable_money"),
    ("tool", "effect"): ManifestPredicate("tool", "effect"),
    ("tool", "name"): ManifestPredicate("tool", "entity_name"),
    ("tool", "principal"): ManifestPredicate("tool", "principal_ref"),
    ("tool", "produces"): ManifestPredicate("tool", "nullable_scope_ref"),
    ("tool", "requires"): ManifestPredicate("tool", "scope_refs"),
    ("tool", "requires_approval"): ManifestPredicate("tool", "boolean"),
    ("tool", "scope_key"): ManifestPredicate("tool", "nullable_scope_ref"),
    ("tool", "unbounded"): ManifestPredicate("tool", "boolean"),
    ("tool", "value_arg"): ManifestPredicate("tool", "nullable_name"),
}

RELATIONS = {
    "acts_as": Relation("tool", "principal", "one", "single", "principal"),
    "acts_under": Relation("hop", "principal", "many", "union", "actors"),
    "at_hop": Relation("principal", "hop", "one", "single", "hop"),
    "can_reach": Relation(
        "agent", "tool", "many", "union", None, True, "reachable"
    ),
    "ceiling_on": Relation("tool", "scope", "one", "single", "scope_key"),
    "contains_tool": Relation("boundary", "tool", "many", "union", "members"),
    "constrained_by": Relation("principal", "principal", "many", "union", "principals"),
    "delegates_for": Relation("delegation", "principal", "one", "single", "subject"),
    "has_breach": Relation(
        "agent", "breach", "many", "union", None, True, "breach"
    ),
    "has_effect": Relation(
        "tool", "scope", "many", "union", None, True, "effect"
    ),
    "has_condition": Relation("tool", "condition", "many", "union", "conditions"),
    "has_hop": Relation("delegation", "hop", "many", "union", "hops"),
    "has_surface": Relation("hop", "surface", "many", "union", "surfaces"),
    "narrows_to": Relation("condition", "effect", "one", "single", "effect"),
    "produces": Relation("tool", "scope", "one", "single", "produces"),
    "previous_hop": Relation("hop", "hop", "one", "single", "previous"),
    "requires": Relation("tool", "scope", "many", "union", "requires"),
    "role_contains": Relation("role", "tool", "many", "union", "members"),
    "transitions_to": Relation(
        "tool", "tool", "many", "union", None, True, "transition"
    ),
    "under_grant": Relation("principal", "grant", "one", "single", "grant"),
    "uses_delegation": Relation(
        "principal", "delegation", "one", "single", "delegation"
    ),
    "uses_context": Relation("condition", "context", "one", "single", "context"),
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
            "source": ("sources", self.sources),
            "entity": ("entities", self.entities),
            "edge": ("edges", self.edges),
        }
        for table, (path, records) in tables.items():
            identifiers: set[str] = set()
            for index, item in enumerate(records):
                if item.id in identifiers:
                    raise IRFormatError(
                        f"authority IR has a duplicate {table} id at {path}[{index}].id"
                    )
                identifiers.add(item.id)

        sources = {item.id for item in self.sources}
        entities = {item.id: item for item in self.entities}
        facts = {item.id: item for item in self.facts}
        predicates: set[tuple[str, str]] = set()
        for index, entity in enumerate(self.entities):
            if entity.id != _entity_id(entity.kind, entity.name):
                raise IRFormatError(
                    f"authority IR entities[{index}].id: entity id does not match kind/name"
                )
        for index, fact in enumerate(self.facts):
            if fact.id != _fact_id(fact.subject, fact.predicate):
                raise IRFormatError(
                    f"authority IR facts[{index}].id: fact id does not match subject/predicate"
                )
            if fact.subject not in entities:
                raise IRFormatError(
                    f"authority IR facts[{index}].subject has unknown subject"
                )
            key = (fact.subject, fact.predicate)
            if key in predicates:
                raise IRFormatError(
                    f"authority IR facts[{index}].id has conflicting facts"
                )
            predicates.add(key)
            for evidence_index, evidence in enumerate(fact.evidence):
                evidence_path = f"facts[{index}].evidence[{evidence_index}]"
                if evidence.source not in sources:
                    raise IRFormatError(
                        f"authority IR {evidence_path}.source has unknown source"
                    )
                if evidence.confidence not in {"exact", "heuristic", "unknown"}:
                    raise IRFormatError(
                        f"authority IR {evidence_path}.confidence has unknown confidence"
                    )
                if evidence.review not in {"unreviewed", "accepted", "contested"}:
                    raise IRFormatError(
                        f"authority IR {evidence_path}.review has unknown review"
                    )

        edges = {edge.id: edge for edge in self.edges}
        actual_edges = {(edge.source, edge.relation, edge.target) for edge in self.edges}
        for index, edge in enumerate(self.edges):
            edge_path = f"edges[{index}]"
            expected_id = _edge_id(edge.source, edge.relation, edge.target)
            if edge.id != expected_id:
                raise IRFormatError(
                    f"authority IR {edge_path}.id: edge id does not match endpoints"
                )
            relation = RELATIONS.get(edge.relation)
            if relation is None:
                raise IRFormatError(
                    f"authority IR {edge_path}.relation has unknown relation"
                )
            source = entities.get(edge.source)
            target = entities.get(edge.target)
            if source is None or target is None:
                raise IRFormatError(f"authority IR {edge_path} has an unknown endpoint")
            if source.kind != relation.source_kind or target.kind != relation.target_kind:
                raise IRFormatError(f"authority IR {edge_path} has invalid endpoint kinds")
            if not edge.support:
                raise IRFormatError(f"authority IR {edge_path} has no support")
            if relation.derived:
                for support_index, support_id in enumerate(edge.support):
                    if support_id not in facts and support_id not in edges:
                        raise IRFormatError(
                            f"authority IR {edge_path}.support[{support_index}] "
                            "has unknown support"
                        )
                _validate_derived_edge(
                    edge, edge_path, entities, facts, edges, relation.support_rule
                )
                continue
            establishes_relation = False
            for support_index, support_id in enumerate(edge.support):
                support = facts.get(support_id)
                if support is None:
                    raise IRFormatError(
                        f"authority IR {edge_path}.support[{support_index}] "
                        "has unknown support"
                    )
                if support.subject != edge.source:
                    raise IRFormatError(
                        f"authority IR {edge_path}.support[{support_index}] cites support "
                        "from another entity"
                    )
                targets = support.value if isinstance(support.value, list) else [support.value]
                if support.predicate == relation.predicate and edge.target in targets:
                    establishes_relation = True
            if not establishes_relation:
                raise IRFormatError(
                    f"authority IR {edge_path} is not established by its support"
                )
        for index, fact in enumerate(self.facts):
            for relation_name, relation in RELATIONS.items():
                if (
                    relation.derived
                    or fact.predicate != relation.predicate
                    or entities[fact.subject].kind != relation.source_kind
                ):
                    continue
                targets = fact.value if isinstance(fact.value, list) else [fact.value]
                for target in (item for item in targets if item is not None):
                    if (fact.subject, relation_name, target) not in actual_edges:
                        raise IRFormatError(
                            f"authority IR facts[{index}] is missing {relation_name} edge"
                        )
        _validate_derived_support(edges, facts)

    @classmethod
    def from_json(cls, text: str) -> AuthorityIR:
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, TypeError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                detail = f" at line {exc.lineno} column {exc.colno}"
            else:
                detail = ""
            raise IRFormatError(f"authority IR is not valid JSON{detail}") from exc
        if not isinstance(raw, dict):
            raise IRFormatError("authority IR root must be an object")
        if "ir_version" not in raw:
            raise IRFormatError("authority IR root is missing field 'ir_version'")
        version = raw["ir_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise IRFormatError(
                f"unsupported authority IR version type; this build reads {IR_VERSION}"
            )
        if version != IR_VERSION:
            raise IRFormatError(
                f"unsupported authority IR version {version!r}; this build reads {IR_VERSION}"
            )
        _record(raw, "root", {"ir_version", "sources", "entities", "facts", "edges"})
        snapshot = cls(
            ir_version=version,
            sources=_table(raw["sources"], "sources", _source_from_dict),
            entities=_table(raw["entities"], "entities", _entity_from_dict),
            facts=_table(raw["facts"], "facts", _fact_from_dict),
            edges=_table(raw["edges"], "edges", _edge_from_dict),
        )
        snapshot.validate()
        return snapshot


@dataclass(frozen=True)
class _IRAnalysis:
    """Private, versioned result envelope around authority and provenance.

    Serializing validates by replaying the complete bounded search. Calls to
    :meth:`as_dict` and :meth:`to_json` are therefore O(full analysis), not
    passive field reads.
    """

    authority: Authority
    graph: AuthorityIR
    source_graph_sha256: str
    source_ir_version: int
    result_version: int = RESULT_VERSION

    def _body_dict(self) -> dict[str, Any]:
        return {
            "result_version": self.result_version,
            "source_graph": {
                "ir_version": self.source_ir_version,
                "sha256": self.source_graph_sha256,
            },
            "analysis": {
                "depth": self.authority.depth,
                "truncated": self.authority.truncated,
            },
            "authority": self.authority.as_dict(),
            "graph": self.graph.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        _validate_ir_analysis(self)
        body = self._body_dict()
        return {
            **body,
            "result_sha256": hashlib.sha256(_canonical_result_bytes(body)).hexdigest(),
        }

    def to_json(self) -> str:
        return _canonical_result_bytes(self.as_dict()).decode("utf-8") + "\n"

    @classmethod
    def from_json(cls, text: str) -> _IRAnalysis:
        return _ir_analysis_from_json(text)


def _validate_derived_edge(
    edge: Edge,
    path: str,
    entities: dict[str, Entity],
    facts: dict[str, Fact],
    edges: dict[str, Edge],
    rule: str,
) -> None:
    """Check the minimum evidence shape declared by a derived relation."""
    support = set(edge.support)

    def require(identifier: str) -> None:
        if identifier not in support:
            raise IRFormatError(
                f"authority IR {path}.support lacks required {rule} support"
            )

    if rule == "reachable":
        tools_fact_id = _fact_id(edge.source, "tools")
        require(tools_fact_id)
        if edge.target not in facts[tools_fact_id].value:
            raise IRFormatError(
                f"authority IR {path}.target targets an undeclared tool"
            )
        require(_fact_id(edge.target, "requires"))
        if any(
            support_id in edges
            and (support_relation := RELATIONS.get(edges[support_id].relation)) is not None
            and support_relation.derived
            for support_id in support
        ):
            raise IRFormatError(
                f"authority IR {path}.support must be rooted in source records"
            )
        required_edges = [
            edges[support_id]
            for support_id in support
            if support_id in edges and edges[support_id].relation == "requires"
        ]
        for required in required_edges:
            if not any(
                support_id in edges
                and edges[support_id].relation == "produces"
                and edges[support_id].target == required.target
                for support_id in support
            ):
                raise IRFormatError(
                    f"authority IR {path}.support lacks a producer for a required scope"
                )
        return
    if rule == "effect":
        require(_edge_id(next(iter(_agents(entities))), "can_reach", edge.source))
        require(_fact_id(edge.source, "effect"))
        if not any(
            support_id in edges
            and edges[support_id].source == edge.source
            and edges[support_id].target == edge.target
            and edges[support_id].relation in {"requires", "produces"}
            for support_id in support
        ):
            raise IRFormatError(
                f"authority IR {path}.support lacks effect scope support"
            )
        return
    if rule == "transition":
        agent = next(iter(_agents(entities)))
        require(_edge_id(agent, "can_reach", edge.source))
        require(_edge_id(agent, "can_reach", edge.target))
        require(_fact_id(edge.target, "requires"))
        return
    if rule == "breach":
        if not any(
            support_id in edges
            and edges[support_id].source == edge.source
            and edges[support_id].relation == "can_reach"
            for support_id in support
        ):
            raise IRFormatError(
                f"authority IR {path}.support lacks a reachable path"
            )
        name = entities[edge.target].name
        if name.startswith("cumulative_value:"):
            require(_fact_id(_entity_id("constraint", "run"), "total"))
        elif name.startswith("effect_count:"):
            require(_fact_id(_entity_id("constraint", "run"), "effects"))
        elif name.startswith("ungated_effect:"):
            tool_id = _entity_id("tool", name.split(":", maxsplit=1)[1])
            require(_fact_id(tool_id, "effect"))
            require(_fact_id(tool_id, "requires_approval"))
        else:
            raise IRFormatError(f"authority IR {path}.target has unknown breach entity")
        return
    raise IRFormatError(f"authority IR has unknown derived support rule {rule!r}")


def _agents(entities: dict[str, Entity]) -> set[str]:
    agents = {identifier for identifier, entity in entities.items() if entity.kind == "agent"}
    if len(agents) != 1:
        raise IRFormatError("authority IR derived relations require exactly one agent")
    return agents


def _validate_derived_support(edges: dict[str, Edge], facts: dict[str, Fact]) -> None:
    """Require derived provenance to be an acyclic chain rooted in source facts."""
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(identifier: str) -> None:
        if identifier in facts or identifier in visited:
            return
        if identifier in visiting:
            raise IRFormatError("authority IR derived support contains a cycle")
        edge = edges[identifier]
        relation = RELATIONS[edge.relation]
        if not relation.derived:
            visited.add(identifier)
            return
        visiting.add(identifier)
        for support_id in edge.support:
            if support_id in edges:
                visit(support_id)
        visiting.remove(identifier)
        visited.add(identifier)

    for edge in edges.values():
        if RELATIONS[edge.relation].derived:
            visit(edge.id)


def _record(
    raw: Any, path: str, required: set[str], optional: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise IRFormatError(f"authority IR {path} must be an object")
    optional = optional or set()
    missing = sorted(required - raw.keys())
    if missing:
        raise IRFormatError(f"authority IR {path} is missing field {missing[0]!r}")
    extra = sorted(raw.keys() - required - optional)
    if extra:
        raise IRFormatError(f"authority IR {path} has unknown field {extra[0]!r}")
    return raw


def _table(
    raw: Any, name: str, load: Callable[[Any, str], _RecordT]
) -> tuple[_RecordT, ...]:
    if not isinstance(raw, list):
        raise IRFormatError(f"authority IR {name} must be an array")
    return tuple(load(item, f"{name}[{index}]") for index, item in enumerate(raw))


def _string(raw: dict[str, Any], field: str, path: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise IRFormatError(f"authority IR {path}.{field} must be a string")
    return value


def _integer(raw: dict[str, Any], field: str, path: str) -> int:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise IRFormatError(f"authority IR {path}.{field} must be an integer")
    return value


def _source_from_dict(raw: Any, path: str) -> Source:
    raw = _record(
        raw,
        path,
        {
            "id",
            "kind",
            "locator",
            "format_version",
            "producer_version",
            "semantic_sha256",
            "adapter",
            "adapter_version",
        },
        {"content_sha256"},
    )
    producer_version = raw["producer_version"]
    if producer_version is not None and not isinstance(producer_version, str):
        raise IRFormatError(
            f"authority IR {path}.producer_version must be a string or null"
        )
    content_sha256 = raw.get("content_sha256")
    if content_sha256 is not None and not isinstance(content_sha256, str):
        raise IRFormatError(
            f"authority IR {path}.content_sha256 must be a string or null"
        )
    return Source(
        id=_string(raw, "id", path),
        kind=_string(raw, "kind", path),
        locator=_string(raw, "locator", path),
        format_version=_integer(raw, "format_version", path),
        producer_version=producer_version,
        semantic_sha256=_string(raw, "semantic_sha256", path),
        adapter=_string(raw, "adapter", path),
        adapter_version=_integer(raw, "adapter_version", path),
        content_sha256=content_sha256,
    )


def _entity_from_dict(raw: Any, path: str) -> Entity:
    raw = _record(raw, path, {"id", "kind", "name"})
    return Entity(
        id=_string(raw, "id", path),
        kind=_string(raw, "kind", path),
        name=_string(raw, "name", path),
    )


def _evidence_from_dict(raw: Any, path: str) -> Evidence:
    raw = _record(raw, path, {"source", "location", "confidence", "review"})
    confidence = _string(raw, "confidence", path)
    if confidence not in {"exact", "heuristic", "unknown"}:
        raise IRFormatError(f"authority IR {path}.confidence has an invalid value")
    review = _string(raw, "review", path)
    if review not in {"unreviewed", "accepted", "contested"}:
        raise IRFormatError(f"authority IR {path}.review has an invalid value")
    return Evidence(
        source=_string(raw, "source", path),
        location=_string(raw, "location", path),
        confidence=confidence,
        review=review,
    )


def _fact_from_dict(raw: Any, path: str) -> Fact:
    raw = _record(raw, path, {"id", "subject", "predicate", "value", "evidence"})
    evidence = raw["evidence"]
    if not isinstance(evidence, list):
        raise IRFormatError(f"authority IR {path}.evidence must be an array")
    return Fact(
        id=_string(raw, "id", path),
        subject=_string(raw, "subject", path),
        predicate=_string(raw, "predicate", path),
        value=raw["value"],
        evidence=tuple(
            _evidence_from_dict(item, f"{path}.evidence[{index}]")
            for index, item in enumerate(evidence)
        ),
    )


def _edge_from_dict(raw: Any, path: str) -> Edge:
    raw = _record(raw, path, {"id", "source", "relation", "target", "support"})
    support = raw["support"]
    if not isinstance(support, list) or any(not isinstance(item, str) for item in support):
        raise IRFormatError(f"authority IR {path}.support must be an array of strings")
    relation = _string(raw, "relation", path)
    if relation not in RELATIONS:
        raise IRFormatError(f"authority IR {path}.relation has an invalid value")
    return Edge(
        id=_string(raw, "id", path),
        source=_string(raw, "source", path),
        relation=relation,
        target=_string(raw, "target", path),
        support=tuple(support),
    )


def _entity_id(kind: str, name: str) -> str:
    return f"{kind}:{quote(name, safe='')}"


_PROFILE_DEFAULT_KINDS = {"agent": "agent", "limits": "constraint", "tool": "tool"}
_PROFILE_DEFAULTS = {
    (_PROFILE_DEFAULT_KINDS[section], predicate): (
        _entity_id("principal", value)
        if (section, predicate) == ("tool", "principal")
        else value
    )
    for key, value in _MANIFEST_V1_DEFAULTS.items()
    for section, predicate in (key.split(".", 1),)
}


def _fact_id(subject: str, predicate: str) -> str:
    return f"fact:{subject}:{quote(predicate, safe='')}"


def _edge_id(source: str, relation: str, target: str) -> str:
    return f"edge:{source}:{quote(relation, safe='')}:{target}"


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _canonical_result_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise IRFormatError("authority IR result contains a non-canonical value") from exc


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


def _validate_manifest_profile(snapshot: AuthorityIR) -> None:
    """Require the closed, trusted manifest-v1 subset eligible for analysis."""
    expected_sources = {
        "source:mandate": (
            "mandate-semantic",
            MANIFEST_ADAPTER,
            MANIFEST_ADAPTER_VERSION,
        ),
        "source:manifest-v1": (
            "manifest-schema",
            MANIFEST_DEFAULTS_ADAPTER,
            MANIFEST_DEFAULTS_ADAPTER_VERSION,
        ),
    }
    sources = {source.id: source for source in snapshot.sources}
    if set(sources) != set(expected_sources):
        raise IRFormatError(
            "authority IR sources do not match the analyzable manifest-v1 profile"
        )
    for index, source in enumerate(snapshot.sources):
        kind, adapter, adapter_version = expected_sources[source.id]
        if (
            source.kind != kind
            or source.format_version != SCHEMA_VERSION
            or source.adapter != adapter
            or source.adapter_version != adapter_version
        ):
            raise IRFormatError(
                f"authority IR sources[{index}] is outside the analyzable "
                "manifest-v1 profile"
            )

    entities = {entity.id: entity for entity in snapshot.entities}
    entity_indexes = {entity.id: index for index, entity in enumerate(snapshot.entities)}
    derived = any(RELATIONS[edge.relation].derived for edge in snapshot.edges)
    allowed_kinds = {kind for kind, _ in MANIFEST_PREDICATES}
    if derived:
        allowed_kinds.add("breach")
    for index, entity in enumerate(snapshot.entities):
        if entity.kind not in allowed_kinds:
            raise IRFormatError(
                f"authority IR entities[{index}].kind is outside the analyzable "
                "manifest-v1 profile"
            )

    facts: dict[tuple[str, str], Fact] = {}
    predicates_by_entity: dict[str, set[str]] = {}
    for index, fact in enumerate(snapshot.facts):
        entity = entities[fact.subject]
        specification = MANIFEST_PREDICATES.get((entity.kind, fact.predicate))
        if specification is None:
            raise IRFormatError(
                f"authority IR facts[{index}].predicate is unsupported by the "
                "analyzable manifest-v1 profile"
            )
        if not fact.evidence:
            raise IRFormatError(
                f"authority IR facts[{index}].evidence is empty in the analyzable profile"
            )
        evidence_sources = {evidence.source for evidence in fact.evidence}
        if "source:mandate" not in evidence_sources:
            raise IRFormatError(
                f"authority IR facts[{index}].evidence lacks reviewed manifest support"
            )
        _validate_profile_value(
            fact.value,
            specification.value_schema,
            f"facts[{index}].value",
            entity,
            entities,
        )
        for evidence_index, evidence in enumerate(fact.evidence):
            path = f"facts[{index}].evidence[{evidence_index}]"
            if evidence.review != "accepted":
                raise IRFormatError(
                    f"authority IR {path}.review is not accepted for analysis"
                )
            if evidence.confidence != "exact":
                raise IRFormatError(
                    f"authority IR {path}.confidence is not exact for analysis"
                )
            if evidence.source == "source:manifest-v1" and (
                (entity.kind, fact.predicate) not in _PROFILE_DEFAULTS
                or fact.value != _PROFILE_DEFAULTS[(entity.kind, fact.predicate)]
            ):
                raise IRFormatError(
                    f"authority IR {path}.source claims an inapplicable schema default"
                )
        facts[(fact.subject, fact.predicate)] = fact
        predicates_by_entity.setdefault(fact.subject, set()).add(fact.predicate)

    for entity in snapshot.entities:
        expected = {
            predicate
            for (kind, predicate), _ in MANIFEST_PREDICATES.items()
            if kind == entity.kind
        }
        actual = predicates_by_entity.get(entity.id, set())
        if actual != expected:
            raise IRFormatError(
                f"authority IR entities[{entity_indexes[entity.id]}] does not have the "
                "complete analyzable manifest-v1 predicate set"
            )

    def fact_value(subject: str, predicate: str) -> Any:
        return facts[(subject, predicate)].value

    agents = [entity for entity in snapshot.entities if entity.kind == "agent"]
    constraints = [entity for entity in snapshot.entities if entity.kind == "constraint"]
    if len(agents) != 1:
        raise IRFormatError("authority IR analyzable profile requires exactly one agent")
    if len(constraints) != 1 or constraints[0].name != "run":
        raise IRFormatError(
            "authority IR analyzable profile requires the run constraint"
        )
    agent = agents[0]
    tool_ids = {entity.id for entity in snapshot.entities if entity.kind == "tool"}
    role_ids = {entity.id for entity in snapshot.entities if entity.kind == "role"}
    scope_ids = {entity.id for entity in snapshot.entities if entity.kind == "scope"}
    principal_ids = {
        entity.id for entity in snapshot.entities if entity.kind == "principal"
    }
    declared_tools = fact_value(agent.id, "tools")
    if (
        set(declared_tools) != tool_ids
        or len(declared_tools) != len(tool_ids)
        or not tool_ids
    ):
        raise IRFormatError(
            "authority IR agent tools do not cover the analyzable tool entities"
        )
    declared_roles = fact_value(agent.id, "roles")
    if set(declared_roles) != role_ids or len(declared_roles) != len(role_ids):
        raise IRFormatError(
            "authority IR agent roles do not cover the analyzable role entities"
        )

    referenced_scopes: set[str] = set()
    referenced_principals: set[str] = set()
    for tool_id in tool_ids:
        required = fact_value(tool_id, "requires")
        referenced_scopes.update(required)
        for predicate in ("produces", "scope_key"):
            scope = fact_value(tool_id, predicate)
            if scope is not None:
                referenced_scopes.add(scope)
        referenced_principals.add(fact_value(tool_id, "principal"))
        ceiling = fact_value(tool_id, "ceiling")
        value_arg = fact_value(tool_id, "value_arg")
        scope_key = fact_value(tool_id, "scope_key")
        if (ceiling is None) != (value_arg is None):
            raise IRFormatError(
                "authority IR tool ceiling and value_arg must be declared together"
            )
        if ceiling is not None and scope_key is None:
            raise IRFormatError(
                "authority IR tool scope_key is required with a ceiling"
            )
    if referenced_scopes != scope_ids:
        raise IRFormatError(
            "authority IR scope entities do not match the analyzable tool references"
        )
    if referenced_principals != principal_ids:
        raise IRFormatError(
            "authority IR principal entities do not match the analyzable tool references"
        )

    source_entities = tuple(
        sorted(
            (entity for entity in snapshot.entities if entity.kind != "breach"),
            key=lambda item: item.id,
        )
    )
    source_facts = tuple(sorted(snapshot.facts, key=lambda item: item.id))
    source_edges = tuple(
        sorted(
            (
                edge
                for edge in snapshot.edges
                if not RELATIONS[edge.relation].derived
            ),
            key=lambda item: item.id,
        )
    )
    semantic = hashlib.sha256(
        _canonical_bytes(_semantic_payload(source_entities, source_facts, source_edges))
    ).hexdigest()
    if sources["source:mandate"].semantic_sha256 != semantic:
        raise IRFormatError(
            "authority IR source:mandate semantic_sha256 does not match the profile"
        )
    defaults_digest = hashlib.sha256(_canonical_bytes(_MANIFEST_V1_DEFAULTS)).hexdigest()
    if sources["source:manifest-v1"].semantic_sha256 != defaults_digest:
        raise IRFormatError(
            "authority IR source:manifest-v1 semantic_sha256 does not match the profile"
        )


def _validate_profile_value(
    value: Any,
    schema: str,
    path: str,
    entity: Entity,
    entities: dict[str, Entity],
) -> None:
    def reject() -> None:
        raise IRFormatError(
            f"authority IR {path} does not match manifest profile schema {schema}"
        )

    def reference(identifier: Any, kind: str) -> bool:
        return (
            isinstance(identifier, str)
            and identifier in entities
            and entities[identifier].kind == kind
        )

    if schema == "entity_name":
        if (
            value != entity.name
            or not isinstance(value, str)
            or not value.strip()
            or any(character in value for character in "\r\n\x00")
        ):
            reject()
        return
    if schema == "nullable_string":
        if value is not None and not isinstance(value, str):
            reject()
        return
    if schema == "nullable_name":
        if value is not None and (
            not isinstance(value, str)
            or not value.strip()
            or any(character in value for character in "\r\n\x00")
        ):
            reject()
        return
    if schema == "effect":
        if value not in EFFECTS:
            reject()
        return
    if schema == "boolean":
        if not isinstance(value, bool):
            reject()
        return
    if schema == "positive_integer":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            reject()
        return
    if schema == "effect_limits":
        if not isinstance(value, dict) or any(
            effect not in EFFECTS
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 0
            for effect, limit in value.items()
        ):
            reject()
        return
    if schema == "nullable_money":
        if value is None:
            return
        if not isinstance(value, dict) or set(value) != {"amount", "currency"}:
            reject()
        amount = value["amount"]
        currency = value["currency"]
        if not isinstance(amount, str) or not isinstance(currency, str):
            reject()
        try:
            decimal = Decimal(amount)
        except InvalidOperation:
            reject()
        if (
            not decimal.is_finite()
            or decimal < 0
            or len(currency) != 3
            or not currency.isascii()
            or not currency.isalpha()
            or currency != currency.upper()
        ):
            reject()
        return
    if schema == "principal_ref":
        if not reference(value, "principal") or entities[value].name not in PRINCIPALS:
            reject()
        return
    if schema == "nullable_scope_ref":
        if value is not None and not reference(value, "scope"):
            reject()
        return
    reference_kinds = {
        "role_refs": "role",
        "scope_refs": "scope",
        "tool_refs": "tool",
    }
    if schema not in reference_kinds:
        raise IRFormatError(f"authority IR has unknown manifest profile schema {schema!r}")
    kind = reference_kinds[schema]
    if not isinstance(value, list) or any(
        not reference(identifier, kind) for identifier in value
    ):
        reject()


def _to_mandate(snapshot: AuthorityIR) -> Mandate:
    """Rebuild a mandate from records emitted by the v1 manifest adapter."""
    snapshot.validate()
    _validate_manifest_profile(snapshot)
    entities = {item.id: item for item in snapshot.entities}
    facts = {(item.subject, item.predicate): item.value for item in snapshot.facts}

    def value(subject: str, predicate: str) -> Any:
        return facts[(subject, predicate)]

    def name(identifier: str) -> str:
        return entities[identifier].name

    agent = next(item for item in snapshot.entities if item.kind == "agent")
    tools: list[Tool] = []
    for tool_id in value(agent.id, "tools"):
        tool_name = name(tool_id)
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
                principal=name(value(tool_id, "principal")),
                requires=tuple(name(item) for item in value(tool_id, "requires")),
                produces=(
                    None
                    if value(tool_id, "produces") is None
                    else name(value(tool_id, "produces"))
                ),
                unbounded=value(tool_id, "unbounded"),
                value_arg=value(tool_id, "value_arg"),
                ceiling=ceiling,
                scope_key=(
                    None
                    if value(tool_id, "scope_key") is None
                    else name(value(tool_id, "scope_key"))
                ),
                requires_approval=value(tool_id, "requires_approval"),
            )
        )

    roles = {
        name(role_id): tuple(
            name(tool_id) for tool_id in value(role_id, "members")
        )
        for role_id in value(agent.id, "roles")
    }
    limits_entity = next(item for item in snapshot.entities if item.kind == "constraint")
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


def _path_is_enabling(mandate: Mandate, path: tuple[Step, ...]) -> bool:
    """Replay the authority preconditions used by search for a retained path."""
    tools = {tool.name: tool for tool in mandate.tools}
    state = _State()
    for step in path:
        tool = tools.get(step.tool)
        if tool is None or not _enabled(tool, state):
            return False
        if _mints(tool, state):
            state = state.with_binding(tool.produces)  # type: ignore[arg-type]
    return bool(path)


def _source_graph(graph: AuthorityIR) -> AuthorityIR:
    """Recover the canonical source snapshot from an augmented result graph."""
    # Gate-3 invariant: breach is the only entity kind minted by analysis.
    # A future derived entity kind must be added to this extraction explicitly;
    # retaining it would make profile validation fail rather than silently
    # treating a derived entity as source input.
    entities = tuple(entity for entity in graph.entities if entity.kind != "breach")
    entity_ids = {entity.id for entity in entities}
    source = AuthorityIR(
        ir_version=graph.ir_version,
        sources=graph.sources,
        entities=entities,
        facts=tuple(fact for fact in graph.facts if fact.subject in entity_ids),
        edges=tuple(
            edge for edge in graph.edges if not RELATIONS[edge.relation].derived
        ),
    )
    source.validate()
    return source


def _source_graph_sha256(graph: AuthorityIR) -> str:
    return hashlib.sha256(graph.to_json().encode("utf-8")).hexdigest()


def _validate_ir_analysis(result: _IRAnalysis) -> None:
    if result.result_version != RESULT_VERSION:
        raise IRFormatError(
            f"unsupported authority IR result version {result.result_version!r}"
        )
    result.graph.validate()
    source = _source_graph(result.graph)
    if result.source_ir_version != source.ir_version:
        raise IRFormatError("authority IR result source graph version does not match")
    digest = _source_graph_sha256(source)
    if result.source_graph_sha256 != digest:
        raise IRFormatError("authority IR result source graph digest does not match")
    expected = _analyse_ir(source, depth=result.authority.depth)
    if result.authority != expected.authority:
        raise IRFormatError("authority IR result authority output does not match analysis")
    if result.graph != expected.graph:
        raise IRFormatError("authority IR result graph does not match analysis")


def _ir_analysis_from_json(text: str) -> _IRAnalysis:
    def reject_constant(_: str) -> None:
        raise ValueError

    try:
        raw = json.loads(text, parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise IRFormatError(
            f"authority IR result is not valid JSON at line {exc.lineno} column {exc.colno}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise IRFormatError("authority IR result contains a non-canonical value") from exc
    if not isinstance(raw, dict):
        raise IRFormatError("authority IR result must be an object")
    if "result_version" not in raw:
        raise IRFormatError("authority IR result is missing field 'result_version'")
    version = raw["result_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise IRFormatError(
            f"unsupported authority IR result version type; this build reads {RESULT_VERSION}"
        )
    if version != RESULT_VERSION:
        raise IRFormatError(
            f"unsupported authority IR result version {version!r}; "
            f"this build reads {RESULT_VERSION}"
        )
    raw = _record(
        raw,
        "result",
        {
            "result_version",
            "result_sha256",
            "source_graph",
            "analysis",
            "authority",
            "graph",
        },
    )
    digest = _string(raw, "result_sha256", "result")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise IRFormatError("authority IR result.result_sha256 must be lowercase SHA-256")

    source_raw = _record(raw["source_graph"], "result.source_graph", {"ir_version", "sha256"})
    source_version = _integer(source_raw, "ir_version", "result.source_graph")
    source_digest = _string(source_raw, "sha256", "result.source_graph")
    if len(source_digest) != 64 or any(
        character not in "0123456789abcdef" for character in source_digest
    ):
        raise IRFormatError("authority IR result.source_graph.sha256 must be lowercase SHA-256")

    analysis = _record(raw["analysis"], "result.analysis", {"depth", "truncated"})
    depth = _integer(analysis, "depth", "result.analysis")
    if depth < 1:
        raise IRFormatError("authority IR result.analysis.depth must be positive")
    if not isinstance(analysis["truncated"], bool):
        raise IRFormatError("authority IR result.analysis.truncated must be a boolean")
    if not isinstance(raw["authority"], dict):
        raise IRFormatError("authority IR result.authority must be an object")
    if not isinstance(raw["graph"], dict):
        raise IRFormatError("authority IR result.graph must be an object")

    body = {key: value for key, value in raw.items() if key != "result_sha256"}
    if digest != hashlib.sha256(_canonical_result_bytes(body)).hexdigest():
        raise IRFormatError("authority IR result.result_sha256 does not match")
    graph = AuthorityIR.from_json(_canonical_result_bytes(raw["graph"]).decode("utf-8"))
    source = _source_graph(graph)
    if source_version != source.ir_version:
        raise IRFormatError("authority IR result source graph version does not match")
    if source_digest != _source_graph_sha256(source):
        raise IRFormatError("authority IR result source graph digest does not match")

    expected = _analyse_ir(source, depth=depth)
    if analysis["truncated"] != expected.authority.truncated:
        raise IRFormatError("authority IR result truncation does not match analysis")
    if raw["authority"] != expected.authority.as_dict():
        raise IRFormatError("authority IR result authority output does not match analysis")
    if graph != expected.graph:
        raise IRFormatError("authority IR result graph does not match analysis")
    return expected


def _analyse_ir(snapshot: AuthorityIR, depth: int | None = None) -> _IRAnalysis:
    """Run reachability from validated IR and attach canonical derived provenance."""
    snapshot.validate()
    if any(RELATIONS[edge.relation].derived for edge in snapshot.edges):
        raise IRFormatError("authority IR analysis input already contains derived edges")

    mandate = _to_mandate(snapshot)
    authority, trace = _analyse_with_trace(mandate, depth=depth)
    paths = dict(trace.reachable_paths)
    if any(not _path_is_enabling(mandate, path) for path in paths.values()):
        raise IRFormatError("reachability retained a path that does not replay")

    entities = {item.id: item for item in snapshot.entities}
    input_edges = {
        (item.source, item.relation, item.target): item for item in snapshot.edges
    }
    derived: dict[str, Edge] = {}
    agent = next(item for item in snapshot.entities if item.kind == "agent")
    tools = {tool.name: tool for tool in mandate.tools}
    tool_ids = {name: _entity_id("tool", name) for name in tools}

    def add_edge(
        source: str, relation: str, target: str, support: set[str]
    ) -> Edge:
        identifier = _edge_id(source, relation, target)
        existing = derived.get(identifier)
        if existing is not None:
            support.update(existing.support)
        edge = Edge(identifier, source, relation, target, tuple(sorted(support)))
        derived[identifier] = edge
        return edge

    def path_support(path: tuple[Step, ...]) -> set[str]:
        support = {_fact_id(agent.id, "tools")}
        for step in path:
            tool = tools[step.tool]
            tool_id = tool_ids[step.tool]
            support.add(_fact_id(tool_id, "requires"))
            support.update(
                input_edges[(tool_id, "requires", _entity_id("scope", scope))].id
                for scope in tool.requires
            )
            support.add(_fact_id(tool_id, "produces"))
            support.add(_fact_id(tool_id, "unbounded"))
            if tool.produces is not None:
                support.add(
                    input_edges[
                        (tool_id, "produces", _entity_id("scope", tool.produces))
                    ].id
                )
        return support

    reachable_edges: dict[str, Edge] = {}
    for tool_name, path in paths.items():
        reachable_edges[tool_name] = add_edge(
            agent.id, "can_reach", tool_ids[tool_name], path_support(path)
        )

    for tool_name in authority.reachable_tools:
        tool = tools[tool_name]
        tool_id = tool_ids[tool_name]
        # Keep this identical to reach.analyse: required scopes describe the
        # effect when present; a produced scope is the fallback. Broadening it
        # here would make provenance claim effects the public result omits.
        scope_names = tool.requires or ((tool.produces,) if tool.produces else ())
        for scope_name in scope_names:
            scope_id = _entity_id("scope", scope_name)
            relation = "requires" if scope_name in tool.requires else "produces"
            support = {
                reachable_edges[tool_name].id,
                _fact_id(tool_id, "effect"),
                input_edges[(tool_id, relation, scope_id)].id,
            }
            add_edge(tool_id, "has_effect", scope_id, support)

    def transition_edges(path: tuple[Step, ...]) -> tuple[Edge, ...]:
        result: list[Edge] = []
        for previous, current in zip(path, path[1:], strict=False):
            current_tool = tools[current.tool]
            current_id = tool_ids[current.tool]
            support = {
                reachable_edges[previous.tool].id,
                reachable_edges[current.tool].id,
                _fact_id(current_id, "requires"),
            }
            support.update(
                input_edges[(current_id, "requires", _entity_id("scope", scope))].id
                for scope in current_tool.requires
            )
            result.append(
                add_edge(
                    tool_ids[previous.tool],
                    "transitions_to",
                    current_id,
                    support,
                )
            )
        return tuple(result)

    constraint_id = _entity_id("constraint", "run")
    for breach in authority.breaches:
        final_tool = breach.path[-1].tool
        discriminator = breach.subject or (
            final_tool if breach.kind == "ungated_effect" else "run"
        )
        breach_name = f"{breach.kind}:{discriminator}"
        breach_id = _entity_id("breach", breach_name)
        entities[breach_id] = Entity(breach_id, "breach", breach_name)
        support = {reachable_edges[breach.path[0].tool].id}
        support.update(edge.id for edge in transition_edges(breach.path))

        if breach.kind == "ungated_effect":
            final_id = tool_ids[final_tool]
            support.update(
                {
                    _fact_id(final_id, "effect"),
                    _fact_id(final_id, "requires_approval"),
                }
            )
        elif breach.kind == "cumulative_value":
            support.add(_fact_id(constraint_id, "total"))
            for step in breach.path:
                tool_id = tool_ids[step.tool]
                support.update(
                    {
                        _fact_id(tool_id, "ceiling"),
                        _fact_id(tool_id, "scope_key"),
                        _fact_id(tool_id, "unbounded"),
                        _fact_id(tool_id, "value_arg"),
                    }
                )
        elif breach.kind == "effect_count":
            support.add(_fact_id(constraint_id, "effects"))
            support.update(
                _fact_id(tool_ids[step.tool], "effect") for step in breach.path
            )
        else:  # pragma: no cover - the closed search vocabulary prevents this
            raise IRFormatError(f"unsupported reachability breach {breach.kind!r}")
        add_edge(agent.id, "has_breach", breach_id, support)

    graph = AuthorityIR(
        ir_version=snapshot.ir_version,
        sources=snapshot.sources,
        entities=tuple(sorted(entities.values(), key=lambda item: item.id)),
        facts=snapshot.facts,
        edges=tuple(sorted(snapshot.edges + tuple(derived.values()), key=lambda item: item.id)),
    )
    graph.validate()
    return _IRAnalysis(
        authority=authority,
        graph=graph,
        source_graph_sha256=_source_graph_sha256(snapshot),
        source_ir_version=snapshot.ir_version,
    )
