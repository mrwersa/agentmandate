"""Evidence-gated scalar state handover and complete integer admission inclusion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._continuity import (
    ContinuityBinding,
    ContinuityEvidence,
    ContinuityFormatError,
    ContinuitySource,
    _boolean,
    _canonical_json,
    _digest,
    _eligible_evidence,
    _evaluation_time,
    _evidence,
    _integer,
    _load,
    _manifest_binding_matches,
    _record,
    _sources,
    _string,
    _strings,
    _utc,
    _verify_sources,
)
from .manifest import Mandate
from .reach import analyse


def _pending(raw: Any, path: str) -> None:
    if raw is None:
        return
    if not isinstance(raw, list):
        raise ContinuityFormatError(f"{path} must be an array or null")
    identities: set[str] = set()
    for item in raw:
        row = _record(item, path, {"id", "amount"})
        identity = _string(row["id"], f"{path}.id")
        if identity in identities:
            raise ContinuityFormatError("duplicate pending operation identity")
        identities.add(identity)
        _integer(row["amount"], f"{path}.amount")
    raw.sort(key=lambda item: item["id"])


@dataclass(frozen=True)
class ScalarHandover:
    body: dict[str, Any]
    sources: tuple[ContinuitySource, ...]
    evidence: ContinuityEvidence
    version: int = 1

    @classmethod
    def from_json(cls, text: str) -> ScalarHandover:
        raw = _record(
            _load(text, "scalar handover"),
            "scalar handover",
            {
                "scalar_handover_version",
                "id",
                "manifest_sha256",
                "cutover_at",
                "bindings",
                "policies",
                "state",
                "fence",
                "attestation",
                "sources",
                "evidence",
            },
        )
        if _integer(raw["scalar_handover_version"], "scalar_handover_version") != 1:
            raise ContinuityFormatError("unsupported scalar handover version")
        _string(raw["id"], "id")
        _digest(raw["manifest_sha256"], "manifest_sha256")
        _utc(raw["cutover_at"], "cutover_at")
        sources = _sources(raw["sources"], "sources")
        identities = frozenset(source.id for source in sources)
        bindings = _record(raw["bindings"], "bindings", {"before", "after"})
        for key, value in bindings.items():
            bindings[key] = ContinuityBinding.from_json(_canonical_json(value)).as_dict()
        policies = _record(raw["policies"], "policies", {"before", "after"})
        for value in policies.values():
            if _string(value, "policy source") not in identities:
                raise ContinuityFormatError("policy refers to an undeclared source")
        state = _record(
            raw["state"],
            "state",
            {
                "completed_before",
                "completed_after",
                "pending_before",
                "pending_after",
            },
        )
        for key in ("completed_before", "completed_after"):
            if state[key] is not None:
                _integer(state[key], key)
        for key in ("pending_before", "pending_after"):
            _pending(state[key], key)
        fence = _record(raw["fence"], "fence", {"predecessor_fenced", "successor_exclusive"})
        for key, value in fence.items():
            if value is not None:
                _boolean(value, key)
        attestation = _record(raw["attestation"], "attestation", {"statement", "sources"})
        _string(attestation["statement"], "attestation.statement")
        _strings(attestation["sources"], "attestation.sources", identities)
        evidence = _evidence(raw["evidence"], "evidence")
        raw["sources"] = [source.as_dict() for source in sources]
        return cls(raw, sources, evidence)

    def to_json(self) -> str:
        return _canonical_json(self.body)


def _policy(data: bytes) -> dict[str, Any]:
    raw = _record(
        _load(data.decode("utf-8"), "scalar policy"),
        "scalar policy",
        {
            "scalar_policy_version",
            "tool",
            "value_arg",
            "unit",
            "limit",
            "accounting",
            "comparison",
        },
    )
    if (
        _integer(raw["scalar_policy_version"], "scalar_policy_version") != 1
        or raw["accounting"] != "completed_plus_reserved"
        or raw["comparison"] != "inclusive"
    ):
        raise ContinuityFormatError("unsupported scalar policy model")
    for key in ("tool", "value_arg", "unit"):
        _string(raw[key], key)
    _integer(raw["limit"], "limit")
    return raw


def _admission_witness(before: int, after: int) -> int | None:
    """Least nonnegative amount in the successor domain but not the predecessor."""
    if after < 0 or after <= before:
        return None
    return max(0, before + 1)


def analyse_scalar_handover(
    mandate: Mandate,
    handover: ScalarHandover,
    contents: dict[str, bytes],
    *,
    as_of: datetime,
    mandate_bytes: bytes,
    depth: int | None = None,
) -> dict[str, Any]:
    handover = ScalarHandover.from_json(handover.to_json())
    raw = handover.body
    evaluated_at = _evaluation_time(as_of)
    authority = analyse(mandate, depth=depth).as_dict()
    findings = []

    def gap(code: str, message: str) -> None:
        findings.append({"code": f"handover.{code}", "message": message})

    try:
        _verify_sources(handover.sources, contents)
    except ContinuityFormatError as exc:
        gap("source-untrusted", str(exc))
    if not _eligible_evidence(handover.evidence, evaluated_at):
        gap("evidence-untrusted", "handover review is not exact, accepted, and current")
    if raw["manifest_sha256"] != hashlib.sha256(mandate_bytes).hexdigest():
        gap("manifest-mismatch", "supplied manifest bytes do not match the handover")
    if raw["cutover_at"] > evaluated_at:
        gap("timing-unresolved", "cutover follows the evaluation time")
    sources = {source.id: source for source in handover.sources}
    bindings = {
        side: ContinuityBinding.from_json(_canonical_json(value))
        for side, value in raw["bindings"].items()
    }
    policies = {}
    for side, binding in bindings.items():
        declared = {source.locator: source for source in handover.sources}
        if any(declared.get(source.locator) != source for source in binding.sources):
            gap("binding-source-mismatch", f"{side} binding sources differ from root declarations")
        try:
            binding.verify_sources(
                {
                    source.locator: contents[source.locator]
                    for source in binding.sources
                    if source.locator in contents
                }
            )
        except ContinuityFormatError as exc:
            gap("binding-source-untrusted", f"{side}: {exc}")
        if (
            not _eligible_evidence(binding.evidence, evaluated_at)
            or not binding.issued_at <= raw["cutover_at"] < binding.expires_at
            or (side == "after" and not binding.issued_at <= evaluated_at < binding.expires_at)
            or not _manifest_binding_matches(mandate, mandate_bytes, binding)
            or binding.mediation != "platform_verified"
        ):
            gap("binding-untrusted", f"{side} binding lacks an eligible, current mandate join")
        source = sources[raw["policies"][side]]
        if source.content_sha256 != binding.policy_sha256:
            gap("policy-binding-mismatch", f"{side} policy digest does not match its binding")
        try:
            policies[side] = _policy(contents.get(source.locator, b""))
        except (ContinuityFormatError, UnicodeError) as exc:
            gap("policy-untrusted", f"{side}: {exc}")
    before_binding, after_binding = bindings["before"], bindings["after"]
    if (
        before_binding.id == after_binding.id
        or before_binding.binding == after_binding.binding
        or before_binding.provider != after_binding.provider
        or before_binding.principal != after_binding.principal
    ):
        gap(
            "binding-sides-unjoined",
            "bindings must distinguish two sides of one provider/principal",
        )
    if len(policies) == 2:
        before_policy, after_policy = policies["before"], policies["after"]
        contract_before = {k: v for k, v in before_policy.items() if k != "limit"}
        contract_after = {k: v for k, v in after_policy.items() if k != "limit"}
        tool = mandate.tool(before_policy["tool"])
        total = mandate.limits.total
        if (
            contract_before != contract_after
            or tool is None
            or not tool.spends_value
            or sum(tool.spends_value for tool in mandate.tools) != 1
            or tool.value_arg != before_policy["value_arg"]
            or tool.ceiling.currency != before_policy["unit"]
            or tool.principal != before_binding.principal
            or total is None
            or total.currency != before_policy["unit"]
            or total.amount != before_policy["limit"]
        ):
            gap("model-unjoined", "policies do not match one manifest monetary tool and total")
    state = raw["state"]
    if any(value is None for value in state.values()):
        gap(
            "state-unresolved", "completed spend and pending operations must be known on both sides"
        )
    if any(value is not True for value in raw["fence"].values()):
        gap("fence-unresolved", "a fenced predecessor and exclusive successor are not established")
    eligible = not findings
    proof = {
        "verdict": "unresolved",
        "admission_inclusion": "unresolved",
        "remaining_before": None,
        "remaining_after": None,
        "successor_only_amount": None,
        "scope": "All nonnegative integer next requests in the declared scalar model at cutover.",
    }
    if eligible:
        before = (
            policies["before"]["limit"]
            - state["completed_before"]
            - sum(item["amount"] for item in state["pending_before"])
        )
        after = (
            policies["after"]["limit"]
            - state["completed_after"]
            - sum(item["amount"] for item in state["pending_after"])
        )
        witness = _admission_witness(before, after)
        proof.update(
            remaining_before=before,
            remaining_after=after,
            successor_only_amount=witness,
            admission_inclusion=(
                "established_for_scalar_model" if witness is None else "violated_for_scalar_model"
            ),
        )
        if policies["after"]["limit"] > policies["before"]["limit"]:
            gap("limit-widens", "successor policy increases the mandate limit")
        if state["completed_after"] < state["completed_before"]:
            gap("completed-state-lost", "successor completed spend is below predecessor spend")
        if state["pending_before"] != state["pending_after"]:
            gap(
                "pending-state-changed", "pending operation identities or amounts were not retained"
            )
        if witness is not None:
            gap("admission-widens", f"successor alone admits amount {witness} at cutover")
        proof["verdict"] = (
            "violated_for_declared_scalar_handover"
            if findings
            else "satisfied_for_declared_scalar_handover"
        )
    if authority["breaches"] or authority["truncated"]:
        gap("manifest-authority", "manifest Authority has a breach or truncated search")
    return {
        "schema": "agentmandate.scalar-handover/v1",
        "as_of": evaluated_at,
        "handover": raw,
        "handover_sha256": hashlib.sha256(handover.to_json().encode()).hexdigest(),
        "evidence_eligible": eligible,
        "proof": proof,
        "findings": findings,
        "authority": authority,
    }


def render_scalar_handover(result: dict[str, Any]) -> str:
    lines = [
        f"scalar handover  evaluated as of {result['as_of']}",
        _canonical_json(result["proof"]).rstrip(),
    ]
    lines.extend(f"FINDING  {f['code']}: {f['message']}" for f in result["findings"])
    lines.extend(["AUTHORITY", _canonical_json(result["authority"]).rstrip()])
    return "\n".join(lines)
