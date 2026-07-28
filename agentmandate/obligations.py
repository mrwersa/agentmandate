"""Turn reachable authority into reviewable test obligations.

A mandate says what an agent is permitted to do. A test suite says what was
actually exercised. Nothing connects them today, so a manifest can declare an
irreversible refund the tests never approach and both artefacts look healthy.

This emits an obligation per consequential thing the agent can reach: a
statement that some reviewed test case ought to exercise this decision point.

What it deliberately does not do:

- It does not generate decision labels. An effect class such as
  ``irreversible on case`` is an authority fact. A decision such as
  ``card_security`` is an application label chosen by whoever designed the
  router. No parsing turns one into the other, and inventing the mapping would
  be a confident guess about somebody else's domain.
- It does not emit compound breaches. A cumulative-value path is a multi-call
  sequence, which is scenario testing rather than decision coverage. Those
  stay in ``reach`` and do not cross into a test suite.

So the output is a skeleton with a blank ``decision`` on every row, for a human
to fill in. Extract then annotate, the same discipline ``scan`` already follows.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import IRREVERSIBLE, SERVICE, Mandate
from .reach import analyse

OBLIGATIONS_SCHEMA = "agentmandate.obligations/v1"


@dataclass(frozen=True)
class Obligation:
    """One reachable authority fact a reviewed test ought to exercise."""

    kind: str
    subject: str
    reason: str
    decision: str = ""
    # Probe texts a reviewer wrote to reach this decision. A generated suite
    # needs real inputs, and inventing them would produce a file that runs and
    # measures nothing.
    cases: tuple[str, ...] = ()

    @property
    def identifier(self) -> str:
        """A stable name, so a reviewed mapping survives regeneration."""
        return f"{self.kind}:{self.subject}"

    @property
    def reviewed(self) -> bool:
        """Whether a human has supplied both the decision and a probe.

        A decision without a case is half a review. The suite it generates
        would carry placeholder text that AgentVerity happily runs, producing
        numbers about nothing.
        """
        return bool(self.decision) and bool(self.cases)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "kind": self.kind,
            "subject": self.subject,
            "reason": self.reason,
            "decision": self.decision,
            "cases": list(self.cases),
        }

    @classmethod
    def from_dict(cls, value: Any) -> Obligation:
        if not isinstance(value, dict):
            raise ValueError("obligation must be an object")
        missing = {"kind", "subject"} - set(value)
        if missing:
            raise ValueError(
                "obligation is missing " + ", ".join(sorted(missing))
            )
        kind = value["kind"]
        subject = value["subject"]
        reason = value.get("reason", "")
        decision = value.get("decision", "")
        cases = value.get("cases", [])
        for field, item in (
            ("kind", kind),
            ("subject", subject),
            ("reason", reason),
            ("decision", decision),
        ):
            if not isinstance(item, str):
                raise ValueError(f"obligation {field} must be a string")
        if not kind.strip() or not subject.strip():
            raise ValueError("obligation kind and subject must not be blank")
        if decision and not decision.strip():
            raise ValueError("obligation decision must not be whitespace")
        if not isinstance(cases, list) or any(
            not isinstance(case, str) or not case.strip() for case in cases
        ):
            raise ValueError("obligation cases must be a list of non-blank strings")
        if len(cases) != len(set(cases)):
            raise ValueError("obligation cases must not contain duplicates")
        identifier = f"{kind}:{subject}"
        if "id" in value and value["id"] != identifier:
            raise ValueError(
                f"obligation id {value['id']!r} does not match {identifier!r}"
            )
        return cls(
            kind=kind,
            subject=subject,
            reason=reason,
            decision=decision,
            cases=tuple(cases),
        )


@dataclass(frozen=True)
class ObligationSet:
    """Every obligation derived from one mandate."""

    agent: str
    obligations: tuple[Obligation, ...]

    @property
    def unreviewed(self) -> tuple[str, ...]:
        """Obligations with no decision mapped to them yet."""
        return tuple(o.identifier for o in self.obligations if not o.reviewed)

    @property
    def decisions(self) -> tuple[str, ...]:
        """The distinct decisions a reviewer has mapped."""
        return tuple(sorted({o.decision for o in self.obligations if o.reviewed}))

    def render(self) -> str:
        lines = [f"test obligations for {self.agent}"]
        if not self.obligations:
            lines.append("  none: no consequential authority is reachable")
            return "\n".join(lines)
        for obligation in self.obligations:
            lines.append(f"  {obligation.identifier}")
            lines.append(f"    why:      {obligation.reason}")
            lines.append(
                f"    decision: {obligation.decision or 'REVIEW: map a decision'}"
            )
            lines.append(
                "    cases:    "
                + (
                    ", ".join(obligation.cases)
                    if obligation.cases
                    else "REVIEW: write at least one probe that reaches it"
                )
            )
        if self.unreviewed:
            lines.append("")
            lines.append(
                f"{len(self.unreviewed)} obligation(s) need a reviewed decision "
                "before a suite can be generated"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OBLIGATIONS_SCHEMA,
            "agent": self.agent,
            "obligations": [o.to_dict() for o in self.obligations],
        }

    @classmethod
    def from_dict(cls, value: Any) -> ObligationSet:
        if not isinstance(value, dict):
            raise ValueError("obligations root must be an object")
        if value.get("schema") != OBLIGATIONS_SCHEMA:
            raise ValueError(
                f"unsupported obligations schema: {value.get('schema')!r}"
            )
        raw = value.get("obligations")
        if not isinstance(raw, list):
            raise ValueError("obligations must be a list")
        return cls(
            agent=str(value.get("agent", "")),
            obligations=tuple(Obligation.from_dict(entry) for entry in raw),
        )


def derive(mandate: Mandate, depth: int | None = None) -> ObligationSet:
    """Derive obligations from what the mandate actually lets the agent reach.

    Reachability rather than declaration: a tool nobody can get to needs no
    test, and listing it would pad the review with work that protects nothing.
    """
    authority = analyse(mandate, depth=depth)
    obligations: list[Obligation] = []

    for name in sorted(authority.reachable_tools):
        tool = mandate.tool(name)
        if tool is None:  # pragma: no cover - reachable names come from tools
            continue
        if tool.effect == IRREVERSIBLE:
            obligations.append(
                Obligation(
                    kind="irreversible",
                    subject=name,
                    reason=(
                        "an irreversible effect is reachable, so some reviewed "
                        "case should exercise the decision that leads to it"
                    ),
                )
            )
        if tool.requires_approval:
            obligations.append(
                Obligation(
                    kind="approval-required",
                    subject=name,
                    reason=(
                        "an approval gate is reachable, and a gate no test "
                        "reaches has never been shown to hold"
                    ),
                )
            )
        if tool.principal == SERVICE:
            obligations.append(
                Obligation(
                    kind="service-principal",
                    subject=name,
                    reason=(
                        "this call spends a service account rather than the "
                        "caller's identity, which is the confused-deputy shape"
                    ),
                )
            )
        if tool.spends_value:
            obligations.append(
                Obligation(
                    kind="value-bearing",
                    subject=name,
                    reason=(
                        f"this call spends value up to {tool.ceiling}, so the "
                        "decision that authorises it deserves reviewed cases"
                    ),
                )
            )
    return ObligationSet(agent=mandate.agent, obligations=tuple(obligations))


def reconcile(current: ObligationSet, reviewed: ObligationSet) -> ObligationSet:
    """Carry reviewed decisions onto obligations derived from the live manifest.

    A reviewed file is a record of decisions somebody mapped, not a substitute
    for the manifest. Trusting it on its own lets a stale or unrelated review
    generate a suite for authority the agent no longer has, which is the exact
    drift this package exists to catch.

    Matching is by stable identifier, so:

    - an obligation that still exists keeps its reviewed decision and cases
    - an obligation the manifest no longer reaches is dropped
    - a newly reachable obligation appears unreviewed, and blocks generation
      until somebody looks at it
    """
    mapped = {o.identifier: o for o in reviewed.obligations}
    return ObligationSet(
        agent=current.agent,
        obligations=tuple(
            (
                Obligation(
                    kind=obligation.kind,
                    subject=obligation.subject,
                    reason=obligation.reason,
                    decision=mapped[obligation.identifier].decision,
                    cases=mapped[obligation.identifier].cases,
                )
                if obligation.identifier in mapped
                else obligation
            )
            for obligation in current.obligations
        ),
    )


def to_decision_suite(
    obligations: ObligationSet, *, critical: bool = True
) -> dict[str, Any]:
    """Render reviewed obligations as an AgentVerity decision-suite skeleton.

    Every obligation must carry a reviewed decision first. Generating a suite
    from unreviewed rows would invent application labels from authority facts,
    which is exactly the guess this module refuses to make.

    Raises:
        ValueError: If any obligation still lacks a decision.
    """
    if obligations.unreviewed:
        raise ValueError(
            "these obligations are not fully reviewed yet: "
            + ", ".join(obligations.unreviewed)
            + ". Each needs the decision your agent returns and at least one "
            "probe that reaches it. A suite generated from placeholders would "
            "run and measure nothing."
        )

    decisions = obligations.decisions
    if not decisions:
        raise ValueError("no obligations to generate a suite from")
    seen: set[str] = set()
    for obligation in obligations.obligations:
        duplicates = seen & set(obligation.cases)
        if duplicates:
            raise ValueError(
                "the same probe is reviewed twice: " + ", ".join(sorted(duplicates))
            )
        seen.update(obligation.cases)

    contract: dict[str, Any] = {
        "allowed": list(decisions),
        "required": list(decisions),
    }
    if critical:
        # An irreversible or value-bearing obligation is what "critical" is
        # for. Approval gates and service principals matter, but they are not
        # in themselves a consequence class.
        contract["critical"] = sorted(
            {
                o.decision
                for o in obligations.obligations
                if o.kind in {"irreversible", "value-bearing"}
            }
        )

    return {
        "schema": "agentverity.decision-suite/v1",
        "contract": contract,
        # Inputs come from the reviewer. Authority analysis cannot invent a
        # probe that reaches a decision, and shipping placeholder text would
        # produce a suite AgentVerity runs happily while measuring nothing.
        "cases": [
            {"input": case, "expected": obligation.decision}
            for obligation in obligations.obligations
            for case in obligation.cases
        ],
    }


def load_obligations(path: str | Path) -> ObligationSet:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load obligations: {exc}") from exc
    return ObligationSet.from_dict(value)


def save_obligations(obligations: ObligationSet, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(obligations.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
