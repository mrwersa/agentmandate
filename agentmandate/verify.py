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
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from pathlib import Path

from .manifest import IRREVERSIBLE, WRITE, Mandate, _quantity_units
from .reach import _arithmetic_context

VIOLATION_KINDS = (
    "no_observations",
    "errored_effect",
    "undeclared_tool",
    "missing_principal",
    "missing_scope",
    "missing_value",
    "missing_unit",
    "missing_quantity",
    "quantity_mismatch",
    "unexpected_value",
    "unexpected_quantity",
    "unexpected_unit",
    "ceiling_exceeded",
    "missing_approval",
    "wrong_principal",
    "unit_mismatch",
    "quantity_exceeded",
    "effect_budget_exceeded",
)


@dataclass(frozen=True)
class Observation:
    """One recorded tool call."""

    tool: str
    scope: str | None = None
    value: Decimal | None = None
    approved: bool = False
    principal: str | None = None
    unit: str | None = None
    quantity: str | None = None
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
        if principal is not None and (not isinstance(principal, str) or not principal.strip()):
            raise ValueError(f"line {line}: principal must be a non-empty string")

        if "currency" in raw:
            raise ValueError(f"line {line}: currency is unsupported; use quantity and unit")
        unit = raw.get("unit")
        quantity = raw.get("quantity")
        for name, item in (("unit", unit), ("quantity", quantity)):
            if item is not None and (
                not isinstance(item, str)
                or not item.strip()
                or item != item.strip()
                or any(c in item for c in "\r\n\x00")
            ):
                raise ValueError(f"line {line}: {name} must be a non-empty trimmed string")

        return cls(
            tool=tool,
            scope=scope,
            value=parsed,
            approved=approved,
            errored=errored,
            principal=principal,
            unit=unit,
            quantity=quantity,
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
                f"{len(self.violations)} violation(s) across {self.observed} observed call(s)"
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
    """Check exact named cumulative quantities without inheriting numeric context."""
    _quantity_units(mandate)
    if any(
        o.value is not None
        and (not isinstance(o.value, Decimal) or not o.value.is_finite() or o.value < 0)
        for o in observations
    ):
        raise ValueError("observed quantity amounts must be finite non-negative Decimal values")
    amounts = [t.ceiling.amount for t in mandate.tools if t.ceiling is not None]
    amounts.extend(o.value for o in observations if o.value is not None)
    try:
        with localcontext(_arithmetic_context(amounts, len(observations))):
            return _replay(mandate, observations)
    except DecimalException as exc:
        raise ValueError("replay quantities exceed supported exact decimal arithmetic") from exc


def _replay(mandate: Mandate, observations: list[Observation]) -> Conformance:
    """Report every observed call the mandate does not permit."""
    violations: list[Violation] = []
    spent: dict[tuple[str, str | None], Decimal] = {}
    totals: dict[str, Decimal] = {}
    effect_counts: dict[str, int] = {}

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

        if observation.errored and (tool.effect in {WRITE, IRREVERSIBLE} or tool.spends_value):
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
                    "the mandate requires approval for this call and the record shows none",
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

        if tool.spends_value and observation.unit is None:
            violations.append(
                Violation(
                    "missing_unit",
                    observation,
                    "the record omits the unit, so its value cannot be compared "
                    "with the declared ceiling",
                )
            )

        if not tool.spends_value and observation.value is not None:
            violations.append(
                Violation(
                    "unexpected_value",
                    observation,
                    "the call records spending but the tool declares no value argument or ceiling",
                )
            )

        if not tool.spends_value and observation.quantity is not None:
            violations.append(
                Violation(
                    "unexpected_quantity",
                    observation,
                    "the call names a quantity but the tool declares no measured quantity",
                )
            )
        if not tool.spends_value and observation.unit is not None:
            violations.append(
                Violation(
                    "unexpected_unit",
                    observation,
                    "the call names a unit but the tool declares no measured quantity",
                )
            )

        if tool.spends_value and observation.quantity is None:
            violations.append(
                Violation("missing_quantity", observation, "the record omits the named quantity")
            )
        elif tool.spends_value and observation.quantity != tool.quantity:
            violations.append(
                Violation(
                    "quantity_mismatch",
                    observation,
                    "the recorded quantity differs from the tool declaration",
                )
            )

        effect_counts[tool.effect] = effect_counts.get(tool.effect, 0) + 1
        effect_cap = mandate.limits.effects.get(tool.effect)
        if effect_cap is not None and effect_counts[tool.effect] > effect_cap:
            violations.append(
                Violation(
                    "effect_budget_exceeded",
                    observation,
                    f"{tool.effect} calls exceed budget {effect_cap}",
                )
            )

        complete_spend = (
            tool.spends_value
            and observation.value is not None
            and observation.scope is not None
            and observation.unit is not None
            and observation.quantity == tool.quantity
        )
        if complete_spend:
            if tool.ceiling is not None and observation.unit != tool.ceiling.unit:
                # Summing across units would make this pool's total a
                # meaningless number, so this is reported rather than converted.
                violations.append(
                    Violation(
                        "unit_mismatch",
                        observation,
                        f"the call spent {observation.unit} against a ceiling "
                        f"declared in {tool.ceiling.unit}",
                    )
                )
                continue

            name = tool.quantity
            totals[name] = totals.get(name, Decimal(0)) + observation.value
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

    for name, cap in mandate.limits.quantities.items():
        total = totals.get(name, Decimal(0))
        if total > cap.amount:
            violations.append(
                Violation(
                    "quantity_exceeded",
                    Observation(tool="<run>", line=0),
                    f"quantity {name!r} consumed {total} {cap.unit}, "
                    f"above budget {cap.amount} {cap.unit}",
                )
            )

    return Conformance(observed=len(observations), violations=tuple(violations))


def replay_file(mandate: Mandate, path: str | Path) -> Conformance:
    text = Path(path).read_text(encoding="utf-8")
    return replay(mandate, parse_observations(text))
