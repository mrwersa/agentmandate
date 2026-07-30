"""Turn reachable breach paths into reviewable scenario-test skeletons.

``reach`` proves that a call sequence is permitted by the reviewed manifest.
It does not prove that an agent will choose that sequence or that a deployed
control will allow it. A scenario test is the dynamic half of that question.

The exporter preserves the counterexample and leaves the application-specific
parts blank. A human must supply the environment setup, agent input, and
expected control boundary. The library never invents those facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .manifest import Mandate
from .reach import Breach, Step, analyse

SCENARIOS_SCHEMA = "agentmandate.scenarios/v1"


def _required_string(value: Any, field: str, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"scenario {field} must be a string")
    if not allow_blank and not value.strip():
        raise ValueError(f"scenario {field} must not be blank")
    if value and not value.strip():
        raise ValueError(f"scenario {field} must not be whitespace")
    return value


@dataclass(frozen=True)
class ScenarioStep:
    """One structured tool call from a static counterexample."""

    tool: str
    binding: str | None = None
    spent: str | None = None
    currency: str | None = None

    @classmethod
    def from_step(cls, step: Step) -> ScenarioStep:
        return cls(
            tool=step.tool,
            binding=step.binding,
            spent=str(step.spent) if step.spent is not None else None,
            currency=step.currency,
        )

    @classmethod
    def from_dict(cls, value: Any) -> ScenarioStep:
        if not isinstance(value, dict):
            raise ValueError("scenario step must be an object")
        tool = _required_string(value.get("tool"), "step tool")
        binding = value.get("binding")
        spent = value.get("spent")
        currency = value.get("currency")
        for field, item in (
            ("step binding", binding),
            ("step spent", spent),
            ("step currency", currency),
        ):
            if item is not None:
                _required_string(item, field)
        if (spent is None) != (currency is None):
            raise ValueError(
                "scenario step spent and currency must be supplied together"
            )
        return cls(tool=tool, binding=binding, spent=spent, currency=currency)

    def to_dict(self) -> dict[str, str]:
        payload = {"tool": self.tool}
        if self.binding is not None:
            payload["binding"] = self.binding
        if self.spent is not None:
            payload["spent"] = self.spent
            payload["currency"] = self.currency or ""
        return payload


@dataclass(frozen=True)
class Scenario:
    """A static witness plus the application facts needed to execute it."""

    kind: str
    detail: str
    path: tuple[ScenarioStep, ...]
    environment: tuple[str, ...] = ()
    agent_input: str = ""
    expected_control: str = ""

    @property
    def identifier(self) -> str:
        route = ">".join(step.tool for step in self.path)
        witness = {
            "kind": self.kind,
            "detail": self.detail,
            "path": [step.to_dict() for step in self.path],
        }
        digest = sha256(
            json.dumps(
                witness,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:12]
        return f"{self.kind}:{route}:{digest}"

    @property
    def reviewed(self) -> bool:
        return (
            bool(self.environment)
            and bool(self.agent_input.strip())
            and bool(self.expected_control.strip())
        )

    @classmethod
    def from_breach(cls, breach: Breach) -> Scenario:
        return cls(
            kind=breach.kind,
            detail=breach.detail,
            path=tuple(ScenarioStep.from_step(step) for step in breach.path),
        )

    @classmethod
    def from_dict(cls, value: Any) -> Scenario:
        if not isinstance(value, dict):
            raise ValueError("scenario must be an object")
        kind = _required_string(value.get("kind"), "kind")
        detail = _required_string(value.get("detail"), "detail")
        raw_path = value.get("path")
        if not isinstance(raw_path, list) or not raw_path:
            raise ValueError("scenario path must be a non-empty list")
        raw_environment = value.get("environment", [])
        if not isinstance(raw_environment, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in raw_environment
        ):
            raise ValueError(
                "scenario environment must be a list of non-blank strings"
            )
        scenario = cls(
            kind=kind,
            detail=detail,
            path=tuple(ScenarioStep.from_dict(step) for step in raw_path),
            environment=tuple(raw_environment),
            agent_input=_required_string(
                value.get("agent_input", ""), "agent_input", allow_blank=True
            ),
            expected_control=_required_string(
                value.get("expected_control", ""),
                "expected_control",
                allow_blank=True,
            ),
        )
        if "id" in value and value["id"] != scenario.identifier:
            raise ValueError(
                f"scenario id {value['id']!r} does not match "
                f"{scenario.identifier!r}"
            )
        return scenario

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.identifier,
            "kind": self.kind,
            "detail": self.detail,
            "path": [step.to_dict() for step in self.path],
            "environment": list(self.environment),
            "agent_input": self.agent_input,
            "expected_control": self.expected_control,
        }


@dataclass(frozen=True)
class ScenarioSet:
    """Scenario skeletons derived from one bounded authority analysis."""

    agent: str
    depth: int
    truncated: bool
    scenarios: tuple[Scenario, ...]

    @property
    def unreviewed(self) -> tuple[str, ...]:
        return tuple(
            scenario.identifier
            for scenario in self.scenarios
            if not scenario.reviewed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCENARIOS_SCHEMA,
            "agent": self.agent,
            "depth": self.depth,
            "truncated": self.truncated,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
        }

    @classmethod
    def from_dict(cls, value: Any) -> ScenarioSet:
        if not isinstance(value, dict):
            raise ValueError("scenarios root must be an object")
        if value.get("schema") != SCENARIOS_SCHEMA:
            raise ValueError(
                f"unsupported scenarios schema: {value.get('schema')!r}"
            )
        agent = _required_string(value.get("agent"), "agent")
        depth = value.get("depth")
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            raise ValueError("scenario depth must be a positive integer")
        truncated = value.get("truncated")
        if not isinstance(truncated, bool):
            raise ValueError("scenario truncated must be true or false")
        raw_scenarios = value.get("scenarios")
        if not isinstance(raw_scenarios, list):
            raise ValueError("scenarios must be a list")
        scenarios = tuple(Scenario.from_dict(item) for item in raw_scenarios)
        identifiers = [scenario.identifier for scenario in scenarios]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("scenarios must not contain duplicate ids")
        return cls(
            agent=agent,
            depth=depth,
            truncated=truncated,
            scenarios=scenarios,
        )

    def render(self) -> str:
        lines = [f"counterexample scenarios for {self.agent}"]
        if not self.scenarios:
            lines.append(f"  none within depth {self.depth}")
            return "\n".join(lines)
        for scenario in self.scenarios:
            lines.append(f"  {scenario.identifier}")
            lines.append(
                "    path: " + " -> ".join(step.tool for step in scenario.path)
            )
            lines.append(
                "    environment: "
                + (
                    "; ".join(scenario.environment)
                    if scenario.environment
                    else "REVIEW: describe the test fixture and starting state"
                )
            )
            lines.append(
                "    agent input: "
                + (
                    scenario.agent_input
                    or "REVIEW: write the input that should exercise this risk"
                )
            )
            lines.append(
                "    expected: "
                + (
                    scenario.expected_control
                    or "REVIEW: state where the deployed control must stop it"
                )
            )
        if self.truncated:
            lines.append("")
            lines.append(
                f"search stopped at depth {self.depth}; deeper paths were not analysed"
            )
        return "\n".join(lines)


def derive_scenarios(mandate: Mandate, depth: int | None = None) -> ScenarioSet:
    """Preserve each reachable breach as a reviewable scenario skeleton."""
    authority = analyse(mandate, depth=depth)
    return ScenarioSet(
        agent=mandate.agent,
        depth=authority.depth,
        truncated=authority.truncated,
        scenarios=tuple(
            Scenario.from_breach(breach) for breach in authority.breaches
        ),
    )


def reconcile_scenarios(
    current: ScenarioSet,
    reviewed: ScenarioSet,
) -> ScenarioSet:
    """Carry human-authored fields onto witnesses that remain reachable."""
    if current.agent != reviewed.agent:
        raise ValueError(
            f"cannot reconcile scenarios for {reviewed.agent!r} with "
            f"{current.agent!r}"
        )
    by_id = {scenario.identifier: scenario for scenario in reviewed.scenarios}
    reconciled = []
    for scenario in current.scenarios:
        earlier = by_id.get(scenario.identifier)
        if earlier is None:
            reconciled.append(scenario)
            continue
        reconciled.append(
            Scenario(
                kind=scenario.kind,
                detail=scenario.detail,
                path=scenario.path,
                environment=earlier.environment,
                agent_input=earlier.agent_input,
                expected_control=earlier.expected_control,
            )
        )
    return ScenarioSet(
        agent=current.agent,
        depth=current.depth,
        truncated=current.truncated,
        scenarios=tuple(reconciled),
    )


def load_scenarios(path: str | Path) -> ScenarioSet:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load scenarios: {exc}") from exc
    return ScenarioSet.from_dict(value)


def save_scenarios(scenarios: ScenarioSet, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(scenarios.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
