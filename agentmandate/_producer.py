"""Private records for evidence-backed finite producer boundaries.

The reader proves structure and caller-supplied byte identity. Its standalone
Authority IR projection remains ineligible for reachability analysis and does
not treat migration as review.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
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
from .manifest import Mandate
from .reach import Authority, _analyse_with_trace

PRODUCER_BOUNDARY_VERSION = 1
PRODUCER_BOUNDARY_ADAPTER = "agentmandate.producer-boundary"
PRODUCER_BOUNDARY_ADAPTER_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_REVIEWED_ALIAS = re.compile(r"reviewed-[a-z0-9]+(?:-[a-z0-9]+)*")
_CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
_REVIEW = frozenset({"accepted", "contested", "unreviewed"})
_COMPLETENESS = frozenset({"complete", "partial", "unknown"})
_CAPACITY_KINDS = frozenset({"concurrent"})
_EXHAUSTION_REASONS = frozenset({"capacity_exhausted"})
_SOURCE_ROLES = frozenset(
    {"upstream-inventory", "capacity-controls", "selected-run-boundary"}
)
_SOURCE_KINDS = {
    "upstream-inventory": "tool-catalogue",
    "capacity-controls": "producer-outcomes",
    "selected-run-boundary": "capture-adapter",
}
_PROFILE_PREDICATES = {
    "producer_boundary": frozenset(
        {
            "adapter",
            "capacity_kind",
            "capacity_maximum",
            "controls",
            "expires",
            "name",
            "output",
            "partition",
            "partition_argument",
            "producer",
            "reviewer",
            "run_boundary",
            "sources",
            "target",
        }
    ),
    "resource_binding": frozenset({"name"}),
    "scope": frozenset({"name"}),
    "tool": frozenset({"name"}),
}


class ProducerBoundaryFormatError(ValueError):
    """Raised when a private producer-boundary artifact is malformed."""


@dataclass(frozen=True)
class ProducerSelection:
    """Caller-selected deployment and partition joined to boundary evidence."""

    source: str
    binding: str
    producer: str
    producer_version: str
    partition_argument: str
    partition_binding: str
    output_scope: str


@dataclass(frozen=True)
class ProducerFinding:
    """One fail-closed producer eligibility finding."""

    boundary: str
    tool: str
    message: str
    support: tuple[str, ...]


@dataclass(frozen=True)
class AppliedProducerBoundary:
    """One producer cap admitted into the private bounded search."""

    boundary: str
    tool: str
    output_scope: str
    partition_binding: str
    maximum: int
    support: tuple[str, ...]


@dataclass(frozen=True)
class ProducerAnalysis:
    """Private producer-aware authority plus eligibility decisions."""

    authority: Authority
    findings: tuple[ProducerFinding, ...]
    applied: tuple[AppliedProducerBoundary, ...]
    as_of: str


def _reject_constant(_: str) -> None:
    raise ValueError


def _load(text: str, label: str) -> Any:
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ProducerBoundaryFormatError(
            f"{label} is not valid JSON at line {exc.lineno} column {exc.colno}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ProducerBoundaryFormatError(f"{label} contains a non-canonical value") from exc


def _record(value: Any, path: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProducerBoundaryFormatError(f"producer boundary {path} must be an object")
    missing = sorted(fields - value.keys())
    if missing:
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} is missing field {missing[0]!r}"
        )
    extra = sorted(value.keys() - fields)
    if extra:
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} has unknown field {extra[0]!r}"
        )
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} must be a non-empty stripped string"
        )
    return value


def _integer(value: Any, path: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} must be an integer of at least {minimum}"
        )
    return value


def _digest(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} must be lowercase SHA-256"
        )
    return value


def _path(value: Any, path: str) -> str:
    value = _string(value, path)
    if value.startswith("/") or "\\" in value or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} must be a repository-relative POSIX path"
        )
    return value


def _pointer(value: Any, path: str) -> str:
    value = _string(value, path)
    if not value.startswith("/"):
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} must be an absolute JSON Pointer"
        )
    return value


def _strings(value: Any, path: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "possibly empty " if allow_empty else "non-empty "
        raise ProducerBoundaryFormatError(
            f"producer boundary {path} must be a {qualifier}array"
        )
    result = tuple(_string(item, f"{path}[]") for item in value)
    if len(result) != len(set(result)):
        raise ProducerBoundaryFormatError(f"producer boundary {path} contains duplicates")
    return tuple(sorted(result))


@dataclass(frozen=True)
class ProducerTarget:
    source: str
    binding: str
    producer: str
    producer_version: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "binding": self.binding,
            "producer": self.producer,
            "producer_version": self.producer_version,
        }


@dataclass(frozen=True)
class ProducerPartition:
    argument: str
    binding: str

    def as_dict(self) -> dict[str, str]:
        return {"argument": self.argument, "binding": self.binding}


@dataclass(frozen=True)
class ProducerCapacity:
    kind: str
    maximum: int

    def as_dict(self) -> dict[str, str | int]:
        return {"kind": self.kind, "maximum": self.maximum}


@dataclass(frozen=True)
class ProducerOutput:
    scope: str
    capacity: ProducerCapacity

    def as_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "capacity": self.capacity.as_dict()}


@dataclass(frozen=True)
class ProducerRunBoundary:
    inventory: tuple[str, ...]
    inventory_completeness: str
    release_tools: tuple[str, ...]
    release_completeness: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "inventory": list(self.inventory),
            "inventory_completeness": self.inventory_completeness,
            "release_tools": list(self.release_tools),
            "release_completeness": self.release_completeness,
        }


@dataclass(frozen=True)
class AcceptedControl:
    count: int
    source: str
    location: str

    def as_dict(self) -> dict[str, str | int]:
        return {"count": self.count, "source": self.source, "location": self.location}


@dataclass(frozen=True)
class ExhaustedControl:
    attempt: int
    reason: str
    source: str
    location: str

    def as_dict(self) -> dict[str, str | int]:
        return {
            "attempt": self.attempt,
            "reason": self.reason,
            "source": self.source,
            "location": self.location,
        }


@dataclass(frozen=True)
class ProducerControls:
    accepted_through: AcceptedControl
    exhausted_at: ExhaustedControl

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted_through": self.accepted_through.as_dict(),
            "exhausted_at": self.exhausted_at.as_dict(),
        }


@dataclass(frozen=True)
class ProducerSource:
    id: str
    kind: str
    role: str
    locator: str
    content_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "role": self.role,
            "locator": self.locator,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class ProducerEvidence:
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
class ProducerBoundary:
    producer_boundary_version: int
    id: str
    adapter_name: str
    adapter_version: int
    target: ProducerTarget
    partition: ProducerPartition
    output: ProducerOutput
    run_boundary: ProducerRunBoundary
    controls: ProducerControls
    sources: tuple[ProducerSource, ...]
    evidence: ProducerEvidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "producer_boundary_version": self.producer_boundary_version,
            "id": self.id,
            "adapter": {"name": self.adapter_name, "version": self.adapter_version},
            "target": self.target.as_dict(),
            "partition": self.partition.as_dict(),
            "output": self.output.as_dict(),
            "run_boundary": self.run_boundary.as_dict(),
            "controls": self.controls.as_dict(),
            "sources": [source.as_dict() for source in self.sources],
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def verify_sources(self, contents: Mapping[str, bytes]) -> None:
        _verify_sources(self.sources, contents)

    def to_ir(self) -> AuthorityIR:
        """Project this record into its closed, standalone Authority IR profile."""
        return _to_producer_ir(self)

    @classmethod
    def from_json(cls, text: str) -> ProducerBoundary:
        raw = _load(text, "producer boundary")
        if not isinstance(raw, dict):
            raise ProducerBoundaryFormatError("producer boundary root must be an object")
        if "producer_boundary_version" not in raw:
            raise ProducerBoundaryFormatError(
                "producer boundary root is missing field 'producer_boundary_version'"
            )
        version = raw["producer_boundary_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ProducerBoundaryFormatError(
                "unsupported producer boundary version type; this build reads 1"
            )
        if version != PRODUCER_BOUNDARY_VERSION:
            raise ProducerBoundaryFormatError(
                f"unsupported producer boundary version {version}; this build reads 1"
            )
        root = _record(
            raw,
            "root",
            {
                "producer_boundary_version",
                "id",
                "adapter",
                "target",
                "partition",
                "output",
                "run_boundary",
                "controls",
                "sources",
                "evidence",
            },
        )
        adapter_name, adapter_version = _adapter(root["adapter"])
        sources = _sources(root["sources"])
        output = _output(root["output"])
        source_roles = {source.id: source.role for source in sources}
        controls = _controls(root["controls"], source_roles)
        if controls.accepted_through.count != output.capacity.maximum:
            raise ProducerBoundaryFormatError(
                "producer boundary accepted control must equal capacity maximum"
            )
        if controls.exhausted_at.attempt != output.capacity.maximum + 1:
            raise ProducerBoundaryFormatError(
                "producer boundary exhaustion control must follow capacity maximum"
            )
        target = _target(root["target"])
        run_boundary = _run_boundary(root["run_boundary"])
        selected_source = next(
            source for source in sources if source.role == "selected-run-boundary"
        )
        if target.source != selected_source.locator or target.binding not in run_boundary.inventory:
            raise ProducerBoundaryFormatError(
                "producer boundary target does not match the selected run boundary"
            )
        return cls(
            version,
            _string(root["id"], "root.id"),
            adapter_name,
            adapter_version,
            target,
            _partition(root["partition"]),
            output,
            run_boundary,
            controls,
            sources,
            _evidence(root["evidence"]),
        )


def _adapter(value: Any) -> tuple[str, int]:
    raw = _record(value, "adapter", {"name", "version"})
    name = _string(raw["name"], "adapter.name")
    version = _integer(raw["version"], "adapter.version")
    if name != PRODUCER_BOUNDARY_ADAPTER or version != PRODUCER_BOUNDARY_ADAPTER_VERSION:
        raise ProducerBoundaryFormatError("producer boundary adapter is not supported")
    return name, version


def _target(value: Any) -> ProducerTarget:
    raw = _record(value, "target", {"source", "binding", "producer", "producer_version"})
    return ProducerTarget(
        _path(raw["source"], "target.source"),
        _string(raw["binding"], "target.binding"),
        _string(raw["producer"], "target.producer"),
        _string(raw["producer_version"], "target.producer_version"),
    )


def _partition(value: Any) -> ProducerPartition:
    raw = _record(value, "partition", {"argument", "binding"})
    binding = _string(raw["binding"], "partition.binding")
    if not _REVIEWED_ALIAS.fullmatch(binding):
        raise ProducerBoundaryFormatError(
            "producer boundary partition.binding must be a reviewed non-secret alias"
        )
    return ProducerPartition(
        _string(raw["argument"], "partition.argument"),
        binding,
    )


def _output(value: Any) -> ProducerOutput:
    raw = _record(value, "output", {"scope", "capacity"})
    capacity = _record(raw["capacity"], "output.capacity", {"kind", "maximum"})
    kind = _string(capacity["kind"], "output.capacity.kind")
    if kind not in _CAPACITY_KINDS:
        raise ProducerBoundaryFormatError("producer boundary capacity kind is not supported")
    return ProducerOutput(
        _string(raw["scope"], "output.scope"),
        ProducerCapacity(kind, _integer(capacity["maximum"], "output.capacity.maximum")),
    )


def _run_boundary(value: Any) -> ProducerRunBoundary:
    raw = _record(
        value,
        "run_boundary",
        {"inventory", "inventory_completeness", "release_tools", "release_completeness"},
    )
    inventory_completeness = _string(
        raw["inventory_completeness"], "run_boundary.inventory_completeness"
    )
    release_completeness = _string(
        raw["release_completeness"], "run_boundary.release_completeness"
    )
    if (
        inventory_completeness not in _COMPLETENESS
        or release_completeness not in _COMPLETENESS
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary run completeness has an invalid value"
        )
    return ProducerRunBoundary(
        _strings(raw["inventory"], "run_boundary.inventory"),
        inventory_completeness,
        _strings(raw["release_tools"], "run_boundary.release_tools", allow_empty=True),
        release_completeness,
    )


def _controls(value: Any, source_roles: dict[str, str]) -> ProducerControls:
    raw = _record(value, "controls", {"accepted_through", "exhausted_at"})
    accepted = _record(
        raw["accepted_through"], "controls.accepted_through", {"count", "source", "location"}
    )
    exhausted = _record(
        raw["exhausted_at"],
        "controls.exhausted_at",
        {"attempt", "reason", "source", "location"},
    )
    accepted_source = _string(accepted["source"], "controls.accepted_through.source")
    exhausted_source = _string(exhausted["source"], "controls.exhausted_at.source")
    if accepted_source not in source_roles or exhausted_source not in source_roles:
        raise ProducerBoundaryFormatError("producer boundary control cites an unknown source")
    if (
        source_roles[accepted_source] != "capacity-controls"
        or source_roles[exhausted_source] != "capacity-controls"
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary controls must cite capacity-control evidence"
        )
    reason = _string(exhausted["reason"], "controls.exhausted_at.reason")
    if reason not in _EXHAUSTION_REASONS:
        raise ProducerBoundaryFormatError("producer boundary exhaustion reason is not supported")
    return ProducerControls(
        AcceptedControl(
            _integer(accepted["count"], "controls.accepted_through.count"),
            accepted_source,
            _pointer(accepted["location"], "controls.accepted_through.location"),
        ),
        ExhaustedControl(
            _integer(exhausted["attempt"], "controls.exhausted_at.attempt"),
            reason,
            exhausted_source,
            _pointer(exhausted["location"], "controls.exhausted_at.location"),
        ),
    )


def _sources(value: Any) -> tuple[ProducerSource, ...]:
    if not isinstance(value, list) or not value:
        raise ProducerBoundaryFormatError("producer boundary sources must be a non-empty array")
    result = []
    for index, item in enumerate(value):
        path = f"sources[{index}]"
        raw = _record(item, path, {"id", "kind", "role", "locator", "content_sha256"})
        role = _string(raw["role"], f"{path}.role")
        if role not in _SOURCE_ROLES:
            raise ProducerBoundaryFormatError("producer boundary source role is not supported")
        kind = _string(raw["kind"], f"{path}.kind")
        if kind != _SOURCE_KINDS[role]:
            raise ProducerBoundaryFormatError(
                "producer boundary source kind does not match its role"
            )
        result.append(
            ProducerSource(
                _string(raw["id"], f"{path}.id"),
                kind,
                role,
                _path(raw["locator"], f"{path}.locator"),
                _digest(raw["content_sha256"], f"{path}.content_sha256"),
            )
        )
    ids = [source.id for source in result]
    locators = [source.locator for source in result]
    roles = [source.role for source in result]
    if (
        len(ids) != len(set(ids))
        or len(locators) != len(set(locators))
        or len(roles) != len(set(roles))
    ):
        raise ProducerBoundaryFormatError("producer boundary sources have duplicate identities")
    if set(roles) != _SOURCE_ROLES:
        raise ProducerBoundaryFormatError(
            "producer boundary sources must cover every required role"
        )
    return tuple(sorted(result, key=lambda source: source.id))


def _evidence(value: Any) -> ProducerEvidence:
    raw = _record(value, "evidence", {"confidence", "review", "reviewer", "expires"})
    confidence = _string(raw["confidence"], "evidence.confidence")
    review = _string(raw["review"], "evidence.review")
    if confidence not in _CONFIDENCE or review not in _REVIEW:
        raise ProducerBoundaryFormatError("producer boundary evidence state is invalid")
    reviewer = raw["reviewer"]
    expires = raw["expires"]
    if review == "unreviewed":
        if reviewer is not None or expires is not None:
            raise ProducerBoundaryFormatError(
                "producer boundary unreviewed evidence cannot carry accountability"
            )
        return ProducerEvidence(confidence, review, None, None)
    reviewer = _string(reviewer, "evidence.reviewer")
    if not isinstance(expires, str) or not _DATE.fullmatch(expires):
        raise ProducerBoundaryFormatError(
            "producer boundary evidence.expires must be a canonical ISO date"
        )
    try:
        date.fromisoformat(expires)
    except ValueError as exc:
        raise ProducerBoundaryFormatError(
            "producer boundary evidence.expires is not a real calendar date"
        ) from exc
    return ProducerEvidence(confidence, review, reviewer, expires)


def _verify_sources(
    sources: tuple[ProducerSource, ...], contents: Mapping[str, bytes]
) -> None:
    if not isinstance(contents, Mapping) or any(
        not isinstance(locator, str) or not isinstance(content, bytes)
        for locator, content in contents.items()
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary source verification requires locator-to-bytes"
        )
    expected = {source.locator for source in sources}
    if set(contents) != expected:
        missing = sorted(expected - set(contents))
        detail = f"; missing locator {missing[0]}" if missing else ""
        raise ProducerBoundaryFormatError(f"producer boundary source set differs{detail}")
    for source in sources:
        if hashlib.sha256(contents[source.locator]).hexdigest() != source.content_sha256:
            raise ProducerBoundaryFormatError(
                f"producer boundary source bytes do not match locator {source.locator}"
            )


def _profile_digest(
    entities: Sequence[Entity], facts: Sequence[Fact], edges: Sequence[Edge]
) -> str:
    body = {
        "entities": [item.as_dict() for item in sorted(entities, key=lambda item: item.id)],
        "facts": [item.as_dict() for item in sorted(facts, key=lambda item: item.id)],
        "edges": [item.as_dict() for item in sorted(edges, key=lambda item: item.id)],
    }
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _to_producer_ir(boundary: ProducerBoundary) -> AuthorityIR:
    source_id = _entity_id("source", f"producer-boundary:{boundary.id}")
    boundary_id = _entity_id("producer_boundary", boundary.id)
    tool_id = _entity_id("tool", boundary.target.binding)
    scope_id = _entity_id("scope", boundary.output.scope)
    partition_id = _entity_id("resource_binding", boundary.partition.binding)
    evidence_state = {
        "confidence": boundary.evidence.confidence,
        "review": boundary.evidence.review,
    }

    def evidence(location: str) -> tuple[Evidence, ...]:
        return (Evidence(source_id, location, **evidence_state),)

    entities = (
        Entity(boundary_id, "producer_boundary", boundary.id),
        Entity(tool_id, "tool", boundary.target.binding),
        Entity(scope_id, "scope", boundary.output.scope),
        Entity(partition_id, "resource_binding", boundary.partition.binding),
    )
    values: dict[str, Any] = {
        "adapter": {"name": boundary.adapter_name, "version": boundary.adapter_version},
        "capacity_kind": boundary.output.capacity.kind,
        "capacity_maximum": boundary.output.capacity.maximum,
        "controls": boundary.controls.as_dict(),
        "expires": boundary.evidence.expires,
        "name": boundary.id,
        "output": scope_id,
        "partition": partition_id,
        "partition_argument": boundary.partition.argument,
        "producer": tool_id,
        "reviewer": boundary.evidence.reviewer,
        "run_boundary": boundary.run_boundary.as_dict(),
        "sources": [source.as_dict() for source in boundary.sources],
        "target": boundary.target.as_dict(),
    }
    locations = {
        "adapter": "/adapter",
        "capacity_kind": "/output/capacity/kind",
        "capacity_maximum": "/output/capacity/maximum",
        "controls": "/controls",
        "expires": "/evidence/expires",
        "name": "/id",
        "output": "/output/scope",
        "partition": "/partition/binding",
        "partition_argument": "/partition/argument",
        "producer": "/target/binding",
        "reviewer": "/evidence/reviewer",
        "run_boundary": "/run_boundary",
        "sources": "/sources",
        "target": "/target",
    }
    facts = tuple(
        Fact(
            _fact_id(boundary_id, predicate),
            boundary_id,
            predicate,
            value,
            evidence(locations[predicate]),
        )
        for predicate, value in values.items()
    ) + (
        Fact(
            _fact_id(tool_id, "name"),
            tool_id,
            "name",
            boundary.target.binding,
            evidence("/target/binding"),
        ),
        Fact(
            _fact_id(scope_id, "name"),
            scope_id,
            "name",
            boundary.output.scope,
            evidence("/output/scope"),
        ),
        Fact(
            _fact_id(partition_id, "name"),
            partition_id,
            "name",
            boundary.partition.binding,
            evidence("/partition/binding"),
        ),
    )
    producer_support = tuple(
        sorted(
            _fact_id(boundary_id, predicate)
            for predicate in ("producer", "target", "run_boundary")
        )
    )
    output_support = tuple(
        sorted(
            _fact_id(boundary_id, predicate)
            for predicate in ("output", "capacity_kind", "capacity_maximum")
        )
    )
    partition_support = tuple(
        sorted(
            _fact_id(boundary_id, predicate)
            for predicate in ("partition", "partition_argument")
        )
    )
    edges = (
        Edge(
            _edge_id(boundary_id, "bounds_producer", tool_id),
            boundary_id,
            "bounds_producer",
            tool_id,
            producer_support,
        ),
        Edge(
            _edge_id(boundary_id, "bounds_output", scope_id),
            boundary_id,
            "bounds_output",
            scope_id,
            output_support,
        ),
        Edge(
            _edge_id(boundary_id, "partitioned_by", partition_id),
            boundary_id,
            "partitioned_by",
            partition_id,
            partition_support,
        ),
    )
    ordered_entities = tuple(sorted(entities, key=lambda item: item.id))
    ordered_facts = tuple(sorted(facts, key=lambda item: item.id))
    ordered_edges = tuple(sorted(edges, key=lambda item: item.id))
    graph = AuthorityIR(
        1,
        (
            Source(
                source_id,
                "producer-boundary",
                f"memory:producer-boundary:{boundary.id}",
                boundary.producer_boundary_version,
                boundary.target.producer_version,
                _profile_digest(ordered_entities, ordered_facts, ordered_edges),
                PRODUCER_BOUNDARY_ADAPTER,
                PRODUCER_BOUNDARY_ADAPTER_VERSION,
                hashlib.sha256(boundary.to_json().encode("utf-8")).hexdigest(),
            ),
        ),
        ordered_entities,
        ordered_facts,
        ordered_edges,
    )
    _validate_producer_profile(graph)
    return graph


def _validate_producer_profile(graph: AuthorityIR) -> None:
    """Require the complete producer profile without making it trusted policy."""
    try:
        graph.validate()
    except (IRFormatError, TypeError) as exc:
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile is structurally invalid"
        ) from exc
    if len(graph.sources) != 1:
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile requires exactly one source"
        )
    source = graph.sources[0]
    if (
        source.kind != "producer-boundary"
        or source.format_version != PRODUCER_BOUNDARY_VERSION
        or source.adapter != PRODUCER_BOUNDARY_ADAPTER
        or source.adapter_version != PRODUCER_BOUNDARY_ADAPTER_VERSION
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile has an unsupported source"
        )
    entities = {entity.id: entity for entity in graph.entities}
    boundaries = [entity for entity in graph.entities if entity.kind == "producer_boundary"]
    if len(boundaries) != 1 or any(
        entity.kind not in _PROFILE_PREDICATES for entity in graph.entities
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile requires one boundary and three typed targets"
        )
    boundary_entity = boundaries[0]
    facts: dict[tuple[str, str], Fact] = {}
    for fact in graph.facts:
        entity = entities[fact.subject]
        if fact.predicate not in _PROFILE_PREDICATES[entity.kind]:
            raise ProducerBoundaryFormatError(
                "producer boundary IR profile contains an unsupported predicate"
            )
        if len(fact.evidence) != 1 or fact.evidence[0].source != source.id:
            raise ProducerBoundaryFormatError(
                "producer boundary IR profile fact has unsupported evidence"
            )
        facts[(fact.subject, fact.predicate)] = fact
    required = {
        (boundary_entity.id, predicate)
        for predicate in _PROFILE_PREDICATES["producer_boundary"]
    }
    required.update(
        (entity.id, "name")
        for entity in graph.entities
        if entity.kind != "producer_boundary"
    )
    if set(facts) != required:
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile does not contain its complete predicate set"
        )
    boundary_facts = {
        predicate: facts[(boundary_entity.id, predicate)]
        for predicate in _PROFILE_PREDICATES["producer_boundary"]
    }
    evidence_states = {
        (fact.evidence[0].confidence, fact.evidence[0].review)
        for fact in graph.facts
    }
    if len(evidence_states) != 1:
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile facts disagree on evidence state"
        )
    confidence, review = next(iter(evidence_states))
    raw = {
        "producer_boundary_version": source.format_version,
        "id": boundary_entity.name,
        "adapter": boundary_facts["adapter"].value,
        "target": boundary_facts["target"].value,
        "partition": {
            "argument": boundary_facts["partition_argument"].value,
            "binding": entities[boundary_facts["partition"].value].name,
        },
        "output": {
            "scope": entities[boundary_facts["output"].value].name,
            "capacity": {
                "kind": boundary_facts["capacity_kind"].value,
                "maximum": boundary_facts["capacity_maximum"].value,
            },
        },
        "run_boundary": boundary_facts["run_boundary"].value,
        "controls": boundary_facts["controls"].value,
        "sources": boundary_facts["sources"].value,
        "evidence": {
            "confidence": confidence,
            "review": review,
            "reviewer": boundary_facts["reviewer"].value,
            "expires": boundary_facts["expires"].value,
        },
    }
    try:
        record = ProducerBoundary.from_json(
            json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        )
    except (KeyError, ProducerBoundaryFormatError) as exc:
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile does not reconstruct a valid record"
        ) from exc
    expected_entities = {
        _entity_id("producer_boundary", record.id): ("producer_boundary", record.id),
        _entity_id("tool", record.target.binding): ("tool", record.target.binding),
        _entity_id("scope", record.output.scope): ("scope", record.output.scope),
        _entity_id("resource_binding", record.partition.binding): (
            "resource_binding",
            record.partition.binding,
        ),
    }
    if {
        identifier: (entity.kind, entity.name) for identifier, entity in entities.items()
    } != expected_entities:
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile entities do not match the record"
        )
    if (
        boundary_facts["name"].value != record.id
        or boundary_facts["producer"].value != _entity_id("tool", record.target.binding)
        or source.producer_version != record.target.producer_version
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile identity does not match the record"
        )
    expected_values: dict[tuple[str, str], Any] = {
        (boundary_entity.id, "adapter"): {
            "name": record.adapter_name,
            "version": record.adapter_version,
        },
        (boundary_entity.id, "capacity_kind"): record.output.capacity.kind,
        (boundary_entity.id, "capacity_maximum"): record.output.capacity.maximum,
        (boundary_entity.id, "controls"): record.controls.as_dict(),
        (boundary_entity.id, "expires"): record.evidence.expires,
        (boundary_entity.id, "name"): record.id,
        (boundary_entity.id, "output"): _entity_id("scope", record.output.scope),
        (boundary_entity.id, "partition"): _entity_id(
            "resource_binding", record.partition.binding
        ),
        (boundary_entity.id, "partition_argument"): record.partition.argument,
        (boundary_entity.id, "producer"): _entity_id("tool", record.target.binding),
        (boundary_entity.id, "reviewer"): record.evidence.reviewer,
        (boundary_entity.id, "run_boundary"): record.run_boundary.as_dict(),
        (boundary_entity.id, "sources"): [item.as_dict() for item in record.sources],
        (boundary_entity.id, "target"): record.target.as_dict(),
    }
    expected_values.update(
        {
            (entity.id, "name"): entity.name
            for entity in graph.entities
            if entity.kind != "producer_boundary"
        }
    )
    if {key: fact.value for key, fact in facts.items()} != expected_values:
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile facts do not match the record"
        )
    boundary_locations = {
        "adapter": "/adapter",
        "capacity_kind": "/output/capacity/kind",
        "capacity_maximum": "/output/capacity/maximum",
        "controls": "/controls",
        "expires": "/evidence/expires",
        "name": "/id",
        "output": "/output/scope",
        "partition": "/partition/binding",
        "partition_argument": "/partition/argument",
        "producer": "/target/binding",
        "reviewer": "/evidence/reviewer",
        "run_boundary": "/run_boundary",
        "sources": "/sources",
        "target": "/target",
    }
    entity_locations = {
        "resource_binding": "/partition/binding",
        "scope": "/output/scope",
        "tool": "/target/binding",
    }
    if any(
        fact.evidence[0].location
        != (
            boundary_locations[fact.predicate]
            if fact.subject == boundary_entity.id
            else entity_locations[entities[fact.subject].kind]
        )
        for fact in graph.facts
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile evidence locations do not match the record"
        )
    expected_edges = {
        (
            "bounds_producer",
            _entity_id("tool", record.target.binding),
            frozenset(
                _fact_id(boundary_entity.id, item)
                for item in ("producer", "target", "run_boundary")
            ),
        ),
        (
            "bounds_output",
            _entity_id("scope", record.output.scope),
            frozenset(
                _fact_id(boundary_entity.id, item)
                for item in ("output", "capacity_kind", "capacity_maximum")
            ),
        ),
        (
            "partitioned_by",
            _entity_id("resource_binding", record.partition.binding),
            frozenset(
                _fact_id(boundary_entity.id, item)
                for item in ("partition", "partition_argument")
            ),
        ),
    }
    actual_edges = {
        (edge.relation, edge.target, frozenset(edge.support)) for edge in graph.edges
    }
    if actual_edges != expected_edges or any(
        edge.source != boundary_entity.id for edge in graph.edges
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary IR profile relations do not match the record"
        )
    content_digest = hashlib.sha256(record.to_json().encode("utf-8")).hexdigest()
    expected_source_id = _entity_id("source", f"producer-boundary:{record.id}")
    if (
        source.id != expected_source_id
        or source.locator != f"memory:producer-boundary:{record.id}"
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary IR source identity does not match the record"
        )
    if source.content_sha256 != content_digest:
        raise ProducerBoundaryFormatError(
            "producer boundary IR source content_sha256 does not match the record"
        )
    if source.semantic_sha256 != _profile_digest(graph.entities, graph.facts, graph.edges):
        raise ProducerBoundaryFormatError(
            "producer boundary IR source semantic_sha256 does not match the profile"
        )


def analyse_producers(
    mandate: Mandate,
    boundaries: Sequence[ProducerBoundary],
    source_bytes: Mapping[str, bytes],
    selections: Sequence[ProducerSelection] = (),
    *,
    as_of: date,
    depth: int | None = None,
) -> ProducerAnalysis:
    """Apply only current, exact producer bounds to private reachability."""
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise ProducerBoundaryFormatError("producer analysis as_of must be a date")
    if not isinstance(selections, Sequence) or isinstance(selections, (str, bytes)) or any(
        not isinstance(selection, ProducerSelection) for selection in selections
    ):
        raise ProducerBoundaryFormatError(
            "producer analysis selections must contain ProducerSelection records"
        )
    if not isinstance(source_bytes, Mapping) or any(
        not isinstance(locator, str) or not isinstance(content, bytes)
        for locator, content in source_bytes.items()
    ):
        raise ProducerBoundaryFormatError(
            "producer analysis sources must map locators to bytes"
        )
    evaluated_on = as_of.isoformat()
    canonical = tuple(
        ProducerBoundary.from_json(boundary.to_json()) for boundary in boundaries
    )
    graphs = tuple(boundary.to_ir() for boundary in canonical)
    for graph in graphs:
        _validate_producer_profile(graph)

    baseline, _ = _analyse_with_trace(mandate, depth=depth)
    tools = {tool.name: tool for tool in mandate.tools}
    boundary_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    for boundary in canonical:
        boundary_counts[boundary.id] = boundary_counts.get(boundary.id, 0) + 1
        binding = boundary.target.binding
        tool_counts[binding] = tool_counts.get(binding, 0) + 1

    findings: list[ProducerFinding] = []
    applied: list[AppliedProducerBoundary] = []
    caps: dict[str, int] = {}

    def support_for(graph: AuthorityIR) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    *(source.id for source in graph.sources),
                    *(fact.id for fact in graph.facts),
                    *(edge.id for edge in graph.edges),
                }
            )
        )

    def unresolved(
        boundary: ProducerBoundary,
        tool_name: str,
        message: str,
        support: tuple[str, ...],
    ) -> None:
        findings.append(ProducerFinding(boundary.id, tool_name, message, support))

    for boundary, graph in sorted(
        zip(canonical, graphs, strict=True), key=lambda item: item[0].id
    ):
        start = len(findings)
        tool_name = boundary.target.binding
        tool = tools.get(tool_name)
        support = support_for(graph)

        if boundary_counts[boundary.id] != 1:
            unresolved(
                boundary,
                tool_name,
                "producer boundary id is declared more than once",
                support,
            )
        if tool_counts[tool_name] != 1:
            unresolved(
                boundary,
                tool_name,
                "multiple producer boundaries target the same tool",
                support,
            )
        matching_selections = [
            selection
            for selection in selections
            if (
                boundary.target.source,
                boundary.target.binding,
                boundary.target.producer,
                boundary.target.producer_version,
                boundary.partition.argument,
                boundary.partition.binding,
                boundary.output.scope,
            )
            == (
                selection.source,
                selection.binding,
                selection.producer,
                selection.producer_version,
                selection.partition_argument,
                selection.partition_binding,
                selection.output_scope,
            )
        ]
        if len(matching_selections) != 1:
            unresolved(
                boundary,
                tool_name,
                "producer boundary lacks one exact selected deployment and partition",
                support,
            )
        if tool is None:
            unresolved(
                boundary,
                tool_name,
                "producer target tool is not present in the mandate",
                support,
            )
        elif tool.produces != boundary.output.scope or not tool.unbounded:
            unresolved(
                boundary,
                tool_name,
                "producer target is not an unbounded mandate producer of the selected scope",
                support,
            )
        if (
            boundary.run_boundary.inventory_completeness != "complete"
            or tool_name not in boundary.run_boundary.inventory
        ):
            unresolved(
                boundary,
                tool_name,
                "producer selected inventory is not complete for the target",
                support,
            )
        if boundary.run_boundary.release_completeness != "complete":
            unresolved(
                boundary,
                tool_name,
                "producer release classification is not complete",
                support,
            )
        reachable_releasers = set(boundary.run_boundary.release_tools).intersection(
            baseline.reachable_tools
        )
        if reachable_releasers:
            unresolved(
                boundary,
                tool_name,
                "producer capacity has a reachable release transition",
                support,
            )
        competing_producers = {
            item.name
            for item in mandate.tools
            if item.name != tool_name
            and item.name in baseline.reachable_tools
            and item.produces == boundary.output.scope
        }
        if competing_producers:
            unresolved(
                boundary,
                tool_name,
                "producer output has another reachable producer",
                support,
            )
        if (
            boundary.evidence.confidence != "exact"
            or boundary.evidence.review != "accepted"
        ):
            unresolved(
                boundary,
                tool_name,
                "producer evidence is not exact and accepted",
                support,
            )
        if (
            boundary.evidence.reviewer is None
            or boundary.evidence.expires is None
            or boundary.evidence.expires < evaluated_on
        ):
            unresolved(
                boundary,
                tool_name,
                "producer review is missing accountability or expired",
                support,
            )
        try:
            boundary.verify_sources(
                {
                    source.locator: source_bytes[source.locator]
                    for source in boundary.sources
                    if source.locator in source_bytes
                }
            )
        except ProducerBoundaryFormatError:
            unresolved(
                boundary,
                tool_name,
                "producer source bytes failed verification",
                support,
            )

        if len(findings) == start:
            caps[tool_name] = boundary.output.capacity.maximum
            tool_id = _entity_id("tool", tool_name)
            applied_support = tuple(
                sorted(
                    {
                        *support,
                        _fact_id(tool_id, "produces"),
                        _fact_id(tool_id, "unbounded"),
                    }
                )
            )
            applied.append(
                AppliedProducerBoundary(
                    boundary.id,
                    tool_name,
                    boundary.output.scope,
                    boundary.partition.binding,
                    boundary.output.capacity.maximum,
                    applied_support,
                )
            )

    authority, _ = _analyse_with_trace(mandate, depth=depth, producer_caps=caps)
    return ProducerAnalysis(
        authority,
        tuple(dict.fromkeys(findings)),
        tuple(applied),
        evaluated_on,
    )


_IAM_BASE = "docs/evidence/aws-iam-access-keys/"
_IAM_SOURCES = {
    _IAM_BASE + "catalogue.json": (
        "tool-catalogue",
        "upstream-inventory",
        "6ad70d0ecf3d05e8e9e2b08a52e7d2b8099954b586f52c6bd68bc3d99e5cff3c",
    ),
    _IAM_BASE + "capture.json": (
        "producer-outcomes",
        "capacity-controls",
        "199f47e9bc87d39ab129bcd01ab69200326d759e1621cfdc5c5abfa9511fb3c8",
    ),
    _IAM_BASE + "capture.py": (
        "capture-adapter",
        "selected-run-boundary",
        "ace01427863ddeb8880ed1f42ed8e1a8dd6a6cc1fbaeb7c856967708120d0b88",
    ),
}


def _migration_sources(contents: Mapping[str, bytes]) -> tuple[ProducerSource, ...]:
    if not isinstance(contents, Mapping) or any(
        not isinstance(locator, str) for locator in contents
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary migration requires locator-to-bytes sources"
        )
    if set(contents) != set(_IAM_SOURCES):
        missing = sorted(set(_IAM_SOURCES) - set(contents))
        detail = f"; missing locator {missing[0]}" if missing else ""
        raise ProducerBoundaryFormatError(
            f"producer boundary migration source set differs{detail}"
        )
    result = []
    for locator, (kind, role, expected_digest) in _IAM_SOURCES.items():
        content = contents[locator]
        if not isinstance(content, bytes):
            raise ProducerBoundaryFormatError(
                "producer boundary migration source contents must be bytes"
            )
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected_digest:
            raise ProducerBoundaryFormatError(
                f"producer boundary migration source bytes do not match reviewed locator {locator}"
            )
        result.append(ProducerSource(f"source:{role}", kind, role, locator, digest))
    return tuple(sorted(result, key=lambda source: source.id))


def _captured(contents: Mapping[str, bytes], locator: str) -> dict[str, Any]:
    content = contents[locator]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProducerBoundaryFormatError(
            f"producer boundary source {locator} is not UTF-8"
        ) from exc
    value = _load(text, f"producer boundary source {locator}")
    if not isinstance(value, dict):
        raise ProducerBoundaryFormatError(
            f"producer boundary source {locator} must contain an object"
        )
    return value


def migrate_aws_iam_access_key_boundary(
    contents: Mapping[str, bytes],
) -> ProducerBoundary:
    """Migrate the digest-pinned IAM access-key capture into boundary v1."""

    sources = _migration_sources(contents)
    catalogue = _captured(contents, _IAM_BASE + "catalogue.json")
    capture = _captured(contents, _IAM_BASE + "capture.json")
    tools = catalogue.get("tools")
    if not isinstance(tools, list):
        raise ProducerBoundaryFormatError(
            "producer boundary migration catalogue tools must be an array"
        )
    selected = [
        tool
        for tool in tools
        if isinstance(tool, dict) and tool.get("name") == "create_access_key"
    ]
    selected_tool = selected[0] if len(selected) == 1 else {}
    input_schema = selected_tool.get("inputSchema")
    output_schema = selected_tool.get("outputSchema")
    if (
        len(tools) != 29
        or len(selected) != 1
        or not isinstance(input_schema, dict)
        or input_schema.get("required") != ["user_name"]
        or not isinstance(output_schema, dict)
        or output_schema.get("required") != ["result"]
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary migration catalogue does not match the selected producer"
        )
    expected_outcomes = [
        {
            "attempt": 1,
            "authenticated": True,
            "binding": "access-key-1",
            "outcome": "created",
            "status": "Active",
        },
        {
            "attempt": 2,
            "authenticated": True,
            "binding": "access-key-2",
            "outcome": "created",
            "status": "Active",
        },
        {"attempt": 3, "error_code": "LimitExceeded", "outcome": "rejected"},
    ]
    producer = capture.get("producer")
    quota = capture.get("quota")
    if (
        capture.get("capture_version") != 1
        or capture.get("adapter")
        != {"name": "agentmandate.aws-iam-access-key-capture", "version": 1}
        or capture.get("capture_date") != "2026-08-29"
        or capture.get("outcomes") != expected_outcomes
        or capture.get("identity") != {"principal_kind": "iam-user", "same_principal": True}
        or capture.get("cleanup") != {"access_keys": 0, "user_absent": True}
        or capture.get("sanitization")
        != {
            "committed_live_identifiers": False,
            "committed_secret_material": False,
            "raw_credentials_written_to_disk": False,
        }
        or capture.get("deployment")
        != {
            "attached_policies": [],
            "region": "us-east-1",
            "user_path": "/agentmandate-evidence/",
        }
        or producer
        != {
            "mcp_version": "1.23.3",
            "package": "awslabs.iam-mcp-server",
            "package_version": "1.0.11",
            "wheel_sha256": (
                "e48d688f8e338098f410fcabfbedec304f65e63c179bb19001e5b80a2523de16"
            ),
        }
        or quota
        != {"adjustable": False, "kind": "access_keys_per_user", "maximum": 2}
    ):
        raise ProducerBoundaryFormatError(
            "producer boundary migration controls do not match the reviewed evidence"
        )
    outcome_source = "source:capacity-controls"
    migrated = ProducerBoundary(
        PRODUCER_BOUNDARY_VERSION,
        "producer-boundaries/iam-user-access-keys",
        PRODUCER_BOUNDARY_ADAPTER,
        PRODUCER_BOUNDARY_ADAPTER_VERSION,
        ProducerTarget(
            _IAM_BASE + "capture.py",
            "create_access_key",
            producer["package"],
            producer["package_version"],
        ),
        ProducerPartition("user_name", "reviewed-iam-user"),
        ProducerOutput("access_key", ProducerCapacity("concurrent", quota["maximum"])),
        ProducerRunBoundary(("create_access_key",), "complete", (), "complete"),
        ProducerControls(
            AcceptedControl(2, outcome_source, "/outcomes/1"),
            ExhaustedControl(3, "capacity_exhausted", outcome_source, "/outcomes/2"),
        ),
        sources,
        ProducerEvidence("exact", "unreviewed", None, None),
    )
    return ProducerBoundary.from_json(migrated.to_json())
