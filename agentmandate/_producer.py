"""Private records for evidence-backed finite producer boundaries.

The reader proves structure and caller-supplied byte identity only. It does not
narrow reachability, project Authority IR, or treat migration as review.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

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


class ProducerBoundaryFormatError(ValueError):
    """Raised when a private producer-boundary artifact is malformed."""


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
