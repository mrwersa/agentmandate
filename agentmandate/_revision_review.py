"""Scoped revision claims beside, never in place of, baseline continuity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._continuity import (
    AgentCoreContinuity,
    AgentCoreControl,
    ContinuityBinding,
    ContinuityFormatError,
    ContinuitySource,
    _canonical_json,
    _digest,
    _eligible_evidence,
    _evidence,
    _integer,
    _load,
    _record,
    _sources,
    _string,
    _strings,
    _utc,
    _verify_sources,
    analyse_continuity,
)
from ._principal_continuity import _array, _reference
from .manifest import Mandate


def _claim(raw: Any, path: str, fields: set[str], sources: frozenset[str]) -> dict[str, Any]:
    claim = _record(raw, path, fields | {"sources", "evidence"})
    _strings(claim["sources"], f"{path}.sources", sources)
    _evidence(claim["evidence"], f"{path}.evidence")
    return claim


@dataclass(frozen=True)
class RevisionReview:
    body: dict[str, Any]
    sources: tuple[ContinuitySource, ...]
    version: int = 1

    @classmethod
    def from_json(cls, text: str) -> RevisionReview:
        raw = _record(
            _load(text, "revision review"),
            "revision review",
            {
                "revision_review_version",
                "id",
                "manifest_sha256",
                "provider_sha256",
                "binding_sha256",
                "controls",
                "sources",
            },
        )
        if _integer(raw["revision_review_version"], "revision_review_version") != 1:
            raise ContinuityFormatError("unsupported revision review version")
        _string(raw["id"], "id")
        for key in ("manifest_sha256", "provider_sha256", "binding_sha256"):
            _digest(raw[key], key)
        sources = _sources(raw["sources"], "sources")
        source_ids = frozenset(source.id for source in sources)
        controls: set[str] = set()
        for item in _array(raw["controls"], "controls"):
            row = _record(
                item,
                "control",
                {
                    "id",
                    "transition_at",
                    "policies",
                    "association",
                    "comparison",
                    "amendment",
                },
            )
            identity = _string(row["id"], "control.id")
            if identity in controls:
                raise ContinuityFormatError("duplicate revision review control")
            controls.add(identity)
            _utc(row["transition_at"], "transition_at")
            _string(row["association"], "association")
            policies = _record(row["policies"], "policies", {"before", "after"})
            for key, value in policies.items():
                _reference(value, f"policies.{key}", source_ids)
            comparison = _claim(row["comparison"], "comparison", {"relation", "scope"}, source_ids)
            _string(comparison["scope"], "comparison.scope")
            if comparison["relation"] not in ("equivalent", "tightens", "incomparable", "unknown"):
                raise ContinuityFormatError("unsupported comparison relation")
            amendment = _claim(
                row["amendment"],
                "amendment",
                {
                    "status",
                    "issuer",
                    "decision_at",
                    "state_treatment",
                },
                source_ids,
            )
            if amendment["status"] not in ("none", "approved", "unknown"):
                raise ContinuityFormatError("unsupported amendment status")
            if amendment["status"] == "unknown":
                if (
                    amendment["issuer"] is not None
                    or amendment["decision_at"] is not None
                    or amendment["state_treatment"] != "unknown"
                ):
                    raise ContinuityFormatError(
                        "unknown amendment must not assert issuer treatment"
                    )
            else:
                _string(amendment["issuer"], "amendment.issuer")
                if amendment["state_treatment"] != "retain_consumed_and_in_flight":
                    raise ContinuityFormatError(
                        "only retaining-state issuer treatment is supported"
                    )
                if amendment["status"] == "approved":
                    _utc(amendment["decision_at"], "amendment.decision_at")
                elif amendment["decision_at"] is not None:
                    raise ContinuityFormatError("no amendment must have null decision_at")
        raw["sources"] = [source.as_dict() for source in sources]
        raw["controls"] = sorted(raw["controls"], key=lambda item: item["id"])
        return cls(raw, sources)

    def to_json(self) -> str:
        return _canonical_json(self.body)


def _finding(code: str, control: str | None, message: str) -> dict[str, Any]:
    return {"code": f"revision.{code}", "control": control, "message": message}


def _assess(
    row: dict[str, Any],
    control: AgentCoreControl,
    *,
    as_of: str,
    joined: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings = []
    comparison = row["comparison"]
    amendment = row["amendment"]
    comparison_ready = _eligible_evidence(_evidence(comparison["evidence"], "comparison"), as_of)
    amendment_ready = _eligible_evidence(_evidence(amendment["evidence"], "amendment"), as_of)
    for claim, ready in (("comparison", comparison_ready), ("amendment", amendment_ready)):
        if not ready:
            findings.append(
                _finding(f"{claim}-untrusted", control.id, f"{claim} review is ineligible")
            )
    relation = comparison["relation"]
    before, after = control.provider_limits[0], control.provider_limits[-1]
    if (relation == "equivalent" and before != after) or (
        relation == "tightens" and after > before
    ):
        comparison_ready = False
        findings.append(
            _finding(
                "comparison-inconsistent",
                control.id,
                "reviewed relation contradicts observed limits",
            )
        )
    if amendment["status"] == "approved" and amendment["decision_at"] > row["transition_at"]:
        amendment_ready = False
        findings.append(
            _finding(
                "amendment-late",
                control.id,
                "issuer decision follows the captured transition",
            )
        )
    comparability = "unresolved"
    if joined and comparison_ready:
        if relation in ("equivalent", "tightens"):
            comparability = "established_within_reviewed_scope"
        elif relation == "incomparable":
            comparability = "not_comparable"
    issuer_amendment = "unresolved"
    if joined and amendment_ready:
        if amendment["status"] == "none":
            issuer_amendment = "not_required_within_reviewed_scope"
        elif amendment["status"] == "approved":
            issuer_amendment = "approved_retaining_state"
    return {
        "control": control.id,
        "scope": comparison["scope"],
        "relation": relation,
        "comparability": comparability,
        "issuer_amendment": issuer_amendment,
        "safe_continuation": "unresolved",
        "control_joined": joined,
    }, findings


def analyse_revision_review(
    mandate: Mandate,
    provider: AgentCoreContinuity,
    provider_contents: dict[str, bytes],
    binding: ContinuityBinding,
    binding_contents: dict[str, bytes],
    review: RevisionReview,
    review_contents: dict[str, bytes],
    *,
    as_of: datetime,
    mandate_bytes: bytes,
    depth: int | None = None,
) -> dict[str, Any]:
    provider = AgentCoreContinuity.from_json(provider.to_json())
    binding = ContinuityBinding.from_json(binding.to_json())
    review = RevisionReview.from_json(review.to_json())
    baseline = analyse_continuity(
        mandate,
        provider,
        provider_contents,
        binding=binding,
        binding_source_bytes=binding_contents,
        as_of=as_of,
        mandate_bytes=mandate_bytes,
        depth=depth,
    )
    findings = []
    try:
        _verify_sources(review.sources, review_contents)
    except ContinuityFormatError as exc:
        findings.append(_finding("source-untrusted", None, str(exc)))
    raw = review.body
    for field, data in (
        ("manifest_sha256", mandate_bytes),
        ("provider_sha256", provider.to_json().encode()),
        ("binding_sha256", binding.to_json().encode()),
    ):
        if raw[field] != hashlib.sha256(data).hexdigest():
            findings.append(
                _finding("input-mismatch", None, f"{field} does not match supplied input")
            )
    if any(
        f.code
        in {
            "continuity.source-untrusted",
            "continuity.evidence-untrusted",
            "continuity.binding-untrusted",
        }
        for f in baseline.findings
    ):
        findings.append(
            _finding("baseline-untrusted", None, "provider or binding evidence is ineligible")
        )
    rows = {row["id"]: row for row in raw["controls"]}
    if not rows.keys() <= {control.id for control in provider.controls}:
        findings.append(
            _finding("input-mismatch", None, "review names an unknown provider control")
        )
    inputs_eligible = not findings
    sources = {source.id: source for source in review.sources}
    outcomes = {outcome.transition: outcome for outcome in baseline.outcomes}
    assessments = []
    for control in provider.controls:
        row = rows.get(control.id)
        if row is None:
            assessments.append(
                {
                    "control": control.id,
                    "scope": None,
                    "relation": None,
                    "comparability": "unresolved",
                    "issuer_amendment": "unresolved",
                    "safe_continuation": "unresolved",
                    "control_joined": False,
                }
            )
            findings.append(
                _finding("review-missing", control.id, "no review supplied for control")
            )
            continue
        joined = inputs_eligible
        if (
            control.transition not in {"configuration_revision", "limit_revision"}
            or control.revision_changed is not True
            or len(control.provider_limits) > 2
            or row["transition_at"] > baseline.as_of
            or not binding.issued_at <= row["transition_at"] < binding.expires_at
            or sources[row["policies"]["before"]].content_sha256 != binding.policy_sha256
            or not any(
                a.check == "derivation_integrity" and a.status == "established"
                for a in outcomes[control.id].alignments
            )
        ):
            joined = False
            findings.append(
                _finding(
                    "control-unjoined",
                    control.id,
                    "revision, timing, predecessor policy, or mandate binding is unestablished",
                )
            )
        assessment, claim_findings = _assess(row, control, as_of=baseline.as_of, joined=joined)
        assessments.append(assessment)
        findings.extend(claim_findings)
    findings.append(
        _finding(
            "continuation-unresolved",
            None,
            "scoped comparison and retaining-state issuer treatment do not prove safe continuation",
        )
    )
    return {
        "schema": "agentmandate.revision-review/v1",
        "as_of": baseline.as_of,
        "baseline": json.loads(baseline.to_result().to_json()),
        "review": raw,
        "review_sha256": hashlib.sha256(review.to_json().encode()).hexdigest(),
        "review_inputs_eligible": inputs_eligible,
        "assessments": assessments,
        "findings": findings,
    }


def render_revision_review(result: dict[str, Any]) -> str:
    lines = [f"revision review  evaluated as of {result['as_of']}"]
    for row in result["assessments"]:
        lines.append(
            f"REVIEW  {row['control']} comparability={row['comparability']} "
            f"issuer_amendment={row['issuer_amendment']} scope={row['scope']}"
        )
    lines.extend(f"FINDING  {f['code']}: {f['message']}" for f in result["findings"])
    lines.extend(["BASELINE CONTINUITY (unchanged)", _canonical_json(result["baseline"]).rstrip()])
    return "\n".join(lines)
