"""Regenerate canonical delegation chains from superseded and captured evidence.

This repository tool owns grant-v1 and Authorizer-specific conversion. The
installed runtime owns strict chain and attachment readers, IR projection, and
delegation analysis only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentmandate._conditions import (
    GRANT_EFFECTS,
    ConditionFormatError,
    ContextSource,
    Evidence,
    _canonical_date,
    _canonical_members,
    _canonical_name,
    _digest_string,
    _evidence,
    _load_json,
    _nonempty_string,
    _record,
    _relative_path,
)
from agentmandate._delegation import (
    DELEGATION_VERSION,
    DelegationChain,
    DelegationFormatError,
    DelegationHop,
    DelegationSource,
    DelegationValidity,
    SurfaceDimension,
    _members,
    _translate,
)

GRANT_VERSION = 1
_GRANT_ROOT_FIELDS = {
    "grant_version",
    "id",
    "grantor",
    "subject",
    "actor",
    "audience",
    "surface",
    "issued",
    "expires",
    "evidence",
    "source",
}


@dataclass(frozen=True)
class Grant:
    """The superseded grant-v1 record retained for repository replay."""

    version: int
    id: str
    grantor: str
    subject: str
    actor: str
    audience: str
    scopes: tuple[str, ...]
    tools: tuple[str, ...]
    effects: tuple[str, ...]
    issued: str
    expires: str
    evidence: Evidence
    source: ContextSource | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "grant_version": self.version,
            "id": self.id,
            "grantor": self.grantor,
            "subject": self.subject,
            "actor": self.actor,
            "audience": self.audience,
            "surface": {
                "scopes": list(self.scopes),
                "tools": list(self.tools),
                "effects": list(self.effects),
            },
            "issued": self.issued,
            "expires": self.expires,
            "evidence": self.evidence.as_dict(),
        }
        if self.source is not None:
            result["source"] = self.source.as_dict()
        return result

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ) + "\n"

    def verify_source(self, content: bytes) -> None:
        if not isinstance(content, bytes):
            raise ConditionFormatError(
                "condition contract grant.verify_source requires bytes"
            )
        if self.source is None or self.source.content_sha256 is None:
            raise ConditionFormatError(
                "condition contract grant declares no content digest to verify"
            )
        if self.source.content_sha256 != hashlib.sha256(content).hexdigest():
            raise ConditionFormatError(
                "condition contract grant source.content_sha256 does not match "
                "the supplied bytes"
            )

    @classmethod
    def from_json(cls, text: str) -> Grant:
        raw = _record(
            _load_json(text, "grant"), "grant", set(), _GRANT_ROOT_FIELDS
        )
        version = raw.get("grant_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ConditionFormatError(
                "condition contract grant_version must be an integer; this "
                f"build reads {GRANT_VERSION}"
            )
        if version != GRANT_VERSION:
            raise ConditionFormatError(
                f"unsupported grant version {version}; this build reads "
                f"{GRANT_VERSION}"
            )
        body = _record(
            raw,
            "grant",
            {
                "id",
                "grantor",
                "subject",
                "actor",
                "audience",
                "surface",
                "issued",
                "expires",
                "evidence",
            },
            {"grant_version", "source"},
        )

        identifier = _nonempty_string(body, "id", "grant")
        grantor = _nonempty_string(body, "grantor", "grant")
        subject = _nonempty_string(body, "subject", "grant")
        actor = _nonempty_string(body, "actor", "grant")
        audience = _nonempty_string(body, "audience", "grant")
        issued = _canonical_date(body, "issued", "grant")
        expires = _canonical_date(body, "expires", "grant")
        if issued > expires:
            raise ConditionFormatError(
                "condition contract grant.issued must not be after grant.expires"
            )

        surface = _record(
            body["surface"],
            "grant.surface",
            {"effects", "scopes", "tools"},
        )
        effects = _canonical_members(
            surface["effects"], "grant.surface", "effects", allowed=GRANT_EFFECTS
        )
        scopes = _canonical_members(surface["scopes"], "grant.surface", "scopes")
        tools = _canonical_members(surface["tools"], "grant.surface", "tools")
        evidence = _evidence(body["evidence"], "grant")

        grant_source: ContextSource | None = None
        if "source" in body:
            source_raw = _record(
                body["source"],
                "grant.source",
                {"kind", "locator"},
                {"producer_version", "content_sha256"},
            )
            grant_source = ContextSource(
                kind=_nonempty_string(source_raw, "kind", "grant.source"),
                locator=_relative_path(source_raw, "locator", "grant.source"),
                producer_version=source_raw.get("producer_version"),
                content_sha256=_digest_string(
                    source_raw, "content_sha256", "grant.source"
                ),
            )
            producer = grant_source.producer_version
            if producer is not None and not isinstance(producer, str):
                raise ConditionFormatError(
                    "condition contract grant.source.producer_version must be "
                    "a string or null"
                )

        return cls(
            version=version,
            id=identifier,
            grantor=grantor,
            subject=subject,
            actor=actor,
            audience=audience,
            scopes=scopes,
            tools=tools,
            effects=effects,
            issued=issued,
            expires=expires,
            evidence=evidence,
            source=grant_source,
        )


def migrate_grant_v1(grant: Grant) -> DelegationChain:
    """Migrate one digest-pinned legacy grant into delegation-chain v1."""

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
    return DelegationChain(DELEGATION_VERSION, grant.id, grant.subject, (hop,))


def migrate_authorizer_capture(text: str, evidence: Evidence) -> DelegationChain:
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
        _members(value["actor_chain"], f"{path}.actor_chain")
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
    projected = DelegationChain(
        DELEGATION_VERSION, "authorizer-demo-chain", subject_name, tuple(hops)
    )
    return DelegationChain.from_json(projected.to_json())


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
GRANT_PATH = FIXTURES / "delegation-grant-v1.json"
GRANT_CAPTURE_PATH = FIXTURES / "delegation-grant-capture.json"
GRANT_CHAIN_PATH = FIXTURES / "delegation-chain-migrated-v1.json"
AUTHORIZER_PATH = ROOT / "docs" / "evidence" / "authorizer-delegation" / "capture.json"
AUTHORIZER_CHAIN_PATH = FIXTURES / "delegation-chain-authorizer-v1.json"
AUTHORIZER_REVIEW = Evidence("exact", "accepted", "evidence-review", "2027-08-25")


def verify_fixtures() -> None:
    grant = Grant.from_json(GRANT_PATH.read_text(encoding="utf-8"))
    grant_capture = GRANT_CAPTURE_PATH.read_bytes()
    grant.verify_source(grant_capture)
    grant_chain = migrate_grant_v1(grant)
    if grant_chain.to_json() != GRANT_CHAIN_PATH.read_text(encoding="utf-8"):
        raise DelegationFormatError(
            "delegation migration no longer reproduces canonical grant-v1 chain"
        )
    grant_chain.verify_sources({grant.source.locator: grant_capture})

    authorizer_bytes = AUTHORIZER_PATH.read_bytes()
    authorizer_chain = migrate_authorizer_capture(
        authorizer_bytes.decode("utf-8"), AUTHORIZER_REVIEW
    )
    if authorizer_chain.to_json() != AUTHORIZER_CHAIN_PATH.read_text(encoding="utf-8"):
        raise DelegationFormatError(
            "delegation migration no longer reproduces canonical Authorizer chain"
        )
    authorizer_chain.verify_sources(
        {"docs/evidence/authorizer-delegation/capture.json": authorizer_bytes}
    )


def main() -> None:
    verify_fixtures()
    print("delegation evidence migrations: canonical fixtures match source evidence")


if __name__ == "__main__":
    main()
