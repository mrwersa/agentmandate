"""Private records for digest-pinned Cedar policy capture bundles.

The reader proves record structure and captured-byte identity.  It does not
parse Cedar, reproduce a decision, trust a deployment mapping, or make a
bundle eligible for authority analysis.
"""

from __future__ import annotations

import hashlib
import json
import re
from base64 import b64decode
from binascii import Error as Base64Error
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

BUNDLE_VERSION = 1
MAPPING_VERSION = 1
SOURCE_KINDS = frozenset(
    {
        "deployment_mapping",
        "entities",
        "implementation_lock",
        "native_output",
        "policy_set",
        "request",
        "schema",
    }
)
REQUIRED_SOURCE_KINDS = frozenset(
    {"entities", "implementation_lock", "native_output", "policy_set", "request", "schema"}
)
DECISIONS = frozenset({"allow", "deny"})
COMPLETENESS = frozenset({"complete", "representative"})
CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
REVIEWS = frozenset({"accepted", "contested", "unreviewed"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class CedarBundleFormatError(ValueError):
    """Raised when a Cedar bundle violates its closed transport contract."""


@dataclass(frozen=True)
class CedarImplementation:
    language_version: str
    sdk_version: str
    implementation: str
    implementation_version: str
    package_integrity: str

    def as_dict(self) -> dict[str, str]:
        return {
            "language_version": self.language_version,
            "sdk_version": self.sdk_version,
            "implementation": self.implementation,
            "implementation_version": self.implementation_version,
            "package_integrity": self.package_integrity,
        }


@dataclass(frozen=True)
class CedarAdapter:
    name: str
    version: int

    def as_dict(self) -> dict[str, str | int]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True)
class CedarSource:
    kind: str
    locator: str
    content_sha256: str
    origin: str | None
    origin_revision: str | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "content_sha256": self.content_sha256,
            "origin": self.origin,
            "origin_revision": self.origin_revision,
        }


@dataclass(frozen=True)
class CedarValidation:
    source: str
    location: str
    status: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "location": self.location,
            "status": self.status,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class CedarDecision:
    id: str
    request: str
    source: str
    location: str
    decision: str
    determining_policies: tuple[str, ...]
    error_policies: tuple[str, ...]
    schema_checked: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request": self.request,
            "source": self.source,
            "location": self.location,
            "decision": self.decision,
            "determining_policies": list(self.determining_policies),
            "error_policies": list(self.error_policies),
            "schema_checked": self.schema_checked,
        }


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


@dataclass(frozen=True)
class CedarBundle:
    bundle_version: int
    cedar: CedarImplementation
    adapter: CedarAdapter
    sources: tuple[CedarSource, ...]
    validation: CedarValidation
    decisions: tuple[CedarDecision, ...]
    mapping: CedarMapping | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_version": self.bundle_version,
            "cedar": self.cedar.as_dict(),
            "adapter": self.adapter.as_dict(),
            "sources": [source.as_dict() for source in self.sources],
            "validation": self.validation.as_dict(),
            "decisions": [decision.as_dict() for decision in self.decisions],
            "mapping": None if self.mapping is None else self.mapping.as_dict(),
        }

    def to_json(self) -> str:
        """Return deterministic JSON suitable for committed fixtures."""
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def verify_sources(self, contents: Mapping[str, bytes]) -> None:
        """Verify caller-supplied bytes without resolving source locators."""
        if not isinstance(contents, Mapping):
            raise CedarBundleFormatError("Cedar source contents must be a locator mapping")
        expected = {source.locator for source in self.sources}
        if set(contents) != expected:
            raise CedarBundleFormatError(
                "Cedar source bytes do not match the bundle's declared locators"
            )
        for source in self.sources:
            content = contents[source.locator]
            if not isinstance(content, bytes):
                raise CedarBundleFormatError(
                    f"Cedar source content for {source.locator} must be bytes"
                )
            if hashlib.sha256(content).hexdigest() != source.content_sha256:
                raise CedarBundleFormatError(
                    f"Cedar source content for {source.locator} does not match its digest"
                )

    @classmethod
    def from_json(cls, text: str) -> CedarBundle:
        """Read a bundle through one strict, value-safe error boundary."""

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
            raise CedarBundleFormatError(f"Cedar bundle is not valid JSON{detail}") from exc
        if not isinstance(raw, dict):
            raise CedarBundleFormatError("Cedar bundle root must be an object")
        if "bundle_version" not in raw:
            raise CedarBundleFormatError("Cedar bundle root is missing field 'bundle_version'")
        version = raw["bundle_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise CedarBundleFormatError(
                f"unsupported Cedar bundle version type; this build reads {BUNDLE_VERSION}"
            )
        if version != BUNDLE_VERSION:
            raise CedarBundleFormatError(
                f"unsupported Cedar bundle version {version}; this build reads {BUNDLE_VERSION}"
            )
        root = _record(
            raw,
            "root",
            {"bundle_version", "cedar", "adapter", "sources", "validation", "decisions", "mapping"},
        )
        sources = _sources(root["sources"])
        source_kinds = {source.locator: source.kind for source in sources}
        validation = _validation(root["validation"])
        decisions = _decisions(root["decisions"])
        mapping = None if root["mapping"] is None else _mapping(root["mapping"])
        _references(source_kinds, validation, decisions, mapping)
        return cls(
            bundle_version=version,
            cedar=_implementation(root["cedar"]),
            adapter=_adapter(root["adapter"]),
            sources=sources,
            validation=validation,
            decisions=decisions,
            mapping=mapping,
        )


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


