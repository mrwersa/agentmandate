"""Private delegation-chain records derived from reviewed external evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._conditions import (
    GRANT_EFFECTS,
    ConditionFormatError,
    Evidence,
    Grant,
    _canonical_name,
    _evidence,
    _fact,
    _load_json,
    _profile_digest,
    _record,
    _relative_path,
    _validate_projected_evidence,
    _validate_projection_facts,
    _validate_projection_source,
    _version,
)
from ._ir import IR_VERSION, AuthorityIR, Edge, Entity, Source, _edge_id, _entity_id, _fact_id

DELEGATION_VERSION = 1
DELEGATION_ADAPTER = "agentmandate.delegation-chain"
DELEGATION_ADAPTER_VERSION = 1
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
