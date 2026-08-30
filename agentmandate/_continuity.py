"""Private Gate 2a records for authority-continuity evidence.

The two provider profiles intentionally remain distinct.  This module parses
and canonicalises reviewed transport records and verifies caller-supplied
bytes; it does not infer continuity outcomes or expose a public format.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

CONTINUITY_BINDING_VERSION = 1
AGENTCORE_CONTINUITY_VERSION = 1
ANTHROPIC_CONTINUITY_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_CONFIDENCE = frozenset({"exact", "heuristic", "unknown"})
_REVIEW = frozenset({"accepted", "contested", "unreviewed"})
_MEDIATION = frozenset({"platform_verified", "exclusive_adapter", "unestablished"})
_TRANSITIONS = frozenset(
    {
        "fresh_session",
        "configuration_revision",
        "limit_revision",
        "delegation_handoff",
        "concurrent_dispatch",
        "same_boundary",
    }
)
_OUTCOMES = frozenset(
    {"allow", "deny", "stale_session", "budget_reached", "rejected_before_network"}
)


class ContinuityFormatError(ValueError):
    """Raised when a private continuity artifact is malformed."""


def _reject_constant(_: str) -> None:
    raise ValueError


def _load(text: str, label: str) -> Any:
    try:
        return json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ContinuityFormatError(
            f"{label} is not valid JSON at line {exc.lineno} column {exc.colno}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ContinuityFormatError(f"{label} contains a non-canonical value") from exc


def _record(
    value: Any, path: str, required: set[str], optional: set[str] | None = None
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContinuityFormatError(f"continuity contract {path} must be an object")
    optional = optional or set()
    missing = sorted(required - value.keys())
    if missing:
        raise ContinuityFormatError(f"continuity contract {path} is missing field {missing[0]!r}")
    extra = sorted(value.keys() - required - optional)
    if extra:
        raise ContinuityFormatError(f"continuity contract {path} has unknown field {extra[0]!r}")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContinuityFormatError(
            f"continuity contract {path} must be a non-empty stripped string"
        )
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContinuityFormatError(
            f"continuity contract {path} must be an integer of at least {minimum}"
        )
    return value


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ContinuityFormatError(f"continuity contract {path} must be a boolean")
    return value


def _digest(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ContinuityFormatError(f"continuity contract {path} must be lowercase SHA-256")
    return value


def _date(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ContinuityFormatError(f"continuity contract {path} must be a canonical ISO date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ContinuityFormatError(
            f"continuity contract {path} is not a real calendar date"
        ) from exc
    return value


def _utc(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ContinuityFormatError(f"continuity contract {path} must be canonical UTC")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContinuityFormatError(f"continuity contract {path} is not a real timestamp") from exc
    return value


def _path(value: Any, path: str) -> str:
    value = _string(value, path)
    if value.startswith("/") or "\\" in value or ".." in value.split("/"):
        raise ContinuityFormatError(
            f"continuity contract {path} must be a repository-relative POSIX path"
        )
    return value


def _strings(
    value: Any,
    path: str,
    allowed: frozenset[str] | None = None,
    *,
    unique: bool = True,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ContinuityFormatError(f"continuity contract {path} must be a non-empty array")
    result = tuple(_string(item, f"{path}[]") for item in value)
    if unique and len(result) != len(set(result)):
        raise ContinuityFormatError(f"continuity contract {path} contains duplicates")
    if allowed is not None and any(item not in allowed for item in result):
        raise ContinuityFormatError(f"continuity contract {path} has an invalid value")
    return result


@dataclass(frozen=True)
class ContinuityEvidence:
    confidence: str
    review: str
    reviewer: str | None
    expires: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "review": self.review,
            "reviewer": self.reviewer,
            "expires": self.expires,
        }


def _evidence(value: Any, path: str) -> ContinuityEvidence:
    raw = _record(value, path, {"confidence", "review", "reviewer", "expires"})
    confidence = _string(raw["confidence"], f"{path}.confidence")
    review = _string(raw["review"], f"{path}.review")
    if confidence not in _CONFIDENCE or review not in _REVIEW:
        raise ContinuityFormatError(f"continuity contract {path} has an invalid evidence state")
    reviewer = raw["reviewer"]
    expires = raw["expires"]
    if review == "unreviewed":
        if reviewer is not None or expires is not None:
            raise ContinuityFormatError(
                f"continuity contract {path} cannot carry accountability while unreviewed"
            )
        return ContinuityEvidence(confidence, review, None, None)
    reviewer = _string(reviewer, f"{path}.reviewer")
    expires = _date(expires, f"{path}.expires")
    return ContinuityEvidence(confidence, review, reviewer, expires)


@dataclass(frozen=True)
class ContinuitySource:
    id: str
    kind: str
    locator: str
    content_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind,
            "locator": self.locator,
            "content_sha256": self.content_sha256,
        }


def _sources(value: Any, path: str) -> tuple[ContinuitySource, ...]:
    if not isinstance(value, list) or not value:
        raise ContinuityFormatError(f"continuity contract {path} must be a non-empty array")
    result = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        raw = _record(item, item_path, {"id", "kind", "locator", "content_sha256"})
        result.append(
            ContinuitySource(
                _string(raw["id"], f"{item_path}.id"),
                _string(raw["kind"], f"{item_path}.kind"),
                _path(raw["locator"], f"{item_path}.locator"),
                _digest(raw["content_sha256"], f"{item_path}.content_sha256"),
            )
        )
    ids = [source.id for source in result]
    locators = [source.locator for source in result]
    if len(ids) != len(set(ids)) or len(locators) != len(set(locators)):
        raise ContinuityFormatError(f"continuity contract {path} has duplicate identities")
    return tuple(sorted(result, key=lambda source: source.id))


def _verify_sources(sources: tuple[ContinuitySource, ...], contents: dict[str, bytes]) -> None:
    if not isinstance(contents, dict) or any(
        not isinstance(key, str) or not isinstance(value, bytes) for key, value in contents.items()
    ):
        raise ContinuityFormatError("continuity source verification requires locator-to-bytes")
    expected = {source.locator for source in sources}
    if set(contents) != expected:
        missing = sorted(expected - set(contents))
        extra = sorted(set(contents) - expected)
        locator = (missing or extra)[0]
        raise ContinuityFormatError(f"continuity source set does not match locator {locator}")
    for source in sources:
        if hashlib.sha256(contents[source.locator]).hexdigest() != source.content_sha256:
            raise ContinuityFormatError(
                f"continuity source bytes do not match locator {source.locator}"
            )


@dataclass(frozen=True)
class ContinuityBinding:
    version: int
    adapter_name: str
    adapter_version: int
    id: str
    mandate_sha256: str
    principal: str
    provider: str
    boundary_kind: str
    binding: str
    policy_sha256: str
    issued_at: str
    expires_at: str
    derivation_algorithm: str
    boundary_alias: str
    signature_algorithm: str
    mediation: str
    sources: tuple[ContinuitySource, ...]
    evidence: ContinuityEvidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "continuity_binding_version": self.version,
            "adapter": {"name": self.adapter_name, "version": self.adapter_version},
            "id": self.id,
            "mandate": {"sha256": self.mandate_sha256, "principal": self.principal},
            "enforcement": {
                "provider": self.provider,
                "boundary_kind": self.boundary_kind,
                "binding": self.binding,
                "policy_sha256": self.policy_sha256,
            },
            "validity": {"issued_at": self.issued_at, "expires_at": self.expires_at},
            "derivation": {
                "algorithm": self.derivation_algorithm,
                "boundary_alias": self.boundary_alias,
            },
            "signature": {"algorithm": self.signature_algorithm},
            "mediation": {"kind": self.mediation},
            "sources": [source.as_dict() for source in self.sources],
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    def verify_sources(self, contents: dict[str, bytes]) -> None:
        _verify_sources(self.sources, contents)

    @classmethod
    def from_json(cls, text: str) -> ContinuityBinding:
        raw = _record(
            _load(text, "continuity binding"),
            "binding",
            {
                "continuity_binding_version",
                "adapter",
                "id",
                "mandate",
                "enforcement",
                "validity",
                "derivation",
                "signature",
                "mediation",
                "sources",
                "evidence",
            },
        )
        version = _integer(raw["continuity_binding_version"], "binding.version", minimum=1)
        if version != CONTINUITY_BINDING_VERSION:
            raise ContinuityFormatError(
                f"unsupported continuity binding version {version}; this build reads 1"
            )
        adapter_name, adapter_version = _adapter(
            raw["adapter"], "binding.adapter", "agentmandate.continuity-binding"
        )
        mandate = _record(raw["mandate"], "binding.mandate", {"sha256", "principal"})
        enforcement = _record(
            raw["enforcement"],
            "binding.enforcement",
            {"provider", "boundary_kind", "binding", "policy_sha256"},
        )
        validity = _record(raw["validity"], "binding.validity", {"issued_at", "expires_at"})
        issued = _utc(validity["issued_at"], "binding.validity.issued_at")
        expires = _utc(validity["expires_at"], "binding.validity.expires_at")
        if issued >= expires:
            raise ContinuityFormatError("continuity contract binding validity must be half-open")
        derivation = _record(
            raw["derivation"], "binding.derivation", {"algorithm", "boundary_alias"}
        )
        signature = _record(raw["signature"], "binding.signature", {"algorithm"})
        derivation_algorithm = _string(derivation["algorithm"], "binding.derivation.algorithm")
        signature_algorithm = _string(signature["algorithm"], "binding.signature.algorithm")
        if derivation_algorithm != "sha256_uuid_v1" or signature_algorithm != "ed25519":
            raise ContinuityFormatError(
                "continuity contract binding uses an unsupported cryptographic algorithm"
            )
        mediation = _record(raw["mediation"], "binding.mediation", {"kind"})
        mediation_kind = _string(mediation["kind"], "binding.mediation.kind")
        if mediation_kind not in _MEDIATION:
            raise ContinuityFormatError(
                "continuity contract binding mediation has an invalid value"
            )
        return cls(
            version,
            adapter_name,
            adapter_version,
            _string(raw["id"], "binding.id"),
            _digest(mandate["sha256"], "binding.mandate.sha256"),
            _string(mandate["principal"], "binding.mandate.principal"),
            _string(enforcement["provider"], "binding.enforcement.provider"),
            _string(enforcement["boundary_kind"], "binding.enforcement.boundary_kind"),
            _string(enforcement["binding"], "binding.enforcement.binding"),
            _digest(enforcement["policy_sha256"], "binding.enforcement.policy_sha256"),
            issued,
            expires,
            derivation_algorithm,
            _string(derivation["boundary_alias"], "binding.derivation.boundary_alias"),
            signature_algorithm,
            mediation_kind,
            _sources(raw["sources"], "binding.sources"),
            _evidence(raw["evidence"], "binding.evidence"),
        )


@dataclass(frozen=True)
class AgentCoreControl:
    id: str
    transition: str
    trials: int
    request_amount: int
    provider_limits: tuple[int, ...]
    outcomes: tuple[str, ...]
    same_mandate: bool | None
    revision_changed: bool | None
    boundary_changed: bool | None
    intervals_overlap: bool | None
    mediation: str
    sources: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "transition": self.transition,
            "trials": self.trials,
            "request_amount": self.request_amount,
            "provider_limits": list(self.provider_limits),
            "outcomes": list(self.outcomes),
            "same_mandate": self.same_mandate,
            "revision_changed": self.revision_changed,
            "boundary_changed": self.boundary_changed,
            "intervals_overlap": self.intervals_overlap,
            "mediation": self.mediation,
            "sources": list(self.sources),
        }


def _agentcore_controls(value: Any, source_ids: set[str]) -> tuple[AgentCoreControl, ...]:
    if not isinstance(value, list) or not value:
        raise ContinuityFormatError("continuity contract agentcore.controls must be an array")
    controls = []
    fields = {
        "id",
        "transition",
        "trials",
        "request_amount",
        "provider_limits",
        "outcomes",
        "same_mandate",
        "revision_changed",
        "boundary_changed",
        "intervals_overlap",
        "mediation",
        "sources",
    }
    for index, item in enumerate(value):
        path = f"agentcore.controls[{index}]"
        raw = _record(item, path, fields)
        transition = _string(raw["transition"], f"{path}.transition")
        mediation = _string(raw["mediation"], f"{path}.mediation")
        if transition not in _TRANSITIONS or mediation not in _MEDIATION:
            raise ContinuityFormatError(
                f"continuity contract {path} has an invalid vocabulary value"
            )
        limits_raw = raw["provider_limits"]
        if not isinstance(limits_raw, list) or not limits_raw:
            raise ContinuityFormatError(
                f"continuity contract {path}.provider_limits must be an array"
            )
        limits = tuple(
            _integer(item, f"{path}.provider_limits[]", minimum=1) for item in limits_raw
        )
        outcomes = _strings(raw["outcomes"], f"{path}.outcomes", _OUTCOMES, unique=False)
        sources = tuple(sorted(_strings(raw["sources"], f"{path}.sources")))
        if not set(sources) <= source_ids:
            raise ContinuityFormatError(f"continuity contract {path} cites an unknown source")
        optional_bools = []
        for field in ("revision_changed", "boundary_changed", "intervals_overlap"):
            optional_bools.append(
                None if raw[field] is None else _boolean(raw[field], f"{path}.{field}")
            )
        controls.append(
            AgentCoreControl(
                _string(raw["id"], f"{path}.id"),
                transition,
                _integer(raw["trials"], f"{path}.trials", minimum=1),
                _integer(raw["request_amount"], f"{path}.request_amount", minimum=1),
                limits,
                outcomes,
                (
                    None
                    if raw["same_mandate"] is None
                    else _boolean(raw["same_mandate"], f"{path}.same_mandate")
                ),
                optional_bools[0],
                optional_bools[1],
                optional_bools[2],
                mediation,
                sources,
            )
        )
    ids = [control.id for control in controls]
    if len(ids) != len(set(ids)):
        raise ContinuityFormatError("continuity contract agentcore.controls has duplicate ids")
    return tuple(sorted(controls, key=lambda control: control.id))


@dataclass(frozen=True)
class AgentCoreContinuity:
    version: int
    adapter_name: str
    adapter_version: int
    provider: str
    binding: str
    protocol: str
    controls: tuple[AgentCoreControl, ...]
    sources: tuple[ContinuitySource, ...]
    evidence: ContinuityEvidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "agentcore_continuity_version": self.version,
            "adapter": {"name": self.adapter_name, "version": self.adapter_version},
            "provider": self.provider,
            "binding": self.binding,
            "protocol": self.protocol,
            "controls": [control.as_dict() for control in self.controls],
            "sources": [source.as_dict() for source in self.sources],
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    def verify_sources(self, contents: dict[str, bytes]) -> None:
        _verify_sources(self.sources, contents)

    @classmethod
    def from_json(cls, text: str) -> AgentCoreContinuity:
        raw = _record(
            _load(text, "AgentCore continuity profile"),
            "agentcore",
            {
                "agentcore_continuity_version",
                "adapter",
                "provider",
                "binding",
                "protocol",
                "controls",
                "sources",
                "evidence",
            },
        )
        version = _integer(raw["agentcore_continuity_version"], "agentcore.version", minimum=1)
        if version != AGENTCORE_CONTINUITY_VERSION:
            raise ContinuityFormatError(
                f"unsupported AgentCore continuity version {version}; this build reads 1"
            )
        adapter_name, adapter_version = _adapter(
            raw["adapter"], "agentcore.adapter", "agentmandate.agentcore-continuity"
        )
        provider = _string(raw["provider"], "agentcore.provider")
        if provider != "aws-agentcore":
            raise ContinuityFormatError("continuity contract agentcore.provider is not supported")
        sources = _sources(raw["sources"], "agentcore.sources")
        return cls(
            version,
            adapter_name,
            adapter_version,
            provider,
            _string(raw["binding"], "agentcore.binding"),
            _string(raw["protocol"], "agentcore.protocol"),
            _agentcore_controls(raw["controls"], {source.id for source in sources}),
            sources,
            _evidence(raw["evidence"], "agentcore.evidence"),
        )


@dataclass(frozen=True)
class AnthropicControl:
    id: str
    transition: str
    trials: int
    cap_before: int
    cap_after: int
    child_count: int | None
    final_costs: tuple[int, ...]
    outcomes: tuple[str, ...]
    topology_complete: bool | None
    boundary_changed: bool
    sources: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "transition": self.transition,
            "trials": self.trials,
            "cap_before": self.cap_before,
            "cap_after": self.cap_after,
            "child_count": self.child_count,
            "final_costs": list(self.final_costs),
            "outcomes": list(self.outcomes),
            "topology_complete": self.topology_complete,
            "boundary_changed": self.boundary_changed,
            "sources": list(self.sources),
        }


def _anthropic_controls(value: Any, source_ids: set[str]) -> tuple[AnthropicControl, ...]:
    if not isinstance(value, list) or not value:
        raise ContinuityFormatError("continuity contract anthropic.controls must be an array")
    controls = []
    fields = {
        "id",
        "transition",
        "trials",
        "cap_before",
        "cap_after",
        "child_count",
        "final_costs",
        "outcomes",
        "topology_complete",
        "boundary_changed",
        "sources",
    }
    for index, item in enumerate(value):
        path = f"anthropic.controls[{index}]"
        raw = _record(item, path, fields)
        transition = _string(raw["transition"], f"{path}.transition")
        if transition not in _TRANSITIONS:
            raise ContinuityFormatError(
                f"continuity contract {path}.transition has an invalid value"
            )
        costs_raw = raw["final_costs"]
        if not isinstance(costs_raw, list) or not costs_raw:
            raise ContinuityFormatError(f"continuity contract {path}.final_costs must be an array")
        costs = tuple(_integer(cost, f"{path}.final_costs[]") for cost in costs_raw)
        child = raw["child_count"]
        child = None if child is None else _integer(child, f"{path}.child_count", minimum=1)
        topology = raw["topology_complete"]
        topology = None if topology is None else _boolean(topology, f"{path}.topology_complete")
        trials = _integer(raw["trials"], f"{path}.trials", minimum=1)
        if len(costs) != trials:
            raise ContinuityFormatError(
                f"continuity contract {path}.final_costs must contain one value per trial"
            )
        if (child is None) != (topology is None):
            raise ContinuityFormatError(
                f"continuity contract {path} must keep child topology together"
            )
        sources = tuple(sorted(_strings(raw["sources"], f"{path}.sources")))
        if not set(sources) <= source_ids:
            raise ContinuityFormatError(f"continuity contract {path} cites an unknown source")
        controls.append(
            AnthropicControl(
                _string(raw["id"], f"{path}.id"),
                transition,
                trials,
                _integer(raw["cap_before"], f"{path}.cap_before", minimum=1),
                _integer(raw["cap_after"], f"{path}.cap_after", minimum=1),
                child,
                costs,
                _strings(raw["outcomes"], f"{path}.outcomes", _OUTCOMES, unique=False),
                topology,
                _boolean(raw["boundary_changed"], f"{path}.boundary_changed"),
                sources,
            )
        )
    ids = [control.id for control in controls]
    if len(ids) != len(set(ids)):
        raise ContinuityFormatError("continuity contract anthropic.controls has duplicate ids")
    return tuple(sorted(controls, key=lambda control: control.id))


@dataclass(frozen=True)
class AnthropicContinuity:
    version: int
    adapter_name: str
    adapter_version: int
    provider: str
    service: str
    beta: str
    sdk: str
    model: str
    capture_date: str
    binding_sha256: str
    controls: tuple[AnthropicControl, ...]
    sources: tuple[ContinuitySource, ...]
    evidence: ContinuityEvidence

    def as_dict(self) -> dict[str, Any]:
        return {
            "anthropic_continuity_version": self.version,
            "adapter": {"name": self.adapter_name, "version": self.adapter_version},
            "provider": self.provider,
            "service": self.service,
            "beta": self.beta,
            "sdk": self.sdk,
            "model": self.model,
            "capture_date": self.capture_date,
            "binding_sha256": self.binding_sha256,
            "controls": [control.as_dict() for control in self.controls],
            "sources": [source.as_dict() for source in self.sources],
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")) + "\n"

    def verify_sources(self, contents: dict[str, bytes]) -> None:
        _verify_sources(self.sources, contents)

    @classmethod
    def from_json(cls, text: str) -> AnthropicContinuity:
        raw = _record(
            _load(text, "Anthropic continuity profile"),
            "anthropic",
            {
                "anthropic_continuity_version",
                "adapter",
                "provider",
                "service",
                "beta",
                "sdk",
                "model",
                "capture_date",
                "binding_sha256",
                "controls",
                "sources",
                "evidence",
            },
        )
        version = _integer(raw["anthropic_continuity_version"], "anthropic.version", minimum=1)
        if version != ANTHROPIC_CONTINUITY_VERSION:
            raise ContinuityFormatError(
                f"unsupported Anthropic continuity version {version}; this build reads 1"
            )
        adapter_name, adapter_version = _adapter(
            raw["adapter"], "anthropic.adapter", "agentmandate.anthropic-continuity"
        )
        provider = _string(raw["provider"], "anthropic.provider")
        service = _string(raw["service"], "anthropic.service")
        if provider != "Anthropic" or service != "Managed Agents":
            raise ContinuityFormatError("continuity contract anthropic provider is not supported")
        sources = _sources(raw["sources"], "anthropic.sources")
        return cls(
            version,
            adapter_name,
            adapter_version,
            provider,
            service,
            _string(raw["beta"], "anthropic.beta"),
            _string(raw["sdk"], "anthropic.sdk"),
            _string(raw["model"], "anthropic.model"),
            _date(raw["capture_date"], "anthropic.capture_date"),
            _digest(raw["binding_sha256"], "anthropic.binding_sha256"),
            _anthropic_controls(raw["controls"], {source.id for source in sources}),
            sources,
            _evidence(raw["evidence"], "anthropic.evidence"),
        )


def _captured(contents: dict[str, bytes], locator: str) -> dict[str, Any]:
    try:
        content = contents[locator]
    except KeyError as exc:
        raise ContinuityFormatError(
            f"continuity migration is missing source locator {locator}"
        ) from exc
    if not isinstance(content, bytes):
        raise ContinuityFormatError("continuity migration source contents must be bytes")
    value = _load(content.decode("utf-8"), f"continuity source {locator}")
    if not isinstance(value, dict):
        raise ContinuityFormatError(f"continuity source {locator} must contain an object")
    return value


def _migration_sources(
    contents: dict[str, bytes], kinds: dict[str, str], expected_digests: dict[str, str]
) -> tuple[ContinuitySource, ...]:
    if set(contents) != set(kinds) or set(kinds) != set(expected_digests):
        difference = sorted(set(contents) ^ set(kinds) | (set(kinds) ^ set(expected_digests)))
        locator = difference[0] if difference else "<unknown>"
        raise ContinuityFormatError(f"continuity migration source set differs at locator {locator}")
    result = []
    for index, locator in enumerate(sorted(contents)):
        actual = hashlib.sha256(contents[locator]).hexdigest()
        if actual != expected_digests[locator]:
            raise ContinuityFormatError(
                f"continuity migration source bytes do not match reviewed locator {locator}"
            )
        result.append(
            ContinuitySource(
                id=f"source:{index + 1}",
                kind=kinds[locator],
                locator=locator,
                content_sha256=actual,
            )
        )
    return tuple(result)


def _migration_evidence() -> ContinuityEvidence:
    # Migration proves byte identity, not an independently accountable review.
    return ContinuityEvidence("exact", "unreviewed", None, None)


def _adapter(value: Any, path: str, expected_name: str) -> tuple[str, int]:
    raw = _record(value, path, {"name", "version"})
    name = _string(raw["name"], f"{path}.name")
    version = _integer(raw["version"], f"{path}.version", minimum=1)
    if name != expected_name or version != 1:
        raise ContinuityFormatError(f"continuity contract {path} is not supported")
    return name, version


def migrate_agentcore_binding(contents: dict[str, bytes]) -> ContinuityBinding:
    """Migrate the reviewed AgentCore signed-binding capture without verifying Ed25519."""

    locators = {
        "docs/evidence/agentcore-refund-policy/mandate-binding.json": "signed-binding",
        "docs/evidence/agentcore-refund-policy/mandate-binding-result.json": "binding-evaluation",
        "docs/evidence/agentcore-refund-policy/binding-public-key.pem": "verification-key",
    }
    sources = _migration_sources(
        contents,
        locators,
        {
            "docs/evidence/agentcore-refund-policy/mandate-binding.json": (
                "d68090083664b72203acd6fe9faa33fdae86499d2b201c3c8927e5754f403ace"
            ),
            "docs/evidence/agentcore-refund-policy/mandate-binding-result.json": (
                "aa80fa7ce4a5543c95adad05e0e6e68a5200b1d89073a96074f440584e3bf74e"
            ),
            "docs/evidence/agentcore-refund-policy/binding-public-key.pem": (
                "c5dff1d6d4eb4212c9ff42ed15e8b7a0f8fa1f109d5df9488299b641ecf38536"
            ),
        },
    )
    binding = _captured(contents, "docs/evidence/agentcore-refund-policy/mandate-binding.json")
    result = _captured(
        contents, "docs/evidence/agentcore-refund-policy/mandate-binding-result.json"
    )
    expected_binding = {
        "binding_version",
        "expires_at",
        "issued_at",
        "issuer",
        "mandate_sha256",
        "policy_sha256",
        "principal",
        "signature",
    }
    _record(binding, "migration.binding", expected_binding)
    if binding["binding_version"] != 1:
        raise ContinuityFormatError("continuity migration requires AgentCore binding version 1")
    controls = result.get("local_controls")
    same = result.get("same_signed_mandate")
    different = result.get("different_signed_mandate")
    if (
        result.get("mandate_binding_evaluation_version") != 1
        or not isinstance(controls, list)
        or not isinstance(same, dict)
        or not isinstance(different, dict)
        or [call.get("outcome") for call in same.get("calls", [])] != ["allow", "deny"]
        or [call.get("outcome") for call in different.get("calls", [])] != ["allow"]
        or {control.get("result") for control in controls} != {"rejected-before-network"}
    ):
        raise ContinuityFormatError("continuity migration binding controls do not match evidence")
    migrated = ContinuityBinding(
        1,
        "agentmandate.continuity-binding",
        1,
        "bindings/agentcore-refund",
        _digest(binding["mandate_sha256"], "migration.binding.mandate_sha256"),
        _string(binding["principal"], "migration.binding.principal"),
        "aws-agentcore",
        "policy_session",
        "agentcore-refund-gateway",
        _digest(binding["policy_sha256"], "migration.binding.policy_sha256"),
        _utc(binding["issued_at"], "migration.binding.issued_at"),
        _utc(binding["expires_at"], "migration.binding.expires_at"),
        "sha256_uuid_v1",
        "reviewed-policy-session",
        "ed25519",
        "exclusive_adapter",
        sources,
        _migration_evidence(),
    )
    return ContinuityBinding.from_json(migrated.to_json())


def migrate_agentcore_continuity(contents: dict[str, bytes]) -> AgentCoreContinuity:
    """Migrate reviewed AgentCore repetition summaries into the provider profile."""

    base = "docs/evidence/agentcore-refund-policy/"
    names = {
        "temporal-repetition.json": "temporal-decisions",
        "temporal-semantic-noop-repetition.json": "revision-control",
        "temporal-update-repetition.json": "revision-decisions",
        "binding-repetition.json": "binding-decisions",
        "binding-policy-revision-repetition.json": "binding-revision-decisions",
    }
    locators = {base + name: kind for name, kind in names.items()}
    sources = _migration_sources(
        contents,
        locators,
        {
            base + "temporal-repetition.json": (
                "2bb58ba1a567da8f2ac020585f56c2ac6a60a378e52cf29be8a221255f35cc57"
            ),
            base + "temporal-semantic-noop-repetition.json": (
                "84949d3ad093b8832c1eab2117bd1fba688f0676b48c56253da5b2e9135380c1"
            ),
            base + "temporal-update-repetition.json": (
                "c130c0c5aaf812dcc1a39d8e6b930cbf4bee667745876b0ab36911c5351bd7a5"
            ),
            base + "binding-repetition.json": (
                "d1ca57b3917a9a547e9bd47e47984c56ed9d5041757d932fa180f4776e46b5db"
            ),
            base + "binding-policy-revision-repetition.json": (
                "79bd9022cffee259c7e5e2a52ceccb924fb804d214690962ae534061a85776f9"
            ),
        },
    )
    source_by_locator = {source.locator: source.id for source in sources}
    temporal = _captured(contents, base + "temporal-repetition.json")
    semantic = _captured(contents, base + "temporal-semantic-noop-repetition.json")
    update = _captured(contents, base + "temporal-update-repetition.json")
    binding = _captured(contents, base + "binding-repetition.json")
    binding_revision = _captured(contents, base + "binding-policy-revision-repetition.json")
    checks = {
        "temporal": temporal.get("results")
        == {
            "concurrent_exactly_one_allow": 10,
            "concurrent_intervals_overlapped": 10,
            "fresh_sessions_allow_then_allow": 10,
            "same_session_allow_then_deny": 10,
        },
        "semantic": semantic.get("results", {}).get("distinct_active_revision") == 10
        and semantic.get("byte_identical_control", {}).get("revision", {}).get("revision_changed")
        is False,
        "update": update.get("results", {}).get("old_session_rejected_as_stale") == 10,
        "binding": binding.get("results", {}).get("same_binding_allow_then_deny") == 10,
        "binding_revision": binding_revision.get("results", {}).get(
            "same_mandate_across_revision_aggregate"
        )
        == 1200,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ContinuityFormatError(
            f"continuity migration AgentCore control does not match source {failed[0]}"
        )
    ref = lambda name: (source_by_locator[base + name],)  # noqa: E731
    controls = (
        AgentCoreControl(
            "same-session",
            "same_boundary",
            10,
            600,
            (1000,),
            ("allow", "deny"),
            None,
            None,
            False,
            None,
            "unestablished",
            ref("temporal-repetition.json"),
        ),
        AgentCoreControl(
            "fresh-sessions",
            "fresh_session",
            10,
            600,
            (1000,),
            ("allow", "allow"),
            None,
            None,
            True,
            None,
            "unestablished",
            ref("temporal-repetition.json"),
        ),
        AgentCoreControl(
            "concurrent-session",
            "concurrent_dispatch",
            10,
            600,
            (1000,),
            ("allow", "deny"),
            None,
            None,
            False,
            True,
            "unestablished",
            ref("temporal-repetition.json"),
        ),
        AgentCoreControl(
            "byte-identical-write",
            "configuration_revision",
            1,
            600,
            (1000,),
            ("allow", "deny"),
            None,
            False,
            False,
            None,
            "unestablished",
            ref("temporal-semantic-noop-repetition.json"),
        ),
        AgentCoreControl(
            "equivalent-revision",
            "configuration_revision",
            10,
            600,
            (1000,),
            ("allow", "stale_session", "allow"),
            None,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-semantic-noop-repetition.json"),
        ),
        AgentCoreControl(
            "limit-revision",
            "limit_revision",
            10,
            600,
            (1000, 1001),
            ("allow", "stale_session", "allow"),
            None,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-update-repetition.json"),
        ),
        AgentCoreControl(
            "signed-binding",
            "same_boundary",
            10,
            600,
            (1000,),
            ("allow", "deny", "rejected_before_network"),
            True,
            None,
            False,
            None,
            "exclusive_adapter",
            ref("binding-repetition.json"),
        ),
        AgentCoreControl(
            "binding-revision",
            "configuration_revision",
            10,
            600,
            (1000, 1001),
            ("allow", "stale_session", "allow"),
            True,
            True,
            True,
            None,
            "exclusive_adapter",
            ref("binding-policy-revision-repetition.json"),
        ),
    )
    migrated = AgentCoreContinuity(
        1,
        "agentmandate.agentcore-continuity",
        1,
        "aws-agentcore",
        "agentcore-refund-gateway",
        "MCP 2025-03-26",
        tuple(sorted(controls, key=lambda control: control.id)),
        sources,
        _migration_evidence(),
    )
    return AgentCoreContinuity.from_json(migrated.to_json())


def migrate_anthropic_continuity(contents: dict[str, bytes]) -> AnthropicContinuity:
    """Migrate reviewed managed-budget summaries without inventing a native binding."""

    base = "docs/evidence/anthropic-managed-budget/"
    names = {
        "protocol.json": "single-agent-protocol",
        "confirmation.json": "single-agent-decisions",
        "multiagent-protocol.json": "multiagent-protocol",
        "multiagent-confirmation.json": "multiagent-decisions",
    }
    locators = {base + name: kind for name, kind in names.items()}
    sources = _migration_sources(
        contents,
        locators,
        {
            base + "protocol.json": (
                "5e7ad330270b36adce17c7b4e9f374ca2f03b548e1c251ab1b37eabb0a6a4001"
            ),
            base + "confirmation.json": (
                "f2b70d732f94ee3381b377fdac58ccb6150922dd5f96a057a9ee66505cfabe51"
            ),
            base + "multiagent-protocol.json": (
                "b56802cd8a4be4ace4369750114c9808d2589e04b34e20527c69c1965819f16e"
            ),
            base + "multiagent-confirmation.json": (
                "7300038f4aeb13fc1b9b35c6a06b6eee9a86d0907bdc3a6af46fd8cc8b2819f7"
            ),
        },
    )
    source_by_locator = {source.locator: source.id for source in sources}
    protocol = _captured(contents, base + "protocol.json")
    confirmation = _captured(contents, base + "confirmation.json")
    multi_protocol = _captured(contents, base + "multiagent-protocol.json")
    multi = _captured(contents, base + "multiagent-confirmation.json")
    if (
        protocol.get("protocol_version") != 1
        or confirmation.get("evidence_version") != 1
        or multi_protocol.get("protocol_version") != 1
        or multi.get("evidence_version") != 1
        or confirmation.get("protocol_sha256")
        != hashlib.sha256(contents[base + "protocol.json"]).hexdigest()
        or multi.get("protocol_sha256")
        != hashlib.sha256(contents[base + "multiagent-protocol.json"]).hexdigest()
    ):
        raise ContinuityFormatError("continuity migration Anthropic protocol join failed")
    single_trials = confirmation.get("trials")
    multi_trials = multi.get("trials")
    if not isinstance(single_trials, list) or not isinstance(multi_trials, list):
        raise ContinuityFormatError("continuity migration Anthropic trials must be arrays")
    if len(single_trials) != 30 or len(multi_trials) != 30:
        raise ContinuityFormatError("continuity migration Anthropic trial counts differ")

    def single_costs(cell: str) -> tuple[int, ...]:
        selected = [trial for trial in single_trials if trial.get("cell") == cell]
        if len(selected) != 10:
            raise ContinuityFormatError(f"continuity migration Anthropic cell {cell} differs")
        costs = []
        for trial in selected:
            if cell == "cap_revision_control":
                costs.append(trial["revision"]["cost_immediately_after"])
            elif cell == "fresh_session_replication":
                costs.append(
                    max(
                        unit["list_cost_minor_units"] for unit in trial["sessions"][1]["work_units"]
                    )
                )
            else:
                costs.append(max(unit["list_cost_minor_units"] for unit in trial["work_units"]))
        return tuple(costs)

    def multi_costs(cell: str) -> tuple[int, ...]:
        selected = [trial for trial in multi_trials if trial.get("cell") == cell]
        if len(selected) != 10 or any(
            not trial.get("topology", {}).get("protocol_conformant") for trial in selected
        ):
            raise ContinuityFormatError(f"continuity migration Anthropic cell {cell} differs")
        return tuple(trial["list_cost_minor_units"] for trial in selected)

    single_sources = (
        source_by_locator[base + "protocol.json"],
        source_by_locator[base + "confirmation.json"],
    )
    multi_sources = (
        source_by_locator[base + "multiagent-protocol.json"],
        source_by_locator[base + "multiagent-confirmation.json"],
    )
    controls = (
        AnthropicControl(
            "sequential",
            "same_boundary",
            10,
            1,
            1,
            None,
            single_costs("sequential_control"),
            ("budget_reached",),
            None,
            False,
            single_sources,
        ),
        AnthropicControl(
            "fresh-sessions",
            "fresh_session",
            10,
            1,
            1,
            None,
            single_costs("fresh_session_replication"),
            ("budget_reached",),
            None,
            True,
            single_sources,
        ),
        AnthropicControl(
            "cap-increase",
            "limit_revision",
            10,
            1,
            2,
            None,
            single_costs("cap_revision_control"),
            ("budget_reached",),
            None,
            False,
            single_sources,
        ),
        AnthropicControl(
            "one-child",
            "delegation_handoff",
            10,
            1,
            1,
            1,
            multi_costs("subagent_handoff"),
            ("budget_reached",),
            True,
            False,
            multi_sources,
        ),
        AnthropicControl(
            "two-children",
            "concurrent_dispatch",
            10,
            1,
            1,
            2,
            multi_costs("concurrent_subagents_2"),
            ("budget_reached",),
            True,
            False,
            multi_sources,
        ),
        AnthropicControl(
            "four-children",
            "concurrent_dispatch",
            10,
            1,
            1,
            4,
            multi_costs("concurrent_subagents_4"),
            ("budget_reached",),
            True,
            False,
            multi_sources,
        ),
    )
    migrated = AnthropicContinuity(
        1,
        "agentmandate.anthropic-continuity",
        1,
        _string(protocol.get("provider"), "migration.anthropic.provider"),
        _string(protocol.get("service"), "migration.anthropic.service"),
        _string(protocol.get("beta"), "migration.anthropic.beta"),
        _string(protocol.get("sdk"), "migration.anthropic.sdk"),
        _string(protocol.get("model"), "migration.anthropic.model"),
        _date(protocol.get("capture_date"), "migration.anthropic.capture_date"),
        _digest(protocol.get("binding", {}).get("sha256"), "migration.anthropic.binding"),
        tuple(sorted(controls, key=lambda control: control.id)),
        sources,
        _migration_evidence(),
    )
    return AnthropicContinuity.from_json(migrated.to_json())
