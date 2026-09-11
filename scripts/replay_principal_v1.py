"""Replay superseded principal-v1 artifacts outside the installed runtime.

Delegation attachment v2 replaces only the delegated-user consumption path.
The fixed-credential and intersecting shapes have no v2 equivalent, so this
tool preserves their exact historical reader and Authority IR projections
without presenting them as supported runtime contracts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentmandate._conditions import (
    ConditionFormatError,
    Evidence,
    ToolTarget,
    _canonical_date,
    _canonical_json,
    _canonical_members,
    _canonical_name,
    _closed_string,
    _evidence,
    _fact,
    _load_json,
    _profile_digest,
    _record,
    _tool_target,
    _validate_projected_evidence,
    _validate_projection_facts,
    _validate_projection_source,
    _version,
)
from agentmandate._ir import (
    IR_VERSION,
    AuthorityIR,
    Edge,
    Entity,
    Source,
    _edge_id,
    _entity_id,
    _fact_id,
)

TOOL_PRINCIPAL_VERSION = 1
PRINCIPAL_ADAPTER = "agentmandate.tool-principal"
PRINCIPAL_ADAPTER_VERSION = 1
PRINCIPAL_KINDS = frozenset(
    {"delegated_user", "fixed_user_credential", "intersecting"}
)
_TOOL_PRINCIPAL_ROOT_FIELDS = {
    "principal_version",
    "id",
    "target",
    "principal",
    "evidence",
}


@dataclass(frozen=True)
class ToolPrincipal:
    """Superseded structured-principal record retained for repository replay."""

    version: int
    id: str
    target: ToolTarget
    kind: str
    evidence: Evidence
    actor: str | None = None
    audience: str | None = None
    subject: str | None = None
    grant: str | None = None
    expires: str | None = None
    principals: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        principal: dict[str, Any] = {"kind": self.kind}
        for field in ("actor", "audience", "subject", "grant", "expires"):
            value = getattr(self, field)
            if value is not None:
                principal[field] = value
        if self.principals:
            principal["principals"] = list(self.principals)
        return {
            "principal_version": self.version,
            "id": self.id,
            "target": self.target.as_dict(),
            "principal": principal,
            "evidence": self.evidence.as_dict(),
        }

    def to_json(self) -> str:
        return _canonical_json(self.as_dict())

    def to_ir(self) -> AuthorityIR:
        return _principal_to_ir(self)

    @classmethod
    def from_json(cls, text: str) -> ToolPrincipal:
        raw = _record(
            _load_json(text, "tool principal"),
            "tool_principal",
            _TOOL_PRINCIPAL_ROOT_FIELDS,
        )
        version = _version(
            raw, "principal_version", "tool_principal", TOOL_PRINCIPAL_VERSION
        )
        principal = _record(
            raw["principal"],
            "tool_principal.principal",
            {"kind"},
            {"actor", "audience", "subject", "grant", "expires", "principals"},
        )
        kind = _closed_string(
            principal,
            "kind",
            "tool_principal.principal",
            PRINCIPAL_KINDS,
        )
        values = _principal_values(principal, kind)
        return cls(
            version=version,
            id=_canonical_name(raw, "id", "tool_principal"),
            target=_tool_target(raw["target"], "tool_principal.target"),
            kind=kind,
            evidence=_evidence(raw["evidence"], "tool_principal"),
            **values,
        )


def _principal_values(raw: dict[str, Any], kind: str) -> dict[str, Any]:
    fields = set(raw) - {"kind"}
    if kind == "intersecting":
        if fields != {"principals"}:
            raise ConditionFormatError(
                "condition contract intersecting principal requires only principals"
            )
        principals = _canonical_members(
            raw["principals"], "tool_principal.principal", "principals"
        )
        if len(principals) < 2:
            raise ConditionFormatError(
                "condition contract intersecting principal requires at least two principals"
            )
        return {"principals": principals}
    required = (
        {"actor", "audience"}
        if kind == "fixed_user_credential"
        else {"subject", "actor", "audience", "grant", "expires"}
    )
    if fields != required:
        raise ConditionFormatError(
            f"condition contract {kind} principal has an invalid field set"
        )
    result = {
        field: _canonical_name(raw, field, "tool_principal.principal")
        for field in required
    }
    if kind == "delegated_user":
        result["expires"] = _canonical_date(
            raw, "expires", "tool_principal.principal"
        )
    return result


def _principal_to_ir(value: ToolPrincipal) -> AuthorityIR:
    source_id = _entity_id("source", f"tool-principal:{value.id}")
    tool_id = _entity_id("tool", value.target.tool)
    principal_id = _entity_id("principal", value.id)
    entities: list[Entity] = [
        Entity(tool_id, "tool", value.target.tool),
        Entity(principal_id, "principal", value.id),
    ]
    facts = [
        _fact(tool_id, "name", value.target.tool, source_id, "/target/tool", value.evidence),
        _fact(tool_id, "target", value.target.as_dict(), source_id, "/target", value.evidence),
        _fact(tool_id, "principal", principal_id, source_id, "/id", value.evidence),
        _fact(principal_id, "name", value.id, source_id, "/id", value.evidence),
        _fact(principal_id, "kind", value.kind, source_id, "/principal/kind", value.evidence),
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
    ]
    edges = [
        Edge(
            _edge_id(tool_id, "acts_as", principal_id),
            tool_id,
            "acts_as",
            principal_id,
            (_fact_id(tool_id, "principal"),),
        )
    ]
    if value.kind == "intersecting":
        member_ids = [_entity_id("principal", name) for name in value.principals]
        facts.append(
            _fact(
                principal_id,
                "principals",
                member_ids,
                source_id,
                "/principal/principals",
                value.evidence,
            )
        )
        for index, (name, member_id) in enumerate(
            zip(value.principals, member_ids, strict=True)
        ):
            entities.append(Entity(member_id, "principal", name))
            facts.append(
                _fact(
                    member_id,
                    "name",
                    name,
                    source_id,
                    f"/principal/principals/{index}",
                    value.evidence,
                )
            )
            edges.append(
                Edge(
                    _edge_id(principal_id, "constrained_by", member_id),
                    principal_id,
                    "constrained_by",
                    member_id,
                    (_fact_id(principal_id, "principals"),),
                )
            )
    else:
        for field in ("actor", "audience", "subject", "expires"):
            item = getattr(value, field)
            if item is not None:
                facts.append(
                    _fact(
                        principal_id,
                        field,
                        item,
                        source_id,
                        f"/principal/{field}",
                        value.evidence,
                    )
                )
        if value.grant is not None:
            grant_id = _entity_id("grant", value.grant)
            entities.append(Entity(grant_id, "grant", value.grant))
            facts.extend(
                (
                    _fact(
                        principal_id,
                        "grant",
                        grant_id,
                        source_id,
                        "/principal/grant",
                        value.evidence,
                    ),
                    _fact(
                        grant_id,
                        "name",
                        value.grant,
                        source_id,
                        "/principal/grant",
                        value.evidence,
                    ),
                )
            )
            edges.append(
                Edge(
                    _edge_id(principal_id, "under_grant", grant_id),
                    principal_id,
                    "under_grant",
                    grant_id,
                    (_fact_id(principal_id, "grant"),),
                )
            )
    entity_tuple = tuple(entities)
    fact_tuple = tuple(facts)
    edge_tuple = tuple(edges)
    graph = AuthorityIR(
        IR_VERSION,
        (
            Source(
                source_id,
                "tool-principal",
                f"memory:tool-principal:{value.id}",
                value.version,
                None,
                _profile_digest(entity_tuple, fact_tuple, edge_tuple),
                PRINCIPAL_ADAPTER,
                PRINCIPAL_ADAPTER_VERSION,
                hashlib.sha256(value.to_json().encode("utf-8")).hexdigest(),
            ),
        ),
        entity_tuple,
        fact_tuple,
        edge_tuple,
    )
    _validate_principal_profile(graph)
    return graph


def _validate_principal_profile(graph: AuthorityIR) -> None:
    _validate_projection_source(
        graph, "tool-principal", PRINCIPAL_ADAPTER, PRINCIPAL_ADAPTER_VERSION
    )
    entities = {entity.id: entity for entity in graph.entities}
    if any(entity.kind not in {"tool", "principal", "grant"} for entity in graph.entities):
        raise ConditionFormatError("principal IR profile has unsupported entities")
    facts = {(fact.subject, fact.predicate): fact for fact in graph.facts}
    roots = [
        entity
        for entity in graph.entities
        if entity.kind == "principal" and (entity.id, "kind") in facts
    ]
    if len(roots) != 1:
        raise ConditionFormatError("principal IR profile requires one structured principal")
    tools = [entity for entity in graph.entities if entity.kind == "tool"]
    if len(tools) != 1:
        raise ConditionFormatError("principal IR profile requires one tool")
    root = roots[0]
    kind = facts[(root.id, "kind")].value
    expected = {
        "fixed_user_credential": {
            "name",
            "kind",
            "actor",
            "audience",
            "reviewer",
            "review_expires",
        },
        "intersecting": {
            "name",
            "kind",
            "principals",
            "reviewer",
            "review_expires",
        },
        "delegated_user": {
            "name",
            "kind",
            "subject",
            "actor",
            "audience",
            "grant",
            "expires",
            "reviewer",
            "review_expires",
        },
    }
    if not isinstance(kind, str) or kind not in expected:
        raise ConditionFormatError("principal IR profile has an invalid kind")
    predicates = {
        entity.id: (
            {"name", "target", "principal"}
            if entity.kind == "tool"
            else {"name"}
            if entity.kind == "grant" or entity.id != root.id
            else expected[kind]
        )
        for entity in graph.entities
    }
    _validate_projection_facts(graph, entities, predicates)
    target = _tool_target(facts[(tools[0].id, "target")].value, "principal_IR.target")
    if target.tool != tools[0].name:
        raise ConditionFormatError("principal IR profile target does not match tool")
    _validate_projected_evidence(graph, root.id, facts)
    if kind == "intersecting":
        members = facts[(root.id, "principals")].value
        if (
            not isinstance(members, list)
            or len(members) < 2
            or any(not isinstance(item, str) for item in members)
        ):
            raise ConditionFormatError("principal IR profile has an invalid intersection")
        member_entities = {
            entity.id
            for entity in graph.entities
            if entity.kind == "principal" and entity.id != root.id
        }
        if set(members) != member_entities or len(members) != len(member_entities):
            raise ConditionFormatError("principal IR profile members do not match entities")
    elif kind == "delegated_user":
        expires = facts[(root.id, "expires")].value
        try:
            _canonical_date({"expires": expires}, "expires", "principal_IR")
        except ConditionFormatError as exc:
            raise ConditionFormatError(
                "principal IR profile has an invalid expiry"
            ) from exc
        grants = [entity for entity in graph.entities if entity.kind == "grant"]
        if len(grants) != 1 or facts[(root.id, "grant")].value != grants[0].id:
            raise ConditionFormatError("principal IR profile grant does not match entity")
    elif any(entity.kind == "grant" for entity in graph.entities):
        raise ConditionFormatError("principal IR profile has an unexpected grant")


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PROJECTION_DIGESTS = {
    "principal-fixed-user-v1.json": (
        "21b1edd7d87175ddfe971577817a0b3ea3540c3f7b6c06e28357db2bd2052c29"
    ),
    "principal-intersecting-v1.json": (
        "e37c6c657b27b10c5418c85bf0cf62e872d89e12fddab8e78d50917b5d9c6b35"
    ),
    "principal-delegated-user-v1.json": (
        "249242e97cfdd8017a1b0e54c4284df94d1eb46af48516c4932ceae89d51a6f4"
    ),
}


def verify_fixtures() -> None:
    for fixture, expected_digest in PROJECTION_DIGESTS.items():
        committed = (FIXTURES / fixture).read_text(encoding="utf-8")
        principal = ToolPrincipal.from_json(committed)
        if principal.to_json() != committed:
            raise ConditionFormatError(
                f"principal-v1 replay no longer round-trips canonical fixture {fixture}"
            )
        projection_digest = hashlib.sha256(
            principal.to_ir().to_json().encode("utf-8")
        ).hexdigest()
        if projection_digest != expected_digest:
            raise ConditionFormatError(
                f"principal-v1 replay projection differs for canonical fixture {fixture}"
            )


def main() -> None:
    verify_fixtures()
    print("principal-v1 replay: canonical fixtures and projections match")


if __name__ == "__main__":
    main()