def _pointer(value: Any, path: str) -> str:
    if not isinstance(value, str) or (value and not value.startswith("/")):
        raise CedarBundleFormatError(f"Cedar bundle {path} must be a JSON Pointer")
    if re.search(r"~(?:[^01]|$)", value):
        raise CedarBundleFormatError(f"Cedar bundle {path} must be a JSON Pointer")
    return value


def _digest(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CedarBundleFormatError(f"Cedar bundle {path} must be lowercase SHA-256")
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


def _implementation(raw: Any) -> CedarImplementation:
    value = _record(
        raw,
        "cedar",
        {
            "language_version",
            "sdk_version",
            "implementation",
            "implementation_version",
            "package_integrity",
        },
    )
    integrity = _name(value, "package_integrity", "cedar")
    try:
        integrity_bytes = b64decode(integrity.removeprefix("sha512-"), validate=True)
    except (Base64Error, ValueError) as exc:
        raise CedarBundleFormatError(
            "Cedar bundle cedar.package_integrity must be npm SHA-512 SRI"
        ) from exc
    if not integrity.startswith("sha512-") or len(integrity_bytes) != 64:
        raise CedarBundleFormatError("Cedar bundle cedar.package_integrity must be npm SHA-512 SRI")
    return CedarImplementation(
        _name(value, "language_version", "cedar"),
        _name(value, "sdk_version", "cedar"),
        _name(value, "implementation", "cedar"),
        _name(value, "implementation_version", "cedar"),
        integrity,
    )


def _adapter(raw: Any) -> CedarAdapter:
    value = _record(raw, "adapter", {"name", "version"})
    return CedarAdapter(_name(value, "name", "adapter"), _integer(value, "version", "adapter"))


def _sources(raw: Any) -> tuple[CedarSource, ...]:
    if not isinstance(raw, list) or not raw:
        raise CedarBundleFormatError("Cedar bundle sources must be a non-empty array")
    result: list[CedarSource] = []
    for index, item in enumerate(raw):
        path = f"sources[{index}]"
        value = _record(
            item, path, {"kind", "locator", "content_sha256", "origin", "origin_revision"}
        )
        kind = _name(value, "kind", path)
        if kind not in SOURCE_KINDS:
            raise CedarBundleFormatError(f"Cedar bundle {path}.kind has an invalid value")
        origin = value["origin"]
        revision = value["origin_revision"]
        if origin is not None and (
            not isinstance(origin, str) or not origin or origin != origin.strip()
        ):
            raise CedarBundleFormatError(f"Cedar bundle {path}.origin must be null or non-empty")
        if revision is not None and (
            not isinstance(revision, str) or not revision or revision != revision.strip()
        ):
            raise CedarBundleFormatError(
                f"Cedar bundle {path}.origin_revision must be null or non-empty"
            )
        result.append(
            CedarSource(
                kind,
                _relative(value["locator"], f"{path}.locator"),
                _digest(value["content_sha256"], f"{path}.content_sha256"),
                origin,
                revision,
            )
        )
    locators = [source.locator for source in result]
    if len(locators) != len(set(locators)):
        raise CedarBundleFormatError("Cedar bundle sources contain duplicate locators")
    missing_kinds = REQUIRED_SOURCE_KINDS - {source.kind for source in result}
    if missing_kinds:
        raise CedarBundleFormatError(
            f"Cedar bundle sources are missing required kind '{min(missing_kinds)}'"
        )
    return tuple(sorted(result, key=lambda source: source.locator))


def _validation(raw: Any) -> CedarValidation:
    value = _record(raw, "validation", {"source", "location", "status", "errors", "warnings"})
    status = _name(value, "status", "validation")
    if status not in {"failure", "success"}:
        raise CedarBundleFormatError("Cedar bundle validation.status has an invalid value")
    errors = _strings(value["errors"], "validation.errors")
    if status == "success" and errors:
        raise CedarBundleFormatError("Cedar bundle successful validation cannot carry errors")
    if status == "failure" and not errors:
        raise CedarBundleFormatError("Cedar bundle failed validation must carry errors")
    return CedarValidation(
        _relative(value["source"], "validation.source"),
        _pointer(value["location"], "validation.location"),
        status,
        errors,
        _strings(value["warnings"], "validation.warnings"),
    )


def _decisions(raw: Any) -> tuple[CedarDecision, ...]:
    if not isinstance(raw, list) or not raw:
        raise CedarBundleFormatError("Cedar bundle decisions must be a non-empty array")
    result: list[CedarDecision] = []
    for index, item in enumerate(raw):
        path = f"decisions[{index}]"
        value = _record(
            item,
            path,
            {
                "id",
                "request",
                "source",
                "location",
                "decision",
                "determining_policies",
                "error_policies",
                "schema_checked",
            },
        )
        decision = _name(value, "decision", path)
        if decision not in DECISIONS:
            raise CedarBundleFormatError(f"Cedar bundle {path}.decision has an invalid value")
        schema_checked = value["schema_checked"]
        if not isinstance(schema_checked, bool):
            raise CedarBundleFormatError(f"Cedar bundle {path}.schema_checked must be a boolean")
        result.append(
            CedarDecision(
                _name(value, "id", path),
                _relative(value["request"], f"{path}.request"),
                _relative(value["source"], f"{path}.source"),
                _pointer(value["location"], f"{path}.location"),
                decision,
                _strings(value["determining_policies"], f"{path}.determining_policies"),
                _strings(value["error_policies"], f"{path}.error_policies"),
                schema_checked,
            )
        )
    ids = [decision.id for decision in result]
    if len(ids) != len(set(ids)):
        raise CedarBundleFormatError("Cedar bundle decisions contain duplicate ids")
    return tuple(sorted(result, key=lambda decision: decision.id))


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


def _references(
    kinds: dict[str, str],
    validation: CedarValidation,
    decisions: tuple[CedarDecision, ...],
    mapping: CedarMapping | None,
) -> None:
    if kinds.get(validation.source) != "native_output":
        raise CedarBundleFormatError(
            "Cedar bundle validation must reference a declared native_output source"
        )
    for index, decision in enumerate(decisions):
        if kinds.get(decision.request) != "request":
            raise CedarBundleFormatError(
                f"Cedar bundle decisions[{index}] must reference a declared request source"
            )
        if kinds.get(decision.source) != "native_output":
            raise CedarBundleFormatError(
                f"Cedar bundle decisions[{index}] must reference a declared native_output source"
            )
    if mapping is not None and kinds.get(mapping.source) != "deployment_mapping":
        raise CedarBundleFormatError(
            "Cedar bundle mapping must reference a declared deployment_mapping source"
        )
