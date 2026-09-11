"""Shared private records and strict parser for Cedar mapping version 1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

MAPPING_VERSION = 1
COMPLETENESS = frozenset({"complete", "representative"})
CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
REVIEWS = frozenset({"accepted", "contested", "unreviewed"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class CedarBundleFormatError(ValueError):
    """Raised when a Cedar transport or mapping violates its closed contract."""


@dataclass(frozen=True)
class CedarEvidence:
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
class CedarTarget:
    source: str
    agent: str

    def as_dict(self) -> dict[str, str]:
        return {"source": self.source, "agent": self.agent}


@dataclass(frozen=True)
class CedarPrincipalMapping:
    cedar_types: tuple[str, ...]
    mandate_principal: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "cedar_types": list(self.cedar_types),
            "mandate_principal": self.mandate_principal,
        }


@dataclass(frozen=True)
class CedarActionMapping:
    cedar: str
    tool: str

    def as_dict(self) -> dict[str, str]:
        return {"cedar": self.cedar, "tool": self.tool}


@dataclass(frozen=True)
class CedarResourceMapping:
    cedar_type: str
    binding: str

    def as_dict(self) -> dict[str, str]:
        return {"cedar_type": self.cedar_type, "binding": self.binding}


@dataclass(frozen=True)
class CedarRequestDomain:
    completeness: str
    evidence: CedarEvidence

    def as_dict(self) -> dict[str, Any]:
        return {"completeness": self.completeness, "evidence": self.evidence.as_dict()}


@dataclass(frozen=True)
class CedarMapping:
    mapping_version: int
    source: str
    target: CedarTarget
    principal: CedarPrincipalMapping
    actions: tuple[CedarActionMapping, ...]
    resources: tuple[CedarResourceMapping, ...]
    request_domain: CedarRequestDomain

    def as_dict(self) -> dict[str, Any]:
        return {
            "mapping_version": self.mapping_version,
            "source": self.source,
            "target": self.target.as_dict(),
            "principal": self.principal.as_dict(),
            "actions": [item.as_dict() for item in self.actions],
            "resources": [item.as_dict() for item in self.resources],
            "request_domain": self.request_domain.as_dict(),
        }


def _record(
    value: Any, path: str, required: set[str], optional: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CedarBundleFormatError(f"Cedar bundle {path} must be an object")
    allowed = required | (optional or set())
    missing = required - set(value)
    extra = set(value) - allowed
    if missing:
        raise CedarBundleFormatError(
            f"Cedar bundle {path} is missing field '{min(missing)}'"
        )
    if extra:
        raise CedarBundleFormatError(
            f"Cedar bundle {path} has unknown field '{min(extra)}'"
        )
    return value


def _name(raw: dict[str, Any], field: str, path: str) -> str:
    value = raw[field]
    if not isinstance(value, str) or not value or value != value.strip():
        raise CedarBundleFormatError(
            f"Cedar bundle {path}.{field} must be a non-empty stripped string"
        )
    return value


def _integer(raw: dict[str, Any], field: str, path: str) -> int:
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CedarBundleFormatError(f"Cedar bundle {path}.{field} must be a positive integer")
    return value


def _relative(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CedarBundleFormatError(
            f"Cedar bundle {path} must be a non-empty repository-relative POSIX path"
        )
    candidate = PurePosixPath(value)
    if (
        candidate.is_absolute()
        or str(candidate) != value
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise CedarBundleFormatError(
            f"Cedar bundle {path} must be a non-empty repository-relative POSIX path"
        )
    return value


def _strings(value: Any, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CedarBundleFormatError(f"Cedar bundle {path} must be an array of strings")
    if (not allow_empty and not value) or any(not item or item != item.strip() for item in value):
        raise CedarBundleFormatError(
            f"Cedar bundle {path} members must be non-empty and stripped"
        )
    if len(value) != len(set(value)):
        raise CedarBundleFormatError(f"Cedar bundle {path} contains duplicates")
    return tuple(sorted(value))


def _evidence(raw: Any) -> CedarEvidence:
    value = _record(
        raw,
        "mapping.request_domain.evidence",
        {"confidence", "review", "reviewer", "expires"},
    )
    confidence = _name(value, "confidence", "mapping.request_domain.evidence")
    review = _name(value, "review", "mapping.request_domain.evidence")
    if confidence not in CONFIDENCE or review not in REVIEWS:
        raise CedarBundleFormatError("Cedar bundle mapping evidence has an invalid state")
    reviewer = value["reviewer"]
    expires = value["expires"]
    if review == "unreviewed":
        if reviewer is not None or expires is not None:
            raise CedarBundleFormatError(
                "Cedar bundle unreviewed mapping evidence cannot carry reviewer or expiry"
            )
    else:
        if (
            not isinstance(reviewer, str)
            or not reviewer
            or reviewer != reviewer.strip()
        ):
            raise CedarBundleFormatError("Cedar bundle reviewed mapping evidence needs a reviewer")
        if not isinstance(expires, str) or not _DATE.fullmatch(expires):
            raise CedarBundleFormatError("Cedar bundle reviewed mapping evidence needs an expiry")
        try:
            datetime.strptime(expires, "%Y-%m-%d")
        except ValueError as exc:
            raise CedarBundleFormatError(
                "Cedar bundle reviewed mapping evidence needs a canonical expiry"
            ) from exc
    return CedarEvidence(confidence, review, reviewer, expires)


def _mapping(raw: Any) -> CedarMapping:
    value = _record(
        raw,
        "mapping",
        {
            "mapping_version",
            "source",
            "target",
            "principal",
            "actions",
            "resources",
            "request_domain",
        },
    )
    version = _integer(value, "mapping_version", "mapping")
    if version != MAPPING_VERSION:
        raise CedarBundleFormatError(
            f"unsupported Cedar mapping version {version}; this build reads {MAPPING_VERSION}"
        )
    target = _record(value["target"], "mapping.target", {"source", "agent"})
    principal = _record(
        value["principal"], "mapping.principal", {"cedar_types", "mandate_principal"}
    )
    actions = _pairs(value["actions"], "actions", "cedar", "tool", CedarActionMapping)
    resources = _pairs(
        value["resources"], "resources", "cedar_type", "binding", CedarResourceMapping
    )
    domain = _record(
        value["request_domain"], "mapping.request_domain", {"completeness", "evidence"}
    )
    completeness = _name(domain, "completeness", "mapping.request_domain")
    if completeness not in COMPLETENESS:
        raise CedarBundleFormatError(
            "Cedar bundle mapping.request_domain.completeness has an invalid value"
        )
    return CedarMapping(
        version,
        _relative(value["source"], "mapping.source"),
        CedarTarget(
            _relative(target["source"], "mapping.target.source"),
            _name(target, "agent", "mapping.target"),
        ),
        CedarPrincipalMapping(
            _strings(principal["cedar_types"], "mapping.principal.cedar_types", allow_empty=False),
            _name(principal, "mandate_principal", "mapping.principal"),
        ),
        actions,
        resources,
        CedarRequestDomain(completeness, _evidence(domain["evidence"])),
    )


def _pairs(raw: Any, path: str, left: str, right: str, cls: Any) -> tuple[Any, ...]:
    if not isinstance(raw, list) or not raw:
        raise CedarBundleFormatError(f"Cedar bundle mapping.{path} must be a non-empty array")
    result = []
    for index, item in enumerate(raw):
        item_path = f"mapping.{path}[{index}]"
        value = _record(item, item_path, {left, right})
        result.append(cls(_name(value, left, item_path), _name(value, right, item_path)))
    lefts = [getattr(item, left) for item in result]
    if len(lefts) != len(set(lefts)):
        raise CedarBundleFormatError(f"Cedar bundle mapping.{path} contains conflicting members")
    return tuple(sorted(result, key=lambda item: (getattr(item, left), getattr(item, right))))
