"""Immutable condition inputs for rechecking report-only repair proposals."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date

from ._conditions import (
    ConditionContext,
    ConditionFinding,
    ToolCondition,
    _condition_payload,
    _resolve_conditions,
)
from .lint import check
from .manifest import Mandate
from .reach import analyse


@dataclass(frozen=True)
class _ConditionEvaluation:
    effective: Mandate
    findings: tuple[ConditionFinding, ...]
    report: dict

    @property
    def repairable_findings(self):
        return ()  # Condition trust failures cannot be repaired by changing a manifest.

    def record(self, mandate, depth):
        return {
            **self.report,
            "unconditional_authority": analyse(mandate, depth=depth).as_dict(),
            "unconditional_lint": [asdict(finding) for finding in check(mandate)],
        }


@dataclass(frozen=True)
class _ConditionScope:
    conditions: tuple[ToolCondition, ...]
    contexts: tuple[ConditionContext, ...]
    captures: tuple[tuple[str, bytes], ...]
    as_of: date

    kind = "conditions"
    description = (
        "manifest-v2 with reviewed conditional effects; candidates require human selection"
    )
    invariant_error = "condition eligibility changed during repair recheck"

    @classmethod
    def from_inputs(cls, conditions, contexts, captures, as_of):
        if not conditions or not contexts:
            raise ValueError("condition-aware remediation requires conditions and contexts")
        return cls(
            tuple(ToolCondition.from_json(item.to_json()) for item in conditions),
            tuple(ConditionContext.from_json(item.to_json()) for item in contexts),
            tuple(sorted(captures.items())),
            as_of,
        )

    def resolve(self, mandate: Mandate, *, candidate=False):
        # Snapshot owned, immutable records once; the shared resolver still
        # revalidates them at every consumption boundary. Removed tools make
        # only their already-validated attachments inactive.
        inactive = tuple(
            item for item in self.conditions
            if candidate and item.target.tool not in mandate.tool_names
        )
        active = tuple(item for item in self.conditions if item not in inactive)
        effective, findings, applied, as_of = _resolve_conditions(
            mandate, active, self.contexts, dict(self.captures), as_of=self.as_of,
        )
        report = {
            **_condition_payload(as_of, applied, findings),
            "scope": "reviewed conditional effects only; source enforcement is not verified",
            "inputs": {
                "artifact_identity": "SHA-256 of canonical artifact JSON, not original file bytes",
                "conditions": [hashlib.sha256(item.to_json().encode()).hexdigest()
                               for item in self.conditions],
                "contexts": [hashlib.sha256(item.to_json().encode()).hexdigest()
                             for item in self.contexts],
                "captures": {name: hashlib.sha256(content).hexdigest()
                             for name, content in self.captures},
            },
            "inactive_conditions": sorted(item.id for item in inactive),
        }
        return _ConditionEvaluation(effective, findings, report)
