"""Experimental records for reviewed dynamic inventory declarations.

The reader proves structure and captured-byte identity only.  It deliberately
does not decide whether evidence is exact, accepted, complete, or current, and
nothing in this module is exported from :mod:`agentmandate`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from typing import Any

INVENTORY_VERSION = 1
BOUNDARY_KINDS = frozenset({"deployment", "factory", "provider", "registry"})
SELECTION_KEYS = frozenset(
    {"configuration", "environment", "provider", "region", "skills", "tenant", "toolsets"}
)
COMPLETENESS = frozenset({"complete", "partial", "unknown"})
CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
REVIEWS = frozenset({"accepted", "contested", "unreviewed"})


class InventoryFormatError(ValueError):
    """Raised when a dynamic inventory declaration cannot be read safely."""


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
