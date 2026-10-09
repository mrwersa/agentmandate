"""Principal/session observations without shared-mandate accounting authority."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._continuity import (
    ContinuityEvidence,
    ContinuityFormatError,
    ContinuitySource,
    _canonical_json,
    _eligible_evidence,
    _evaluation_time,
    _evidence,
    _integer,
    _load,
    _record,
    _sources,
    _string,
    _strings,
    _verify_sources,
)
from .manifest import Mandate
from .reach import analyse


def _array(value: Any, path: str, minimum: int = 1) -> list[Any]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ContinuityFormatError(f"{path} must contain at least {minimum} records")
    return value


def _reference(value: Any, path: str, identities: set[str]) -> str:
    name = _string(value, path)
    if name not in identities:
        raise ContinuityFormatError(f"{path} refers to an undeclared identity")
    return name


def _validate_trials(raw: Any, principals: set[str], sources: set[str]) -> None:
    trial_ids: set[str] = set()
    occurrences: set[tuple[str, str]] = set()
    for trial in _array(raw, "trials"):
        row = _record(trial, "trial", {"id", "ordering", "calls"})
        identity = _string(row["id"], "trial.id")
        if identity in trial_ids:
            raise ContinuityFormatError("duplicate trial identity")
        trial_ids.add(identity)
        if row["ordering"] not in ("attested_program_order", "unknown"):
            raise ContinuityFormatError("trial.ordering must be attested_program_order or unknown")
        for call in _array(row["calls"], "trial.calls", 2):
            call = _record(
                call,
                "call",
                {
                    "principal",
                    "session",
                    "amount",
                    "completion",
                    "native_outcome",
                    "source",
                    "pointer",
                },
            )
            _reference(call["principal"], "call.principal", principals)
            if call["session"] is not None:
                _string(call["session"], "call.session")
            _integer(call["amount"], "call.amount")
            if call["completion"] not in ("completed", "not_completed", "unknown"):
                raise ContinuityFormatError("call.completion has an unsupported value")
            _string(call["native_outcome"], "call.native_outcome")
            source = _reference(call["source"], "call.source", sources)
            pointer = _string(call["pointer"], "call.pointer")
            if re.fullmatch(r"/(?:[^~]|~[01])*", pointer) is None:
                raise ContinuityFormatError("call.pointer must be a non-root JSON Pointer")
            occurrence = (source, pointer)
            if occurrence in occurrences:
                raise ContinuityFormatError("duplicate captured call reference")
            occurrences.add(occurrence)


@dataclass(frozen=True)
class PrincipalContinuity:
    body: dict[str, Any]
    sources: tuple[ContinuitySource, ...]
    evidence: ContinuityEvidence
    version: int = 1

    @classmethod
    def from_json(cls, text: str) -> PrincipalContinuity:
        raw = _record(
            _load(text, "principal continuity"),
            "principal continuity",
            {
                "principal_continuity_version",
                "provider",
                "boundary",
                "measurement",
                "principals",
                "trials",
                "sources",
                "evidence",
            },
        )
        if _integer(raw["principal_continuity_version"], "principal_continuity_version") != 1:
            raise ContinuityFormatError("unsupported principal continuity version")
        _string(raw["provider"], "provider")
        _string(raw["boundary"], "boundary")
        measurement = _record(raw["measurement"], "measurement", {"tool", "dimension", "unit"})
        for key, value in measurement.items():
            _string(value, f"measurement.{key}")
        sources = _sources(raw["sources"], "sources")
        source_ids = {source.id for source in sources}
        principals: set[str] = set()
        for principal in _array(raw["principals"], "principals"):
            principal = _record(principal, "principal", {"alias", "authentication", "sources"})
            alias = _string(principal["alias"], "principal.alias")
            if alias in principals:
                raise ContinuityFormatError("duplicate principal alias")
            principals.add(alias)
            _string(principal["authentication"], "principal.authentication")
            _strings(principal["sources"], "principal.sources", frozenset(source_ids))
        _validate_trials(raw["trials"], principals, source_ids)
        evidence = _evidence(raw["evidence"], "evidence")
        raw["sources"] = [source.as_dict() for source in sources]
        raw["principals"] = sorted(raw["principals"], key=lambda item: item["alias"])
        raw["trials"] = sorted(raw["trials"], key=lambda item: item["id"])
        return cls(raw, sources, evidence)

    def to_json(self) -> str:
        return _canonical_json(self.body)


def _trial_result(trial: dict[str, Any]) -> dict[str, Any]:
    calls = trial["calls"]
    completed = {call["principal"]: 0 for call in calls}
    for call in calls:
        if call["completion"] == "completed":
            completed[call["principal"]] += call["amount"]
    relations = []
    for before, after in zip(calls[:-1], calls[1:], strict=True):
        session = "unknown"
        if before["session"] is not None and after["session"] is not None:
            session = "same" if before["session"] == after["session"] else "changed"
        relations.append(
            {
                "principal": "same" if before["principal"] == after["principal"] else "changed",
                "session": session,
            }
        )
    return {
        **trial,
        "relations": relations,
        "observed_completed_by_principal": completed,
        "completion_known": all(call["completion"] != "unknown" for call in calls),
        "mandate_identity": "unresolved",
        "state": "unresolved",
        "admission": "unresolved",
        "safe_continuation": "unresolved",
    }


def analyse_principal_continuity(
    mandate: Mandate,
    profile: PrincipalContinuity,
    contents: dict[str, bytes],
    *,
    as_of: datetime,
    mandate_bytes: bytes,
    depth: int | None = None,
) -> dict[str, Any]:
    """Report observations while preserving full, independent manifest authority."""
    profile = PrincipalContinuity.from_json(profile.to_json())
    evaluated_at = _evaluation_time(as_of)
    findings = []
    try:
        _verify_sources(profile.sources, contents)
    except ContinuityFormatError as exc:
        findings.append({"code": "continuity.source-untrusted", "message": str(exc)})
    if not _eligible_evidence(profile.evidence, evaluated_at):
        findings.append(
            {
                "code": "continuity.evidence-untrusted",
                "message": "principal observations are not exact, accepted, and current",
            }
        )
    eligible = not findings
    findings.append(
        {
            "code": "continuity.shared-mandate-unresolved",
            "message": "no supported binding authorizes mandate accounting for these observations",
        }
    )
    return {
        "schema": "agentmandate.principal-continuity/v1",
        "as_of": evaluated_at,
        "profile_sha256": hashlib.sha256(profile.to_json().encode()).hexdigest(),
        "manifest_sha256": hashlib.sha256(mandate_bytes).hexdigest(),
        "provider": profile.body["provider"],
        "boundary": profile.body["boundary"],
        "measurement": profile.body["measurement"],
        "principals": profile.body["principals"],
        "sources": profile.body["sources"],
        "evidence": profile.evidence.as_dict(),
        "observations_eligible": eligible,
        "trials": [_trial_result(trial) for trial in profile.body["trials"]],
        "findings": findings,
        "authority": analyse(mandate, depth=depth).as_dict(),
    }


def render_principal_continuity(result: dict[str, Any]) -> str:
    lines = [
        f"principal continuity observations  evaluated as of {result['as_of']}",
        f"observations eligible: {str(result['observations_eligible']).lower()}",
        f"measurement: {result['measurement']}",
    ]
    for trial in result["trials"]:
        lines.extend(
            [
                f"UNRESOLVED  {trial['id']} ordering={trial['ordering']}",
                f"  relations={trial['relations']}",
                f"  observed completed by principal={trial['observed_completed_by_principal']}",
                f"  completion known={str(trial['completion_known']).lower()}",
            ]
        )
    lines.extend(f"FINDING     {f['code']}: {f['message']}" for f in result["findings"])
    lines.extend(["AUTHORITY", _canonical_json(result["authority"]).rstrip()])
    return "\n".join(lines)
