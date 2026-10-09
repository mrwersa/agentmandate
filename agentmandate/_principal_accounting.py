"""Reviewed, per-trial monetary accounting; no provider continuity inference."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._continuity import (
    ContinuityEvidence,
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
    _verify_sources,
)
from ._principal_continuity import (
    PrincipalContinuity,
    _array,
    analyse_principal_continuity,
    render_principal_continuity,
)
from .manifest import Mandate, ManifestError, loads


def _unique(value: str, seen: set[str], path: str) -> None:
    if value in seen:
        raise ContinuityFormatError(f"duplicate {path}")
    seen.add(value)


def _mappings(raw: dict[str, Any], source_ids: frozenset[str]) -> None:
    aliases: set[str] = set()
    for item in _array(raw["principals"], "principals"):
        row = _record(item, "principal", {"alias", "subject", "manifest_principal", "sources"})
        for key in ("alias", "subject", "manifest_principal"):
            _string(row[key], f"principal.{key}")
        _unique(row["alias"], aliases, "principal alias")
        _strings(row["sources"], "principal.sources", source_ids)
    trials: set[str] = set()
    accounts: set[str] = set()
    executions: set[str] = set()
    occurrences: set[str] = set()
    for item in _array(raw["trials"], "trials"):
        row = _record(item, "trial", {"id", "account", "sources", "executions"})
        _unique(_string(row["id"], "trial.id"), trials, "trial identity")
        _unique(_string(row["account"], "trial.account"), accounts, "trial account")
        _strings(row["sources"], "trial.sources", source_ids)
        for item in _array(row["executions"], "trial.executions", 2):
            execution = _record(item, "execution", {"source", "pointer", "id"})
            for key, value in execution.items():
                _string(value, f"execution.{key}")
            _unique(execution["id"], executions, "execution identity")
            # JSON encoding preserves tuple boundaries even for adversarial strings.
            occurrence = _canonical_json([execution["source"], execution["pointer"]])
            _unique(occurrence, occurrences, "execution reference")
        row["executions"] = sorted(
            row["executions"], key=lambda item: (item["source"], item["pointer"])
        )


@dataclass(frozen=True)
class PrincipalAccountingBinding:
    body: dict[str, Any]
    sources: tuple[ContinuitySource, ...]
    evidence: ContinuityEvidence
    version: int = 1

    @classmethod
    def from_json(cls, text: str) -> PrincipalAccountingBinding:
        raw = _record(
            _load(text, "principal accounting binding"),
            "principal accounting binding",
            {
                "principal_accounting_binding_version", "id", "manifest_sha256",
                "profile_sha256", "provider", "boundary", "measurement", "limit",
                "intent", "mediation", "principals", "trials", "sources", "evidence",
            },
        )
        if _integer(raw["principal_accounting_binding_version"], "binding version") != 1:
            raise ContinuityFormatError("unsupported principal accounting binding version")
        for key in ("id", "provider", "boundary"):
            _string(raw[key], key)
        for key in ("manifest_sha256", "profile_sha256"):
            _digest(raw[key], key)
        measurement = _record(
            raw["measurement"], "measurement",
            {"profile_tool", "manifest_tool", "value_arg", "dimension", "unit"},
        )
        for key, value in measurement.items():
            _string(value, f"measurement.{key}")
        limit = _record(raw["limit"], "limit", {"amount", "unit", "comparison", "scope"})
        _integer(limit["amount"], "limit.amount")
        _string(limit["unit"], "limit.unit")
        if limit["comparison"] != "inclusive" or limit["scope"] != "per_trial_run":
            raise ContinuityFormatError("accounting requires an inclusive per-trial run limit")
        sources = _sources(raw["sources"], "sources")
        source_ids = frozenset(source.id for source in sources)
        intent = _record(raw["intent"], "intent", {"kind", "statement", "sources"})
        if intent["kind"] != "shared_mandate_per_trial":
            raise ContinuityFormatError("unsupported accounting intent")
        _string(intent["statement"], "intent.statement")
        _strings(intent["sources"], "intent.sources", source_ids)
        mediation = _record(raw["mediation"], "mediation", {"kind", "sources"})
        if mediation["kind"] not in ("complete", "unknown"):
            raise ContinuityFormatError("unsupported accounting mediation")
        _strings(mediation["sources"], "mediation.sources", source_ids)
        _mappings(raw, source_ids)
        evidence = _evidence(raw["evidence"], "evidence")
        raw["sources"] = [source.as_dict() for source in sources]
        raw["principals"] = sorted(raw["principals"], key=lambda item: item["alias"])
        raw["trials"] = sorted(raw["trials"], key=lambda item: item["id"])
        return cls(raw, sources, evidence)

    def to_json(self) -> str:
        return _canonical_json(self.body)


def _join_gaps(
    mandate: Mandate, manifest_bytes: bytes, profile: PrincipalContinuity,
    binding: PrincipalAccountingBinding,
) -> list[str]:
    raw = binding.body
    body = profile.body
    gaps = []
    try:
        parsed = loads(manifest_bytes.decode("utf-8"), source=mandate.source)
    except (UnicodeError, ManifestError):
        parsed = None
    if parsed != mandate or hashlib.sha256(manifest_bytes).hexdigest() != raw["manifest_sha256"]:
        gaps.append("manifest bytes do not match the analyzed mandate and binding")
    if hashlib.sha256(profile.to_json().encode()).hexdigest() != raw["profile_sha256"]:
        gaps.append("canonical profile digest does not match binding")
    if any(body[key] != raw[key] for key in ("provider", "boundary")):
        gaps.append("provider or enforcement boundary does not match binding")
    measurement = raw["measurement"]
    expected = {
        "tool": measurement["profile_tool"],
        "dimension": measurement["dimension"],
        "unit": measurement["unit"],
    }
    if body["measurement"] != expected or measurement["dimension"] != "value":
        gaps.append("measurement does not support the bound monetary accounting")
    tool = mandate.tool(measurement["manifest_tool"])
    if (
        tool is None or not tool.spends_value or tool.value_arg != measurement["value_arg"]
        or tool.ceiling.currency != measurement["unit"]
    ):
        gaps.append("manifest value-spending tool, value argument, or currency does not match")
    total = mandate.limits.total
    if (
        total is None or total.amount != raw["limit"]["amount"]
        or total.currency != raw["limit"]["unit"]
        or raw["limit"]["unit"] != measurement["unit"]
    ):
        gaps.append("binding limit does not match the manifest total and measurement unit")
    if (
        {p["alias"] for p in raw["principals"]} != {p["alias"] for p in body["principals"]}
        or tool is None
        or any(p["manifest_principal"] != tool.principal for p in raw["principals"])
    ):
        gaps.append("principal mappings do not cover the profile and selected tool role")
    trials = {trial["id"]: trial for trial in raw["trials"]}
    if set(trials) != {trial["id"] for trial in body["trials"]}:
        gaps.append("trial mappings do not exactly cover the profile")
    else:
        for trial in body["trials"]:
            calls = {(call["source"], call["pointer"]) for call in trial["calls"]}
            mapped = {(e["source"], e["pointer"]) for e in trials[trial["id"]]["executions"]}
            if calls != mapped:
                gaps.append(f"execution mappings do not exactly cover trial {trial['id']}")
    if raw["mediation"]["kind"] != "complete":
        gaps.append("complete mediation of the listed calls is not attested")
    return gaps


def analyse_principal_accounting(
    mandate: Mandate, profile: PrincipalContinuity, contents: dict[str, bytes],
    binding: PrincipalAccountingBinding, binding_contents: dict[str, bytes], *,
    as_of: datetime, mandate_bytes: bytes, depth: int | None = None,
) -> dict[str, Any]:
    """Add shared totals only under a separately eligible, exactly joined binding."""
    profile = PrincipalContinuity.from_json(profile.to_json())
    binding = PrincipalAccountingBinding.from_json(binding.to_json())
    result = analyse_principal_continuity(
        mandate, profile, contents, as_of=as_of, mandate_bytes=mandate_bytes, depth=depth,
    )
    findings = [
        f for f in result["findings"] if f["code"] != "continuity.shared-mandate-unresolved"
    ]
    binding_findings = []
    try:
        _verify_sources(binding.sources, binding_contents)
    except ContinuityFormatError as exc:
        binding_findings.append({
            "code": "continuity.accounting-source-untrusted", "message": str(exc),
        })
    if not _eligible_evidence(binding.evidence, result["as_of"]):
        binding_findings.append({
            "code": "continuity.accounting-evidence-untrusted",
            "message": "accounting binding is not exact, accepted, and current",
        })
    binding_findings.extend(
        {"code": "continuity.accounting-binding-mismatch", "message": gap}
        for gap in _join_gaps(mandate, mandate_bytes, profile, binding)
    )
    findings.extend(binding_findings)
    eligible = not binding_findings
    mapped_trials = {trial["id"]: trial for trial in binding.body["trials"]}
    unresolved = False
    for trial in result["trials"]:
        accounting = {
            "status": "unresolved", "account": None, "observed_completed": None,
            "limit": None, "budget": "unresolved",
        }
        if eligible and result["observations_eligible"] and trial["completion_known"]:
            amount = sum(trial["observed_completed_by_principal"].values())
            limit = binding.body["limit"]["amount"]
            accounting.update(
                status="reviewed", account=mapped_trials[trial["id"]]["account"],
                observed_completed=amount, limit=limit,
                budget=(
                    "exceeded_by_observed_calls" if amount > limit
                    else "not_exceeded_by_observed_calls"
                ),
            )
            trial["mandate_identity"] = "bound_by_review"
            if amount > limit:
                findings.append({
                    "code": "continuity.observed-budget-exceeded",
                    "message": f"trial {trial['id']}: observed completed {amount} exceeds {limit}",
                })
        else:
            unresolved = True
        trial["accounting"] = accounting
    if unresolved:
        findings.append({
            "code": "continuity.shared-mandate-unresolved",
            "message": (
                "shared accounting needs eligible observations, binding, and known completion"
            ),
        })
    findings.append({
        "code": "continuity.continuation-unresolved",
        "message": (
            "accounting does not establish state continuity, admission, or safe continuation"
        ),
    })
    result.update(
        schema="agentmandate.principal-accounting/v1", binding=binding.body,
        binding_sha256=hashlib.sha256(binding.to_json().encode()).hexdigest(),
        binding_eligible=eligible, findings=findings,
    )
    return result


def render_principal_accounting(result: dict[str, Any]) -> str:
    lines = [render_principal_continuity(result), "REVIEWED ACCOUNTING"]
    for trial in result["trials"]:
        lines.append(f"  {trial['id']}: {trial['accounting']}")
    return "\n".join(lines)
