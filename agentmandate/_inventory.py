"""Experimental records for reviewed dynamic inventory declarations.

The reader proves structure and captured-byte identity only.  It deliberately
does not decide whether evidence is exact, accepted, complete, or current, and
nothing in this module is exported from :mod:`agentmandate`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from typing import Any

from ._ir import (
    AuthorityIR,
    Edge,
    Entity,
    Evidence,
    Fact,
    IRFormatError,
    Source,
    _edge_id,
    _entity_id,
    _fact_id,
)
from .inventory import Inventory

INVENTORY_VERSION = 1
BOUNDARY_KINDS = frozenset({"deployment", "factory", "provider", "registry"})
SELECTION_KEYS = frozenset(
    {"configuration", "environment", "provider", "region", "skills", "tenant", "toolsets"}
)
COMPLETENESS = frozenset({"complete", "partial", "unknown"})
CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
REVIEWS = frozenset({"accepted", "contested", "unreviewed"})
INVENTORY_ADAPTER = "agentmandate.dynamic-inventory"
INVENTORY_ADAPTER_VERSION = 1
INVENTORY_CAPTURE_ADAPTER = "agentmandate.dynamic-inventory-capture"
INVENTORY_CAPTURE_ADAPTER_VERSION = 1
INVENTORY_PREDICATES = {
    "boundary": frozenset(
        {
            "capture",
            "completeness",
            "expires",
            "members",
            "name",
            "reviewer",
            "selection",
            "target",
        }
    ),
    "tool": frozenset({"name"}),
}


class InventoryFormatError(ValueError):
    """Raised when a dynamic inventory declaration cannot be read safely."""


@dataclass(frozen=True)
class InventoryReconciliationFinding:
    boundary: str
    message: str


@dataclass(frozen=True)
class InventoryReconciliation:
    """Private evidence passed into the existing drift comparison."""

    as_of: str
    members: tuple[str, ...]
    findings: tuple[InventoryReconciliationFinding, ...]
    complete: bool
    covers_binding: bool
    graphs: tuple[AuthorityIR, ...]


@dataclass(frozen=True)
class InventoryTarget:
    source: str
    binding: str

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "binding": self.binding}


@dataclass(frozen=True)
class InventoryBoundary:
    id: str
    kind: str
    target: InventoryTarget

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "target": self.target.as_dict()}


@dataclass(frozen=True)
class InventorySource:
    kind: str
    locator: str
    format_version: str
    producer: str
    producer_version: str
    content_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "format_version": self.format_version,
            "producer": self.producer,
            "producer_version": self.producer_version,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class InventoryMembership:
    relation: str
    completeness: str
    members: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "completeness": self.completeness,
            "members": sorted(self.members),
        }


@dataclass(frozen=True)
class InventoryEvidence:
    confidence: str
    review: str
    reviewer: str | None
    expires: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "confidence": self.confidence,
            "review": self.review,
            "reviewer": self.reviewer,
            "expires": self.expires,
        }


@dataclass(frozen=True)
class DynamicInventory:
    inventory_version: int
    boundary: InventoryBoundary
    selection: tuple[tuple[str, str | tuple[str, ...]], ...]
    source: InventorySource
    membership: InventoryMembership
    evidence: InventoryEvidence

    def as_dict(self) -> dict[str, Any]:
        selection: dict[str, str | list[str]] = {}
        for key, value in sorted(self.selection):
            selection[key] = sorted(value) if isinstance(value, tuple) else value
        return {
            "inventory_version": self.inventory_version,
            "boundary": self.boundary.as_dict(),
            "selection": selection,
            "source": self.source.as_dict(),
            "membership": self.membership.as_dict(),
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        """Return deterministic JSON suitable for committed fixtures."""
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def verify_source(self, content: bytes) -> None:
        """Verify explicitly supplied capture bytes without resolving the locator."""
        if not isinstance(content, bytes):
            raise InventoryFormatError("dynamic inventory source content must be bytes")
        digest = hashlib.sha256(content).hexdigest()
        if digest != self.source.content_sha256:
            raise InventoryFormatError(
                "dynamic inventory source.content_sha256 does not match supplied bytes"
            )

    def to_ir(self) -> AuthorityIR:
        """Project the declaration into its closed, provenance-bearing IR profile."""
        return _to_inventory_ir(self)

    @classmethod
    def from_json(cls, text: str) -> DynamicInventory:
        """Read one declaration through a strict, value-safe error boundary."""

        def reject_constant(_value: str) -> None:
            raise ValueError

        try:
            raw = json.loads(text, parse_constant=reject_constant)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            detail = (
                f" at line {exc.lineno} column {exc.colno}"
                if isinstance(exc, json.JSONDecodeError)
                else ""
            )
            raise InventoryFormatError(f"dynamic inventory is not valid JSON{detail}") from exc
        if not isinstance(raw, dict):
            raise InventoryFormatError("dynamic inventory root must be an object")
        if "inventory_version" not in raw:
            raise InventoryFormatError(
                "dynamic inventory root is missing field 'inventory_version'"
            )
        version = raw["inventory_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise InventoryFormatError(
                "unsupported dynamic inventory version type; "
                f"this build reads {INVENTORY_VERSION}"
            )
        if version != INVENTORY_VERSION:
            raise InventoryFormatError(
                f"unsupported dynamic inventory version {version}; "
                f"this build reads {INVENTORY_VERSION}"
            )
        root = _record(
            raw,
            "root",
            {"inventory_version", "boundary", "selection", "source", "membership", "evidence"},
        )
        return cls(
            inventory_version=version,
            boundary=_boundary(root["boundary"]),
            selection=_selection(root["selection"]),
            source=_source(root["source"]),
            membership=_membership(root["membership"]),
            evidence=_evidence(root["evidence"]),
        )


def reconcile(
    inventory: Inventory,
    declarations: Sequence[DynamicInventory],
    source_contents: Mapping[str, bytes],
    *,
    selection: Mapping[str, str | Sequence[str]],
    as_of: date,
) -> InventoryReconciliation:
    """Evaluate declarations for one selected static binding without side effects."""
    if type(as_of) is not date:
        raise InventoryFormatError("dynamic inventory as_of must be a date")
    expected_selection = _selection(
        {
            key: list(value)
            if isinstance(value, Sequence) and not isinstance(value, str)
            else value
            for key, value in selection.items()
        }
    )
    graphs = tuple(declaration.to_ir() for declaration in declarations)
    findings: list[InventoryReconciliationFinding] = []
    members: set[str] = set()
    matching: list[DynamicInventory] = []

    selected = inventory.selected
    for declaration in declarations:
        boundary = declaration.boundary.id
        target = declaration.boundary.target
        if (
            selected is None
            or target.source != selected.module
            or target.binding != selected.label
        ):
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    "the boundary target does not match the selected source binding",
                )
            )
            continue
        matching.append(declaration)
        if declaration.selection != expected_selection:
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    "the boundary selection does not match the reviewed deployment context",
                )
            )
            continue

        content = source_contents.get(declaration.source.locator)
        if content is None:
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    "the captured source bytes were not supplied, so its digest cannot be verified",
                )
            )
            continue
        try:
            declaration.verify_source(content)
        except InventoryFormatError:
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    "the captured source bytes do not match the reviewed digest",
                )
            )
            continue
        members.update(declaration.membership.members)

    blocked = _conflicted_boundaries(matching, findings)
    for declaration in matching:
        boundary = declaration.boundary.id
        if declaration.selection != expected_selection or boundary in blocked:
            continue
        # Source failures above already prevent both widening and eligibility.
        content = source_contents.get(declaration.source.locator)
        if (
            content is None
            or hashlib.sha256(content).hexdigest()
            != declaration.source.content_sha256
        ):
            continue
        if declaration.membership.completeness != "complete":
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    "the membership claim is not complete, so absence cannot be established",
                )
            )
        if declaration.evidence.confidence != "exact":
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    "the membership evidence is not exact",
                )
            )
        if declaration.evidence.review != "accepted":
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    "the membership evidence is not accepted",
                )
            )
        expires = declaration.evidence.expires
        if expires is None or date.fromisoformat(expires) < as_of:
            findings.append(
                InventoryReconciliationFinding(
                    boundary,
                    f"the membership review is expired at the {as_of.isoformat()} evaluation date",
                )
            )

    covers = bool(matching)
    complete = bool(declarations) and covers and not findings
    return InventoryReconciliation(
        as_of=as_of.isoformat(),
        members=tuple(sorted(members)),
        findings=tuple(findings),
        complete=complete,
        covers_binding=covers,
        graphs=graphs,
    )


def _conflicted_boundaries(
    declarations: Sequence[DynamicInventory],
    findings: list[InventoryReconciliationFinding],
) -> set[str]:
    grouped: dict[str, list[DynamicInventory]] = {}
    for declaration in declarations:
        grouped.setdefault(declaration.boundary.id, []).append(declaration)
    blocked: set[str] = set()
    for boundary, claims in grouped.items():
        if len(claims) == 1:
            continue
        blocked.add(boundary)
        member_sets = {frozenset(claim.membership.members) for claim in claims}
        message = (
            "complete claims for this boundary disagree across producer revisions"
            if len(member_sets) > 1
            else "the boundary ID is declared more than once"
        )
        findings.append(InventoryReconciliationFinding(boundary, message))
    return blocked


def _to_inventory_ir(declaration: DynamicInventory) -> AuthorityIR:
    declaration_source_id = _entity_id(
        "source", f"inventory-declaration:{declaration.boundary.id}"
    )
    capture_source_id = _entity_id(
        "source", f"inventory-capture:{declaration.boundary.id}"
    )
    boundary_id = _entity_id("boundary", declaration.boundary.id)
    tool_ids = tuple(
        _entity_id("tool", member) for member in declaration.membership.members
    )
    def evidence(location: str, *, captured: bool = False) -> tuple[Evidence, ...]:
        items = [
            Evidence(
                source=declaration_source_id,
                location=location,
                confidence=declaration.evidence.confidence,
                review=declaration.evidence.review,
            )
        ]
        if captured:
            items.append(
                Evidence(
                    source=capture_source_id,
                    location="/",
                    confidence=declaration.evidence.confidence,
                    review=declaration.evidence.review,
                )
            )
        return tuple(items)
    entities = (
        Entity(boundary_id, "boundary", declaration.boundary.id),
        *(Entity(identifier, "tool", name) for identifier, name in zip(
            tool_ids, declaration.membership.members, strict=True
        )),
    )
    selection = {
        key: sorted(value) if isinstance(value, tuple) else value
        for key, value in declaration.selection
    }
    boundary_values: dict[str, Any] = {
        "name": declaration.boundary.id,
        "target": declaration.boundary.target.as_dict(),
        "selection": selection,
        "capture": declaration.source.as_dict(),
        "completeness": declaration.membership.completeness,
        "members": list(tool_ids),
        "reviewer": declaration.evidence.reviewer,
        "expires": declaration.evidence.expires,
    }
    boundary_locations = {
        "name": "/boundary/id",
        "target": "/boundary/target",
        "selection": "/selection",
        "capture": "/source",
        "completeness": "/membership/completeness",
        "members": "/membership/members",
        "reviewer": "/evidence/reviewer",
        "expires": "/evidence/expires",
    }
    facts = tuple(
        Fact(
            _fact_id(boundary_id, predicate),
            boundary_id,
            predicate,
            value,
            evidence(
                boundary_locations[predicate],
                captured=predicate == "members",
            ),
        )
        for predicate, value in boundary_values.items()
    ) + tuple(
        Fact(
            _fact_id(identifier, "name"),
            identifier,
            "name",
            name,
            evidence(f"/membership/members/{index}", captured=True),
        )
        for index, (identifier, name) in enumerate(
            zip(tool_ids, declaration.membership.members, strict=True)
        )
    )
    members_fact = _fact_id(boundary_id, "members")
    edges = tuple(
        Edge(
            _edge_id(boundary_id, "contains_tool", identifier),
            boundary_id,
            "contains_tool",
            identifier,
            (members_fact,),
        )
        for identifier in tool_ids
    )
    semantic_sha256 = _inventory_semantic_sha256(entities, facts, edges)
    capture_semantic = hashlib.sha256(
        json.dumps(
            {"members": sorted(declaration.membership.members)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    graph = AuthorityIR(
        ir_version=1,
        sources=(
            Source(
                id=declaration_source_id,
                kind="dynamic-inventory-declaration",
                locator=f"memory:dynamic-inventory:{declaration.boundary.id}",
                format_version=declaration.inventory_version,
                producer_version=None,
                semantic_sha256=semantic_sha256,
                adapter=INVENTORY_ADAPTER,
                adapter_version=INVENTORY_ADAPTER_VERSION,
                content_sha256=hashlib.sha256(
                    declaration.to_json().encode("utf-8")
                ).hexdigest(),
            ),
            Source(
                id=capture_source_id,
                kind=declaration.source.kind,
                locator=declaration.source.locator,
                format_version=declaration.inventory_version,
                producer_version=declaration.source.producer_version,
                semantic_sha256=capture_semantic,
                adapter=INVENTORY_CAPTURE_ADAPTER,
                adapter_version=INVENTORY_CAPTURE_ADAPTER_VERSION,
                content_sha256=declaration.source.content_sha256,
            ),
        ),
        entities=entities,
        facts=facts,
        edges=edges,
    )
    _validate_inventory_profile(graph)
    return graph


def _inventory_semantic_sha256(
    entities: Sequence[Entity], facts: Sequence[Fact], edges: Sequence[Edge]
) -> str:
    body = {
        "entities": [entity.as_dict() for entity in sorted(entities, key=lambda item: item.id)],
        "facts": [fact.as_dict() for fact in sorted(facts, key=lambda item: item.id)],
        "edges": [edge.as_dict() for edge in sorted(edges, key=lambda item: item.id)],
    }
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_inventory_profile(graph: AuthorityIR) -> None:
    """Require the closed inventory projection without making it trusted policy."""
    try:
        graph.validate()
    except IRFormatError as exc:
        raise InventoryFormatError("dynamic inventory IR profile is structurally invalid") from exc
    if len(graph.sources) != 2:
        raise InventoryFormatError("dynamic inventory IR profile requires exactly two sources")
    sources = {source.adapter: source for source in graph.sources}
    if set(sources) != {INVENTORY_ADAPTER, INVENTORY_CAPTURE_ADAPTER}:
        raise InventoryFormatError("dynamic inventory IR profile has unsupported sources")
    declaration_source = sources[INVENTORY_ADAPTER]
    capture_source = sources[INVENTORY_CAPTURE_ADAPTER]
    if (
        declaration_source.kind != "dynamic-inventory-declaration"
        or declaration_source.format_version != INVENTORY_VERSION
        or declaration_source.adapter_version != INVENTORY_ADAPTER_VERSION
        or capture_source.format_version != INVENTORY_VERSION
        or capture_source.adapter_version != INVENTORY_CAPTURE_ADAPTER_VERSION
    ):
        raise InventoryFormatError("dynamic inventory IR profile has an unsupported source")

    entities = {entity.id: entity for entity in graph.entities}
    boundaries = [entity for entity in graph.entities if entity.kind == "boundary"]
    if len(boundaries) != 1 or any(
        entity.kind not in INVENTORY_PREDICATES for entity in graph.entities
    ):
        raise InventoryFormatError(
            "dynamic inventory IR profile requires one boundary and only tool entities"
        )
    boundary = boundaries[0]
    facts: dict[tuple[str, str], Fact] = {}
    for fact in graph.facts:
        entity = entities[fact.subject]
        if fact.predicate not in INVENTORY_PREDICATES[entity.kind]:
            raise InventoryFormatError(
                "dynamic inventory IR profile contains an unsupported predicate"
            )
        key = (fact.subject, fact.predicate)
        evidence_sources = {item.source for item in fact.evidence}
        if declaration_source.id not in evidence_sources or not evidence_sources <= {
            declaration_source.id,
            capture_source.id,
        }:
            raise InventoryFormatError(
                "dynamic inventory IR profile fact has unsupported evidence"
            )
        facts[key] = fact

    required = {(boundary.id, predicate) for predicate in INVENTORY_PREDICATES["boundary"]}
    required.update(
        (entity.id, "name") for entity in graph.entities if entity.kind == "tool"
    )
    if set(facts) != required:
        raise InventoryFormatError(
            "dynamic inventory IR profile does not contain its complete predicate set"
        )
    all_evidence = [item for fact in graph.facts for item in fact.evidence]
    if any(
        (item.confidence, item.review)
        != (all_evidence[0].confidence, all_evidence[0].review)
        for item in all_evidence
    ):
        raise InventoryFormatError(
            "dynamic inventory IR profile facts disagree on evidence state"
        )
    if facts[(boundary.id, "name")].value != boundary.name:
        raise InventoryFormatError("dynamic inventory IR boundary name does not match entity")
    for entity in graph.entities:
        if entity.kind == "tool" and facts[(entity.id, "name")].value != entity.name:
            raise InventoryFormatError("dynamic inventory IR tool name does not match entity")

    target = facts[(boundary.id, "target")].value
    target_record = _record(target, "IR target", {"source", "binding"})
    _relative_path(target_record, "source", "IR target")
    _string(target_record, "binding", "IR target")
    _selection(facts[(boundary.id, "selection")].value)
    capture = _record(
        facts[(boundary.id, "capture")].value,
        "IR capture",
        {
            "kind",
            "locator",
            "format_version",
            "producer",
            "producer_version",
            "content_sha256",
        },
    )
    if (
        _string(capture, "kind", "IR capture") != capture_source.kind
        or _relative_path(capture, "locator", "IR capture")
        != capture_source.locator
        or _string(capture, "producer_version", "IR capture")
        != capture_source.producer_version
        or _string(capture, "content_sha256", "IR capture")
        != capture_source.content_sha256
    ):
        raise InventoryFormatError(
            "dynamic inventory IR capture fact does not match its source"
        )
    _string(capture, "format_version", "IR capture")
    _string(capture, "producer", "IR capture")
    completeness = facts[(boundary.id, "completeness")].value
    if completeness not in COMPLETENESS:
        raise InventoryFormatError(
            "dynamic inventory IR profile completeness has an invalid value"
        )
    _evidence(
        {
            "confidence": all_evidence[0].confidence,
            "review": all_evidence[0].review,
            "reviewer": facts[(boundary.id, "reviewer")].value,
            "expires": facts[(boundary.id, "expires")].value,
        }
    )
    members = facts[(boundary.id, "members")].value
    tool_ids = {entity.id for entity in graph.entities if entity.kind == "tool"}
    if not isinstance(members, list) or set(members) != tool_ids or len(members) != len(tool_ids):
        raise InventoryFormatError("dynamic inventory IR profile members do not match tools")
    required_capture_facts = {
        (boundary.id, "members"),
        *(
            (entity.id, "name")
            for entity in graph.entities
            if entity.kind == "tool"
        ),
    }
    if any(
        capture_source.id
        not in {item.source for item in facts[key].evidence}
        for key in required_capture_facts
    ):
        raise InventoryFormatError(
            "dynamic inventory IR membership lacks captured-source evidence"
        )
    digest = capture_source.content_sha256
    if digest is None or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise InventoryFormatError(
            "dynamic inventory IR source content_sha256 must be lowercase SHA-256"
        )
    semantic = _inventory_semantic_sha256(graph.entities, graph.facts, graph.edges)
    if declaration_source.semantic_sha256 != semantic:
        raise InventoryFormatError(
            "dynamic inventory IR source semantic_sha256 does not match the profile"
        )
    member_names = sorted(
        entity.name for entity in graph.entities if entity.kind == "tool"
    )
    capture_semantic = hashlib.sha256(
        json.dumps(
            {"members": member_names},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    if capture_source.semantic_sha256 != capture_semantic:
        raise InventoryFormatError(
            "dynamic inventory IR capture semantic_sha256 does not match members"
        )


def _record(raw: Any, path: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise InventoryFormatError(f"dynamic inventory {path} must be an object")
    missing = sorted(fields - raw.keys())
    if missing:
        raise InventoryFormatError(
            f"dynamic inventory {path} is missing field {missing[0]!r}"
        )
    extra = sorted(raw.keys() - fields)
    if extra:
        raise InventoryFormatError(
            f"dynamic inventory {path} has unknown field {extra[0]!r}"
        )
    return raw


def _string(raw: dict[str, Any], field: str, path: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value or value.strip() != value:
        raise InventoryFormatError(
            f"dynamic inventory {path}.{field} must be a non-empty string"
        )
    return value


def _enum(raw: dict[str, Any], field: str, path: str, allowed: frozenset[str]) -> str:
    value = _string(raw, field, path)
    if value not in allowed:
        raise InventoryFormatError(f"dynamic inventory {path}.{field} has an invalid value")
    return value


def _relative_path(raw: dict[str, Any], field: str, path: str) -> str:
    value = _string(raw, field, path)
    parsed = PurePosixPath(value)
    if (
        parsed.is_absolute()
        or "\\" in value
        or ".." in parsed.parts
        or value == "."
        or str(parsed) != value
    ):
        raise InventoryFormatError(
            f"dynamic inventory {path}.{field} must be a safe relative POSIX path"
        )
    return value


def _boundary(raw: Any) -> InventoryBoundary:
    path = "boundary"
    record = _record(raw, path, {"id", "kind", "target"})
    target_path = f"{path}.target"
    target = _record(record["target"], target_path, {"source", "binding"})
    return InventoryBoundary(
        id=_string(record, "id", path),
        kind=_enum(record, "kind", path, BOUNDARY_KINDS),
        target=InventoryTarget(
            source=_relative_path(target, "source", target_path),
            binding=_string(target, "binding", target_path),
        ),
    )


def _selection(raw: Any) -> tuple[tuple[str, str | tuple[str, ...]], ...]:
    path = "selection"
    if not isinstance(raw, dict):
        raise InventoryFormatError(f"dynamic inventory {path} must be an object")
    unknown = sorted(raw.keys() - SELECTION_KEYS)
    if unknown:
        raise InventoryFormatError(
            f"dynamic inventory {path} has unsupported key {unknown[0]!r}"
        )
    result: list[tuple[str, str | tuple[str, ...]]] = []
    for key, value in raw.items():
        item_path = f"{path}.{key}"
        if isinstance(value, str) and value and value.strip() == value:
            result.append((key, value))
            continue
        if (
            isinstance(value, list)
            and value
            and all(
                isinstance(item, str) and item and item.strip() == item for item in value
            )
        ):
            if len(set(value)) != len(value):
                raise InventoryFormatError(
                    f"dynamic inventory {item_path} must not contain duplicates"
                )
            result.append((key, tuple(value)))
            continue
        raise InventoryFormatError(
            f"dynamic inventory {item_path} must be a non-empty string or string array"
        )
    return tuple(result)


def _source(raw: Any) -> InventorySource:
    path = "source"
    record = _record(
        raw,
        path,
        {
            "kind",
            "locator",
            "format_version",
            "producer",
            "producer_version",
            "content_sha256",
        },
    )
    digest = _string(record, "content_sha256", path)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise InventoryFormatError(
            "dynamic inventory source.content_sha256 must be lowercase SHA-256"
        )
    return InventorySource(
        kind=_string(record, "kind", path),
        locator=_relative_path(record, "locator", path),
        format_version=_string(record, "format_version", path),
        producer=_string(record, "producer", path),
        producer_version=_string(record, "producer_version", path),
        content_sha256=digest,
    )


def _membership(raw: Any) -> InventoryMembership:
    path = "membership"
    record = _record(raw, path, {"relation", "completeness", "members"})
    relation = _string(record, "relation", path)
    if relation != "contains_tool":
        raise InventoryFormatError("dynamic inventory membership.relation has an invalid value")
    members = record["members"]
    if not isinstance(members, list) or any(
        not isinstance(member, str) or not member or member.strip() != member
        for member in members
    ):
        raise InventoryFormatError(
            "dynamic inventory membership.members must be an array of non-empty strings"
        )
    if len(set(members)) != len(members):
        raise InventoryFormatError(
            "dynamic inventory membership.members must not contain duplicates"
        )
    return InventoryMembership(
        relation=relation,
        completeness=_enum(record, "completeness", path, COMPLETENESS),
        members=tuple(members),
    )


def _nullable_string(raw: dict[str, Any], field: str, path: str) -> str | None:
    value = raw[field]
    if value is not None and (
        not isinstance(value, str) or not value or value.strip() != value
    ):
        raise InventoryFormatError(
            f"dynamic inventory {path}.{field} must be a non-empty string or null"
        )
    return value


def _evidence(raw: Any) -> InventoryEvidence:
    path = "evidence"
    record = _record(raw, path, {"confidence", "review", "reviewer", "expires"})
    review = _enum(record, "review", path, REVIEWS)
    reviewer = _nullable_string(record, "reviewer", path)
    expires = _nullable_string(record, "expires", path)
    if review == "unreviewed" and (reviewer is not None or expires is not None):
        raise InventoryFormatError(
            "dynamic inventory unreviewed evidence cannot name a reviewer or expiry"
        )
    if review != "unreviewed" and (reviewer is None or expires is None):
        raise InventoryFormatError(
            "dynamic inventory reviewed evidence requires a reviewer and expiry"
        )
    if expires is not None:
        try:
            parsed = date.fromisoformat(expires)
        except ValueError as exc:
            raise InventoryFormatError(
                "dynamic inventory evidence.expires must be an ISO calendar date"
            ) from exc
        if parsed.isoformat() != expires:
            raise InventoryFormatError(
                "dynamic inventory evidence.expires must be an ISO calendar date"
            )
    return InventoryEvidence(
        confidence=_enum(record, "confidence", path, CONFIDENCE),
        review=review,
        reviewer=reviewer,
        expires=expires,
    )
