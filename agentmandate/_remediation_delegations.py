"""Recheck manifest repair proposals against owned, immutable grant evidence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from ._delegation import (
    DelegationAttachment,
    DelegationChain,
    DelegationFinding,
    _delegation_payload,
    _resolve_delegations,
)
from .manifest import Mandate


@dataclass(frozen=True)
class _DelegationEvaluation:
    effective: Mandate
    findings: tuple[DelegationFinding, ...]
    repairable_findings: tuple[DelegationFinding, ...]
    report: dict

    def record(self, mandate, depth):
        # Unlike conditions, grants do not change Authority; the planner already reports it.
        return self.report


@dataclass(frozen=True)
class _DelegationScope:
    attachments: tuple[DelegationAttachment, ...]
    chains: tuple[DelegationChain, ...]
    captures: tuple[tuple[str, bytes], ...]
    as_of: str
    target_source: str
    target_binding: str

    kind = "delegations"
    description = "manifest-v2 with fixed reviewed delegation surfaces; human selection required"
    invariant_error = "delegation eligibility changed during repair recheck"

    @classmethod
    def from_inputs(cls, attachments, chains, captures, as_of, target_source, target_binding):
        if not attachments or not chains:
            raise ValueError("delegation-aware remediation requires attachments and chains")
        return cls(
            tuple(DelegationAttachment.from_json(item.to_json()) for item in attachments),
            tuple(DelegationChain.from_json(item.to_json()) for item in chains),
            tuple(sorted(captures.items())), as_of, target_source, target_binding,
        )

    def resolve(self, mandate: Mandate, *, candidate=False):
        # Inputs are owned snapshots; the shared reader revalidates them once per consumption.
        inactive = tuple(
            item for item in self.attachments
            if candidate and item.target.tool not in mandate.tool_names
        )
        active = tuple(item for item in self.attachments if item not in inactive)
        findings, decisions, excesses, evaluated_at = _resolve_delegations(
            mandate, active, self.chains, dict(self.captures), as_of=self.as_of,
            target_source=self.target_source, target_binding=self.target_binding,
        )
        payload = _delegation_payload(evaluated_at, decisions, findings)
        report = {
            **payload,
            "scope": "fixed reviewed grant surfaces; no authentication or live enforcement claim",
            "repairable_tool_findings": [
                row for item, row in zip(findings, payload["findings"], strict=True)
                if item in excesses
            ],
            "inputs": {
                "artifact_identity": "SHA-256 of canonical artifact JSON, not original file bytes",
                "attachments": [hashlib.sha256(item.to_json().encode()).hexdigest()
                                for item in self.attachments],
                "chains": [hashlib.sha256(item.to_json().encode()).hexdigest()
                           for item in self.chains],
                "captures": {name: hashlib.sha256(content).hexdigest()
                             for name, content in self.captures},
                "target_source": self.target_source, "target_binding": self.target_binding,
            },
            "inactive_attachments": sorted(item.id for item in inactive),
        }
        return _DelegationEvaluation(
            mandate, tuple(item for item in findings if item not in excesses), excesses, report,
        )
