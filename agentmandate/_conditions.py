"""Experimental records for condition contexts and delegation grants.

Gate 2a of the conditions-and-delegation contract: the two external
artifacts (condition contexts and grants) with strict typed-error readers,
canonical serialization, and captured-byte verification against caller-
supplied bytes only.  Tool-side condition and structured-principal records,
their IR projection, and registered relations follow in gate 2b/3.  Nothing
in this module decides eligibility and nothing is exported from
:mod:`agentmandate`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

CONDITION_CONTEXT_VERSION = 1
GRANT_VERSION = 1
CONDITION_PREDICATES = frozenset({"dispatch_target", "statement_class"})
CONTEXT_COMPLETENESS = frozenset({"complete", "representative"})
CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
REVIEWS = frozenset({"accepted", "contested", "unreviewed"})
GRANT_EFFECTS = frozenset({"irreversible", "read", "write"})
_CONTEXT_ROOT_FIELDS = {
    "context_version",
    "target",
    "domain",
    "completeness",
    "evidence",
    "source",
}
_GRANT_ROOT_FIELDS = {
    "grant_version",
    "id",
    "subject",
    "actor",
    "audience",
    "surface",
    "issued",
    "expires",
    "evidence",
    "source",
}
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ConditionFormatError(ValueError):
    """Raised when an experimental condition or grant artifact cannot be read."""


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
            {"target", "domain", "completeness", "evidence"},
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
            {"id", "subject", "actor", "audience", "surface", "issued", "expires", "evidence"},
            {"grant_version", "source"},
        )

        identifier = _nonempty_string(body, "id", "grant")
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
