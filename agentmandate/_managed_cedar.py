"""Private records for digest-pinned managed Cedar enforcement captures.

This profile is deliberately separate from :mod:`agentmandate._cedar`.  A
managed AgentCore response does not expose the local Cedar schema, entities,
validation diagnostics, or determining policies required by ``CedarBundle``.
The reader proves transport structure and caller-supplied byte identity only;
analysis eligibility is a later gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any

from ._cedar import CedarBundleFormatError, CedarMapping, _mapping
from ._ir import (
    IR_VERSION,
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
from .manifest import Mandate, ManifestError, loads
from .reach import Authority, analyse

MANAGED_ORACLE_VERSION = 1
MANAGED_ADAPTER = "agentmandate.agentcore-managed-capture"
MANAGED_ADAPTER_VERSION = 1
MANAGED_IR_ADAPTER = "agentmandate.managed-cedar-oracle"
MANAGED_IR_ADAPTER_VERSION = 1
SOURCE_KINDS = frozenset(
    {
        "decision_request",
        "decision_response",
        "deployment_mapping",
        "handler_source",
        "managed_state",
        "manifest",
        "policy",
        "protocol_output",
        "tool_inventory_request",
        "tool_inventory_response",
        "tool_schema",
    }
)
REQUIRED_SOURCE_KINDS = frozenset(
    {
        "decision_request",
        "decision_response",
        "deployment_mapping",
        "managed_state",
        "manifest",
        "policy",
        "tool_inventory_response",
        "tool_schema",
    }
)
OUTCOMES = frozenset({"allow", "deny"})
REASONS = frozenset({"managed_allow", "default_deny", "explicit_deny"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ManagedOracleFormatError(ValueError):
    """Raised when a managed enforcement record violates its closed contract."""


@dataclass(frozen=True)
class ManagedProvider:
    name: str
    region: str
    protocol: str
    protocol_version: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "region": self.region,
            "protocol": self.protocol,
            "protocol_version": self.protocol_version,
        }


@dataclass(frozen=True)
class ManagedAdapter:
    name: str
    version: int

    def as_dict(self) -> dict[str, str | int]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True)
class ManagedSource:
    kind: str
    locator: str
    content_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class ManagedState:
    source: str
    authorizer_type: str
    gateway_status: str
    policy_engine_status: str
    policy_engine_mode: str
    requested_validation_mode: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source": self.source,
            "authorizer_type": self.authorizer_type,
            "gateway_status": self.gateway_status,
            "policy_engine_status": self.policy_engine_status,
            "policy_engine_mode": self.policy_engine_mode,
            "requested_validation_mode": self.requested_validation_mode,
        }


@dataclass(frozen=True)
class ManagedPolicy:
    name: str
    status: str
    enforcement_mode: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "enforcement_mode": self.enforcement_mode,
        }


@dataclass(frozen=True)
class ManagedInventory:
    source: str
    complete: bool
    members: tuple[str, ...] | tuple[ManagedPolicy, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "complete": self.complete,
            "members": [
                member.as_dict() if isinstance(member, ManagedPolicy) else member
                for member in self.members
            ],
        }


@dataclass(frozen=True)
class ManagedDecision:
    id: str
    request: str
    response: str
    outcome: str
    reason: str
    method: str
    tool: str
    arguments: dict[str, Any]

    @property
    def request_key(self) -> str:
        return json.dumps(
            {"method": self.method, "tool": self.tool, "arguments": self.arguments},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request": self.request,
            "response": self.response,
            "outcome": self.outcome,
            "reason": self.reason,
            "method": self.method,
            "tool": self.tool,
            "arguments": self.arguments,
        }


@dataclass(frozen=True)
class ManagedAlias:
    cedar_type: str
    binding: str
    placeholder: str

    def as_dict(self) -> dict[str, str]:
        return {
            "cedar_type": self.cedar_type,
            "binding": self.binding,
            "placeholder": self.placeholder,
        }


@dataclass(frozen=True)
class ManagedSanitization:
    source: str
    omitted: tuple[str, ...]
    decision_messages_changed: bool
    aliases: tuple[ManagedAlias, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "omitted": list(self.omitted),
            "decision_messages_changed": self.decision_messages_changed,
            "aliases": [alias.as_dict() for alias in self.aliases],
        }


@dataclass(frozen=True)
class ManagedOracle:
    managed_oracle_version: int
    provider: ManagedProvider
    adapter: ManagedAdapter
    capture_date: str
    sources: tuple[ManagedSource, ...]
    state: ManagedState
    tool_inventory: ManagedInventory
    policy_inventory: ManagedInventory
    mapping: CedarMapping
    decisions: tuple[ManagedDecision, ...]
    sanitization: ManagedSanitization

    def as_dict(self) -> dict[str, Any]:
        return {
            "managed_oracle_version": self.managed_oracle_version,
            "provider": self.provider.as_dict(),
            "adapter": self.adapter.as_dict(),
            "capture_date": self.capture_date,
            "sources": [source.as_dict() for source in self.sources],
            "state": self.state.as_dict(),
            "tool_inventory": self.tool_inventory.as_dict(),
            "policy_inventory": self.policy_inventory.as_dict(),
            "mapping": self.mapping.as_dict(),
            "decisions": [decision.as_dict() for decision in self.decisions],
            "sanitization": self.sanitization.as_dict(),
        }

    def to_json(self) -> str:
        return (
            json.dumps(
                self.as_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        )

    @classmethod
    def from_json(cls, text: str) -> ManagedOracle:
        try:
            raw = json.loads(
                text,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ValueError("non-finite number")
                ),
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            detail = (
                f" at line {exc.lineno} column {exc.colno}"
                if isinstance(exc, json.JSONDecodeError)
                else ""
            )
            raise ManagedOracleFormatError(
                f"managed Cedar oracle is not valid JSON{detail}"
            ) from exc
        root = _record(
            raw,
            "root",
            {
                "managed_oracle_version",
                "provider",
                "adapter",
                "capture_date",
                "sources",
                "state",
                "tool_inventory",
                "policy_inventory",
                "mapping",
                "decisions",
                "sanitization",
            },
        )
        version = root["managed_oracle_version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ManagedOracleFormatError(
                "unsupported managed Cedar oracle version type; "
                f"this build reads {MANAGED_ORACLE_VERSION}"
            )
        if version != MANAGED_ORACLE_VERSION:
            raise ManagedOracleFormatError(
                f"unsupported managed Cedar oracle version {version}; "
                f"this build reads {MANAGED_ORACLE_VERSION}"
            )
        try:
            mapping = _mapping(root["mapping"])
        except CedarBundleFormatError as exc:
            raise ManagedOracleFormatError("managed Cedar oracle mapping is invalid") from exc
        oracle = cls(
            version,
            _provider(root["provider"]),
            _adapter(root["adapter"]),
            _date(root["capture_date"], "capture_date"),
            _sources(root["sources"]),
            _state(root["state"]),
            _inventory(root["tool_inventory"], "tool_inventory", policies=False),
            _inventory(root["policy_inventory"], "policy_inventory", policies=True),
            mapping,
            _decisions(root["decisions"]),
            _sanitization(root["sanitization"]),
        )
        _references(oracle)
        return oracle

    def verify_sources(self, contents: Mapping[str, bytes]) -> None:
        if not isinstance(contents, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, bytes)
            for key, value in contents.items()
        ):
            raise ManagedOracleFormatError(
                "managed Cedar oracle source contents must be a locator-to-bytes mapping"
            )
        expected = {source.locator for source in self.sources}
        if set(contents) != expected:
            missing = sorted(expected - set(contents))
            extra = sorted(set(contents) - expected)
            locator = missing[0] if missing else extra[0]
            raise ManagedOracleFormatError(
                f"managed Cedar oracle source bytes do not match declared locator '{locator}'"
            )
        for source in self.sources:
            if hashlib.sha256(contents[source.locator]).hexdigest() != source.content_sha256:
                raise ManagedOracleFormatError(
                    f"managed Cedar oracle source digest does not match locator '{source.locator}'"
                )
        _verify_projection(self, contents)

    def to_ir(self) -> AuthorityIR:
        """Project transport facts without making them analyzable authority."""
        return _managed_to_ir(self)


@dataclass(frozen=True)
class ManagedFinding:
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class ManagedAlignment:
    decision: str
    request_key: str
    tool: str | None
    outcome: str
    reason: str
    alignment: str
    support: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "request_key": self.request_key,
            "tool": self.tool,
            "outcome": self.outcome,
            "reason": self.reason,
            "alignment": self.alignment,
            "support": list(self.support),
        }


@dataclass(frozen=True)
class ManagedAnalysis:
    authority: Authority
    as_of: str
    alignments: tuple[ManagedAlignment, ...]
    findings: tuple[ManagedFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings and all(
            item.alignment == "aligned_allow" for item in self.alignments
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "authority": self.authority.as_dict(),
            "alignments": [item.as_dict() for item in self.alignments],
            "findings": [item.as_dict() for item in self.findings],
            "clean": self.clean,
        }


@dataclass(frozen=True)
class ManagedChange:
    request_key: str
    tool: str | None
    baseline: str
    candidate: str
    classification: str
    support: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_key": self.request_key,
            "tool": self.tool,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "classification": self.classification,
            "support": list(self.support),
        }


@dataclass(frozen=True)
class ManagedDiff:
    baseline: ManagedAnalysis
    candidate: ManagedAnalysis
    changes: tuple[ManagedChange, ...]
    findings: tuple[ManagedFinding, ...]

    @property
    def clean(self) -> bool:
        return (
            self.baseline.clean
            and self.candidate.clean
            and not self.findings
            and all(item.classification.startswith("stable_") for item in self.changes)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.as_dict(),
            "candidate": self.candidate.as_dict(),
            "changes": [item.as_dict() for item in self.changes],
            "findings": [item.as_dict() for item in self.findings],
            "clean": self.clean,
        }


def _record(value: Any, path: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManagedOracleFormatError(f"managed Cedar oracle {path} must be an object")
    missing = fields - set(value)
    extra = set(value) - fields
    if missing:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle {path} is missing field '{min(missing)}'"
        )
    if extra:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle {path} has unknown field '{min(extra)}'"
        )
    return value


def _name(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ManagedOracleFormatError(
            f"managed Cedar oracle {path} must be a non-empty stripped string"
        )
    return value


def _positive_integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ManagedOracleFormatError(f"managed Cedar oracle {path} must be a positive integer")
    return value


def _date(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ManagedOracleFormatError(f"managed Cedar oracle {path} must be a canonical date")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle {path} must be a canonical date"
        ) from exc
    return value


def _relative(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle {path} must be a repository-relative POSIX path"
        )
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or str(candidate) != value or ".." in candidate.parts:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle {path} must be a repository-relative POSIX path"
        )
    return value


def _digest(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ManagedOracleFormatError(f"managed Cedar oracle {path} must be lowercase SHA-256")
    return value


def _strings(value: Any, path: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ManagedOracleFormatError(f"managed Cedar oracle {path} must be an array of strings")
    if (not allow_empty and not value) or any(not item or item != item.strip() for item in value):
        raise ManagedOracleFormatError(
            f"managed Cedar oracle {path} members must be non-empty and stripped"
        )
    if len(value) != len(set(value)):
        raise ManagedOracleFormatError(f"managed Cedar oracle {path} contains duplicates")
    return tuple(sorted(value))


def _provider(raw: Any) -> ManagedProvider:
    value = _record(raw, "provider", {"name", "region", "protocol", "protocol_version"})
    return ManagedProvider(
        _name(value["name"], "provider.name"),
        _name(value["region"], "provider.region"),
        _name(value["protocol"], "provider.protocol"),
        _name(value["protocol_version"], "provider.protocol_version"),
    )


def _adapter(raw: Any) -> ManagedAdapter:
    value = _record(raw, "adapter", {"name", "version"})
    name = _name(value["name"], "adapter.name")
    version = _positive_integer(value["version"], "adapter.version")
    if (name, version) != (MANAGED_ADAPTER, MANAGED_ADAPTER_VERSION):
        raise ManagedOracleFormatError("managed Cedar oracle has an unsupported adapter")
    return ManagedAdapter(name, version)


def _sources(raw: Any) -> tuple[ManagedSource, ...]:
    if not isinstance(raw, list) or not raw:
        raise ManagedOracleFormatError("managed Cedar oracle sources must be a non-empty array")
    result = []
    for index, item in enumerate(raw):
        path = f"sources[{index}]"
        value = _record(item, path, {"kind", "locator", "content_sha256"})
        kind = _name(value["kind"], f"{path}.kind")
        if kind not in SOURCE_KINDS:
            raise ManagedOracleFormatError(f"managed Cedar oracle {path}.kind is invalid")
        result.append(
            ManagedSource(
                kind,
                _relative(value["locator"], f"{path}.locator"),
                _digest(value["content_sha256"], f"{path}.content_sha256"),
            )
        )
    locators = [item.locator for item in result]
    if len(locators) != len(set(locators)):
        raise ManagedOracleFormatError("managed Cedar oracle sources contain duplicate locators")
    missing = REQUIRED_SOURCE_KINDS - {item.kind for item in result}
    if missing:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle sources are missing required kind '{min(missing)}'"
        )
    return tuple(sorted(result, key=lambda item: item.locator))


def _state(raw: Any) -> ManagedState:
    fields = {
        "source",
        "authorizer_type",
        "gateway_status",
        "policy_engine_status",
        "policy_engine_mode",
        "requested_validation_mode",
    }
    value = _record(raw, "state", fields)
    return ManagedState(
        _relative(value["source"], "state.source"),
        _name(value["authorizer_type"], "state.authorizer_type"),
        _name(value["gateway_status"], "state.gateway_status"),
        _name(value["policy_engine_status"], "state.policy_engine_status"),
        _name(value["policy_engine_mode"], "state.policy_engine_mode"),
        _name(value["requested_validation_mode"], "state.requested_validation_mode"),
    )


def _inventory(raw: Any, path: str, *, policies: bool) -> ManagedInventory:
    value = _record(raw, path, {"source", "complete", "members"})
    if not isinstance(value["complete"], bool):
        raise ManagedOracleFormatError(f"managed Cedar oracle {path}.complete must be boolean")
    if policies:
        if not isinstance(value["members"], list):
            raise ManagedOracleFormatError(f"managed Cedar oracle {path}.members must be an array")
        members: tuple[str, ...] | tuple[ManagedPolicy, ...] = tuple(
            sorted(
                (
                    ManagedPolicy(
                        _name(item_value["name"], f"{path}.members[{index}].name"),
                        _name(item_value["status"], f"{path}.members[{index}].status"),
                        _name(
                            item_value["enforcement_mode"],
                            f"{path}.members[{index}].enforcement_mode",
                        ),
                    )
                    for index, item in enumerate(value["members"])
                    for item_value in [
                        _record(
                            item, f"{path}.members[{index}]", {"name", "status", "enforcement_mode"}
                        )
                    ]
                ),
                key=lambda item: item.name,
            )
        )
        names = [item.name for item in members]
        if not members or len(names) != len(set(names)):
            raise ManagedOracleFormatError(
                f"managed Cedar oracle {path}.members must be non-empty and unique"
            )
    else:
        members = _strings(value["members"], f"{path}.members", allow_empty=False)
    return ManagedInventory(
        _relative(value["source"], f"{path}.source"), value["complete"], members
    )


def _decisions(raw: Any) -> tuple[ManagedDecision, ...]:
    if not isinstance(raw, list) or not raw:
        raise ManagedOracleFormatError("managed Cedar oracle decisions must be a non-empty array")
    result = []
    fields = {"id", "request", "response", "outcome", "reason", "method", "tool", "arguments"}
    for index, item in enumerate(raw):
        path = f"decisions[{index}]"
        value = _record(item, path, fields)
        outcome = _name(value["outcome"], f"{path}.outcome")
        reason = _name(value["reason"], f"{path}.reason")
        if outcome not in OUTCOMES or reason not in REASONS:
            raise ManagedOracleFormatError(f"managed Cedar oracle {path} has an invalid outcome")
        if (outcome == "allow") != (reason == "managed_allow"):
            raise ManagedOracleFormatError(
                f"managed Cedar oracle {path} outcome contradicts reason"
            )
        arguments = value["arguments"]
        if not isinstance(arguments, dict) or any(not isinstance(key, str) for key in arguments):
            raise ManagedOracleFormatError(
                f"managed Cedar oracle {path}.arguments must be a JSON object"
            )
        canonical_arguments = json.loads(json.dumps(arguments, sort_keys=True))
        result.append(
            ManagedDecision(
                _name(value["id"], f"{path}.id"),
                _relative(value["request"], f"{path}.request"),
                _relative(value["response"], f"{path}.response"),
                outcome,
                reason,
                _name(value["method"], f"{path}.method"),
                _name(value["tool"], f"{path}.tool"),
                canonical_arguments,
            )
        )
    ids = [item.id for item in result]
    keys = [item.request_key for item in result]
    if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
        raise ManagedOracleFormatError("managed Cedar oracle decisions contain duplicates")
    return tuple(sorted(result, key=lambda item: item.id))


def _sanitization(raw: Any) -> ManagedSanitization:
    value = _record(
        raw, "sanitization", {"source", "omitted", "decision_messages_changed", "aliases"}
    )
    if not isinstance(value["decision_messages_changed"], bool):
        raise ManagedOracleFormatError(
            "managed Cedar oracle sanitization.decision_messages_changed must be boolean"
        )
    if not isinstance(value["aliases"], list) or not value["aliases"]:
        raise ManagedOracleFormatError(
            "managed Cedar oracle sanitization.aliases must be non-empty"
        )
    aliases = []
    for index, item in enumerate(value["aliases"]):
        path = f"sanitization.aliases[{index}]"
        item_value = _record(item, path, {"cedar_type", "binding", "placeholder"})
        aliases.append(
            ManagedAlias(
                _name(item_value["cedar_type"], f"{path}.cedar_type"),
                _name(item_value["binding"], f"{path}.binding"),
                _name(item_value["placeholder"], f"{path}.placeholder"),
            )
        )
    if len({(item.cedar_type, item.binding) for item in aliases}) != len(aliases):
        raise ManagedOracleFormatError("managed Cedar oracle sanitization aliases conflict")
    return ManagedSanitization(
        _relative(value["source"], "sanitization.source"),
        _strings(value["omitted"], "sanitization.omitted"),
        value["decision_messages_changed"],
        tuple(sorted(aliases, key=lambda item: (item.cedar_type, item.binding))),
    )


def _references(oracle: ManagedOracle) -> None:
    if len(oracle.mapping.resources) != 1:
        raise ManagedOracleFormatError(
            "managed Cedar oracle mapping must identify exactly one resource binding"
        )
    kinds = {source.locator: source.kind for source in oracle.sources}
    expected = {
        oracle.state.source: "managed_state",
        oracle.tool_inventory.source: "tool_inventory_response",
        oracle.policy_inventory.source: "managed_state",
        oracle.mapping.source: "deployment_mapping",
        oracle.mapping.target.source: "manifest",
        oracle.sanitization.source: "managed_state",
    }
    for locator, kind in expected.items():
        if kinds.get(locator) != kind:
            raise ManagedOracleFormatError(
                f"managed Cedar oracle reference '{locator}' must name source kind '{kind}'"
            )
    for decision in oracle.decisions:
        if (
            kinds.get(decision.request) != "decision_request"
            or kinds.get(decision.response) != "decision_response"
        ):
            raise ManagedOracleFormatError(
                f"managed Cedar oracle decision '{decision.id}' has invalid source references"
            )


def _json_source(contents: Mapping[str, bytes], locator: str) -> Any:
    try:
        return json.loads(contents[locator])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle source '{locator}' is not valid JSON"
        ) from exc


def _verify_projection(oracle: ManagedOracle, contents: Mapping[str, bytes]) -> None:
    try:
        projected_mapping = _mapping(_json_source(contents, oracle.mapping.source))
    except CedarBundleFormatError as exc:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle mapping source '{oracle.mapping.source}' is invalid"
        ) from exc
    if projected_mapping != oracle.mapping:
        raise ManagedOracleFormatError("managed Cedar oracle mapping source disagrees with record")
    try:
        mandate = loads(
            contents[oracle.mapping.target.source].decode("utf-8"),
            source=oracle.mapping.target.source,
        )
    except (ManifestError, UnicodeDecodeError) as exc:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle manifest source '{oracle.mapping.target.source}' is invalid"
        ) from exc
    if mandate.agent != oracle.mapping.target.agent or set(mandate.tool_names) != {
        item.tool for item in oracle.mapping.actions
    }:
        raise ManagedOracleFormatError(
            "managed Cedar oracle mapping target disagrees with manifest"
        )
    listed = _json_source(contents, oracle.tool_inventory.source)
    try:
        listed_names = {item["name"] for item in listed["result"]["tools"]}
    except (KeyError, TypeError) as exc:
        raise ManagedOracleFormatError(
            "managed Cedar oracle tool inventory source "
            f"'{oracle.tool_inventory.source}' has invalid shape"
        ) from exc
    if listed_names != set(oracle.tool_inventory.members):
        raise ManagedOracleFormatError("managed Cedar oracle tool inventory disagrees with record")
    schema_source = next(source for source in oracle.sources if source.kind == "tool_schema")
    schema = _json_source(contents, schema_source.locator)
    try:
        schema_names = {item["name"] for item in schema}
    except (KeyError, TypeError) as exc:
        raise ManagedOracleFormatError(
            f"managed Cedar oracle tool schema source '{schema_source.locator}' has invalid shape"
        ) from exc
    if schema_names != set(mandate.tool_names):
        raise ManagedOracleFormatError("managed Cedar oracle tool schema disagrees with manifest")
    mapped_actions = {item.cedar for item in oracle.mapping.actions}
    if mapped_actions != {f'AgentCore::Action::"{name}"' for name in listed_names}:
        raise ManagedOracleFormatError("managed Cedar oracle actions disagree with tool inventory")
    state = _json_source(contents, oracle.state.source)
    policies = tuple(oracle.policy_inventory.members)
    if (
        state.get("gateway")
        != {
            "authorizer_type": oracle.state.authorizer_type,
            "policy_engine_mode": oracle.state.policy_engine_mode,
            "protocol_type": oracle.provider.protocol,
            "status": oracle.state.gateway_status,
        }
        or state.get("policy_engine") != {"status": oracle.state.policy_engine_status}
        or len(policies) != 1
        or state.get("policy")
        != {
            "enforcement_mode": policies[0].enforcement_mode,
            "inventory_count": 1,
            "name": policies[0].name,
            "requested_validation_mode": oracle.state.requested_validation_mode,
            "status": policies[0].status,
        }
        or state.get("tool_inventory_complete") is not oracle.tool_inventory.complete
        or state.get("sanitization", {}).get("decision_messages_changed")
        is not oracle.sanitization.decision_messages_changed
        or set(state.get("sanitization", {}).get("omitted", [])) != set(oracle.sanitization.omitted)
        or state.get("sanitization", {}).get("policy_resource_replaced_with_binding") is not True
    ):
        raise ManagedOracleFormatError(
            "managed Cedar oracle managed-state source disagrees with record"
        )
    policy_source = next(source for source in oracle.sources if source.kind == "policy")
    policy_text = contents[policy_source.locator].decode("utf-8")
    if any(
        alias.placeholder not in policy_text
        or not any(
            resource.cedar_type == alias.cedar_type and resource.binding == alias.binding
            for resource in oracle.mapping.resources
        )
        for alias in oracle.sanitization.aliases
    ):
        raise ManagedOracleFormatError("managed Cedar oracle sanitization aliases do not join")
    for decision in oracle.decisions:
        request = _json_source(contents, decision.request)
        response = _json_source(contents, decision.response)
        expected_request = {
            "jsonrpc": "2.0",
            "id": decision.id,
            "method": decision.method,
            "params": {"arguments": decision.arguments, "name": decision.tool},
        }
        if request != expected_request:
            raise ManagedOracleFormatError(
                f"managed Cedar oracle request source '{decision.request}' disagrees with record"
            )
        result = response.get("result") if isinstance(response, dict) else None
        allowed = (
            isinstance(result, dict)
            and result.get("isError") is False
            and response.get("error") is None
        )
        error = response.get("error") if isinstance(response, dict) else None
        denied = isinstance(error, dict) and error.get("code") == -32002
        default_denied = denied and "denied by default" in str(error.get("message", "")).lower()
        # This adapter has captured AgentCore's default-deny diagnostic only.
        # Do not invent an explicit-deny response shape before service evidence
        # establishes one and an adapter-version change pins it.
        response_matches = (
            decision.outcome == "allow"
            and decision.reason == "managed_allow"
            and allowed
        ) or (
            decision.outcome == "deny"
            and decision.reason == "default_deny"
            and default_denied
        )
        if not response_matches:
            raise ManagedOracleFormatError(
                f"managed Cedar oracle response source '{decision.response}' disagrees with outcome"
            )


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
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _projection_parts(
    oracle: ManagedOracle, source_id: str
) -> tuple[tuple[Entity, ...], tuple[Fact, ...], tuple[Edge, ...]]:
    binding = oracle.mapping.resources[0].binding
    root_id = _entity_id("enforcement_point", binding)
    tool_ids = {action.tool: _entity_id("tool", action.tool) for action in oracle.mapping.actions}
    action_ids = {
        action.cedar: _entity_id("policy_action", action.cedar) for action in oracle.mapping.actions
    }
    policy_ids = {
        policy.name: _entity_id("policy", policy.name) for policy in oracle.policy_inventory.members
    }
    request_ids = {decision.id: _entity_id("request", decision.id) for decision in oracle.decisions}
    decision_ids = {
        decision.id: _entity_id("decision", decision.id) for decision in oracle.decisions
    }
    entities = (
        Entity(root_id, "enforcement_point", binding),
        *(
            Entity(action_ids[action.cedar], "policy_action", action.cedar)
            for action in oracle.mapping.actions
        ),
        *(Entity(tool_ids[name], "tool", name) for name in sorted(tool_ids)),
        *(Entity(policy_ids[name], "policy", name) for name in sorted(policy_ids)),
        *(
            Entity(request_ids[decision.id], "request", decision.id)
            for decision in oracle.decisions
        ),
        *(
            Entity(decision_ids[decision.id], "decision", decision.id)
            for decision in oracle.decisions
        ),
    )

    def fact(subject: str, predicate: str, value: Any, location: str) -> Fact:
        return Fact(
            _fact_id(subject, predicate),
            subject,
            predicate,
            value,
            (Evidence(source_id, location, "exact", "unreviewed"),),
        )

    facts: list[Fact] = [
        fact(root_id, "name", binding, "/mapping/resources/0/binding"),
        fact(root_id, "oracle", oracle.as_dict(), ""),
        fact(
            root_id,
            "decisions",
            [decision_ids[item.id] for item in oracle.decisions],
            "/decisions",
        ),
    ]
    for action in oracle.mapping.actions:
        action_id = action_ids[action.cedar]
        facts.extend(
            (
                fact(action_id, "name", action.cedar, "/mapping/actions"),
                fact(action_id, "tool", tool_ids[action.tool], "/mapping/actions"),
            )
        )
    for name, tool_id in sorted(tool_ids.items()):
        facts.append(fact(tool_id, "name", name, "/mapping/actions"))
    for name, policy_id in sorted(policy_ids.items()):
        policy = next(item for item in oracle.policy_inventory.members if item.name == name)
        facts.extend(
            (
                fact(policy_id, "name", name, "/policy_inventory/members"),
                fact(policy_id, "status", policy.status, "/policy_inventory/members"),
                fact(
                    policy_id,
                    "enforcement_mode",
                    policy.enforcement_mode,
                    "/policy_inventory/members",
                ),
            )
        )
    for index, decision in enumerate(oracle.decisions):
        location = f"/decisions/{index}"
        request_id = request_ids[decision.id]
        decision_id = decision_ids[decision.id]
        facts.extend(
            (
                fact(request_id, "name", decision.id, f"{location}/id"),
                fact(request_id, "request_key", decision.request_key, location),
                fact(request_id, "method", decision.method, f"{location}/method"),
                fact(request_id, "tool_name", decision.tool, f"{location}/tool"),
                fact(request_id, "arguments", decision.arguments, f"{location}/arguments"),
                fact(request_id, "source", decision.request, f"{location}/request"),
                fact(decision_id, "name", decision.id, f"{location}/id"),
                fact(decision_id, "outcome", decision.outcome, f"{location}/outcome"),
                fact(decision_id, "reason", decision.reason, f"{location}/reason"),
                fact(decision_id, "request", request_id, f"{location}/request"),
                fact(decision_id, "source", decision.response, f"{location}/response"),
            )
        )
    edges = [
        Edge(
            _edge_id(root_id, "enforces_for", decision_ids[item.id]),
            root_id,
            "enforces_for",
            decision_ids[item.id],
            (_fact_id(root_id, "decisions"),),
        )
        for item in oracle.decisions
    ]
    edges.extend(
        Edge(
            _edge_id(action_ids[item.cedar], "maps_to_tool", tool_ids[item.tool]),
            action_ids[item.cedar],
            "maps_to_tool",
            tool_ids[item.tool],
            (_fact_id(action_ids[item.cedar], "tool"),),
        )
        for item in oracle.mapping.actions
    )
    edges.extend(
        Edge(
            _edge_id(decision_ids[item.id], "decides_request", request_ids[item.id]),
            decision_ids[item.id],
            "decides_request",
            request_ids[item.id],
            (_fact_id(decision_ids[item.id], "request"),),
        )
        for item in oracle.decisions
    )
    return (
        tuple(sorted(entities, key=lambda item: item.id)),
        tuple(sorted(facts, key=lambda item: item.id)),
        tuple(sorted(edges, key=lambda item: item.id)),
    )


def _managed_to_ir(oracle: ManagedOracle) -> AuthorityIR:
    content_sha256 = hashlib.sha256(oracle.to_json().encode("utf-8")).hexdigest()
    source_id = _entity_id("source", f"managed-cedar-oracle:{content_sha256}")
    entities, facts, edges = _projection_parts(oracle, source_id)
    graph = AuthorityIR(
        IR_VERSION,
        (
            Source(
                source_id,
                "managed-cedar-oracle",
                "memory:managed-cedar-oracle",
                oracle.managed_oracle_version,
                oracle.provider.protocol_version,
                _profile_digest(entities, facts, edges),
                MANAGED_IR_ADAPTER,
                MANAGED_IR_ADAPTER_VERSION,
                content_sha256,
            ),
        ),
        entities,
        facts,
        edges,
    )
    _validate_managed_profile(graph)
    return graph


def _validate_managed_profile(graph: AuthorityIR) -> None:
    """Validate the closed managed transport profile without granting authority."""
    try:
        graph.validate()
    except IRFormatError as exc:
        raise ManagedOracleFormatError("managed Cedar IR profile is structurally invalid") from exc
    if len(graph.sources) != 1:
        raise ManagedOracleFormatError("managed Cedar IR profile requires exactly one source")
    source = graph.sources[0]
    if (
        source.kind != "managed-cedar-oracle"
        or source.format_version != MANAGED_ORACLE_VERSION
        or source.adapter != MANAGED_IR_ADAPTER
        or source.adapter_version != MANAGED_IR_ADAPTER_VERSION
        or source.content_sha256 is None
    ):
        raise ManagedOracleFormatError("managed Cedar IR profile has an unsupported source")
    if source.semantic_sha256 != _profile_digest(graph.entities, graph.facts, graph.edges):
        raise ManagedOracleFormatError("managed Cedar IR profile semantic digest does not match")
    roots = [item for item in graph.entities if item.kind == "enforcement_point"]
    if len(roots) != 1:
        raise ManagedOracleFormatError("managed Cedar IR profile requires one enforcement point")
    oracle_facts = [
        item for item in graph.facts if item.subject == roots[0].id and item.predicate == "oracle"
    ]
    if len(oracle_facts) != 1:
        raise ManagedOracleFormatError("managed Cedar IR profile has no unique oracle fact")
    try:
        oracle = ManagedOracle.from_json(_canonical_json(oracle_facts[0].value))
    except ManagedOracleFormatError as exc:
        raise ManagedOracleFormatError("managed Cedar IR profile oracle fact is invalid") from exc
    expected_entities, expected_facts, expected_edges = _projection_parts(oracle, source.id)
    if (
        graph.entities != expected_entities
        or graph.facts != expected_facts
        or graph.edges != expected_edges
    ):
        raise ManagedOracleFormatError("managed Cedar IR profile does not match its oracle")
    expected_content = hashlib.sha256(oracle.to_json().encode("utf-8")).hexdigest()
    if source.content_sha256 != expected_content:
        raise ManagedOracleFormatError("managed Cedar IR profile content digest does not match")


def _evaluation_date(as_of: date) -> str:
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise ManagedOracleFormatError("managed Cedar analysis as_of must be a date")
    return as_of.isoformat()


def _manifest_matches(
    mandate: Mandate, oracle: ManagedOracle, contents: Mapping[str, bytes]
) -> bool:
    projected = loads(
        contents[oracle.mapping.target.source].decode("utf-8"),
        source=mandate.source,
    )
    return projected == mandate


def _trust_findings(
    mandate: Mandate,
    oracle: ManagedOracle,
    contents: Mapping[str, bytes],
    evaluated_on: str,
) -> tuple[ManagedFinding, ...]:
    findings: list[ManagedFinding] = []
    try:
        oracle.verify_sources(contents)
        graph = AuthorityIR.from_json(oracle.to_ir().to_json())
        _validate_managed_profile(graph)
    except (ManagedOracleFormatError, IRFormatError) as exc:
        return (ManagedFinding("managed.source-untrusted", str(exc)),)
    if not _manifest_matches(mandate, oracle, contents):
        findings.append(
            ManagedFinding(
                "managed.target-mismatch",
                "managed Cedar mapping target does not match the analyzed mandate",
            )
        )
    if (
        oracle.provider.name != "aws-agentcore"
        or oracle.provider.protocol != "MCP"
        or oracle.state.authorizer_type != "AWS_IAM"
        or oracle.state.gateway_status != "READY"
        or oracle.state.policy_engine_status != "ACTIVE"
        or oracle.state.policy_engine_mode != "ENFORCE"
        or oracle.state.requested_validation_mode != "FAIL_ON_ANY_FINDINGS"
    ):
        findings.append(
            ManagedFinding(
                "managed.enforcement-ineligible",
                "managed Cedar capture does not prove a ready IAM ENFORCE boundary",
            )
        )
    if oracle.capture_date > evaluated_on:
        findings.append(
            ManagedFinding(
                "managed.capture-in-future",
                "managed Cedar capture date is after the evaluation date",
            )
        )
    policies = tuple(oracle.policy_inventory.members)
    if (
        not oracle.tool_inventory.complete
        or not oracle.policy_inventory.complete
        or any(
            policy.status != "ACTIVE" or policy.enforcement_mode != "ACTIVE" for policy in policies
        )
    ):
        findings.append(
            ManagedFinding(
                "managed.inventory-incomplete",
                "managed Cedar tool or policy inventory is not complete and active",
            )
        )
    evidence = oracle.mapping.request_domain.evidence
    if (
        evidence.confidence != "exact"
        or evidence.review != "accepted"
        or evidence.reviewer is None
        or evidence.expires is None
        or evidence.expires < evaluated_on
    ):
        findings.append(
            ManagedFinding(
                "managed.mapping-untrusted",
                "managed Cedar mapping is not exact, accepted, and current",
            )
        )
    if oracle.sanitization.decision_messages_changed:
        findings.append(
            ManagedFinding(
                "managed.sanitization-changed-decision",
                "managed Cedar sanitization changed decision messages",
            )
        )
    if (
        oracle.mapping.principal.cedar_types != ("AgentCore::IamEntity",)
        or oracle.mapping.principal.mandate_principal != "caller"
    ):
        findings.append(
            ManagedFinding(
                "managed.principal-mismatch",
                "managed Cedar principal mapping does not match the IAM caller boundary",
            )
        )
    if oracle.mapping.resources[0].cedar_type != "AgentCore::Gateway":
        findings.append(
            ManagedFinding(
                "managed.resource-mismatch",
                "managed Cedar resource mapping is not an AgentCore Gateway",
            )
        )
    return tuple(findings)


def _action_tools(oracle: ManagedOracle) -> dict[str, str]:
    return {item.cedar: item.tool for item in oracle.mapping.actions}


def _alignment_support(oracle: ManagedOracle, decision: ManagedDecision) -> tuple[str, ...]:
    source_digests = {item.locator: item.content_sha256 for item in oracle.sources}
    return (
        f"mapping:{oracle.mapping.source}",
        f"request:{decision.request}:{source_digests[decision.request]}",
        f"response:{decision.response}:{source_digests[decision.response]}",
    )


def analyse_managed_cedar(
    mandate: Mandate,
    oracle: ManagedOracle,
    contents: Mapping[str, bytes],
    *,
    as_of: date,
) -> ManagedAnalysis:
    """Align exact managed decisions with unchanged reviewed authority."""
    evaluated_on = _evaluation_date(as_of)
    reread = ManagedOracle.from_json(oracle.to_json())
    authority = analyse(mandate)
    findings = list(_trust_findings(mandate, reread, contents, evaluated_on))
    action_tools = _action_tools(reread)
    alignments = []
    blocked = bool(findings)
    for decision in reread.decisions:
        cedar_action = f'AgentCore::Action::"{decision.tool}"'
        tool = action_tools.get(cedar_action)
        alignment = "unresolved"
        if tool is None or tool not in authority.reachable_tools:
            findings.append(
                ManagedFinding(
                    "managed.request-unmapped",
                    f"managed Cedar decision '{decision.id}' has no reachable reviewed tool",
                )
            )
            blocked = True
        elif not blocked:
            alignment = (
                "aligned_allow" if decision.outcome == "allow" else "enforcement_narrows_request"
            )
        alignments.append(
            ManagedAlignment(
                decision.id,
                decision.request_key,
                tool,
                decision.outcome,
                decision.reason,
                alignment,
                _alignment_support(reread, decision),
            )
        )
    if blocked:
        alignments = [replace(item, alignment="unresolved") for item in alignments]
    unique_findings = tuple(
        {
            (
                item.code,
                item.message,
            ): item
            for item in findings
        }.values()
    )
    return ManagedAnalysis(
        authority,
        evaluated_on,
        tuple(alignments),
        unique_findings,
    )


def _comparison_identity(oracle: ManagedOracle) -> dict[str, Any]:
    state = oracle.state.as_dict()
    sanitization = oracle.sanitization.as_dict()
    tool_inventory = oracle.tool_inventory.as_dict()
    # Evidence locators differ across captures; the referenced bytes are
    # independently verified before comparison. Pin their semantic boundary,
    # not the repository filename used to preserve each observation.
    del state["source"]
    del sanitization["source"]
    del tool_inventory["source"]
    return {
        "provider": oracle.provider.as_dict(),
        "state": state,
        "mapping": oracle.mapping.as_dict(),
        "tool_inventory": tool_inventory,
        "sanitization": sanitization,
    }


def compare_managed_cedar(
    mandate: Mandate,
    baseline: ManagedOracle,
    baseline_contents: Mapping[str, bytes],
    candidate: ManagedOracle,
    candidate_contents: Mapping[str, bytes],
    *,
    as_of: date,
) -> ManagedDiff:
    """Compare reproduced outcomes only for identical managed request boundaries."""
    baseline_result = analyse_managed_cedar(mandate, baseline, baseline_contents, as_of=as_of)
    candidate_result = analyse_managed_cedar(mandate, candidate, candidate_contents, as_of=as_of)
    findings: list[ManagedFinding] = []
    if baseline_result.findings or candidate_result.findings:
        findings.append(
            ManagedFinding(
                "managed.comparison-untrusted",
                "managed Cedar revisions are not both eligible for comparison",
            )
        )
    if _comparison_identity(baseline) != _comparison_identity(candidate):
        findings.append(
            ManagedFinding(
                "managed.comparison-boundary-changed",
                "managed Cedar revisions do not share one reviewed enforcement boundary",
            )
        )
    baseline_by_key = {item.request_key: item for item in baseline_result.alignments}
    candidate_by_key = {item.request_key: item for item in candidate_result.alignments}
    if set(baseline_by_key) != set(candidate_by_key):
        findings.append(
            ManagedFinding(
                "managed.comparison-requests-changed",
                "managed Cedar revisions do not contain the same canonical requests",
            )
        )
    changes = []
    if not findings:
        classifications = {
            ("allow", "allow"): "stable_allow",
            ("deny", "deny"): "stable_deny",
            ("deny", "allow"): "widens",
            ("allow", "deny"): "tightens",
        }
        for before in baseline_result.alignments:
            request_key = before.request_key
            after = candidate_by_key[request_key]
            changes.append(
                ManagedChange(
                    request_key,
                    before.tool,
                    before.outcome,
                    after.outcome,
                    classifications[(before.outcome, after.outcome)],
                    (*before.support, *after.support),
                )
            )
    return ManagedDiff(
        baseline_result,
        candidate_result,
        tuple(changes),
        tuple(findings),
    )
