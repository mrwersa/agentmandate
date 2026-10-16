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

    def record(self, mandate, depth):
        return {
            **self.report,
            "unconditional_authority": analyse(mandate, depth=depth).as_dict(),
            "unconditional_lint": [asdict(finding) for finding in check(mandate)],
        }


@dataclass(frozen=True)
class _ConditionScope:
    conditions: tuple[str, ...]
    contexts: tuple[str, ...]
    captures: tuple[tuple[str, bytes], ...]
    as_of: date

    @classmethod
    def from_inputs(cls, conditions, contexts, captures, as_of):
        if not conditions or not contexts:
            raise ValueError("condition-aware remediation requires conditions and contexts")
        return cls(
            tuple(item.to_json() for item in conditions),
            tuple(item.to_json() for item in contexts),
            tuple(sorted(captures.items())),
            as_of,
        )

    def resolve(self, mandate: Mandate, *, candidate=False):
        # Re-read the same canonical records on every recheck. Removed tools make
        # their already-validated attachments inactive, never newly accepted.
        conditions = tuple(ToolCondition.from_json(text) for text in self.conditions)
        contexts = tuple(ConditionContext.from_json(text) for text in self.contexts)
        inactive = tuple(
            item for item in conditions if candidate and item.target.tool not in mandate.tool_names
        )
        active = tuple(item for item in conditions if item not in inactive)
        effective, findings, applied, as_of = _resolve_conditions(
            mandate, active, contexts, dict(self.captures), as_of=self.as_of,
        )
        report = {
            **_condition_payload(as_of, applied, findings),
            "scope": "reviewed conditional effects only; source enforcement is not verified",
            "inputs": {
                "artifact_identity": "SHA-256 of canonical artifact JSON, not original file bytes",
                "conditions": [hashlib.sha256(text.encode()).hexdigest()
                               for text in self.conditions],
                "contexts": [hashlib.sha256(text.encode()).hexdigest() for text in self.contexts],
                "captures": {name: hashlib.sha256(content).hexdigest()
                             for name, content in self.captures},
            },
            "inactive_conditions": sorted(item.id for item in inactive),
        }
        return _ConditionEvaluation(effective, findings, report)
