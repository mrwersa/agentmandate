"""Private delegation-chain records derived from reviewed external evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._conditions import (
    GRANT_EFFECTS,
    ConditionFormatError,
    Evidence,
    Grant,
    ToolTarget,
    _canonical_name,
    _evidence,
    _fact,
    _load_json,
    _profile_digest,
    _record,
    _relative_path,
    _tool_target,
    _validate_projected_evidence,
    _validate_projection_facts,
    _validate_projection_source,
    _version,
)
from ._ir import IR_VERSION, AuthorityIR, Edge, Entity, Source, _edge_id, _entity_id, _fact_id
from .manifest import Mandate, Tool
from .reach import Authority, analyse

DELEGATION_VERSION = 1
DELEGATION_ADAPTER = "agentmandate.delegation-chain"
DELEGATION_ADAPTER_VERSION = 1
DELEGATION_ATTACHMENT_VERSION = 2
DELEGATION_ATTACHMENT_ADAPTER = "agentmandate.delegation-attachment"
DELEGATION_ATTACHMENT_ADAPTER_VERSION = 1
ACTOR_HISTORY = frozenset({"complete", "partial"})
VALIDITY_KINDS = frozenset({"window", "duration", "date_window"})
SURFACE_BASES = frozenset({"issuer", "deployment_policy", "unavailable"})
SURFACE_COMPLETENESS = frozenset({"complete", "partial", "unknown"})
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class DelegationFormatError(ValueError):
    """Raised when a delegation-chain artifact violates its closed contract."""


def _translate(callable_: Any, *args: Any) -> Any:
    try:
        return callable_(*args)
    except ConditionFormatError as exc:
        raise DelegationFormatError(str(exc).replace("condition contract ", "delegation ")) from exc


def _enum(raw: dict[str, Any], field: str, path: str, allowed: frozenset[str]) -> str:
    value = _translate(_canonical_name, raw, field, path)
    if value not in allowed:
        raise DelegationFormatError(f"delegation {path}.{field} has an invalid value")
    return value


def _members(value: Any, path: str, *, allowed: frozenset[str] | None = None) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DelegationFormatError(f"delegation {path}.members must be an array of strings")
    if any(not item or item != item.strip() for item in value):
        raise DelegationFormatError(f"delegation {path}.members must be non-empty and stripped")
    if len(value) != len(set(value)):
        raise DelegationFormatError(f"delegation {path}.members contains duplicates")
    if allowed is not None and any(item not in allowed for item in value):
        raise DelegationFormatError(f"delegation {path}.members has an invalid effect")
    return tuple(sorted(value))


def _date_value(raw: dict[str, Any], field: str, path: str) -> str:
    value = _translate(_canonical_name, raw, field, path)
    if not _DATE.fullmatch(value):
        raise DelegationFormatError(f"delegation {path}.{field} must be a canonical date")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise DelegationFormatError(f"delegation {path}.{field} must be a canonical date") from exc
    return value


def _timestamp(raw: dict[str, Any], field: str, path: str) -> str:
    value = _translate(_canonical_name, raw, field, path)
    if not _UTC_TIMESTAMP.fullmatch(value):
        raise DelegationFormatError(f"delegation {path}.{field} must be a canonical UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise DelegationFormatError(
            f"delegation {path}.{field} must be a canonical UTC timestamp"
        ) from exc
    return value


def _pointer(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise DelegationFormatError(f"delegation {path}.location must be a JSON Pointer")
    if value and not value.startswith("/"):
        raise DelegationFormatError(f"delegation {path}.location must be a JSON Pointer")
    if re.search(r"~(?:[^01]|$)", value):
        raise DelegationFormatError(f"delegation {path}.location must be a JSON Pointer")
    return value


@dataclass(frozen=True)
class DelegationSource:
    kind: str
    locator: str
    location: str
    content_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "locator": self.locator,
            "location": self.location,
            "content_sha256": self.content_sha256,
        }


def _source(raw: Any, path: str) -> DelegationSource:
    value = _translate(_record, raw, path, {"kind", "locator", "location", "content_sha256"})
    digest = value["content_sha256"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise DelegationFormatError(f"delegation {path}.content_sha256 must be lowercase SHA-256")
    return DelegationSource(
        _translate(_canonical_name, value, "kind", path),
        _translate(_relative_path, value, "locator", path),
        _pointer(value["location"], path),
        digest,
    )


@dataclass(frozen=True)
class DelegationValidity:
    kind: str
    issued_at: str | None = None
    expires_at: str | None = None
    ttl_seconds: int | None = None
    issued: str | None = None
    expires: str | None = None

    @property
    def attenuation_eligible(self) -> bool:
        return self.kind == "window"

    def as_dict(self) -> dict[str, Any]:
        result = {"kind": self.kind}
        for field in ("issued_at", "expires_at", "ttl_seconds", "issued", "expires"):
            value = getattr(self, field)
            if value is not None:
                result[field] = value
        return result


def _validity(raw: Any, path: str) -> DelegationValidity:
    value = _translate(
        _record,
        raw,
        path,
        {"kind"},
        {"issued_at", "expires_at", "ttl_seconds", "issued", "expires"},
    )
    kind = _enum(value, "kind", path, VALIDITY_KINDS)
    fields = set(value) - {"kind"}
    expected = {
        "window": {"issued_at", "expires_at"},
        "duration": {"ttl_seconds"},
        "date_window": {"issued", "expires"},
    }[kind]
    if fields != expected:
        raise DelegationFormatError(f"delegation {path} has an invalid field set for {kind}")
    if kind == "duration":
        ttl = value["ttl_seconds"]
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise DelegationFormatError(f"delegation {path}.ttl_seconds must be a positive integer")
        return DelegationValidity(kind, ttl_seconds=ttl)
    if kind == "window":
        issued_at = _timestamp(value, "issued_at", path)
        expires_at = _timestamp(value, "expires_at", path)
        if issued_at >= expires_at:
            raise DelegationFormatError(f"delegation {path} must end after it begins")
        return DelegationValidity(kind, issued_at=issued_at, expires_at=expires_at)
    issued = _date_value(value, "issued", path)
    expires = _date_value(value, "expires", path)
    if issued > expires:
        raise DelegationFormatError(f"delegation {path} must not end before it begins")
    return DelegationValidity(kind, issued=issued, expires=expires)


@dataclass(frozen=True)
class SurfaceDimension:
    domain: str | None
    basis: str
    completeness: str
    members: tuple[str, ...]
    evidence: Evidence | None = None
    source: DelegationSource | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "domain": self.domain,
            "basis": self.basis,
            "completeness": self.completeness,
            "members": list(self.members),
        }
        if self.evidence is not None:
            result["evidence"] = self.evidence.as_dict()
        if self.source is not None:
            result["source"] = self.source.as_dict()
        return result


def _dimension(raw: Any, name: str, path: str) -> SurfaceDimension:
    value = _translate(
        _record,
        raw,
        path,
        {"domain", "basis", "completeness", "members"},
        {"evidence", "source"},
    )
    basis = _enum(value, "basis", path, SURFACE_BASES)
    completeness = _enum(value, "completeness", path, SURFACE_COMPLETENESS)
    members = _members(value["members"], path, allowed=GRANT_EFFECTS if name == "effects" else None)
    domain = value["domain"]
    if completeness == "unknown":
        if (
            basis != "unavailable"
            or domain is not None
            or members
            or set(value) != {"domain", "basis", "completeness", "members"}
        ):
            raise DelegationFormatError(f"delegation {path} has invalid unknown semantics")
        return SurfaceDimension(None, basis, completeness, members)
    if not isinstance(domain, str) or not domain or domain != domain.strip():
        raise DelegationFormatError(f"delegation {path}.domain must be non-empty and stripped")
    if basis == "unavailable" or "evidence" not in value or "source" not in value:
        raise DelegationFormatError(f"delegation {path} claimed members require provenance")
    if completeness == "partial" and not members:
        raise DelegationFormatError(f"delegation {path} partial members must not be empty")
    if name in {"tools", "effects"} and basis != "deployment_policy":
        raise DelegationFormatError(f"delegation {path} requires deployment-policy evidence")
    evidence = _translate(_evidence, value["evidence"], path)
    return SurfaceDimension(
        domain, basis, completeness, members, evidence, _source(value["source"], f"{path}.source")
    )


@dataclass(frozen=True)
class DelegationHop:
    id: str
    grantor: str
    actors: tuple[str, ...]
    actor_history: str
    audience: str
    validity: DelegationValidity
    scopes: SurfaceDimension
    tools: SurfaceDimension
    effects: SurfaceDimension
    evidence: Evidence
    source: DelegationSource

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "grantor": self.grantor,
            "actors": list(self.actors),
            "actor_history": self.actor_history,
            "audience": self.audience,
            "validity": self.validity.as_dict(),
            "surface": {
                "scopes": self.scopes.as_dict(),
                "tools": self.tools.as_dict(),
                "effects": self.effects.as_dict(),
            },
            "evidence": self.evidence.as_dict(),
            "source": self.source.as_dict(),
        }


def _hop(raw: Any, index: int) -> DelegationHop:
    path = f"chain.hops[{index}]"
    value = _translate(
        _record,
        raw,
        path,
        {
            "id",
            "grantor",
            "actors",
            "actor_history",
            "audience",
            "validity",
            "surface",
            "evidence",
            "source",
        },
    )
    actors = _members(value["actors"], f"{path}.actors")
    # Actor order is semantic and must not be sorted.
    actors = tuple(value["actors"])
    surface = _translate(
        _record, value["surface"], f"{path}.surface", {"scopes", "tools", "effects"}
    )
    return DelegationHop(
        _translate(_canonical_name, value, "id", path),
        _translate(_canonical_name, value, "grantor", path),
        actors,
        _enum(value, "actor_history", path, ACTOR_HISTORY),
        _translate(_canonical_name, value, "audience", path),
        _validity(value["validity"], f"{path}.validity"),
        _dimension(surface["scopes"], "scopes", f"{path}.surface.scopes"),
        _dimension(surface["tools"], "tools", f"{path}.surface.tools"),
        _dimension(surface["effects"], "effects", f"{path}.surface.effects"),
        _translate(_evidence, value["evidence"], path),
        _source(value["source"], f"{path}.source"),
    )


@dataclass(frozen=True)
class DelegationChain:
    version: int
    id: str
    subject: str
    hops: tuple[DelegationHop, ...]

    @property
    def actor_history_complete(self) -> bool:
        return all(hop.actor_history == "complete" for hop in self.hops)

    @property
    def actor_history_unresolved_hops(self) -> tuple[str, ...]:
        """Every hop is unresolved when any actor-history link is partial."""
        if self.actor_history_complete:
            return ()
        return tuple(hop.id for hop in self.hops)

    def as_dict(self) -> dict[str, Any]:
        return {
            "delegation_version": self.version,
            "id": self.id,
            "subject": self.subject,
            "hops": [hop.as_dict() for hop in self.hops],
        }

    def to_json(self) -> str:
        return (
            json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n"
        )

    def to_ir(self) -> AuthorityIR:
        return _delegation_to_ir(self)

    def verify_sources(self, contents: Mapping[str, bytes]) -> None:
        expected: dict[str, str] = {}
        for hop in self.hops:
            for source in (hop.source, hop.scopes.source, hop.tools.source, hop.effects.source):
                if source is None:
                    continue
                previous = expected.setdefault(source.locator, source.content_sha256)
                if previous != source.content_sha256:
                    raise DelegationFormatError(
                        f"delegation sources disagree on the digest for {source.locator}"
                    )
        missing = sorted(set(expected) - set(contents))
        if missing:
            raise DelegationFormatError(
                f"delegation source bytes are missing reviewed locator {missing[0]}"
            )
        if set(contents) - set(expected):
            raise DelegationFormatError("delegation source bytes include an unexpected locator")
        for locator, digest in expected.items():
            content = contents[locator]
            if not isinstance(content, bytes):
                raise DelegationFormatError(
                    f"delegation source verification for {locator} requires bytes"
                )
            if hashlib.sha256(content).hexdigest() != digest:
                raise DelegationFormatError(
                    f"delegation source bytes for {locator} do not match the reviewed digest"
                )

    @classmethod
    def from_json(cls, text: str) -> DelegationChain:
        raw = _translate(
            _record,
            _translate(_load_json, text, "delegation chain"),
            "chain",
            {"delegation_version", "id", "subject", "hops"},
        )
        version = _translate(_version, raw, "delegation_version", "chain", DELEGATION_VERSION)
        if not isinstance(raw["hops"], list) or not raw["hops"]:
            raise DelegationFormatError("delegation chain.hops must be a non-empty array")
        hops = tuple(_hop(value, index) for index, value in enumerate(raw["hops"]))
        if len({hop.id for hop in hops}) != len(hops):
            raise DelegationFormatError("delegation chain contains duplicate hop IDs")
        for previous, current in zip(hops, hops[1:], strict=False):
            if len(current.actors) < 2 or current.actors[1] != previous.actors[0]:
                raise DelegationFormatError("delegation chain actor continuity is broken")
            if previous.actor_history == current.actor_history == "complete" and current.actors != (
                current.actors[0],
                *previous.actors,
            ):
                raise DelegationFormatError(
                    "delegation chain complete actor history is inconsistent"
                )
        chain = cls(
            version,
            _translate(_canonical_name, raw, "id", "chain"),
            _translate(_canonical_name, raw, "subject", "chain"),
            hops,
        )
        # Force same-locator digest conflicts to fail at the reader boundary.
        declared: dict[str, str] = {}
        for hop in hops:
            for source in (hop.source, hop.scopes.source, hop.tools.source, hop.effects.source):
                if (
                    source is not None
                    and declared.setdefault(source.locator, source.content_sha256)
                    != source.content_sha256
                ):
                    raise DelegationFormatError("delegation sources disagree on a locator digest")
        return chain

    @classmethod
    def from_grant_v1(cls, grant: Grant) -> DelegationChain:
        if grant.source is None or grant.source.content_sha256 is None:
            raise DelegationFormatError(
                "delegation grant-v1 migration requires a digest-pinned source"
            )
        source = DelegationSource(
            grant.source.kind,
            grant.source.locator,
            "",
            grant.source.content_sha256,
        )

        def dimension(members: tuple[str, ...]) -> SurfaceDimension:
            return SurfaceDimension(
                grant.audience,
                "deployment_policy",
                "complete",
                members,
                grant.evidence,
                source,
            )

        hop = DelegationHop(
            "hop-1",
            grant.grantor,
            (grant.actor,),
            "complete",
            grant.audience,
            DelegationValidity("date_window", issued=grant.issued, expires=grant.expires),
            dimension(grant.scopes),
            dimension(grant.tools),
            dimension(grant.effects),
            grant.evidence,
            source,
        )
        return cls(DELEGATION_VERSION, grant.id, grant.subject, (hop,))

    @classmethod
    def from_authorizer_capture(cls, text: str, evidence: Evidence) -> DelegationChain:
        """Project the pinned, sanitized Authorizer evidence without adding policy."""
        raw = _translate(
            _record,
            _translate(_load_json, text, "Authorizer capture"),
            "capture",
            {"capture_version", "deployment", "hops", "implementation", "rejections", "subject"},
        )
        if raw["capture_version"] != 1 or not isinstance(raw["hops"], list) or not raw["hops"]:
            raise DelegationFormatError("delegation Authorizer capture has an unsupported shape")
        subject = _translate(
            _record, raw["subject"], "capture.subject", {"alias", "initial_scopes"}
        )
        subject_name = _translate(_canonical_name, subject, "alias", "capture.subject")
        content = text.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        locator = "docs/evidence/authorizer-delegation/capture.json"
        hops: list[DelegationHop] = []
        for index, item in enumerate(raw["hops"]):
            path = f"capture.hops[{index}]"
            value = _translate(
                _record,
                item,
                path,
                {
                    "actor",
                    "actor_chain",
                    "audience",
                    "grantor",
                    "hop",
                    "issued_token_type",
                    "scopes",
                    "subject",
                    "ttl_seconds",
                },
            )
            actors = _members(value["actor_chain"], f"{path}.actor_chain")
            actors = tuple(value["actor_chain"])
            if (
                value["actor"] != actors[0]
                or value["subject"] != subject_name
                or value["hop"] != index + 1
            ):
                raise DelegationFormatError("delegation Authorizer hop identity is inconsistent")
            ttl = value["ttl_seconds"]
            if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
                raise DelegationFormatError("delegation Authorizer TTL must be a positive integer")
            hop_source = DelegationSource("oauth-claims", locator, f"/hops/{index}", digest)
            scope_source = DelegationSource(
                "oauth-claims", locator, f"/hops/{index}/scopes", digest
            )
            scopes = SurfaceDimension(
                _translate(_canonical_name, value, "grantor", path),
                "issuer",
                "complete",
                _members(value["scopes"], f"{path}.scopes"),
                evidence,
                scope_source,
            )
            unknown = SurfaceDimension(None, "unavailable", "unknown", ())
            hops.append(
                DelegationHop(
                    f"hop-{index + 1}",
                    value["grantor"],
                    actors,
                    "complete",
                    value["audience"],
                    DelegationValidity("duration", ttl_seconds=ttl),
                    scopes,
                    unknown,
                    unknown,
                    evidence,
                    hop_source,
                )
            )
        projected = cls(DELEGATION_VERSION, "authorizer-demo-chain", subject_name, tuple(hops))
        # Re-read to apply the same continuity and strict-profile checks as external input.
        return cls.from_json(projected.to_json())


def _delegation_to_ir(value: DelegationChain) -> AuthorityIR:
    source_id = _entity_id("source", f"delegation-chain:{value.id}")
    root_id = _entity_id("delegation", value.id)
    subject_id = _entity_id("principal", value.subject)
    entities: dict[str, Entity] = {
        root_id: Entity(root_id, "delegation", value.id),
        subject_id: Entity(subject_id, "principal", value.subject),
    }
    root_evidence = value.hops[0].evidence
    hop_ids = [_entity_id("hop", hop.id) for hop in value.hops]
    facts = [
        _fact(root_id, "name", value.id, source_id, "/id", root_evidence),
        _fact(root_id, "subject", subject_id, source_id, "/subject", root_evidence),
        _fact(root_id, "hops", hop_ids, source_id, "/hops", root_evidence),
        _fact(
            root_id,
            "reviewer",
            root_evidence.reviewer,
            source_id,
            "/hops/0/evidence/reviewer",
            root_evidence,
        ),
        _fact(
            root_id,
            "review_expires",
            root_evidence.expires,
            source_id,
            "/hops/0/evidence/expires",
            root_evidence,
        ),
        _fact(subject_id, "name", value.subject, source_id, "/subject", root_evidence),
    ]
    edges = [
        Edge(
            _edge_id(root_id, "delegates_for", subject_id),
            root_id,
            "delegates_for",
            subject_id,
            (_fact_id(root_id, "subject"),),
        )
    ]
    for index, (hop, hop_id) in enumerate(zip(value.hops, hop_ids, strict=True)):
        entities[hop_id] = Entity(hop_id, "hop", hop.id)
        actor_ids = [_entity_id("principal", actor) for actor in hop.actors]
        for actor, actor_id in zip(hop.actors, actor_ids, strict=True):
            if actor_id not in entities:
                entities[actor_id] = Entity(actor_id, "principal", actor)
                facts.append(
                    _fact(
                        actor_id,
                        "name",
                        actor,
                        source_id,
                        f"/hops/{index}/actors",
                        hop.evidence,
                    )
                )
        surface_ids = [
            _entity_id("surface", f"{hop.id}:{dimension}")
            for dimension in ("scopes", "tools", "effects")
        ]
        previous = hop_ids[index - 1] if index else None
        hop_path = f"/hops/{index}"
        facts.extend(
            (
                _fact(hop_id, "name", hop.id, source_id, f"{hop_path}/id", hop.evidence),
                _fact(
                    hop_id, "grantor", hop.grantor, source_id, f"{hop_path}/grantor", hop.evidence
                ),
                _fact(hop_id, "actors", actor_ids, source_id, f"{hop_path}/actors", hop.evidence),
                _fact(
                    hop_id,
                    "actor_history",
                    hop.actor_history,
                    source_id,
                    f"{hop_path}/actor_history",
                    hop.evidence,
                ),
                _fact(
                    hop_id,
                    "audience",
                    hop.audience,
                    source_id,
                    f"{hop_path}/audience",
                    hop.evidence,
                ),
                _fact(
                    hop_id,
                    "validity",
                    hop.validity.as_dict(),
                    source_id,
                    f"{hop_path}/validity",
                    hop.evidence,
                ),
                _fact(
                    hop_id, "surfaces", surface_ids, source_id, f"{hop_path}/surface", hop.evidence
                ),
                _fact(hop_id, "previous", previous, source_id, hop_path, hop.evidence),
                _fact(
                    hop_id,
                    "reviewer",
                    hop.evidence.reviewer,
                    source_id,
                    f"{hop_path}/evidence/reviewer",
                    hop.evidence,
                ),
                _fact(
                    hop_id,
                    "review_expires",
                    hop.evidence.expires,
                    source_id,
                    f"{hop_path}/evidence/expires",
                    hop.evidence,
                ),
            )
        )
        edges.append(
            Edge(
                _edge_id(root_id, "has_hop", hop_id),
                root_id,
                "has_hop",
                hop_id,
                (_fact_id(root_id, "hops"),),
            )
        )
        if previous is not None:
            edges.append(
                Edge(
                    _edge_id(hop_id, "previous_hop", previous),
                    hop_id,
                    "previous_hop",
                    previous,
                    (_fact_id(hop_id, "previous"),),
                )
            )
        for actor_id in actor_ids:
            edges.append(
                Edge(
                    _edge_id(hop_id, "acts_under", actor_id),
                    hop_id,
                    "acts_under",
                    actor_id,
                    (_fact_id(hop_id, "actors"),),
                )
            )
        for dimension, surface_id in zip(("scopes", "tools", "effects"), surface_ids, strict=True):
            surface = getattr(hop, dimension)
            evidence = surface.evidence or hop.evidence
            name = f"{hop.id}:{dimension}"
            entities[surface_id] = Entity(surface_id, "surface", name)
            surface_path = f"{hop_path}/surface/{dimension}"
            facts.extend(
                (
                    _fact(surface_id, "name", name, source_id, surface_path, evidence),
                    _fact(surface_id, "dimension", dimension, source_id, surface_path, evidence),
                    _fact(
                        surface_id,
                        "domain",
                        surface.domain,
                        source_id,
                        f"{surface_path}/domain",
                        evidence,
                    ),
                    _fact(
                        surface_id,
                        "basis",
                        surface.basis,
                        source_id,
                        f"{surface_path}/basis",
                        evidence,
                    ),
                    _fact(
                        surface_id,
                        "completeness",
                        surface.completeness,
                        source_id,
                        f"{surface_path}/completeness",
                        evidence,
                    ),
                    _fact(
                        surface_id,
                        "members",
                        list(surface.members),
                        source_id,
                        f"{surface_path}/members",
                        evidence,
                    ),
                    _fact(
                        surface_id,
                        "reviewer",
                        evidence.reviewer,
                        source_id,
                        f"{surface_path}/evidence/reviewer",
                        evidence,
                    ),
                    _fact(
                        surface_id,
                        "review_expires",
                        evidence.expires,
                        source_id,
                        f"{surface_path}/evidence/expires",
                        evidence,
                    ),
                )
            )
            edges.append(
                Edge(
                    _edge_id(hop_id, "has_surface", surface_id),
                    hop_id,
                    "has_surface",
                    surface_id,
                    (_fact_id(hop_id, "surfaces"),),
                )
            )
    entity_tuple = tuple(entities.values())
    fact_tuple = tuple(facts)
    edge_tuple = tuple(edges)
    graph = AuthorityIR(
        IR_VERSION,
        (
            Source(
                source_id,
                "delegation-chain",
                f"memory:delegation-chain:{value.id}",
                value.version,
                None,
                _profile_digest(entity_tuple, fact_tuple, edge_tuple),
                DELEGATION_ADAPTER,
                DELEGATION_ADAPTER_VERSION,
                hashlib.sha256(value.to_json().encode("utf-8")).hexdigest(),
            ),
        ),
        entity_tuple,
        fact_tuple,
        edge_tuple,
    )
    _validate_delegation_profile(graph)
    return graph


def _validate_delegation_profile(graph: AuthorityIR) -> None:
    _translate(
        _validate_projection_source,
        graph,
        "delegation-chain",
        DELEGATION_ADAPTER,
        DELEGATION_ADAPTER_VERSION,
    )
    entities = {entity.id: entity for entity in graph.entities}
    roots = [entity for entity in graph.entities if entity.kind == "delegation"]
    if len(roots) != 1 or any(
        entity.kind not in {"delegation", "hop", "principal", "surface"}
        for entity in graph.entities
    ):
        raise DelegationFormatError("delegation IR profile has unsupported entities")
    predicates = {
        entity.id: {
            "delegation": {"name", "subject", "hops", "reviewer", "review_expires"},
            "hop": {
                "name",
                "grantor",
                "actors",
                "actor_history",
                "audience",
                "validity",
                "surfaces",
                "previous",
                "reviewer",
                "review_expires",
            },
            "principal": {"name"},
            "surface": {
                "name",
                "dimension",
                "domain",
                "basis",
                "completeness",
                "members",
                "reviewer",
                "review_expires",
            },
        }[entity.kind]
        for entity in graph.entities
    }
    # A delegation projection is deliberately a single-source profile: mixed
    # confidence or review states must be split into separately reviewed chains.
    _translate(_validate_projection_facts, graph, entities, predicates)
    facts = {(fact.subject, fact.predicate): fact for fact in graph.facts}
    root = roots[0]
    _translate(_validate_projected_evidence, graph, root.id, facts)
    hop_ids = facts[(root.id, "hops")].value
    actual_hops = [entity.id for entity in graph.entities if entity.kind == "hop"]
    if (
        not isinstance(hop_ids, list)
        or set(hop_ids) != set(actual_hops)
        or len(hop_ids) != len(actual_hops)
    ):
        raise DelegationFormatError("delegation IR profile hops do not match entities")
    prior_actors: list[str] | None = None
    prior_history: str | None = None
    for index, hop_id in enumerate(hop_ids):
        actors = facts[(hop_id, "actors")].value
        surfaces = facts[(hop_id, "surfaces")].value
        previous = facts[(hop_id, "previous")].value
        if (
            not isinstance(actors, list)
            or not actors
            or any(entities.get(item, Entity("", "", "")).kind != "principal" for item in actors)
        ):
            raise DelegationFormatError("delegation IR profile has invalid actors")
        if (
            not isinstance(surfaces, list)
            or len(surfaces) != 3
            or any(entities.get(item, Entity("", "", "")).kind != "surface" for item in surfaces)
        ):
            raise DelegationFormatError("delegation IR profile has invalid surfaces")
        expected_previous = hop_ids[index - 1] if index else None
        if previous != expected_previous:
            raise DelegationFormatError("delegation IR profile has invalid hop order")
        history = facts[(hop_id, "actor_history")].value
        if history not in ACTOR_HISTORY:
            raise DelegationFormatError("delegation IR profile has invalid actor history")
        if prior_actors is not None:
            if len(actors) < 2 or actors[1] != prior_actors[0]:
                raise DelegationFormatError("delegation IR profile has broken actor continuity")
            if prior_history == history == "complete" and actors != [actors[0], *prior_actors]:
                raise DelegationFormatError("delegation IR profile has incomplete actor continuity")
        prior_actors = actors
        prior_history = history
        validity = facts[(hop_id, "validity")].value
        if not isinstance(validity, dict):
            raise DelegationFormatError("delegation IR profile has invalid validity")
        _validity(validity, "delegation_IR.validity")
        dimensions: set[str] = set()
        for surface_id in surfaces:
            dimension = facts[(surface_id, "dimension")].value
            domain = facts[(surface_id, "domain")].value
            basis = facts[(surface_id, "basis")].value
            completeness = facts[(surface_id, "completeness")].value
            members = facts[(surface_id, "members")].value
            if dimension not in {"scopes", "tools", "effects"} or dimension in dimensions:
                raise DelegationFormatError("delegation IR profile has invalid surface dimensions")
            dimensions.add(dimension)
            _members(
                members,
                "delegation_IR.surface",
                allowed=GRANT_EFFECTS if dimension == "effects" else None,
            )
            if completeness not in SURFACE_COMPLETENESS or basis not in SURFACE_BASES:
                raise DelegationFormatError("delegation IR profile has invalid surface state")
            if completeness == "unknown":
                if basis != "unavailable" or domain is not None or members:
                    raise DelegationFormatError("delegation IR profile has invalid unknown surface")
            elif (
                not isinstance(domain, str)
                or not domain
                or basis == "unavailable"
                or (completeness == "partial" and not members)
                or (dimension in {"tools", "effects"} and basis != "deployment_policy")
            ):
                raise DelegationFormatError("delegation IR profile has invalid claimed surface")


@dataclass(frozen=True)
class DelegationAttachment:
    """Reviewed attachment of one manifest tool to one delegation hop."""

    version: int
    id: str
    target: ToolTarget
    delegation: str
    hop: str
    scope_domain: str
    tool_domain: str
    effect_domain: str
    evidence: Evidence

    def domain_for(self, dimension: str) -> str:
        return {
            "scopes": self.scope_domain,
            "tools": self.tool_domain,
            "effects": self.effect_domain,
        }[dimension]

    def as_dict(self) -> dict[str, Any]:
        return {
            "principal_version": self.version,
            "id": self.id,
            "target": self.target.as_dict(),
            "principal": {
                "kind": "delegated_user",
                "delegation": self.delegation,
                "hop": self.hop,
                "domains": {
                    "scopes": self.scope_domain,
                    "tools": self.tool_domain,
                    "effects": self.effect_domain,
                },
            },
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def to_ir(self) -> AuthorityIR:
        return _attachment_to_ir(self)

    @classmethod
    def from_json(cls, text: str) -> DelegationAttachment:
        raw = _translate(
            _record,
            _translate(_load_json, text, "delegation attachment"),
            "attachment",
            {"principal_version", "id", "target", "principal", "evidence"},
        )
        principal = _translate(
            _record,
            raw["principal"],
            "attachment.principal",
            {"kind", "delegation", "hop", "domains"},
        )
        if principal["kind"] != "delegated_user":
            raise DelegationFormatError("delegation attachment has an unsupported principal kind")
        domains = _translate(
            _record,
            principal["domains"],
            "attachment.principal.domains",
            {"scopes", "tools", "effects"},
        )
        return cls(
            _translate(
                _version,
                raw,
                "principal_version",
                "attachment",
                DELEGATION_ATTACHMENT_VERSION,
            ),
            _translate(_canonical_name, raw, "id", "attachment"),
            _translate(_tool_target, raw["target"], "attachment.target"),
            _translate(_canonical_name, principal, "delegation", "attachment.principal"),
            _translate(_canonical_name, principal, "hop", "attachment.principal"),
            _translate(_canonical_name, domains, "scopes", "attachment.principal.domains"),
            _translate(_canonical_name, domains, "tools", "attachment.principal.domains"),
            _translate(_canonical_name, domains, "effects", "attachment.principal.domains"),
            _translate(_evidence, raw["evidence"], "attachment"),
        )


@dataclass(frozen=True)
class DelegationFinding:
    code: str
    attachment: str
    tool: str
    hop: str | None
    dimension: str | None
    message: str
    support: tuple[str, ...]


@dataclass(frozen=True)
class DelegationDecision:
    attachment: str
    tool: str
    delegation: str
    hop: str
    support: tuple[str, ...]


@dataclass(frozen=True)
class DelegationAnalysis:
    authority: Authority
    findings: tuple[DelegationFinding, ...]
    attenuated: tuple[DelegationDecision, ...]
    as_of: str

    @property
    def clean(self) -> bool:
        return not self.findings


def _attachment_to_ir(value: DelegationAttachment) -> AuthorityIR:
    source_id = _entity_id("source", f"delegation-attachment:{value.id}")
    tool_id = _entity_id("tool", value.target.tool)
    principal_id = _entity_id("principal", value.id)
    delegation_id = _entity_id("delegation", value.delegation)
    hop_id = _entity_id("hop", value.hop)
    entities = (
        Entity(tool_id, "tool", value.target.tool),
        Entity(principal_id, "principal", value.id),
        Entity(delegation_id, "delegation", value.delegation),
        Entity(hop_id, "hop", value.hop),
    )
    facts = (
        _fact(tool_id, "name", value.target.tool, source_id, "/target/tool", value.evidence),
        _fact(tool_id, "target", value.target.as_dict(), source_id, "/target", value.evidence),
        _fact(tool_id, "principal", principal_id, source_id, "/id", value.evidence),
        _fact(principal_id, "name", value.id, source_id, "/id", value.evidence),
        _fact(
            principal_id,
            "kind",
            "delegated_user",
            source_id,
            "/principal/kind",
            value.evidence,
        ),
        _fact(
            principal_id,
            "delegation",
            delegation_id,
            source_id,
            "/principal/delegation",
            value.evidence,
        ),
        _fact(principal_id, "hop", hop_id, source_id, "/principal/hop", value.evidence),
        _fact(
            principal_id,
            "domains",
            {
                "scopes": value.scope_domain,
                "tools": value.tool_domain,
                "effects": value.effect_domain,
            },
            source_id,
            "/principal/domains",
            value.evidence,
        ),
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
        _fact(
            delegation_id,
            "name",
            value.delegation,
            source_id,
            "/principal/delegation",
            value.evidence,
        ),
        _fact(hop_id, "name", value.hop, source_id, "/principal/hop", value.evidence),
    )
    edges = (
        Edge(
            _edge_id(tool_id, "acts_as", principal_id),
            tool_id,
            "acts_as",
            principal_id,
            (_fact_id(tool_id, "principal"),),
        ),
        Edge(
            _edge_id(principal_id, "uses_delegation", delegation_id),
            principal_id,
            "uses_delegation",
            delegation_id,
            (_fact_id(principal_id, "delegation"),),
        ),
        Edge(
            _edge_id(principal_id, "at_hop", hop_id),
            principal_id,
            "at_hop",
            hop_id,
            (_fact_id(principal_id, "hop"),),
        ),
    )
    graph = AuthorityIR(
        IR_VERSION,
        (
            Source(
                source_id,
                "delegation-attachment",
                f"memory:delegation-attachment:{value.id}",
                value.version,
                None,
                _profile_digest(entities, facts, edges),
                DELEGATION_ATTACHMENT_ADAPTER,
                DELEGATION_ATTACHMENT_ADAPTER_VERSION,
                hashlib.sha256(value.to_json().encode()).hexdigest(),
            ),
        ),
        entities,
        facts,
        edges,
    )
    _validate_attachment_profile(graph)
    return graph


def _validate_attachment_profile(graph: AuthorityIR) -> None:
    _translate(
        _validate_projection_source,
        graph,
        "delegation-attachment",
        DELEGATION_ATTACHMENT_ADAPTER,
        DELEGATION_ATTACHMENT_ADAPTER_VERSION,
        DELEGATION_ATTACHMENT_VERSION,
    )
    entities = {entity.id: entity for entity in graph.entities}
    counts = {
        kind: sum(entity.kind == kind for entity in graph.entities)
        for kind in {"tool", "principal", "delegation", "hop"}
    }
    if counts != {"tool": 1, "principal": 1, "delegation": 1, "hop": 1}:
        raise DelegationFormatError("delegation attachment IR profile has unsupported entities")
    predicates = {
        entity.id: {
            "tool": {"name", "target", "principal"},
            "principal": {
                "name",
                "kind",
                "delegation",
                "hop",
                "domains",
                "reviewer",
                "review_expires",
            },
            "delegation": {"name"},
            "hop": {"name"},
        }[entity.kind]
        for entity in graph.entities
    }
    _translate(_validate_projection_facts, graph, entities, predicates)
    facts = {(fact.subject, fact.predicate): fact for fact in graph.facts}
    tool = next(entity for entity in graph.entities if entity.kind == "tool")
    principal = next(entity for entity in graph.entities if entity.kind == "principal")
    _translate(_validate_projected_evidence, graph, principal.id, facts)
    target = _translate(_tool_target, facts[(tool.id, "target")].value, "attachment_IR.target")
    if target.tool != tool.name:
        raise DelegationFormatError("delegation attachment IR target does not match tool")
    if facts[(principal.id, "kind")].value != "delegated_user":
        raise DelegationFormatError("delegation attachment IR profile has invalid kind")


def _chain_locators(chain: DelegationChain) -> set[str]:
    result: set[str] = set()
    for hop in chain.hops:
        for source in (hop.source, hop.scopes.source, hop.tools.source, hop.effects.source):
            if source is not None:
                result.add(source.locator)
    return result


def _surface_for(hop: DelegationHop, dimension: str) -> SurfaceDimension:
    return getattr(hop, dimension)


def _surface_actual(tool: Tool, dimension: str) -> set[str]:
    if dimension == "scopes":
        return set(tool.requires)
    if dimension == "tools":
        return {tool.name}
    return {tool.effect}


def analyse_delegations(
    mandate: Mandate,
    attachments: Sequence[DelegationAttachment],
    chains: Sequence[DelegationChain],
    source_bytes: Mapping[str, bytes],
    *,
    as_of: str,
    depth: int | None = None,
    target_source: str | None = None,
    target_binding: str | None = None,
) -> DelegationAnalysis:
    """Consume only re-read and profile-validated delegation evidence."""
    evaluated_at = _timestamp({"as_of": as_of}, "as_of", "analysis")
    canonical_attachments = tuple(
        DelegationAttachment.from_json(item.to_json()) for item in attachments
    )
    canonical_chains = tuple(DelegationChain.from_json(item.to_json()) for item in chains)
    attachment_graphs = {item.id: item.to_ir() for item in canonical_attachments}
    for graph in attachment_graphs.values():
        _validate_attachment_profile(graph)
    chain_graphs = {item.id: item.to_ir() for item in canonical_chains}
    for graph in chain_graphs.values():
        _validate_delegation_profile(graph)

    authority = analyse(mandate, depth=depth)
    tools = {tool.name: tool for tool in mandate.tools}
    attachment_counts: dict[str, int] = {}
    chain_groups: dict[str, list[DelegationChain]] = {}
    for item in canonical_attachments:
        attachment_counts[item.id] = attachment_counts.get(item.id, 0) + 1
    for chain in canonical_chains:
        chain_groups.setdefault(chain.id, []).append(chain)
    findings: list[DelegationFinding] = []
    decisions: list[DelegationDecision] = []

    def finding(
        code: str,
        attachment: DelegationAttachment,
        message: str,
        *,
        hop: str | None = None,
        dimension: str | None = None,
    ) -> None:
        support: set[str] = set()
        attachment_graph = attachment_graphs.get(attachment.id)
        if attachment_graph is not None:
            support.update(source.id for source in attachment_graph.sources)
            support.update(fact.id for fact in attachment_graph.facts)
            support.update(edge.id for edge in attachment_graph.edges)
        chain_graph = chain_graphs.get(attachment.delegation)
        if chain_graph is not None:
            support.update(source.id for source in chain_graph.sources)
            support.update(fact.id for fact in chain_graph.facts)
            support.update(edge.id for edge in chain_graph.edges)
        findings.append(
            DelegationFinding(
                code,
                attachment.id,
                attachment.target.tool,
                hop,
                dimension,
                message,
                tuple(sorted(support)),
            )
        )

    for attachment in sorted(canonical_attachments, key=lambda item: item.id):
        start = len(findings)
        tool = tools.get(attachment.target.tool)
        if tool is None:
            finding(
                "delegation.unresolved",
                attachment,
                "target tool is not present in the mandate",
            )
            continue
        if attachment_counts[attachment.id] != 1:
            finding("delegation.unresolved", attachment, "attachment id is declared more than once")
            continue
        if (
            target_source is None
            or target_binding is None
            or attachment.target.source != target_source
            or attachment.target.binding != target_binding
        ):
            finding(
                "delegation.unresolved",
                attachment,
                "attachment target does not match the selected source binding",
            )
            continue
        matches = chain_groups.get(attachment.delegation, [])
        if len(matches) != 1:
            finding("delegation.unresolved", attachment, "delegation chain is missing or ambiguous")
            continue
        chain = matches[0]
        hops = {hop.id: hop for hop in chain.hops}
        referenced = hops.get(attachment.hop)
        if referenced is None:
            finding("delegation.unresolved", attachment, "referenced delegation hop is missing")
            continue
        attachment_eligible = True
        if attachment.evidence.confidence != "exact" or attachment.evidence.review != "accepted":
            attachment_eligible = False
            finding(
                "delegation.unresolved",
                attachment,
                "attachment evidence is not exact and accepted",
            )
        if attachment.evidence.expires is None or attachment.evidence.expires < evaluated_at[:10]:
            attachment_eligible = False
            finding("delegation.unresolved", attachment, "attachment review is expired")
        source_verified = True
        try:
            locators = _chain_locators(chain)
            chain.verify_sources(
                {
                    locator: source_bytes[locator]
                    for locator in locators
                    if locator in source_bytes
                }
            )
        except DelegationFormatError as exc:
            source_verified = False
            finding("delegation.source-unresolved", attachment, str(exc))
        history_complete = chain.actor_history_complete
        if not chain.actor_history_complete:
            finding(
                "delegation.actor-history-unresolved",
                attachment,
                "partial actor history makes every chain-derived decision unresolved",
            )
        surface_eligible: dict[tuple[str, str], bool] = {}
        for hop in chain.hops:
            hop_eligible = source_verified and history_complete
            if hop.evidence.confidence != "exact" or hop.evidence.review != "accepted":
                hop_eligible = False
                finding(
                    "delegation.unresolved",
                    attachment,
                    "hop evidence is not exact and accepted",
                    hop=hop.id,
                )
            if hop.evidence.expires is None or hop.evidence.expires < evaluated_at[:10]:
                hop_eligible = False
                finding("delegation.unresolved", attachment, "hop review is expired", hop=hop.id)
            if hop.validity.kind != "window":
                hop_eligible = False
                finding(
                    "delegation.validity-unresolved",
                    attachment,
                    "hop validity lacks an absolute timestamp window",
                    hop=hop.id,
                )
            elif not (hop.validity.issued_at <= evaluated_at < hop.validity.expires_at):
                hop_eligible = False
                finding(
                    "delegation.validity-unresolved",
                    attachment,
                    "evaluation time is outside the hop validity window",
                    hop=hop.id,
                )
            for dimension in ("scopes", "tools", "effects"):
                surface = _surface_for(hop, dimension)
                eligible = hop_eligible
                if surface.completeness != "complete":
                    eligible = False
                    finding(
                        "delegation.surface-unresolved",
                        attachment,
                        "surface is not complete and comparable",
                        hop=hop.id,
                        dimension=dimension,
                    )
                elif (
                    surface.evidence is None
                    or surface.evidence.confidence != "exact"
                    or surface.evidence.review != "accepted"
                    or surface.evidence.expires is None
                    or surface.evidence.expires < evaluated_at[:10]
                ):
                    eligible = False
                    finding(
                        "delegation.surface-unresolved",
                        attachment,
                        "surface evidence is not current, exact, and accepted",
                        hop=hop.id,
                        dimension=dimension,
                    )
                surface_eligible[(hop.id, dimension)] = eligible

        for previous, current in zip(chain.hops, chain.hops[1:], strict=False):
            for dimension in ("scopes", "tools", "effects"):
                before = _surface_for(previous, dimension)
                after = _surface_for(current, dimension)
                if not (
                    surface_eligible[(previous.id, dimension)]
                    and surface_eligible[(current.id, dimension)]
                ):
                    continue
                if before.domain != after.domain:
                    finding(
                        "delegation.surface-unresolved",
                        attachment,
                        "adjacent surfaces use incomparable domains",
                        hop=current.id,
                        dimension=dimension,
                    )
                elif not set(after.members).issubset(before.members):
                    finding(
                        "delegation.widens",
                        attachment,
                        "downstream hop regains authority absent from its grantor hop",
                        hop=current.id,
                        dimension=dimension,
                    )

        for dimension in ("scopes", "tools", "effects"):
            surface = _surface_for(referenced, dimension)
            if (
                surface_eligible[(referenced.id, dimension)]
                and surface.domain != attachment.domain_for(dimension)
            ):
                finding(
                    "delegation.surface-unresolved",
                    attachment,
                    "tool attachment and hop surface use incomparable domains",
                    hop=referenced.id,
                    dimension=dimension,
                )
                continue
            if (
                attachment_eligible
                and surface_eligible[(referenced.id, dimension)]
                and not _surface_actual(tool, dimension).issubset(surface.members)
            ):
                finding(
                    "delegation.widens",
                    attachment,
                    "tool authority exceeds the referenced hop surface",
                    hop=referenced.id,
                    dimension=dimension,
                )
        if len(findings) == start:
            graph = attachment_graphs[attachment.id]
            decisions.append(
                DelegationDecision(
                    attachment.id,
                    tool.name,
                    chain.id,
                    referenced.id,
                    tuple(
                        sorted(
                            {
                                *(source.id for source in graph.sources),
                                *(fact.id for fact in graph.facts),
                                *(edge.id for edge in graph.edges),
                                *(source.id for source in chain_graphs[chain.id].sources),
                                *(fact.id for fact in chain_graphs[chain.id].facts),
                                *(edge.id for edge in chain_graphs[chain.id].edges),
                            }
                        )
                    ),
                )
            )
    return DelegationAnalysis(
        authority,
        tuple(dict.fromkeys(findings)),
        tuple(decisions),
        evaluated_at,
    )
