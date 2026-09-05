"""Private records and reconciliation for authority-continuity evidence.

The two provider profiles intentionally remain distinct.  This module parses
and canonicalises transport records, verifies caller-supplied bytes, and keeps
provider-specific facts separate before a common private analysis. It exposes
no public format.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

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
    _from_mandate,
)
from ._ir import (
    Evidence as IREvidence,
)
from ._result import validate_authority
from .manifest import Mandate, ManifestError, loads
from .reach import Authority, analyse

CONTINUITY_BINDING_VERSION = 1
AGENTCORE_CONTINUITY_VERSION = 1
ANTHROPIC_CONTINUITY_VERSION = 1
CONTINUITY_BINDING_IR_ADAPTER = "agentmandate.continuity-binding-ir"
AGENTCORE_CONTINUITY_IR_ADAPTER = "agentmandate.agentcore-continuity-ir"
ANTHROPIC_CONTINUITY_IR_ADAPTER = "agentmandate.anthropic-continuity-ir"
CONTINUITY_IR_ADAPTER_VERSION = 1
CONTINUITY_RESULT_VERSION = 1
CONTINUITY_RESULT_SCHEMA = "agentmandate.continuity/v1"
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
_FINDING_CODES = frozenset(
    {
        "continuity.source-untrusted",
        "continuity.evidence-untrusted",
        "continuity.binding-untrusted",
        "continuity.state-reset",
        "continuity.state-unresolved",
        "continuity.authority-widens",
        "continuity.admission-overshot",
        "continuity.continuity-unresolved",
        "continuity.derivation-integrity-unresolved",
        "continuity.isolation-unresolved",
        "continuity.complete-mediation-unresolved",
    }
)
_UNSUPPORTED_COMPOSITIONS = frozenset(
    {
        "cedar",
        "conditions",
        "delegations",
        "ir",
        "mermaid",
        "otel",
        "producers",
        "sarif",
    }
)


class ContinuityFormatError(ValueError):
    """Raised when a private continuity artifact is malformed."""


def _refuse_continuity_composition(composition: frozenset[str]) -> None:
    unknown = sorted(composition - _UNSUPPORTED_COMPOSITIONS)
    if unknown:
        raise ContinuityFormatError(
            f"unsupported authority-continuity composition {unknown[0]!r}"
        )
    if composition:
        requested = ", ".join(sorted(composition))
        raise ContinuityFormatError(
            f"authority continuity cannot yet be composed with {requested}"
        )


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

    def to_ir(self) -> AuthorityIR:
        return _binding_to_ir(self)

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

    def to_ir(self) -> AuthorityIR:
        return _provider_to_ir(self)

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
    consumed_before: tuple[int, ...] | None
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
            "consumed_before": (
                None if self.consumed_before is None else list(self.consumed_before)
            ),
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
        "consumed_before",
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
        before_raw = raw["consumed_before"]
        if before_raw is None:
            before = None
        elif not isinstance(before_raw, list):
            raise ContinuityFormatError(
                f"continuity contract {path}.consumed_before must be an array or null"
            )
        else:
            before = tuple(_integer(cost, f"{path}.consumed_before[]") for cost in before_raw)
        child = raw["child_count"]
        child = None if child is None else _integer(child, f"{path}.child_count", minimum=1)
        topology = raw["topology_complete"]
        topology = None if topology is None else _boolean(topology, f"{path}.topology_complete")
        trials = _integer(raw["trials"], f"{path}.trials", minimum=1)
        if len(costs) != trials:
            raise ContinuityFormatError(
                f"continuity contract {path}.final_costs must contain one value per trial"
            )
        if before is not None and len(before) != trials:
            raise ContinuityFormatError(
                f"continuity contract {path}.consumed_before must contain one value per trial"
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
                before,
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

    def to_ir(self) -> AuthorityIR:
        return _provider_to_ir(self)

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
        "temporal-transition-confirmation-summary.json": "revision-control",
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
            base + "temporal-transition-confirmation-summary.json": (
                "129c018ea16266e51187cf9d499fa989ed93cb3d33da8b8a591891dedf17d512"
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
    semantic = _captured(contents, base + "temporal-transition-confirmation-summary.json")
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
        "semantic": semantic.get("results")
        == {
            "alpha_equivalent_revision_changed": 10,
            "byte_identical_revision_unchanged": 10,
            "byte_identical_second_request_denied": 10,
            "description_only_revision_changed": True,
            "description_only_statement_changed": False,
            "fresh_successor_allow_then_deny": 21,
            "maximum_transition_seconds": 15.377992,
            "predecessor_session_rejected_as_stale": 21,
            "whitespace_only_revision_changed": 10,
        },
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
            10,
            600,
            (1000,),
            ("allow", "deny"),
            True,
            False,
            False,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
        ),
        AgentCoreControl(
            "equivalent-revision",
            "configuration_revision",
            10,
            600,
            (1000,),
            ("allow", "stale_session", "allow", "deny"),
            True,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
        ),
        AgentCoreControl(
            "whitespace-revision",
            "configuration_revision",
            10,
            600,
            (1000,),
            ("allow", "stale_session", "allow", "deny"),
            True,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
        ),
        AgentCoreControl(
            "description-revision",
            "configuration_revision",
            1,
            600,
            (1000,),
            ("allow", "stale_session", "allow", "deny"),
            True,
            True,
            True,
            None,
            "unestablished",
            ref("temporal-transition-confirmation-summary.json"),
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

    def single_before_costs(cell: str) -> tuple[int, ...]:
        selected = [trial for trial in single_trials if trial.get("cell") == cell]
        if cell == "fresh_session_replication":
            return tuple(
                max(unit["list_cost_minor_units"] for unit in trial["sessions"][0]["work_units"])
                for trial in selected
            )
        return tuple(trial["revision"]["consumed_before"] for trial in selected)

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
            single_before_costs("fresh_session_replication"),
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
            single_before_costs("cap_revision_control"),
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
            None,
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
            None,
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
            None,
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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _profile_digest(
    entities: tuple[Entity, ...], facts: tuple[Fact, ...], edges: tuple[Edge, ...]
) -> str:
    body = {
        "entities": [item.as_dict() for item in sorted(entities, key=lambda item: item.id)],
        "facts": [item.as_dict() for item in sorted(facts, key=lambda item: item.id)],
        "edges": [item.as_dict() for item in sorted(edges, key=lambda item: item.id)],
    }
    return hashlib.sha256(_canonical_json(body).encode()).hexdigest()


def _ir_fact(
    subject: str,
    predicate: str,
    value: Any,
    source: str,
    location: str,
    evidence: ContinuityEvidence,
) -> Fact:
    return Fact(
        _fact_id(subject, predicate),
        subject,
        predicate,
        value,
        (IREvidence(source, location, evidence.confidence, evidence.review),),
    )


def _binding_projection_parts(
    value: ContinuityBinding, source_id: str
) -> tuple[tuple[Entity, ...], tuple[Fact, ...], tuple[Edge, ...]]:
    binding_id = _entity_id("continuity_binding", value.id)
    mandate_id = _entity_id("mandate", value.mandate_sha256)
    boundary_name = f"{value.provider}:{value.binding}"
    boundary_id = _entity_id("enforcement_boundary", boundary_name)
    entities = (
        Entity(binding_id, "continuity_binding", value.id),
        Entity(mandate_id, "mandate", value.mandate_sha256),
        Entity(boundary_id, "enforcement_boundary", boundary_name),
    )
    facts = (
        _ir_fact(binding_id, "name", value.id, source_id, "/id", value.evidence),
        _ir_fact(binding_id, "record", value.as_dict(), source_id, "", value.evidence),
        _ir_fact(binding_id, "mandate", mandate_id, source_id, "/mandate", value.evidence),
        _ir_fact(
            binding_id,
            "boundary",
            boundary_id,
            source_id,
            "/enforcement",
            value.evidence,
        ),
        _ir_fact(
            mandate_id,
            "sha256",
            value.mandate_sha256,
            source_id,
            "/mandate/sha256",
            value.evidence,
        ),
        _ir_fact(
            mandate_id,
            "principal",
            value.principal,
            source_id,
            "/mandate/principal",
            value.evidence,
        ),
        _ir_fact(boundary_id, "name", boundary_name, source_id, "/enforcement", value.evidence),
        _ir_fact(
            boundary_id,
            "provider",
            value.provider,
            source_id,
            "/enforcement/provider",
            value.evidence,
        ),
        _ir_fact(
            boundary_id,
            "boundary_kind",
            value.boundary_kind,
            source_id,
            "/enforcement/boundary_kind",
            value.evidence,
        ),
    )
    edges = (
        Edge(
            _edge_id(binding_id, "binds_mandate", mandate_id),
            binding_id,
            "binds_mandate",
            mandate_id,
            (_fact_id(binding_id, "mandate"),),
        ),
        Edge(
            _edge_id(binding_id, "binds_boundary", boundary_id),
            binding_id,
            "binds_boundary",
            boundary_id,
            (_fact_id(binding_id, "boundary"),),
        ),
    )
    return (
        tuple(sorted(entities, key=lambda item: item.id)),
        tuple(sorted(facts, key=lambda item: item.id)),
        tuple(sorted(edges, key=lambda item: item.id)),
    )


def _control_values(
    value: AgentCoreControl | AnthropicControl,
) -> tuple[int, int, list[int] | None, list[int] | None]:
    if isinstance(value, AgentCoreControl):
        return value.provider_limits[0], value.provider_limits[-1], None, None
    return (
        value.cap_before,
        value.cap_after,
        None if value.consumed_before is None else list(value.consumed_before),
        list(value.final_costs),
    )


def _provider_projection_parts(
    value: AgentCoreContinuity | AnthropicContinuity, source_id: str
) -> tuple[tuple[Entity, ...], tuple[Fact, ...], tuple[Edge, ...]]:
    if isinstance(value, AgentCoreContinuity):
        boundary_name = f"{value.provider}:{value.binding}"
    else:
        boundary_name = f"anthropic-managed-agents:{value.binding_sha256}"
    boundary_id = _entity_id("enforcement_boundary", boundary_name)
    entities: list[Entity] = [Entity(boundary_id, "enforcement_boundary", boundary_name)]
    transition_ids = {
        control.id: _entity_id("transition", control.id) for control in value.controls
    }
    facts: list[Fact] = [
        _ir_fact(boundary_id, "name", boundary_name, source_id, "/", value.evidence),
        _ir_fact(boundary_id, "record", value.as_dict(), source_id, "", value.evidence),
        _ir_fact(
            boundary_id,
            "transitions",
            [transition_ids[item.id] for item in value.controls],
            source_id,
            "/controls",
            value.evidence,
        ),
    ]
    edges: list[Edge] = []
    for control_index, control in enumerate(value.controls):
        transition_id = transition_ids[control.id]
        before_id = _entity_id("boundary_state", f"{control.id}:before")
        after_id = _entity_id("boundary_state", f"{control.id}:after")
        decision_ids = [
            _entity_id("decision", f"{control.id}:event:{index}")
            for index in range(len(control.outcomes))
        ]
        entities.extend(
            (
                Entity(transition_id, "transition", control.id),
                Entity(before_id, "boundary_state", f"{control.id}:before"),
                Entity(after_id, "boundary_state", f"{control.id}:after"),
            )
        )
        before_limit, after_limit, before_completed, after_completed = _control_values(control)
        path = f"/controls/{control_index}"
        facts.extend(
            (
                _ir_fact(
                    transition_id, "name", control.id, source_id, f"{path}/id", value.evidence
                ),
                _ir_fact(
                    transition_id,
                    "control",
                    control.as_dict(),
                    source_id,
                    path,
                    value.evidence,
                ),
                _ir_fact(
                    transition_id,
                    "before",
                    before_id,
                    source_id,
                    path,
                    value.evidence,
                ),
                _ir_fact(
                    transition_id,
                    "after",
                    after_id,
                    source_id,
                    path,
                    value.evidence,
                ),
                _ir_fact(
                    transition_id,
                    "decisions",
                    decision_ids,
                    source_id,
                    f"{path}/outcomes",
                    value.evidence,
                ),
            )
        )
        for state_id, phase, limit, completed in (
            (before_id, "before", before_limit, before_completed),
            (after_id, "after", after_limit, after_completed),
        ):
            facts.extend(
                (
                    _ir_fact(
                        state_id, "name", f"{control.id}:{phase}", source_id, path, value.evidence
                    ),
                    _ir_fact(
                        state_id,
                        "boundary",
                        boundary_id,
                        source_id,
                        path,
                        value.evidence,
                    ),
                    _ir_fact(state_id, "phase", phase, source_id, path, value.evidence),
                    _ir_fact(
                        state_id,
                        "provider_limit",
                        limit,
                        source_id,
                        path,
                        value.evidence,
                    ),
                )
            )
            edges.append(
                Edge(
                    _edge_id(state_id, "state_of", boundary_id),
                    state_id,
                    "state_of",
                    boundary_id,
                    (_fact_id(state_id, "boundary"),),
                )
            )
            if completed is not None:
                completed_path = "consumed_before" if phase == "before" else "final_costs"
                facts.append(
                    _ir_fact(
                        state_id,
                        "completed_values",
                        completed,
                        source_id,
                        f"{path}/{completed_path}",
                        value.evidence,
                    )
                )
        edges.extend(
            (
                Edge(
                    _edge_id(transition_id, "before_state", before_id),
                    transition_id,
                    "before_state",
                    before_id,
                    (_fact_id(transition_id, "before"),),
                ),
                Edge(
                    _edge_id(transition_id, "after_state", after_id),
                    transition_id,
                    "after_state",
                    after_id,
                    (_fact_id(transition_id, "after"),),
                ),
            )
        )
        for decision_index, (decision_id, outcome) in enumerate(
            zip(decision_ids, control.outcomes, strict=True)
        ):
            decision_name = f"{control.id}:event:{decision_index}"
            entities.append(Entity(decision_id, "decision", decision_name))
            facts.extend(
                (
                    _ir_fact(decision_id, "name", decision_name, source_id, path, value.evidence),
                    _ir_fact(
                        decision_id,
                        "outcome",
                        outcome,
                        source_id,
                        f"{path}/outcomes/{decision_index}",
                        value.evidence,
                    ),
                    _ir_fact(
                        decision_id,
                        "ordinal",
                        decision_index,
                        source_id,
                        f"{path}/outcomes/{decision_index}",
                        value.evidence,
                    ),
                    _ir_fact(
                        decision_id,
                        "trials",
                        control.trials,
                        source_id,
                        f"{path}/trials",
                        value.evidence,
                    ),
                )
            )
            edges.append(
                Edge(
                    _edge_id(transition_id, "observes_decision", decision_id),
                    transition_id,
                    "observes_decision",
                    decision_id,
                    (_fact_id(transition_id, "decisions"),),
                )
            )
    return (
        tuple(sorted(entities, key=lambda item: item.id)),
        tuple(sorted(facts, key=lambda item: item.id)),
        tuple(sorted(edges, key=lambda item: item.id)),
    )


def _make_profile(
    record: ContinuityBinding | AgentCoreContinuity | AnthropicContinuity,
    kind: str,
    adapter: str,
    producer_version: str | None,
    parts,
) -> AuthorityIR:
    content_sha256 = hashlib.sha256(record.to_json().encode()).hexdigest()
    source_id = _entity_id("source", f"{kind}:{content_sha256}")
    entities, facts, edges = parts(record, source_id)
    graph = AuthorityIR(
        IR_VERSION,
        (
            Source(
                source_id,
                kind,
                f"memory:{kind}",
                record.version,
                producer_version,
                _profile_digest(entities, facts, edges),
                adapter,
                CONTINUITY_IR_ADAPTER_VERSION,
                content_sha256,
            ),
        ),
        entities,
        facts,
        edges,
    )
    _validate_continuity_profile(graph, kind, adapter)
    return graph


def _binding_to_ir(value: ContinuityBinding) -> AuthorityIR:
    return _make_profile(
        value,
        "continuity-binding",
        CONTINUITY_BINDING_IR_ADAPTER,
        value.derivation_algorithm,
        _binding_projection_parts,
    )


def _provider_to_ir(value: AgentCoreContinuity | AnthropicContinuity) -> AuthorityIR:
    if isinstance(value, AgentCoreContinuity):
        return _make_profile(
            value,
            "agentcore-continuity",
            AGENTCORE_CONTINUITY_IR_ADAPTER,
            value.protocol,
            _provider_projection_parts,
        )
    return _make_profile(
        value,
        "anthropic-continuity",
        ANTHROPIC_CONTINUITY_IR_ADAPTER,
        value.beta,
        _provider_projection_parts,
    )


def _validate_continuity_profile(graph: AuthorityIR, kind: str, adapter: str) -> None:
    """Validate and regenerate one closed standalone continuity profile."""

    contracts = {
        "continuity-binding": (CONTINUITY_BINDING_IR_ADAPTER, ContinuityBinding),
        "agentcore-continuity": (AGENTCORE_CONTINUITY_IR_ADAPTER, AgentCoreContinuity),
        "anthropic-continuity": (ANTHROPIC_CONTINUITY_IR_ADAPTER, AnthropicContinuity),
    }
    contract = contracts.get(kind)
    if contract is None or contract[0] != adapter:
        raise ContinuityFormatError("continuity IR profile kind is not supported")
    try:
        graph.validate()
    except IRFormatError as exc:
        raise ContinuityFormatError("continuity IR profile is structurally invalid") from exc
    if len(graph.sources) != 1:
        raise ContinuityFormatError("continuity IR profile requires exactly one source")
    source = graph.sources[0]
    if (
        source.kind != kind
        or source.adapter != adapter
        or source.adapter_version != CONTINUITY_IR_ADAPTER_VERSION
        or source.format_version != 1
        or source.content_sha256 is None
        or source.locator != f"memory:{kind}"
    ):
        raise ContinuityFormatError("continuity IR profile has an unsupported source")
    if source.semantic_sha256 != _profile_digest(graph.entities, graph.facts, graph.edges):
        raise ContinuityFormatError("continuity IR profile semantic digest does not match")
    root_kind = "continuity_binding" if kind == "continuity-binding" else "enforcement_boundary"
    roots = [entity for entity in graph.entities if entity.kind == root_kind]
    record_facts = [
        fact
        for fact in graph.facts
        if fact.predicate == "record" and fact.subject in {root.id for root in roots}
    ]
    if len(roots) != 1 or len(record_facts) != 1:
        raise ContinuityFormatError("continuity IR profile requires one record root")
    reader = contract[1]
    try:
        record = reader.from_json(_canonical_json(record_facts[0].value))
    except ContinuityFormatError as exc:
        raise ContinuityFormatError("continuity IR profile record fact is invalid") from exc
    content_sha256 = hashlib.sha256(record.to_json().encode()).hexdigest()
    producer_version = (
        record.derivation_algorithm
        if isinstance(record, ContinuityBinding)
        else record.protocol
        if isinstance(record, AgentCoreContinuity)
        else record.beta
    )
    if (
        source.id != _entity_id("source", f"{kind}:{content_sha256}")
        or source.producer_version != producer_version
    ):
        raise ContinuityFormatError("continuity IR profile source identity does not match")
    parts = (
        _binding_projection_parts if kind == "continuity-binding" else _provider_projection_parts
    )
    expected_entities, expected_facts, expected_edges = parts(record, source.id)
    if (
        graph.entities != expected_entities
        or graph.facts != expected_facts
        or graph.edges != expected_edges
    ):
        raise ContinuityFormatError("continuity IR profile does not match its record")
    if source.content_sha256 != content_sha256:
        raise ContinuityFormatError("continuity IR profile content digest does not match")


@dataclass(frozen=True)
class ContinuityFinding:
    """One fail-closed continuity or trust finding."""

    code: str
    transition: str | None
    message: str
    support: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "transition": self.transition,
            "message": self.message,
            "support": list(self.support),
        }


@dataclass(frozen=True)
class ContinuityAlignment:
    """One independently reported boundary-alignment check."""

    check: str
    status: str
    strength: str
    support: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "status": self.status,
            "strength": self.strength,
            "support": list(self.support),
        }


@dataclass(frozen=True)
class ContinuityOutcome:
    """The three orthogonal outcomes for one observed transition."""

    provider: str
    transition: str
    kind: str
    dimension: str
    unit: str
    limit_before: int
    limit_after: int
    completed_values: tuple[int, ...]
    state: str
    authority_change: str
    admission: str
    comparability: str
    issuer_amendment: str
    safe_continuation: str
    alignments: tuple[ContinuityAlignment, ...]
    assumptions: tuple[str, ...]
    support: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "transition": self.transition,
            "kind": self.kind,
            "dimension": self.dimension,
            "unit": self.unit,
            "limit_before": self.limit_before,
            "limit_after": self.limit_after,
            "completed_values": list(self.completed_values),
            "state": self.state,
            "authority_change": self.authority_change,
            "admission": self.admission,
            "comparability": self.comparability,
            "issuer_amendment": self.issuer_amendment,
            "safe_continuation": self.safe_continuation,
            "alignments": [item.as_dict() for item in self.alignments],
            "assumptions": list(self.assumptions),
            "support": list(self.support),
        }


@dataclass(frozen=True)
class ContinuityManifestIdentity:
    locator: str
    semantic_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {"locator": self.locator, "semantic_sha256": self.semantic_sha256}


@dataclass(frozen=True)
class ContinuityArtifactIdentity:
    kind: str
    id: str
    content_sha256: str
    semantic_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "id": self.id,
            "content_sha256": self.content_sha256,
            "semantic_sha256": self.semantic_sha256,
        }


@dataclass(frozen=True)
class ContinuityAnalysis:
    """Internal reconciliation result beside unchanged manifest authority."""

    authority: Authority
    as_of: str
    outcomes: tuple[ContinuityOutcome, ...]
    findings: tuple[ContinuityFinding, ...]
    manifest: ContinuityManifestIdentity
    provider: ContinuityArtifactIdentity
    binding: ContinuityArtifactIdentity | None

    @property
    def clean(self) -> bool:
        return not self.findings and all(
            item.safe_continuation == "satisfied" for item in self.outcomes
        )

    def to_result(self) -> ContinuityResult:
        """Return the versioned CLI presentation envelope."""
        return ContinuityResult(
            CONTINUITY_RESULT_VERSION,
            CONTINUITY_RESULT_SCHEMA,
            self.as_of,
            self.manifest,
            self.provider,
            self.binding,
            self.authority.as_dict(),
            self.outcomes,
            self.findings,
        )


@dataclass(frozen=True)
class ContinuityResult:
    """Internal record for canonical CLI output; never an authority input."""

    result_version: int
    schema: str
    as_of: str
    manifest: ContinuityManifestIdentity
    provider: ContinuityArtifactIdentity
    binding: ContinuityArtifactIdentity | None
    authority: dict[str, Any]
    outcomes: tuple[ContinuityOutcome, ...]
    findings: tuple[ContinuityFinding, ...]

    def _body_dict(self) -> dict[str, Any]:
        return {
            "result_version": self.result_version,
            "schema": self.schema,
            "as_of": self.as_of,
            "inputs": {
                "manifest": self.manifest.as_dict(),
                "provider": self.provider.as_dict(),
                "binding": None if self.binding is None else self.binding.as_dict(),
            },
            "authority": self.authority,
            "outcomes": [item.as_dict() for item in self.outcomes],
            "findings": [item.as_dict() for item in self.findings],
        }

    def as_dict(self) -> dict[str, Any]:
        body = self._body_dict()
        _parse_continuity_result_body(body)
        return {
            **body,
            "result_sha256": hashlib.sha256(_canonical_json(body).encode()).hexdigest(),
        }

    def to_json(self) -> str:
        return _canonical_json(self.as_dict()) + "\n"

    @classmethod
    def from_json(cls, text: str) -> ContinuityResult:
        return _continuity_result_from_json(text)


_ALIGNMENT_CHECKS = (
    "continuity",
    "derivation_integrity",
    "isolation",
    "complete_mediation",
)
_ALIGNMENT_STATUSES = frozenset({"established", "conditional", "unresolved"})
_ALIGNMENT_STRENGTHS = frozenset(
    {"observed", "documented", "platform_verified", "configured", "unestablished"}
)
_STATES = frozenset({"preserved", "reset", "unresolved"})
_AUTHORITY_CHANGES = frozenset({"stable", "widens", "tightens", "unresolved"})
_ADMISSIONS = frozenset({"within_bound", "overshot", "unresolved"})
_COMPARABILITY = frozenset({"established", "unresolved"})
_ISSUER_AMENDMENTS = frozenset({"not_required", "approved", "unresolved"})
_SAFE_CONTINUATION = frozenset({"satisfied", "violated", "unresolved"})
_ARTIFACT_KINDS = frozenset(
    {"continuity-binding", "agentcore-continuity", "anthropic-continuity"}
)


def _result_record(value: Any, path: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContinuityFormatError(f"continuity result {path} must be an object")
    missing = sorted(fields - value.keys())
    if missing:
        raise ContinuityFormatError(
            f"continuity result {path} is missing field {missing[0]!r}"
        )
    extra = sorted(value.keys() - fields)
    if extra:
        raise ContinuityFormatError(
            f"continuity result {path} has unknown field {extra[0]!r}"
        )
    return value


def _result_strings(value: Any, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ContinuityFormatError(f"continuity result {path} must be an array")
    items = tuple(_string(item, f"result{path}/{index}") for index, item in enumerate(value))
    if list(items) != sorted(set(items)):
        raise ContinuityFormatError(
            f"continuity result {path} must contain sorted unique strings"
        )
    return items


def _result_identity(value: Any, path: str) -> ContinuityArtifactIdentity:
    record = _result_record(
        value, path, {"kind", "id", "content_sha256", "semantic_sha256"}
    )
    kind = _string(record["kind"], f"result{path}/kind")
    if kind not in _ARTIFACT_KINDS:
        raise ContinuityFormatError(f"continuity result {path}/kind is unsupported")
    return ContinuityArtifactIdentity(
        kind,
        _string(record["id"], f"result{path}/id"),
        _digest(record["content_sha256"], f"result{path}/content_sha256"),
        _digest(record["semantic_sha256"], f"result{path}/semantic_sha256"),
    )


def _validate_result_authority(value: Any) -> dict[str, Any]:
    return validate_authority(
        value,
        error_type=ContinuityFormatError,
        result_name="continuity result",
        whitespace_term="stripped",
    )


def _parse_alignment(value: Any, path: str) -> ContinuityAlignment:
    record = _result_record(value, path, {"check", "status", "strength", "support"})
    check = _string(record["check"], f"result{path}/check")
    status = _string(record["status"], f"result{path}/status")
    strength = _string(record["strength"], f"result{path}/strength")
    if check not in _ALIGNMENT_CHECKS or status not in _ALIGNMENT_STATUSES:
        raise ContinuityFormatError(f"continuity result {path} has unsupported alignment state")
    if strength not in _ALIGNMENT_STRENGTHS:
        raise ContinuityFormatError(f"continuity result {path}/strength is unsupported")
    return ContinuityAlignment(
        check, status, strength, _result_strings(record["support"], f"{path}/support")
    )


def _parse_outcomes(value: Any) -> tuple[ContinuityOutcome, ...]:
    if not isinstance(value, list) or not value:
        raise ContinuityFormatError("continuity result /outcomes must be a non-empty array")
    fields = {
        "provider",
        "transition",
        "kind",
        "dimension",
        "unit",
        "limit_before",
        "limit_after",
        "completed_values",
        "state",
        "authority_change",
        "admission",
        "comparability",
        "issuer_amendment",
        "safe_continuation",
        "alignments",
        "assumptions",
        "support",
    }
    items = []
    for index, item in enumerate(value):
        path = f"/outcomes/{index}"
        record = _result_record(item, path, fields)
        completed = record["completed_values"]
        if not isinstance(completed, list) or not completed:
            raise ContinuityFormatError(
                f"continuity result {path}/completed_values must be non-empty"
            )
        completed_values = tuple(
            _integer(number, f"result{path}/completed_values/{offset}")
            for offset, number in enumerate(completed)
        )
        alignments = record["alignments"]
        if not isinstance(alignments, list):
            raise ContinuityFormatError(f"continuity result {path}/alignments must be an array")
        parsed_alignments = tuple(
            _parse_alignment(alignment, f"{path}/alignments/{offset}")
            for offset, alignment in enumerate(alignments)
        )
        if tuple(alignment.check for alignment in parsed_alignments) != _ALIGNMENT_CHECKS:
            raise ContinuityFormatError(
                f"continuity result {path}/alignments must cover the canonical checks"
            )
        state = _string(record["state"], f"result{path}/state")
        authority_change = _string(
            record["authority_change"], f"result{path}/authority_change"
        )
        admission = _string(record["admission"], f"result{path}/admission")
        comparability = _string(record["comparability"], f"result{path}/comparability")
        amendment = _string(record["issuer_amendment"], f"result{path}/issuer_amendment")
        verdict = _string(record["safe_continuation"], f"result{path}/safe_continuation")
        if (
            state not in _STATES
            or authority_change not in _AUTHORITY_CHANGES
            or admission not in _ADMISSIONS
            or comparability not in _COMPARABILITY
            or amendment not in _ISSUER_AMENDMENTS
            or verdict not in _SAFE_CONTINUATION
        ):
            raise ContinuityFormatError(f"continuity result {path} has an unsupported outcome")
        outcome = ContinuityOutcome(
            _string(record["provider"], f"result{path}/provider"),
            _string(record["transition"], f"result{path}/transition"),
            _string(record["kind"], f"result{path}/kind"),
            _string(record["dimension"], f"result{path}/dimension"),
            _string(record["unit"], f"result{path}/unit"),
            _integer(record["limit_before"], f"result{path}/limit_before", minimum=1),
            _integer(record["limit_after"], f"result{path}/limit_after", minimum=1),
            completed_values,
            state,
            authority_change,
            admission,
            comparability,
            amendment,
            verdict,
            parsed_alignments,
            _result_strings(record["assumptions"], f"{path}/assumptions"),
            _result_strings(record["support"], f"{path}/support"),
        )
        if verdict != _safe_continuation(
            outcome.state,
            outcome.authority_change,
            outcome.admission,
            outcome.comparability,
            outcome.issuer_amendment,
            outcome.alignments,
        ):
            raise ContinuityFormatError(
                f"continuity result {path}/safe_continuation is inconsistent"
            )
        items.append(outcome)
    transitions = [item.transition for item in items]
    if transitions != sorted(set(transitions)):
        raise ContinuityFormatError(
            "continuity result /outcomes must have sorted unique transition identities"
        )
    return tuple(items)


def _parse_findings(value: Any) -> tuple[ContinuityFinding, ...]:
    if not isinstance(value, list):
        raise ContinuityFormatError("continuity result /findings must be an array")
    items = []
    for index, item in enumerate(value):
        path = f"/findings/{index}"
        record = _result_record(item, path, {"code", "transition", "message", "support"})
        code = _string(record["code"], f"result{path}/code")
        if code not in _FINDING_CODES:
            raise ContinuityFormatError(f"continuity result {path}/code is unsupported")
        transition = record["transition"]
        if transition is not None:
            transition = _string(transition, f"result{path}/transition")
        items.append(
            ContinuityFinding(
                code,
                transition,
                _string(record["message"], f"result{path}/message"),
                _result_strings(record["support"], f"{path}/support"),
            )
        )
    keys = [(item.code, item.transition, item.message, item.support) for item in items]
    if len(keys) != len(set(keys)):
        raise ContinuityFormatError("continuity result /findings must be unique")
    return tuple(items)


def _parse_continuity_result_body(value: Any) -> ContinuityResult:
    root = _result_record(
        value,
        "/",
        {"result_version", "schema", "as_of", "inputs", "authority", "outcomes", "findings"},
    )
    if (
        type(root["result_version"]) is not int
        or root["result_version"] != CONTINUITY_RESULT_VERSION
    ):
        raise ContinuityFormatError("unsupported continuity result version")
    if root["schema"] != CONTINUITY_RESULT_SCHEMA:
        raise ContinuityFormatError("unsupported continuity result schema")
    inputs = _result_record(root["inputs"], "/inputs", {"manifest", "provider", "binding"})
    manifest = _result_record(
        inputs["manifest"], "/inputs/manifest", {"locator", "semantic_sha256"}
    )
    provider = _result_identity(inputs["provider"], "/inputs/provider")
    if provider.kind == "continuity-binding":
        raise ContinuityFormatError("continuity result provider identity has the wrong kind")
    binding = inputs["binding"]
    parsed_binding = None if binding is None else _result_identity(binding, "/inputs/binding")
    if parsed_binding is not None and parsed_binding.kind != "continuity-binding":
        raise ContinuityFormatError("continuity result binding identity has the wrong kind")
    outcomes = _parse_outcomes(root["outcomes"])
    expected_provider = (
        "aws-agentcore" if provider.kind == "agentcore-continuity" else "Anthropic"
    )
    if any(outcome.provider != expected_provider for outcome in outcomes):
        raise ContinuityFormatError(
            "continuity result outcome provider does not match its input profile"
        )
    findings = _parse_findings(root["findings"])
    transitions = {outcome.transition for outcome in outcomes}
    if any(
        finding.transition is not None and finding.transition not in transitions
        for finding in findings
    ):
        raise ContinuityFormatError(
            "continuity result finding cites an unknown transition"
        )
    return ContinuityResult(
        CONTINUITY_RESULT_VERSION,
        CONTINUITY_RESULT_SCHEMA,
        _utc(root["as_of"], "result.as_of"),
        ContinuityManifestIdentity(
            _string(manifest["locator"], "result.inputs.manifest.locator"),
            _digest(
                manifest["semantic_sha256"], "result.inputs.manifest.semantic_sha256"
            ),
        ),
        provider,
        parsed_binding,
        _validate_result_authority(root["authority"]),
        outcomes,
        findings,
    )


def _continuity_result_from_json(text: str) -> ContinuityResult:
    value = _load(text, "continuity result")
    root = _result_record(
        value,
        "/",
        {
            "result_version",
            "schema",
            "as_of",
            "inputs",
            "authority",
            "outcomes",
            "findings",
            "result_sha256",
        },
    )
    claimed = _digest(root.pop("result_sha256"), "result.result_sha256")
    actual = hashlib.sha256(_canonical_json(root).encode()).hexdigest()
    if claimed != actual:
        raise ContinuityFormatError("continuity result SHA-256 does not match")
    return _parse_continuity_result_body(root)


def _evaluation_time(as_of: datetime) -> str:
    if (
        not isinstance(as_of, datetime)
        or as_of.tzinfo is None
        or as_of.utcoffset() != timezone.utc.utcoffset(as_of)
        or as_of.microsecond
    ):
        raise ContinuityFormatError("continuity analysis as_of must be a whole-second UTC datetime")
    return as_of.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _eligible_evidence(evidence: ContinuityEvidence, evaluated_at: str) -> bool:
    return (
        evidence.confidence == "exact"
        and evidence.review == "accepted"
        and evidence.reviewer is not None
        and evidence.expires is not None
        and evidence.expires >= evaluated_at[:10]
    )


def _profile_support(
    graph: AuthorityIR,
    control_id: str,
    sources: tuple[ContinuitySource, ...],
    selected_sources: tuple[str, ...],
) -> tuple[str, ...]:
    transition = next(
        entity
        for entity in graph.entities
        if entity.kind == "transition" and entity.name == control_id
    )
    selected_entities = {transition.id}
    selected_edges = []
    for edge in graph.edges:
        if edge.source == transition.id:
            selected_edges.append(edge)
            selected_entities.add(edge.target)
    selected_facts = [fact for fact in graph.facts if fact.subject in selected_entities]
    source_digests = {source.id: source for source in sources}
    return tuple(
        sorted(
            {graph.sources[0].id}
            | {edge.id for edge in selected_edges}
            | {fact.id for fact in selected_facts}
            | {
                f"capture:{source_digests[source_id].locator}:"
                f"{source_digests[source_id].content_sha256}"
                for source_id in selected_sources
            }
        )
    )


def _binding_support(graph: AuthorityIR | None) -> tuple[str, ...]:
    if graph is None:
        return ()
    return tuple(
        sorted(
            {graph.sources[0].id}
            | {fact.id for fact in graph.facts}
            | {edge.id for edge in graph.edges}
        )
    )


def _alignment(
    check: str, status: str, strength: str, support: tuple[str, ...]
) -> ContinuityAlignment:
    return ContinuityAlignment(check, status, strength, support)


def _agentcore_axes(
    control: AgentCoreControl,
    *,
    binding_ready: bool,
) -> tuple[str, str, str, tuple[ContinuityAlignment, ...], tuple[str, ...]]:
    same_boundary = control.boundary_changed is False
    same_mandate = control.same_mandate is True and binding_ready
    outcomes = control.outcomes
    allowed = outcomes.count("allow")

    missing_required_binding = control.same_mandate is True and not binding_ready
    if missing_required_binding:
        state = "unresolved"
    elif same_boundary and outcomes[:2] == ("allow", "deny"):
        state = "preserved"
    elif (
        control.boundary_changed is True
        and same_mandate
        and outcomes[0] == "allow"
        and outcomes[-1] == "allow"
    ):
        state = "reset"
    else:
        state = "unresolved"

    authority = (
        "unresolved"
        if missing_required_binding
        else "stable"
        if len(set(control.provider_limits)) == 1
        else "widens"
        if control.provider_limits[-1] > control.provider_limits[0]
        else "tightens"
    )
    completed = allowed * control.request_amount
    if missing_required_binding or (control.boundary_changed and not same_mandate):
        admission = "unresolved"
    else:
        admission = "overshot" if completed > control.provider_limits[-1] else "within_bound"

    continuity_status = "established" if state != "unresolved" else "unresolved"
    derivation_status = "established" if same_mandate else "unresolved"
    if control.mediation == "platform_verified":
        isolation_status = "established"
        mediation_status = "established"
        boundary_strength = "platform_verified"
    elif control.mediation == "exclusive_adapter":
        isolation_status = "conditional"
        mediation_status = "conditional"
        boundary_strength = "configured"
    else:
        isolation_status = "unresolved"
        mediation_status = "unresolved"
        boundary_strength = "unestablished"
    assumptions = []
    if control.intervals_overlap:
        assumptions.append("completed decisions do not prove reservation of in-flight work")
    if control.mediation == "exclusive_adapter":
        assumptions.append("continuity is conditional on the adapter being the exclusive path")
    return (
        state,
        authority,
        admission,
        (
            _alignment("continuity", continuity_status, "observed", ()),
            _alignment("derivation_integrity", derivation_status, "observed", ()),
            _alignment("isolation", isolation_status, boundary_strength, ()),
            _alignment("complete_mediation", mediation_status, boundary_strength, ()),
        ),
        tuple(assumptions),
    )


def _anthropic_axes(
    control: AnthropicControl,
) -> tuple[str, str, str, tuple[ContinuityAlignment, ...], tuple[str, ...]]:
    before_complete = (
        control.consumed_before is not None
        and len(control.consumed_before) == control.trials
        and all(value > 0 for value in control.consumed_before)
    )
    if control.transition == "fresh_session":
        state = "reset" if before_complete else "unresolved"
    elif control.transition == "limit_revision":
        state = (
            "preserved"
            if before_complete
            and all(
                after >= before
                for before, after in zip(
                    control.consumed_before or (), control.final_costs, strict=True
                )
            )
            else "unresolved"
        )
    elif control.boundary_changed is False:
        state = "preserved"
    else:
        state = "unresolved"
    authority = (
        "stable"
        if control.cap_after == control.cap_before
        else "widens"
        if control.cap_after > control.cap_before
        else "tightens"
    )
    completed = _anthropic_completed(control)
    admission = (
        "unresolved"
        if control.transition == "fresh_session" and not before_complete
        else "overshot"
        if max(completed) > control.cap_after
        else "within_bound"
    )
    assumptions = []
    if control.child_count is not None:
        assumptions.append("completed session cost does not prove in-flight reservation")
    return (
        state,
        authority,
        admission,
        (
            _alignment(
                "continuity",
                "established" if state != "unresolved" else "unresolved",
                "observed",
                (),
            ),
            _alignment("derivation_integrity", "conditional", "documented", ()),
            _alignment("isolation", "unresolved", "unestablished", ()),
            _alignment("complete_mediation", "unresolved", "unestablished", ()),
        ),
        tuple(assumptions),
    )


def _anthropic_completed(control: AnthropicControl) -> tuple[int, ...]:
    if control.transition == "fresh_session" and control.consumed_before is not None:
        return tuple(
            before + after
            for before, after in zip(control.consumed_before, control.final_costs, strict=True)
        )
    return control.final_costs


def _transition_claims(
    control: AgentCoreControl | AnthropicControl,
    *,
    provider_ready: bool,
) -> tuple[str, str]:
    """Return reviewed comparability and issuer-amendment states."""

    if not provider_ready:
        return "unresolved", "unresolved"
    if isinstance(control, AgentCoreControl):
        unchanged = control.boundary_changed is False and control.revision_changed is not True
    else:
        unchanged = control.boundary_changed is False and control.transition == "same_boundary"
    if unchanged:
        return "established", "not_required"
    return "unresolved", "unresolved"


def _safe_continuation(
    state: str,
    authority_change: str,
    admission: str,
    comparability: str,
    issuer_amendment: str,
    alignments: tuple[ContinuityAlignment, ...],
) -> str:
    """Derive the private three-valued safe-continuation verdict."""

    if "unresolved" in {state, authority_change, admission, comparability, issuer_amendment} or any(
        item.status != "established" for item in alignments
    ):
        return "unresolved"
    if issuer_amendment == "approved":
        return "satisfied" if admission == "within_bound" else "violated"
    if state == "reset" or authority_change == "widens" or admission == "overshot":
        return "violated"
    if (
        state == "preserved"
        and authority_change in {"stable", "tightens"}
        and admission == "within_bound"
        and comparability == "established"
        and issuer_amendment == "not_required"
    ):
        return "satisfied"
    return "unresolved"


def _manifest_binding_matches(
    mandate: Mandate,
    mandate_bytes: bytes | None,
    binding: ContinuityBinding,
) -> bool:
    if not isinstance(mandate_bytes, bytes):
        return False
    try:
        parsed = loads(mandate_bytes.decode("utf-8"), source=mandate.source)
    except (UnicodeDecodeError, ManifestError):
        return False
    principal_matches = binding.principal == mandate.identity or binding.principal in {
        tool.principal for tool in mandate.tools
    }
    return (
        parsed == mandate
        and hashlib.sha256(mandate_bytes).hexdigest() == binding.mandate_sha256
        and principal_matches
    )


def analyse_continuity(
    mandate: Mandate,
    provider: AgentCoreContinuity | AnthropicContinuity,
    source_bytes: Mapping[str, bytes],
    *,
    as_of: datetime,
    binding: ContinuityBinding | None = None,
    binding_source_bytes: Mapping[str, bytes] | None = None,
    mandate_bytes: bytes | None = None,
    depth: int | None = None,
    composition: frozenset[str] = frozenset(),
) -> ContinuityAnalysis:
    """Reconcile reviewed transitions without changing manifest authority.

    Records are strictly re-read, source-verified, projected, and closed-profile
    validated at this consumption boundary. Trust failures keep every transition
    unresolved and always retain ordinary manifest reachability.
    """

    _refuse_continuity_composition(composition)
    evaluated_at = _evaluation_time(as_of)
    authority = analyse(mandate, depth=depth)
    canonical_provider = (
        AgentCoreContinuity.from_json(provider.to_json())
        if isinstance(provider, AgentCoreContinuity)
        else AnthropicContinuity.from_json(provider.to_json())
    )
    provider_graph = AuthorityIR.from_json(canonical_provider.to_ir().to_json())
    provider_kind = (
        "agentcore-continuity"
        if isinstance(canonical_provider, AgentCoreContinuity)
        else "anthropic-continuity"
    )
    provider_adapter = (
        AGENTCORE_CONTINUITY_IR_ADAPTER
        if isinstance(canonical_provider, AgentCoreContinuity)
        else ANTHROPIC_CONTINUITY_IR_ADAPTER
    )
    findings: list[ContinuityFinding] = []
    provider_ready = True
    try:
        canonical_provider.verify_sources(dict(source_bytes))
        _validate_continuity_profile(provider_graph, provider_kind, provider_adapter)
    except (ContinuityFormatError, IRFormatError) as exc:
        provider_ready = False
        findings.append(ContinuityFinding("continuity.source-untrusted", None, str(exc), ()))
    if not _eligible_evidence(canonical_provider.evidence, evaluated_at):
        provider_ready = False
        findings.append(
            ContinuityFinding(
                "continuity.evidence-untrusted",
                None,
                "continuity profile is not exact, accepted, and current",
                (provider_graph.sources[0].id,),
            )
        )

    canonical_binding = None
    binding_graph = None
    binding_ready = False
    if binding is not None:
        canonical_binding = ContinuityBinding.from_json(binding.to_json())
        binding_graph = AuthorityIR.from_json(canonical_binding.to_ir().to_json())
        try:
            canonical_binding.verify_sources(dict(binding_source_bytes or {}))
            _validate_continuity_profile(
                binding_graph,
                "continuity-binding",
                CONTINUITY_BINDING_IR_ADAPTER,
            )
            binding_ready = (
                _eligible_evidence(canonical_binding.evidence, evaluated_at)
                and canonical_binding.issued_at <= evaluated_at < canonical_binding.expires_at
                and canonical_binding.provider == canonical_provider.provider
                and (
                    not isinstance(canonical_provider, AgentCoreContinuity)
                    or canonical_binding.binding == canonical_provider.binding
                )
                and _manifest_binding_matches(mandate, mandate_bytes, canonical_binding)
            )
        except (ContinuityFormatError, IRFormatError):
            binding_ready = False
        if not binding_ready:
            findings.append(
                ContinuityFinding(
                    "continuity.binding-untrusted",
                    None,
                    "continuity binding is not exact, accepted, current, and joined to the mandate",
                    _binding_support(binding_graph),
                )
            )

    outcomes = []
    for control in canonical_provider.controls:
        control_binding_support = (
            _binding_support(binding_graph)
            if isinstance(control, AgentCoreControl) and control.same_mandate is True
            else ()
        )
        support = tuple(
            sorted(
                set(
                    _profile_support(
                        provider_graph,
                        control.id,
                        canonical_provider.sources,
                        control.sources,
                    )
                    + control_binding_support
                )
            )
        )
        if not provider_ready:
            axes = (
                "unresolved",
                "unresolved",
                "unresolved",
                tuple(
                    _alignment(check, "unresolved", "unestablished", support)
                    for check in (
                        "continuity",
                        "derivation_integrity",
                        "isolation",
                        "complete_mediation",
                    )
                ),
                (),
            )
        elif isinstance(control, AgentCoreControl):
            control_binding_ready = (
                binding_ready
                and canonical_binding is not None
                and canonical_binding.mediation == control.mediation
            )
            axes = _agentcore_axes(control, binding_ready=control_binding_ready)
        else:
            axes = _anthropic_axes(control)
        state, authority_change, admission, alignments, assumptions = axes
        alignments = tuple(
            ContinuityAlignment(item.check, item.status, item.strength, support)
            for item in alignments
        )
        comparability, issuer_amendment = _transition_claims(
            control,
            provider_ready=provider_ready,
        )
        safe_continuation = _safe_continuation(
            state,
            authority_change,
            admission,
            comparability,
            issuer_amendment,
            alignments,
        )
        outcome = ContinuityOutcome(
            canonical_provider.provider,
            control.id,
            control.transition,
            (
                "tool_argument.process_refund.amount"
                if isinstance(control, AgentCoreControl)
                else "session_cost"
            ),
            "integer" if isinstance(control, AgentCoreControl) else "minor_currency_unit",
            (
                control.provider_limits[0]
                if isinstance(control, AgentCoreControl)
                else control.cap_before
            ),
            (
                control.provider_limits[-1]
                if isinstance(control, AgentCoreControl)
                else control.cap_after
            ),
            (
                (control.outcomes.count("allow") * control.request_amount,)
                if isinstance(control, AgentCoreControl)
                else _anthropic_completed(control)
            ),
            state,
            authority_change,
            admission,
            comparability,
            issuer_amendment,
            safe_continuation,
            alignments,
            assumptions,
            support,
        )
        outcomes.append(outcome)
        if provider_ready:
            if state == "reset":
                findings.append(
                    ContinuityFinding(
                        "continuity.state-reset",
                        control.id,
                        "consumed authority did not survive the transition",
                        support,
                    )
                )
            elif state == "unresolved":
                findings.append(
                    ContinuityFinding(
                        "continuity.state-unresolved",
                        control.id,
                        "the capture cannot establish one mandate across the transition",
                        support,
                    )
                )
            if authority_change == "widens":
                findings.append(
                    ContinuityFinding(
                        "continuity.authority-widens",
                        control.id,
                        "remaining authority increased without a cited successor approval",
                        support,
                    )
                )
            if admission == "overshot":
                findings.append(
                    ContinuityFinding(
                        "continuity.admission-overshot",
                        control.id,
                        "completed usage exceeded the reviewed transition bound",
                        support,
                    )
                )
            for alignment in alignments:
                if alignment.status != "established":
                    findings.append(
                        ContinuityFinding(
                            f"continuity.{alignment.check.replace('_', '-')}-unresolved",
                            control.id,
                            f"{alignment.check.replace('_', ' ')} is {alignment.status}",
                            support,
                        )
                    )
    unique_findings = tuple(
        dict.fromkeys((item.code, item.transition, item.message, item.support) for item in findings)
    )
    manifest_source = next(
        source for source in _from_mandate(mandate).sources if source.id == "source:mandate"
    )
    provider_source = provider_graph.sources[0]
    provider_identity = ContinuityArtifactIdentity(
        provider_kind,
        (
            canonical_provider.binding
            if isinstance(canonical_provider, AgentCoreContinuity)
            else canonical_provider.binding_sha256
        ),
        provider_source.content_sha256 or "",
        provider_source.semantic_sha256,
    )
    binding_identity = None
    if canonical_binding is not None and binding_graph is not None:
        binding_source = binding_graph.sources[0]
        binding_identity = ContinuityArtifactIdentity(
            "continuity-binding",
            canonical_binding.id,
            binding_source.content_sha256 or "",
            binding_source.semantic_sha256,
        )
    return ContinuityAnalysis(
        authority,
        evaluated_at,
        tuple(outcomes),
        tuple(ContinuityFinding(*item) for item in unique_findings),
        ContinuityManifestIdentity(
            manifest_source.locator, manifest_source.semantic_sha256
        ),
        provider_identity,
        binding_identity,
    )
