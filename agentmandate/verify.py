"""Check recorded runs against the declared mandate.

A manifest nobody verifies is a wish. This command replays observed tool calls
and reports every one that the mandate does not permit, which is the only thing
that keeps the declaration honest as the implementation drifts away from it.

Input is a JSON Lines file of observed calls. The shape is deliberately close
to OpenTelemetry GenAI tool-call attributes, with principal and control fields
added by the exporter. Nothing here requires OpenTelemetry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .manifest import IRREVERSIBLE, WRITE, Mandate

VIOLATION_KINDS = (
    "no_observations",
    "errored_effect",
    "undeclared_tool",
    "missing_principal",
    "missing_scope",
    "missing_value",
    "missing_currency",
    "unexpected_value",
    "ceiling_exceeded",
    "missing_approval",
    "wrong_principal",
    "currency_mismatch",
    "total_exceeded",
)


@dataclass(frozen=True)
class Observation:
    """One recorded tool call."""

    tool: str
    scope: str | None = None
    value: Decimal | None = None
    approved: bool = False
    principal: str | None = None
    currency: str | None = None
    # The call ended in an error. For a read that is uninteresting. For a call
    # that changes something it is ambiguous: an error means the operation
    # ended badly, not that the effect failed to commit, and a timeout is
    # exactly the case where the write may already have landed.
    errored: bool = False
    line: int = 0

    @classmethod
    def parse(cls, raw: dict, line: int) -> Observation:
        tool = raw.get("tool")
        if not isinstance(tool, str) or not tool.strip():
            raise ValueError(f"line {line}: tool must be a non-empty string")

        scope = raw.get("scope")
        if scope is not None and (not isinstance(scope, str) or not scope.strip()):
            raise ValueError(f"line {line}: scope must be a non-empty string")

        value = raw.get("value")
        parsed: Decimal | None = None
        if value is not None:
            try:
                parsed = Decimal(str(value))
            except InvalidOperation as exc:
                raise ValueError(f"line {line}: value is not a number") from exc
            if not parsed.is_finite():
                raise ValueError(f"line {line}: value must be finite")
            if parsed < 0:
                raise ValueError(f"line {line}: value must not be negative")

        approved = raw.get("approved", False)
        if not isinstance(approved, bool):
            raise ValueError(f"line {line}: approved must be true or false")

        errored = raw.get("errored", False)
        if not isinstance(errored, bool):
            raise ValueError(f"line {line}: errored must be true or false")

        principal = raw.get("principal")
        if principal is not None and (
            not isinstance(principal, str) or not principal.strip()
        ):
            raise ValueError(f"line {line}: principal must be a non-empty string")

        currency = raw.get("currency")
        if currency is not None:
            if (
                not isinstance(currency, str)
                or len(currency) != 3
                or not currency.isascii()
                or not currency.isalpha()
            ):
                raise ValueError(f"line {line}: currency must be a three-letter code")
            currency = currency.upper()

        return cls(
            tool=tool,
            scope=scope,
            value=parsed,
            approved=approved,
            errored=errored,
            principal=principal,
            currency=currency,
            line=line,
        )


@dataclass(frozen=True)
class Violation:
    kind: str
    observation: Observation
    message: str

    def render(self) -> str:
        where = f"line {self.observation.line}"
        head = f"VIOLATION  {self.kind:18} {self.observation.tool:22} {where}"
        return f"{head}\n           {self.message}"


@dataclass(frozen=True)
class Conformance:
    observed: int
    violations: tuple[Violation, ...]

    @property
    def conformant(self) -> bool:
        return not self.violations

    def render(self) -> str:
        lines = [f"replayed {self.observed} observed call(s)"]
        if self.conformant:
            lines.append("every call was within the declared mandate")
        else:
            lines.extend(v.render() for v in self.violations)
            lines.append("")
            lines.append(
                f"{len(self.violations)} violation(s) across "
                f"{self.observed} observed call(s)"
            )
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "observed": self.observed,
            "conformant": self.conformant,
            "violations": [
                {
                    "kind": v.kind,
                    "tool": v.observation.tool,
                    "line": v.observation.line,
                    "message": v.message,
                }
                for v in self.violations
            ],
        }


def parse_observations(text: str) -> list[Observation]:
    """Read JSON Lines, skipping blank lines and ignoring comment lines."""
    observations: list[Observation] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {number}: not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"line {number}: expected a JSON object")
        observations.append(Observation.parse(payload, number))
    return observations


def replay(mandate: Mandate, observations: list[Observation]) -> Conformance:
    """Report every observed call the mandate does not permit."""
    violations: list[Violation] = []
    spent: dict[tuple[str, str | None], Decimal] = {}
    total = Decimal(0)

    if not observations:
        violations.append(
            Violation(
                "no_observations",
                Observation(tool="<trace>", line=0),
                "the trace contains no calls, so it cannot establish conformance",
            )
        )

    for observation in observations:
        tool = mandate.tool(observation.tool)
        if tool is None:
            violations.append(
                Violation(
                    "undeclared_tool",
                    observation,
                    "the run called a tool the mandate does not declare, so the "
                    "declaration no longer describes the agent",
                )
            )
            continue

        if observation.principal is None:
            violations.append(
                Violation(
                    "missing_principal",
                    observation,
                    "the record does not identify which principal executed the call",
                )
            )
        elif observation.principal != tool.principal:
            violations.append(
                Violation(
                    "wrong_principal",
                    observation,
                    f"declared principal is {tool.principal!r} but the call ran as "
                    f"{observation.principal!r}",
                )
            )

        if observation.errored and (
            tool.effect in {WRITE, IRREVERSIBLE} or tool.spends_value
        ):
            violations.append(
                Violation(
                    "errored_effect",
                    observation,
                    "the call ended in an error, and an error does not "
                    "establish that the effect was not applied. This evidence "
                    "cannot show the control held. Record whether the effect "
                    "committed, or replay an authoritative effect log.",
                )
            )
            # Its value is not accumulated, because whether it was spent is
            # exactly what the evidence fails to establish.
            continue

        if tool.requires_approval and not observation.approved:
            violations.append(
                Violation(
                    "missing_approval",
                    observation,
                    "the mandate requires approval for this call and the record "
                    "shows none",
                )
            )

        if tool.spends_value and observation.scope is None:
            violations.append(
                Violation(
                    "missing_scope",
                    observation,
                    f"the record omits the {tool.scope_key!r} scope used by the ceiling",
                )
            )

        if tool.spends_value and observation.value is None:
            violations.append(
                Violation(
                    "missing_value",
                    observation,
                    f"the record omits the declared value argument {tool.value_arg!r}",
                )
            )

        if tool.spends_value and observation.currency is None:
            violations.append(
                Violation(
                    "missing_currency",
                    observation,
                    "the record omits the currency, so its value cannot be compared "
                    "with the declared ceiling",
                )
            )

        if not tool.spends_value and observation.value is not None:
            violations.append(
                Violation(
                    "unexpected_value",
                    observation,
                    "the call records spending but the tool declares no value argument "
                    "or ceiling",
                )
            )

        complete_spend = (
            tool.spends_value
            and observation.value is not None
            and observation.scope is not None
            and observation.currency is not None
        )
        if complete_spend:
            if (
                tool.ceiling is not None
                and observation.currency != tool.ceiling.currency
            ):
                # Summing across currencies would make the run total a
                # meaningless number, so this is reported rather than converted.
                violations.append(
                    Violation(
                        "currency_mismatch",
                        observation,
                        f"the call spent {observation.currency} against a ceiling "
                        f"declared in {tool.ceiling.currency}",
                    )
                )
                continue

            if (
                mandate.limits.total is not None
                and observation.currency != mandate.limits.total.currency
            ):
                violations.append(
                    Violation(
                        "currency_mismatch",
                        observation,
                        f"the call spent {observation.currency} against a run limit "
                        f"declared in {mandate.limits.total.currency}",
                    )
                )
                continue

            total += observation.value
            if tool.ceiling is not None and observation.scope is not None:
                key = (tool.name, observation.scope)
                spent[key] = spent.get(key, Decimal(0)) + observation.value
                if spent[key] > tool.ceiling.amount:
                    violations.append(
                        Violation(
                            "ceiling_exceeded",
                            observation,
                            f"cumulative {spent[key]} against scope "
                            f"{observation.scope!r} exceeds the declared ceiling "
                            f"{tool.ceiling.amount}",
                        )
                    )

    if mandate.limits.total is not None and total > mandate.limits.total.amount:
        violations.append(
            Violation(
                "total_exceeded",
                Observation(tool="<run>", line=0),
                f"the run spent {total} against a declared total limit of "
                f"{mandate.limits.total.amount}",
            )
        )

    return Conformance(observed=len(observations), violations=tuple(violations))


def replay_file(mandate: Mandate, path: str | Path) -> Conformance:
    text = Path(path).read_text(encoding="utf-8")
    return replay(mandate, parse_observations(text))
