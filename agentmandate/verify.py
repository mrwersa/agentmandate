"""Check recorded runs against the declared mandate.

A manifest nobody verifies is a wish. This command replays observed tool calls
and reports every one that the mandate does not permit, which is the only thing
that keeps the declaration honest as the implementation drifts away from it.

Input is a JSON Lines file of observed calls. The shape is deliberately close
to the OpenTelemetry GenAI tool-call attributes so an exporter can be pointed at
it without a translation layer, but nothing here requires OpenTelemetry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .manifest import Mandate

VIOLATION_KINDS = (
    "undeclared_tool",
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
    line: int = 0

    @classmethod
    def parse(cls, raw: dict, line: int) -> Observation:
        value = raw.get("value")
        parsed: Decimal | None = None
        if value is not None:
            try:
                parsed = Decimal(str(value))
            except InvalidOperation:
                parsed = None
        return cls(
            tool=str(raw.get("tool", "")),
            scope=raw.get("scope"),
            value=parsed,
            approved=bool(raw.get("approved", False)),
            principal=raw.get("principal"),
            currency=(str(raw["currency"]).upper() if raw.get("currency") else None),
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
            lines.append(f"{len(self.violations)} call(s) exceeded the declaration")
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

        if tool.requires_approval and not observation.approved:
            violations.append(
                Violation(
                    "missing_approval",
                    observation,
                    "the mandate requires approval for this call and the record "
                    "shows none",
                )
            )

        if observation.principal is not None and observation.principal != tool.principal:
            violations.append(
                Violation(
                    "wrong_principal",
                    observation,
                    f"declared principal is {tool.principal!r} but the call ran as "
                    f"{observation.principal!r}",
                )
            )

        if observation.value is not None:
            if (
                tool.ceiling is not None
                and observation.currency is not None
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
            total += observation.value
            if tool.ceiling is not None:
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
