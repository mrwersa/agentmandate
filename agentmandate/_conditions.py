"""Experimental records for condition contexts and delegation grants.

Gates 2a and 2b of the conditions-and-delegation contract: strict external
context and grant readers, private tool-side condition and structured-principal
records, their closed Authority IR projections, and private trust consumers.
Nothing is exported from :mod:`agentmandate`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from ._ir import (
    IR_VERSION,
    AuthorityIR,
    Edge,
    Entity,
    Fact,
    IRFormatError,
    Source,
    _edge_id,
    _entity_id,
    _fact_id,
)
from ._ir import Evidence as IREvidence
from .manifest import EFFECT_RANK, Mandate
from .reach import Authority, _analyse_with_trace

if TYPE_CHECKING:
    from ._inventory import InventoryReconciliation
    from .drift import Drift
    from .inventory import Inventory

CONDITION_CONTEXT_VERSION = 1
GRANT_VERSION = 1
TOOL_CONDITION_VERSION = 1
TOOL_PRINCIPAL_VERSION = 1
CONDITION_PREDICATES = frozenset({"dispatch_target", "statement_class"})
CONTEXT_COMPLETENESS = frozenset({"complete", "representative"})
CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
REVIEWS = frozenset({"accepted", "contested", "unreviewed"})
GRANT_EFFECTS = frozenset({"irreversible", "read", "write"})
CONDITION_EFFECTS = frozenset({"read", "write"})
_CONTEXT_ROOT_FIELDS = {
    "context_version",
    "id",
    "target",
    "domain",
    "completeness",
    "evidence",
    "source",
}
_GRANT_ROOT_FIELDS = {
    "grant_version",
    "id",
    "grantor",
    "subject",
    "actor",
    "audience",
    "surface",
    "issued",
    "expires",
    "evidence",
    "source",
}
_TOOL_CONDITION_ROOT_FIELDS = {
    "condition_version",
    "id",
    "target",
    "predicate",
    "arg",
    "class",
    "effect",
    "context",
    "evidence",
}
_TOOL_PRINCIPAL_ROOT_FIELDS = {
    "principal_version",
    "id",
    "target",
    "principal",
    "evidence",
}
CONDITION_ADAPTER = "agentmandate.tool-condition"
CONDITION_ADAPTER_VERSION = 1
PRINCIPAL_ADAPTER = "agentmandate.tool-principal"
PRINCIPAL_ADAPTER_VERSION = 1
PRINCIPAL_KINDS = frozenset(
    {"delegated_user", "fixed_user_credential", "intersecting"}
)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ConditionFormatError(ValueError):
    """Raised when an experimental condition or grant artifact cannot be read."""


@dataclass(frozen=True)
class ConditionFinding:
    """Why one reviewed narrowing could not safely be applied."""

    condition: str
    tool: str
    message: str


@dataclass(frozen=True)
class AppliedCondition:
    """One effective narrowing and its replayable artifact provenance."""

    condition: str
    context: str
    tool: str
    default_effect: str
    effective_effect: str
    support: tuple[str, ...]


@dataclass(frozen=True)
class ConditionalAnalysis:
    """Private Gate 3 result: ordinary authority plus trust decisions."""

    authority: Authority
    findings: tuple[ConditionFinding, ...]
    applied: tuple[AppliedCondition, ...]
    as_of: str


@dataclass(frozen=True)
class ConditionalDrift:
    """Private Gate 3b result joining source drift and condition decisions."""

    drift: Drift
    analysis: ConditionalAnalysis

    @property
    def clean(self) -> bool:
        return self.drift.clean and not self.analysis.findings


def _reject_constant(_: str) -> None:
    raise ValueError


def _load_json(text: str, label: str) -> Any:
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ConditionFormatError(
            f"{label} is not valid JSON at line {exc.lineno} column {exc.colno}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ConditionFormatError(f"{label} contains a non-canonical value") from exc


def _record(
    raw: Any, path: str, required: set[str], optional: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConditionFormatError(f"condition contract {path} must be an object")
    optional = optional or set()
    missing = sorted(required - raw.keys())
    if missing:
        raise ConditionFormatError(
            f"condition contract {path} is missing field {missing[0]!r}"
        )
    extra = sorted(raw.keys() - required - optional)
    if extra:
        raise ConditionFormatError(
            f"condition contract {path} has unknown field {extra[0]!r}"
        )
    return raw


def _string(raw: dict[str, Any], field: str, path: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise ConditionFormatError(f"condition contract {path}.{field} must be a string")
    return value


def _nonempty_string(raw: dict[str, Any], field: str, path: str) -> str:
    value = _string(raw, field, path)
    if not value:
        raise ConditionFormatError(
            f"condition contract {path}.{field} must not be empty"
        )
    return value


def _canonical_date(raw: dict[str, Any], field: str, path: str) -> str:
    value = _string(raw, field, path)
    if not _ISO_DATE.fullmatch(value):
        raise ConditionFormatError(
            f"condition contract {path}.{field} must be a canonical ISO date"
        )
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ConditionFormatError(
            f"condition contract {path}.{field} is not a real calendar date"
        ) from exc
    return value


def _relative_path(raw: dict[str, Any], field: str, path: str) -> str:
    value = _string(raw, field, path)
    if (
        not value
        or "\\" in value
        or value.startswith("/")
        or ".." in value.replace("\\", "/").split("/")
    ):
        raise ConditionFormatError(
            f"condition contract {path}.{field} must be a non-empty "
            "repository-relative POSIX path"
        )
    return value


def _digest_string(raw: dict[str, Any], field: str, path: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ConditionFormatError(
            f"condition contract {path}.{field} must be lowercase SHA-256"
        )
    return value


def _canonical_members(
    values: Any, path: str, label: str, allowed: frozenset[str] | None = None
) -> tuple[str, ...]:
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ConditionFormatError(
            f"condition contract {path}.{label} must be an array of strings"
        )
    if not values or any(not v or v != v.strip() for v in values):
        raise ConditionFormatError(
            f"condition contract {path}.{label} members must be non-empty and "
            "stripped"
        )
    if len(values) != len(set(values)):
        raise ConditionFormatError(
            f"condition contract {path}.{label} contains duplicate members"
        )
    if allowed is not None:
        invalid = [v for v in values if v not in allowed]
        if invalid:
            raise ConditionFormatError(
                f"condition contract {path}.{label} contains a value outside "
                "the closed vocabulary"
            )
    return tuple(sorted(values))


@dataclass(frozen=True)
class Evidence:
    """Review state for one artifact. Reviewer and expiry stand or fall together."""

    confidence: str
    review: str
    reviewer: str | None = None
    expires: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "confidence": self.confidence,
            "review": self.review,
            "reviewer": self.reviewer,
            "expires": self.expires,
        }


def _evidence(raw: dict[str, Any], path: str) -> Evidence:
    raw = _record(
        raw,
        f"{path}.evidence",
        {"confidence", "review"},
        {"reviewer", "expires"},
    )
    confidence = _string(raw, "confidence", path)
    if confidence not in CONFIDENCE:
        raise ConditionFormatError(
            f"condition contract {path}.evidence.confidence has an invalid value"
        )
    review = _string(raw, "review", path)
    if review not in REVIEWS:
        raise ConditionFormatError(
            f"condition contract {path}.evidence.review has an invalid value"
        )
    reviewer = raw.get("reviewer")
    expires = raw.get("expires")
    # Dynamic-inventory rule: unreviewed evidence carries neither field;
    # reviewed evidence requires both, so accountability is never partial.
    if review == "unreviewed":
        if reviewer is not None or expires is not None:
            raise ConditionFormatError(
                f"condition contract {path}.evidence must not name a reviewer "
                "or expiry while unreviewed"
            )
        return Evidence(confidence=confidence, review=review)
    if reviewer is None or expires is None:
        raise ConditionFormatError(
            f"condition contract {path}.evidence requires a reviewer and an "
            "expiry once it is reviewed"
        )
    if not isinstance(reviewer, str):
        raise ConditionFormatError(
            f"condition contract {path}.evidence.reviewer must be a string"
        )
    _canonical_date(raw, "expires", path)
    return Evidence(confidence=confidence, review=review, reviewer=reviewer, expires=expires)


@dataclass(frozen=True)
class ContextSource:
    """Provenance for the captured bytes behind a condition context."""

    kind: str
    locator: str
    producer_version: str | None
    content_sha256: str | None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind,
            "locator": self.locator,
            "producer_version": self.producer_version,
            "content_sha256": self.content_sha256,
        }
        return {key: value for key, value in result.items() if value is not None}


@dataclass(frozen=True)
class ConditionContext:
    """A reviewed domain record that lets one predicate narrow one tool."""

    version: int
    id: str
    target_source: str
    target_binding: str
    predicate: str
    arg: str
    classifier: str
    classifier_version: str
    dialect: str | None
    classes: tuple[str, ...]
    completeness: str
    evidence: Evidence
    source: ContextSource | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "context_version": self.version,
            "id": self.id,
            "target": {"source": self.target_source, "binding": self.target_binding},
            "domain": {
                "predicate": self.predicate,
                "arg": self.arg,
                "classifier": self.classifier,
                "classifier_version": self.classifier_version,
                "classes": list(self.classes),
                **({"dialect": self.dialect} if self.dialect is not None else {}),
            },
            "completeness": self.completeness,
            "evidence": self.evidence.as_dict(),
        }
        if self.source is not None:
            result["source"] = self.source.as_dict()
        return result

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def verify_source(self, content: bytes) -> None:
        if not isinstance(content, bytes):
            raise ConditionFormatError(
                "condition contract context.verify_source requires bytes"
            )
        if self.source is None or self.source.content_sha256 is None:
            raise ConditionFormatError(
                "condition contract context declares no content digest to verify"
            )
        if self.source.content_sha256 != hashlib.sha256(content).hexdigest():
            raise ConditionFormatError(
                "condition contract context source.content_sha256 does not match "
                "the supplied bytes"
            )

    @classmethod
    def from_json(cls, text: str) -> ConditionContext:
        raw = _record(
            _load_json(text, "condition context"),
            "context",
            set(),
            _CONTEXT_ROOT_FIELDS,
        )
        version = raw.get("context_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ConditionFormatError(
                "condition contract context_version must be an integer; this "
                f"build reads {CONDITION_CONTEXT_VERSION}"
            )
        if version != CONDITION_CONTEXT_VERSION:
            raise ConditionFormatError(
                f"unsupported condition context version {version}; this build "
                f"reads {CONDITION_CONTEXT_VERSION}"
            )
        body = _record(
            raw,
            "context",
            {"id", "target", "domain", "completeness", "evidence"},
            {"context_version", "source", "dialect"},
        )

        target = _record(body["target"], "context.target", {"source", "binding"})
        target_source = _relative_path(target, "source", "context.target")
        binding = _nonempty_string(target, "binding", "context.target")

        domain_raw = _record(
            body["domain"],
            "context.domain",
            {"predicate", "arg", "classifier", "classifier_version", "classes"},
            {"dialect"},
        )
        predicate = _string(domain_raw, "predicate", "context.domain")
        if predicate not in CONDITION_PREDICATES:
            raise ConditionFormatError(
                "condition contract context.domain.predicate has an invalid value"
            )
        arg = _nonempty_string(domain_raw, "arg", "context.domain")
        classifier = _nonempty_string(domain_raw, "classifier", "context.domain")
        classifier_version = _nonempty_string(
            domain_raw, "classifier_version", "context.domain"
        )
        dialect_value = domain_raw.get("dialect")
        if dialect_value is not None and not isinstance(dialect_value, str):
            raise ConditionFormatError(
                "condition contract context.domain.dialect must be a string"
            )
        if predicate == "statement_class":
            # unchanged guard below
            if dialect_value is None:
                raise ConditionFormatError(
                    "condition contract context.domain.dialect is required for "
                    "statement_class predicates"
                )
            if not dialect_value:
                raise ConditionFormatError(
                    "condition contract context.domain.dialect must not be empty"
                )
        classes = _canonical_members(
            domain_raw["classes"], "context.domain", "classes"
        )

        completeness = _string(body, "completeness", "context")
        if completeness not in CONTEXT_COMPLETENESS:
            raise ConditionFormatError(
                "condition contract context.completeness has an invalid value"
            )
        evidence = _evidence(body["evidence"], "context")

        context_source: ContextSource | None = None
        if "source" in body:
            source_raw = _record(
                body["source"],
                "context.source",
                {"kind", "locator"},
                {"producer_version", "content_sha256"},
            )
            context_source = ContextSource(
                kind=_nonempty_string(source_raw, "kind", "context.source"),
                locator=_relative_path(source_raw, "locator", "context.source"),
                producer_version=source_raw.get("producer_version"),
                content_sha256=_digest_string(
                    source_raw, "content_sha256", "context.source"
                ),
            )
            producer = context_source.producer_version
            if producer is not None and not isinstance(producer, str):
                raise ConditionFormatError(
                    "condition contract context.source.producer_version must be "
                    "a string or null"
                )

        return cls(
            version=version,
            id=_nonempty_string(body, "id", "context"),
            target_source=target_source,
            target_binding=binding,
            predicate=predicate,
            arg=arg,
            classifier=classifier,
            classifier_version=classifier_version,
            dialect=dialect_value if isinstance(dialect_value, str) else None,
            classes=classes,
            completeness=completeness,
            evidence=evidence,
            source=context_source,
        )


@dataclass(frozen=True)
class Grant:
    """The reviewed authority surface a subject conferred on one actor."""

    version: int
    id: str
    grantor: str
    subject: str
    actor: str
    audience: str
    scopes: tuple[str, ...]
    tools: tuple[str, ...]
    effects: tuple[str, ...]
    issued: str
    expires: str
    evidence: Evidence
    source: ContextSource | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "grant_version": self.version,
            "id": self.id,
            "grantor": self.grantor,
            "subject": self.subject,
            "actor": self.actor,
            "audience": self.audience,
            "surface": {
                "scopes": list(self.scopes),
                "tools": list(self.tools),
                "effects": list(self.effects),
            },
            "issued": self.issued,
            "expires": self.expires,
            "evidence": self.evidence.as_dict(),
        }
        if self.source is not None:
            result["source"] = self.source.as_dict()
        return result

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def verify_source(self, content: bytes) -> None:
        if not isinstance(content, bytes):
            raise ConditionFormatError(
                "condition contract grant.verify_source requires bytes"
            )
        if self.source is None or self.source.content_sha256 is None:
            raise ConditionFormatError(
                "condition contract grant declares no content digest to verify"
            )
        if self.source.content_sha256 != hashlib.sha256(content).hexdigest():
            raise ConditionFormatError(
                "condition contract grant source.content_sha256 does not match "
                "the supplied bytes"
            )

    @classmethod
    def from_json(cls, text: str) -> Grant:
        raw = _record(
            _load_json(text, "grant"), "grant", set(), _GRANT_ROOT_FIELDS
        )
        version = raw.get("grant_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ConditionFormatError(
                "condition contract grant_version must be an integer; this "
                f"build reads {GRANT_VERSION}"
            )
        if version != GRANT_VERSION:
            raise ConditionFormatError(
                f"unsupported grant version {version}; this build reads "
                f"{GRANT_VERSION}"
            )
        body = _record(
            raw,
            "grant",
            {
                "id", "grantor", "subject", "actor", "audience", "surface",
                "issued", "expires", "evidence",
            },
            {"grant_version", "source"},
        )

        identifier = _nonempty_string(body, "id", "grant")
        grantor = _nonempty_string(body, "grantor", "grant")
        subject = _nonempty_string(body, "subject", "grant")
        actor = _nonempty_string(body, "actor", "grant")
        audience = _nonempty_string(body, "audience", "grant")
        issued = _canonical_date(body, "issued", "grant")
        expires = _canonical_date(body, "expires", "grant")
        if issued > expires:
            raise ConditionFormatError(
                "condition contract grant.issued must not be after grant.expires"
            )

        surface = _record(
            body["surface"],
            "grant.surface",
            {"effects", "scopes", "tools"},
        )
        # The effect set is the single source of truth for irreversible
        # authority; there is no separate boolean to disagree with it.
        effects = _canonical_members(
            surface["effects"], "grant.surface", "effects", allowed=GRANT_EFFECTS
        )
        scopes = _canonical_members(surface["scopes"], "grant.surface", "scopes")
        tools = _canonical_members(surface["tools"], "grant.surface", "tools")

        evidence = _evidence(body["evidence"], "grant")

        grant_source: ContextSource | None = None
        if "source" in body:
            source_raw = _record(
                body["source"],
                "grant.source",
                {"kind", "locator"},
                {"producer_version", "content_sha256"},
            )
            grant_source = ContextSource(
                kind=_nonempty_string(source_raw, "kind", "grant.source"),
                locator=_relative_path(source_raw, "locator", "grant.source"),
                producer_version=source_raw.get("producer_version"),
                content_sha256=_digest_string(
                    source_raw, "content_sha256", "grant.source"
                ),
            )
            producer = grant_source.producer_version
            if producer is not None and not isinstance(producer, str):
                raise ConditionFormatError(
                    "condition contract grant.source.producer_version must be "
                    "a string or null"
                )

        return cls(
            version=version,
            id=identifier,
            grantor=grantor,
            subject=subject,
            actor=actor,
            audience=audience,
            scopes=scopes,
            tools=tools,
            effects=effects,
            issued=issued,
            expires=expires,
            evidence=evidence,
            source=grant_source,
        )


@dataclass(frozen=True)
class ToolTarget:
    """Repository binding and reviewed tool name addressed by a record."""

    source: str
    binding: str
    tool: str

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "binding": self.binding, "tool": self.tool}


@dataclass(frozen=True)
class ToolCondition:
    """One reviewed conditional narrowing attached to one tool."""

    version: int
    id: str
    target: ToolTarget
    predicate: str
    arg: str
    value_class: str
    effect: str
    context: str
    evidence: Evidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "condition_version": self.version,
            "id": self.id,
            "target": self.target.as_dict(),
            "predicate": self.predicate,
            "arg": self.arg,
            "class": self.value_class,
            "effect": self.effect,
            "context": self.context,
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return _canonical_json(self.as_dict())

    def to_ir(self) -> AuthorityIR:
        return _condition_to_ir(self)

    @classmethod
    def from_json(cls, text: str) -> ToolCondition:
        raw = _record(
            _load_json(text, "tool condition"),
            "tool_condition",
            _TOOL_CONDITION_ROOT_FIELDS,
        )
        version = _version(
            raw, "condition_version", "tool_condition", TOOL_CONDITION_VERSION
        )
        predicate = _closed_string(
            raw,
            "predicate",
            "tool_condition",
            CONDITION_PREDICATES,
        )
        effect = _closed_string(
            raw,
            "effect",
            "tool_condition",
            CONDITION_EFFECTS,
        )
        return cls(
            version=version,
            id=_canonical_name(raw, "id", "tool_condition"),
            target=_tool_target(raw["target"], "tool_condition.target"),
            predicate=predicate,
            arg=_canonical_name(raw, "arg", "tool_condition"),
            value_class=_canonical_name(raw, "class", "tool_condition"),
            effect=effect,
            context=_canonical_name(raw, "context", "tool_condition"),
            evidence=_evidence(raw["evidence"], "tool_condition"),
        )


@dataclass(frozen=True)
class ToolPrincipal:
    """One reviewed structured principal attached to one tool."""

    version: int
    id: str
    target: ToolTarget
    kind: str
    evidence: Evidence
    actor: str | None = None
    audience: str | None = None
    subject: str | None = None
    grant: str | None = None
    expires: str | None = None
    principals: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        principal: dict[str, Any] = {"kind": self.kind}
        for field in ("actor", "audience", "subject", "grant", "expires"):
            value = getattr(self, field)
            if value is not None:
                principal[field] = value
        if self.principals:
            principal["principals"] = list(self.principals)
        return {
            "principal_version": self.version,
            "id": self.id,
            "target": self.target.as_dict(),
            "principal": principal,
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return _canonical_json(self.as_dict())

    def to_ir(self) -> AuthorityIR:
        return _principal_to_ir(self)

    @classmethod
    def from_json(cls, text: str) -> ToolPrincipal:
        raw = _record(
            _load_json(text, "tool principal"),
            "tool_principal",
            _TOOL_PRINCIPAL_ROOT_FIELDS,
        )
        version = _version(
            raw, "principal_version", "tool_principal", TOOL_PRINCIPAL_VERSION
        )
        principal = _record(
            raw["principal"],
            "tool_principal.principal",
            {"kind"},
            {"actor", "audience", "subject", "grant", "expires", "principals"},
        )
        kind = _closed_string(
            principal,
            "kind",
            "tool_principal.principal",
            PRINCIPAL_KINDS,
        )
        values = _principal_values(principal, kind)
        return cls(
            version=version,
            id=_canonical_name(raw, "id", "tool_principal"),
            target=_tool_target(raw["target"], "tool_principal.target"),
            kind=kind,
            evidence=_evidence(raw["evidence"], "tool_principal"),
            **values,
        )


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ) + "\n"


def _version(
    raw: dict[str, Any], field: str, path: str, supported: int
) -> int:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConditionFormatError(
            f"condition contract {path}.{field} must be an integer; this build reads {supported}"
        )
    if value != supported:
        raise ConditionFormatError(
            f"unsupported condition contract version {value}; this build reads {supported}"
        )
    return value


def _closed_string(
    raw: dict[str, Any], field: str, path: str, allowed: frozenset[str]
) -> str:
    value = _string(raw, field, path)
    if value not in allowed:
        raise ConditionFormatError(
            f"condition contract {path}.{field} has an invalid value"
        )
    return value


def _canonical_name(raw: dict[str, Any], field: str, path: str) -> str:
    value = _nonempty_string(raw, field, path)
    if value != value.strip():
        raise ConditionFormatError(
            f"condition contract {path}.{field} must be stripped"
        )
    return value


def _tool_target(raw: Any, path: str) -> ToolTarget:
    value = _record(raw, path, {"source", "binding", "tool"})
    return ToolTarget(
        source=_relative_path(value, "source", path),
        binding=_canonical_name(value, "binding", path),
        tool=_canonical_name(value, "tool", path),
    )


def _principal_values(raw: dict[str, Any], kind: str) -> dict[str, Any]:
    fields = set(raw) - {"kind"}
    if kind == "intersecting":
        if fields != {"principals"}:
            raise ConditionFormatError(
                "condition contract intersecting principal requires only principals"
            )
        principals = _canonical_members(
            raw["principals"], "tool_principal.principal", "principals"
        )
        if len(principals) < 2:
            raise ConditionFormatError(
                "condition contract intersecting principal requires at least two principals"
            )
        return {"principals": principals}
    required = (
        {"actor", "audience"}
        if kind == "fixed_user_credential"
        else {"subject", "actor", "audience", "grant", "expires"}
    )
    if fields != required:
        raise ConditionFormatError(
            f"condition contract {kind} principal has an invalid field set"
        )
    result = {
        field: _canonical_name(raw, field, "tool_principal.principal")
        for field in required
    }
    if kind == "delegated_user":
        result["expires"] = _canonical_date(
            raw, "expires", "tool_principal.principal"
        )
    return result


def _ir_evidence(source_id: str, location: str, evidence: Evidence) -> tuple[IREvidence, ...]:
    return (
        IREvidence(
            source=source_id,
            location=location,
            confidence=evidence.confidence,
            review=evidence.review,
        ),
    )


def _profile_digest(
    entities: tuple[Entity, ...], facts: tuple[Fact, ...], edges: tuple[Edge, ...]
) -> str:
    body = {
        "entities": [item.as_dict() for item in sorted(entities, key=lambda item: item.id)],
        "facts": [item.as_dict() for item in sorted(facts, key=lambda item: item.id)],
        "edges": [item.as_dict() for item in sorted(edges, key=lambda item: item.id)],
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _fact(
    subject: str,
    predicate: str,
    value: Any,
    source_id: str,
    location: str,
    evidence: Evidence,
) -> Fact:
    return Fact(
        _fact_id(subject, predicate),
        subject,
        predicate,
        value,
        _ir_evidence(source_id, location, evidence),
    )


def _condition_to_ir(value: ToolCondition) -> AuthorityIR:
    source_id = _entity_id("source", f"tool-condition:{value.id}")
    tool_id = _entity_id("tool", value.target.tool)
    condition_id = _entity_id("condition", value.id)
    context_id = _entity_id("context", value.context)
    effect_id = _entity_id("effect", value.effect)
    entities = (
        Entity(tool_id, "tool", value.target.tool),
        Entity(condition_id, "condition", value.id),
        Entity(context_id, "context", value.context),
        Entity(effect_id, "effect", value.effect),
    )
    facts = (
        _fact(tool_id, "name", value.target.tool, source_id, "/target/tool", value.evidence),
        _fact(tool_id, "target", value.target.as_dict(), source_id, "/target", value.evidence),
        _fact(tool_id, "conditions", [condition_id], source_id, "/id", value.evidence),
        _fact(condition_id, "name", value.id, source_id, "/id", value.evidence),
        _fact(condition_id, "predicate", value.predicate, source_id, "/predicate", value.evidence),
        _fact(condition_id, "arg", value.arg, source_id, "/arg", value.evidence),
        _fact(condition_id, "class", value.value_class, source_id, "/class", value.evidence),
        _fact(condition_id, "effect", effect_id, source_id, "/effect", value.evidence),
        _fact(condition_id, "context", context_id, source_id, "/context", value.evidence),
        _fact(
            condition_id,
            "reviewer",
            value.evidence.reviewer,
            source_id,
            "/evidence/reviewer",
            value.evidence,
        ),
        _fact(
            condition_id,
            "review_expires",
            value.evidence.expires,
            source_id,
            "/evidence/expires",
            value.evidence,
        ),
        _fact(context_id, "name", value.context, source_id, "/context", value.evidence),
        _fact(effect_id, "name", value.effect, source_id, "/effect", value.evidence),
    )
    edges = (
        Edge(
            _edge_id(tool_id, "has_condition", condition_id),
            tool_id,
            "has_condition",
            condition_id,
            (_fact_id(tool_id, "conditions"),),
        ),
        Edge(
            _edge_id(condition_id, "narrows_to", effect_id),
            condition_id,
            "narrows_to",
            effect_id,
            (_fact_id(condition_id, "effect"),),
        ),
        Edge(
            _edge_id(condition_id, "uses_context", context_id),
            condition_id,
            "uses_context",
            context_id,
            (_fact_id(condition_id, "context"),),
        ),
    )
    graph = AuthorityIR(
        IR_VERSION,
        (
            Source(
                source_id,
                "tool-condition",
                f"memory:tool-condition:{value.id}",
                value.version,
                None,
                _profile_digest(entities, facts, edges),
                CONDITION_ADAPTER,
                CONDITION_ADAPTER_VERSION,
                hashlib.sha256(value.to_json().encode("utf-8")).hexdigest(),
            ),
        ),
        entities,
        facts,
        edges,
    )
    _validate_condition_profile(graph)
    return graph


def _principal_to_ir(value: ToolPrincipal) -> AuthorityIR:
    source_id = _entity_id("source", f"tool-principal:{value.id}")
    tool_id = _entity_id("tool", value.target.tool)
    principal_id = _entity_id("principal", value.id)
    entities: list[Entity] = [
        Entity(tool_id, "tool", value.target.tool),
        Entity(principal_id, "principal", value.id),
    ]
    facts: list[Fact] = [
        _fact(tool_id, "name", value.target.tool, source_id, "/target/tool", value.evidence),
        _fact(tool_id, "target", value.target.as_dict(), source_id, "/target", value.evidence),
        _fact(tool_id, "principal", principal_id, source_id, "/id", value.evidence),
        _fact(principal_id, "name", value.id, source_id, "/id", value.evidence),
        _fact(principal_id, "kind", value.kind, source_id, "/principal/kind", value.evidence),
        _fact(
            principal_id,
            "reviewer",
            value.evidence.reviewer,
            source_id,
            "/evidence/reviewer",
            value.evidence,
        ),
        _fact(
            principal_id,
            "review_expires",
            value.evidence.expires,
            source_id,
            "/evidence/expires",
            value.evidence,
        ),
    ]
    edges: list[Edge] = [
        Edge(
            _edge_id(tool_id, "acts_as", principal_id),
            tool_id,
            "acts_as",
            principal_id,
            (_fact_id(tool_id, "principal"),),
        )
    ]
    if value.kind == "intersecting":
        member_ids = [_entity_id("principal", name) for name in value.principals]
        facts.append(
            _fact(
                principal_id,
                "principals",
                member_ids,
                source_id,
                "/principal/principals",
                value.evidence,
            )
        )
        for index, (name, member_id) in enumerate(
            zip(value.principals, member_ids, strict=True)
        ):
            entities.append(Entity(member_id, "principal", name))
            facts.append(
                _fact(
                    member_id,
                    "name",
                    name,
                    source_id,
                    f"/principal/principals/{index}",
                    value.evidence,
                )
            )
            edges.append(
                Edge(
                    _edge_id(principal_id, "constrained_by", member_id),
                    principal_id,
                    "constrained_by",
                    member_id,
                    (_fact_id(principal_id, "principals"),),
                )
            )
    else:
        for field in ("actor", "audience", "subject", "expires"):
            item = getattr(value, field)
            if item is not None:
                facts.append(
                    _fact(
                        principal_id,
                        field,
                        item,
                        source_id,
                        f"/principal/{field}",
                        value.evidence,
                    )
                )
        if value.grant is not None:
            grant_id = _entity_id("grant", value.grant)
            entities.append(Entity(grant_id, "grant", value.grant))
            facts.extend(
                (
                    _fact(
                        principal_id,
                        "grant",
                        grant_id,
                        source_id,
                        "/principal/grant",
                        value.evidence,
                    ),
                    _fact(
                        grant_id,
                        "name",
                        value.grant,
                        source_id,
                        "/principal/grant",
                        value.evidence,
                    ),
                )
            )
            edges.append(
                Edge(
                    _edge_id(principal_id, "under_grant", grant_id),
                    principal_id,
                    "under_grant",
                    grant_id,
                    (_fact_id(principal_id, "grant"),),
                )
            )
    entity_tuple = tuple(entities)
    fact_tuple = tuple(facts)
    edge_tuple = tuple(edges)
    graph = AuthorityIR(
        IR_VERSION,
        (
            Source(
                source_id,
                "tool-principal",
                f"memory:tool-principal:{value.id}",
                value.version,
                None,
                _profile_digest(entity_tuple, fact_tuple, edge_tuple),
                PRINCIPAL_ADAPTER,
                PRINCIPAL_ADAPTER_VERSION,
                hashlib.sha256(value.to_json().encode("utf-8")).hexdigest(),
            ),
        ),
        entity_tuple,
        fact_tuple,
        edge_tuple,
    )
    _validate_principal_profile(graph)
    return graph


def analyse_conditions(
    mandate: Mandate,
    conditions: Sequence[ToolCondition],
    contexts: Sequence[ConditionContext],
    source_bytes: Mapping[str, bytes],
    *,
    as_of: date,
    depth: int | None = None,
) -> ConditionalAnalysis:
    """Apply only fully reviewed, complete conditional narrowings.

    Every record is serialized, strictly reread, projected, and profile-checked
    at this consumption boundary. Any trust or context uncertainty retains the
    manifest's strongest declared effect and becomes a named finding.
    """
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise ConditionFormatError("conditional analysis as_of must be a date")
    evaluated_on = as_of.isoformat()
    canonical_conditions = tuple(
        ToolCondition.from_json(item.to_json()) for item in conditions
    )
    canonical_contexts = tuple(
        ConditionContext.from_json(item.to_json()) for item in contexts
    )
    condition_graphs = {
        item.id: item.to_ir() for item in canonical_conditions
    }
    for graph in condition_graphs.values():
        _validate_condition_profile(graph)

    context_groups: dict[str, list[ConditionContext]] = {}
    for context in canonical_contexts:
        context_groups.setdefault(context.id, []).append(context)
    condition_counts: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    for condition in canonical_conditions:
        condition_counts[condition.id] = condition_counts.get(condition.id, 0) + 1
        tool_counts[condition.target.tool] = tool_counts.get(condition.target.tool, 0) + 1

    tools = {tool.name: tool for tool in mandate.tools}
    effective = dict(tools)
    findings: list[ConditionFinding] = []
    applied: list[AppliedCondition] = []

    def unresolved(condition: ToolCondition, message: str) -> None:
        findings.append(
            ConditionFinding(condition.id, condition.target.tool, message)
        )

    for condition in sorted(canonical_conditions, key=lambda item: item.id):
        tool = tools.get(condition.target.tool)
        if tool is None:
            unresolved(condition, "target tool is not present in the mandate")
            continue
        if condition_counts[condition.id] != 1:
            unresolved(condition, "condition id is declared more than once")
            continue
        if tool_counts[condition.target.tool] != 1:
            unresolved(condition, "multiple conditions target the same tool")
            continue
        matches = context_groups.get(condition.context, [])
        if len(matches) != 1:
            unresolved(
                condition,
                "condition context is missing or declared more than once",
            )
            continue
        context = matches[0]
        if (
            condition.target.source != context.target_source
            or condition.target.binding != context.target_binding
            or condition.predicate != context.predicate
            or condition.arg != context.arg
        ):
            unresolved(condition, "condition and context operands do not match")
            continue
        if condition.evidence.confidence != "exact" or condition.evidence.review != "accepted":
            unresolved(condition, "condition evidence is not exact and accepted")
            continue
        if context.evidence.confidence != "exact" or context.evidence.review != "accepted":
            unresolved(condition, "context evidence is not exact and accepted")
            continue
        if (
            condition.evidence.expires is None
            or context.evidence.expires is None
            or condition.evidence.expires < evaluated_on
            or context.evidence.expires < evaluated_on
        ):
            unresolved(condition, "condition or context review is expired")
            continue
        if context.completeness != "complete":
            unresolved(condition, "condition context is not complete")
            continue
        if context.classes != (condition.value_class,):
            unresolved(
                condition,
                "condition context does not exclusively admit the selected class",
            )
            continue
        if EFFECT_RANK[condition.effect] >= EFFECT_RANK[tool.effect]:
            unresolved(condition, "condition does not attenuate the declared effect")
            continue
        captured = source_bytes.get(context.id)
        if captured is None:
            unresolved(condition, "reviewed context capture bytes were not supplied")
            continue
        try:
            context.verify_source(captured)
        except ConditionFormatError:
            unresolved(condition, "reviewed context capture bytes failed verification")
            continue

        graph = condition_graphs[condition.id]
        support = tuple(
            sorted(
                {
                    graph.sources[0].id,
                    *(
                        fact.id
                        for fact in graph.facts
                        if fact.predicate
                        in {
                            "arg",
                            "class",
                            "context",
                            "effect",
                            "predicate",
                            "review_expires",
                            "reviewer",
                            "target",
                        }
                    ),
                    f"context:{context.id}#/completeness",
                    f"context:{context.id}#/domain/classes",
                    f"context:{context.id}#/evidence",
                    f"context:{context.id}#/source/content_sha256",
                }
            )
        )
        effective[tool.name] = replace(tool, effect=condition.effect)
        applied.append(
            AppliedCondition(
                condition.id,
                context.id,
                tool.name,
                tool.effect,
                condition.effect,
                support,
            )
        )

    adjusted = replace(
        mandate,
        tools=tuple(effective[tool.name] for tool in mandate.tools),
    )
    authority, _ = _analyse_with_trace(adjusted, depth=depth)
    return ConditionalAnalysis(
        authority=authority,
        findings=tuple(findings),
        applied=tuple(applied),
        as_of=evaluated_on,
    )


def reconcile_condition_drift(
    mandate: Mandate,
    inventory: Inventory,
    conditions: Sequence[ToolCondition],
    contexts: Sequence[ConditionContext],
    source_bytes: Mapping[str, bytes],
    *,
    as_of: date,
    depth: int | None = None,
    dynamic: InventoryReconciliation | None = None,
) -> ConditionalDrift:
    """Reconcile conditional authority against one live source inventory.

    The analysis is computed here rather than accepted from a caller, so a
    result derived from another mandate or source cannot be attached to this
    drift report. Source mismatch affects condition eligibility only; it does
    not suppress the independent tool-removal checks in ordinary drift.
    """
    from .drift import compare

    canonical_conditions = tuple(
        ToolCondition.from_json(item.to_json()) for item in conditions
    )
    # Structural projection and its closed profile are rechecked even for a
    # record whose source target later proves ineligible.
    for condition in canonical_conditions:
        _validate_condition_profile(condition.to_ir())

    selected = inventory.selected
    live_tools = {item.name for item in inventory.declarations}
    if dynamic is not None:
        live_tools.update(dynamic.members)

    candidates: list[ToolCondition] = []
    source_findings: list[ConditionFinding] = []
    failed_tools: set[str] = set()
    for condition in sorted(canonical_conditions, key=lambda item: item.id):
        if selected is None:
            message = (
                "source inventory does not identify one selected binding; "
                "select one with --binding rather than --union-bindings"
            )
        elif (
            condition.target.source != selected.module
            or condition.target.binding != selected.label
        ):
            message = "condition target does not match the selected source binding"
        elif condition.target.tool not in live_tools:
            message = "condition target tool is not present in the reconciled source inventory"
        else:
            candidates.append(condition)
            continue
        failed_tools.add(condition.target.tool)
        source_findings.append(
            ConditionFinding(condition.id, condition.target.tool, message)
        )

    eligible: list[ToolCondition] = []
    for condition in candidates:
        if condition.target.tool not in failed_tools:
            eligible.append(condition)
            continue
        source_findings.append(
            ConditionFinding(
                condition.id,
                condition.target.tool,
                "another condition targeting this tool failed source reconciliation",
            )
        )

    analysis = analyse_conditions(
        mandate,
        eligible,
        contexts,
        source_bytes,
        as_of=as_of,
        depth=depth,
    )
    # Duplicate record IDs can produce identical trust failures. Drift names
    # the collision once while preserving distinct failures and target tools.
    findings = tuple(dict.fromkeys((*source_findings, *analysis.findings)))
    combined = replace(analysis, findings=findings)
    return ConditionalDrift(
        drift=compare(mandate, inventory, dynamic=dynamic),
        analysis=combined,
    )


def _validate_condition_profile(graph: AuthorityIR) -> None:
    _validate_projection_source(
        graph, "tool-condition", CONDITION_ADAPTER, CONDITION_ADAPTER_VERSION
    )
    entities = {entity.id: entity for entity in graph.entities}
    counts = {
        kind: sum(entity.kind == kind for entity in graph.entities)
        for kind in {"tool", "condition", "context", "effect"}
    }
    if counts != {"tool": 1, "condition": 1, "context": 1, "effect": 1}:
        raise ConditionFormatError("condition IR profile has unsupported entities")
    predicates = {
        entity.id: {
            "tool": {"name", "target", "conditions"},
            "condition": {
                "name", "predicate", "arg", "class", "effect", "context",
                "reviewer", "review_expires",
            },
            "context": {"name"},
            "effect": {"name"},
        }[entity.kind]
        for entity in graph.entities
    }
    _validate_projection_facts(graph, entities, predicates)
    condition = next(entity for entity in graph.entities if entity.kind == "condition")
    tool = next(entity for entity in graph.entities if entity.kind == "tool")
    facts = {(fact.subject, fact.predicate): fact for fact in graph.facts}
    predicate = facts[(condition.id, "predicate")].value
    effect = facts[(condition.id, "effect")].value
    effect_entity = entities.get(effect)
    if (
        not isinstance(predicate, str)
        or predicate not in CONDITION_PREDICATES
        or not isinstance(effect, str)
        or effect_entity is None
        or effect_entity.name not in CONDITION_EFFECTS
    ):
        raise ConditionFormatError("condition IR profile has an invalid closed value")
    target = _tool_target(facts[(tool.id, "target")].value, "condition_IR.target")
    if target.tool != tool.name:
        raise ConditionFormatError("condition IR profile target does not match tool")
    _validate_projected_evidence(graph, condition.id, facts)


def _validate_principal_profile(graph: AuthorityIR) -> None:
    _validate_projection_source(
        graph, "tool-principal", PRINCIPAL_ADAPTER, PRINCIPAL_ADAPTER_VERSION
    )
    entities = {entity.id: entity for entity in graph.entities}
    if any(entity.kind not in {"tool", "principal", "grant"} for entity in graph.entities):
        raise ConditionFormatError("principal IR profile has unsupported entities")
    facts = {(fact.subject, fact.predicate): fact for fact in graph.facts}
    roots = [
        entity
        for entity in graph.entities
        if entity.kind == "principal" and (entity.id, "kind") in facts
    ]
    if len(roots) != 1:
        raise ConditionFormatError("principal IR profile requires one structured principal")
    tools = [entity for entity in graph.entities if entity.kind == "tool"]
    if len(tools) != 1:
        raise ConditionFormatError("principal IR profile requires one tool")
    root = roots[0]
    kind = facts[(root.id, "kind")].value
    expected = {
        "fixed_user_credential": {
            "name", "kind", "actor", "audience", "reviewer", "review_expires"
        },
        "intersecting": {
            "name", "kind", "principals", "reviewer", "review_expires"
        },
        "delegated_user": {
            "name", "kind", "subject", "actor", "audience", "grant", "expires",
            "reviewer", "review_expires",
        },
    }
    if not isinstance(kind, str) or kind not in expected:
        raise ConditionFormatError("principal IR profile has an invalid kind")
    predicates = {
        entity.id: (
            {"name", "target", "principal"}
            if entity.kind == "tool"
            else {"name"}
            if entity.kind == "grant" or entity.id != root.id
            else expected[kind]
        )
        for entity in graph.entities
    }
    _validate_projection_facts(graph, entities, predicates)
    target = _tool_target(facts[(tools[0].id, "target")].value, "principal_IR.target")
    if target.tool != tools[0].name:
        raise ConditionFormatError("principal IR profile target does not match tool")
    _validate_projected_evidence(graph, root.id, facts)
    if kind == "intersecting":
        members = facts[(root.id, "principals")].value
        if (
            not isinstance(members, list)
            or len(members) < 2
            or any(not isinstance(item, str) for item in members)
        ):
            raise ConditionFormatError("principal IR profile has an invalid intersection")
        member_entities = {
            entity.id
            for entity in graph.entities
            if entity.kind == "principal" and entity.id != root.id
        }
        if set(members) != member_entities or len(members) != len(member_entities):
            raise ConditionFormatError("principal IR profile members do not match entities")
    elif kind == "delegated_user":
        expires = facts[(root.id, "expires")].value
        try:
            _canonical_date({"expires": expires}, "expires", "principal_IR")
        except ConditionFormatError as exc:
            raise ConditionFormatError(
                "principal IR profile has an invalid expiry"
            ) from exc
        grants = [entity for entity in graph.entities if entity.kind == "grant"]
        if len(grants) != 1 or facts[(root.id, "grant")].value != grants[0].id:
            raise ConditionFormatError("principal IR profile grant does not match entity")
    elif any(entity.kind == "grant" for entity in graph.entities):
        raise ConditionFormatError("principal IR profile has an unexpected grant")


def _validate_projection_source(
    graph: AuthorityIR, kind: str, adapter: str, adapter_version: int
) -> None:
    try:
        graph.validate()
    except IRFormatError as exc:
        raise ConditionFormatError("condition contract IR profile is structurally invalid") from exc
    if len(graph.sources) != 1:
        raise ConditionFormatError("condition contract IR profile requires one source")
    source = graph.sources[0]
    if (
        source.kind != kind
        or source.format_version != 1
        or source.adapter != adapter
        or source.adapter_version != adapter_version
    ):
        raise ConditionFormatError("condition contract IR profile has an unsupported source")
    if (
        source.content_sha256 is None
        or len(source.content_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source.content_sha256)
    ):
        raise ConditionFormatError("condition contract IR source digest is invalid")
    digest = _profile_digest(graph.entities, graph.facts, graph.edges)
    if source.semantic_sha256 != digest:
        raise ConditionFormatError("condition contract IR semantic digest does not match")


def _validate_projection_facts(
    graph: AuthorityIR,
    entities: dict[str, Entity],
    predicates: dict[str, set[str]],
) -> None:
    actual: dict[str, set[str]] = {entity.id: set() for entity in graph.entities}
    source_id = graph.sources[0].id
    evidence_state: tuple[str, str] | None = None
    for fact in graph.facts:
        allowed = predicates.get(fact.subject, set())
        if fact.predicate not in allowed:
            raise ConditionFormatError("condition contract IR profile has an unsupported predicate")
        actual[fact.subject].add(fact.predicate)
        if len(fact.evidence) != 1 or fact.evidence[0].source != source_id:
            raise ConditionFormatError("condition contract IR profile has unsupported evidence")
        state = (fact.evidence[0].confidence, fact.evidence[0].review)
        if evidence_state is None:
            evidence_state = state
        elif state != evidence_state:
            raise ConditionFormatError("condition contract IR facts disagree on evidence state")
        if fact.predicate == "name" and fact.value != entities[fact.subject].name:
            raise ConditionFormatError("condition contract IR entity name does not match")
    for entity in graph.entities:
        expected = predicates[entity.id]
        if actual[entity.id] != expected:
            raise ConditionFormatError("condition contract IR profile is incomplete")


def _validate_projected_evidence(
    graph: AuthorityIR, subject: str, facts: dict[tuple[str, str], Fact]
) -> None:
    first = graph.facts[0].evidence[0]
    raw: dict[str, Any] = {
        "confidence": first.confidence,
        "review": first.review,
    }
    reviewer = facts[(subject, "reviewer")].value
    expires = facts[(subject, "review_expires")].value
    if reviewer is not None:
        raw["reviewer"] = reviewer
    if expires is not None:
        raw["expires"] = expires
    _evidence(raw, "IR")
