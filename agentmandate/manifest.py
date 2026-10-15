"""The mandate manifest: a declarative statement of what an agent may do.

A manifest is the input to every command in this package. It names the tools an
agent can call, what each one requires and produces, which effect class it sits
in, and the ceilings that bound it. Everything else in AgentMandate is analysis
over this structure.

The format is deliberately small. Reachability analysis needs three facts per
tool that an ordinary tool schema does not carry: the effect class, which
argument spends value, and which scope the ceiling is measured against. Asking
for a full behavioural contract would be more expressive and would not get
written, so the manifest asks for the minimum that makes compound analysis
possible.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

READ = "read"
WRITE = "write"
IRREVERSIBLE = "irreversible"
EFFECTS = (READ, WRITE, IRREVERSIBLE)

# Ordered weakest to strongest so comparisons can ask whether one effect class
# grants strictly more than another.
EFFECT_RANK = {READ: 0, WRITE: 1, IRREVERSIBLE: 2}

CALLER = "caller"
SERVICE = "service"
PRINCIPALS = (CALLER, SERVICE)

DEFAULT_DEPTH = 8


class ManifestError(ValueError):
    """Raised when a manifest cannot be read as a well-formed mandate."""


def _required_name(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"{where} must be a non-empty string")
    if any(character in raw for character in "\r\n\x00"):
        raise ManifestError(f"{where} must not contain control characters")
    return raw


def _quantity_name(value: Any, where: str) -> str:
    name = _required_name(value, where)
    if name != name.strip():
        raise ManifestError(f"{where}: quantity name must be trimmed")
    return name


@dataclass(frozen=True)
class Quantity:
    """An exact non-negative cumulative amount with a declared unit.

    Decimal rather than float because these values are compared against
    ceilings and summed across a call sequence. Binary floating point would
    make a breach report arguable, and an arguable breach report is useless.
    """

    amount: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount < 0:
            raise ManifestError("quantity amount must be a finite non-negative Decimal")
        if self.amount.is_zero() and self.amount.is_signed():
            object.__setattr__(self, "amount", self.amount.copy_abs())
        _required_name(self.unit, "quantity unit")
        if self.unit != self.unit.strip():
            raise ManifestError("quantity unit must not have surrounding whitespace")

    @classmethod
    def parse(cls, raw: Any, where: str) -> Quantity:
        if not isinstance(raw, dict):
            raise ManifestError(f"{where}: expected a mapping with amount and unit")
        if set(raw) - {"amount", "unit"}:
            raise ManifestError(f"{where}: expected only amount and unit")
        missing = {"amount", "unit"} - set(raw)
        if missing:
            raise ManifestError(f"{where}: missing {', '.join(sorted(missing))}")
        try:
            amount = Decimal(str(raw["amount"]))
        except InvalidOperation as exc:
            raise ManifestError(f"{where}: amount is not a number") from exc
        if not amount.is_finite():
            raise ManifestError(f"{where}: amount must be finite")
        if amount < 0:
            raise ManifestError(f"{where}: amount must not be negative")
        raw_unit = raw["unit"]
        if not isinstance(raw_unit, str):
            raise ManifestError(f"{where}: unit must be a non-empty string")
        unit = _required_name(raw_unit, f"{where}: unit")
        if isinstance(raw["amount"], str) and not re.fullmatch(
            r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", raw["amount"]
        ):
            raise ManifestError(f"{where}: amount must use an unsigned decimal literal")
        return cls(amount=amount, unit=unit)

    def __str__(self) -> str:
        return f"{self.amount} {self.unit}"


@dataclass(frozen=True)
class Tool:
    """One callable capability and the authority it carries."""

    name: str
    effect: str
    principal: str = CALLER
    requires: tuple[str, ...] = ()
    produces: str | None = None
    # A tool that can be called repeatedly to mint fresh bindings of the scope
    # it produces. This single flag is what makes compound breach possible: a
    # per-scope ceiling is only a real bound when the scope itself is bounded.
    unbounded: bool = False
    value_arg: str | None = None
    ceiling: Quantity | None = None
    quantity: str | None = None
    scope_key: str | None = None
    requires_approval: bool = False

    @property
    def spends_value(self) -> bool:
        return self.value_arg is not None and self.ceiling is not None

    @classmethod
    def parse(cls, raw: Any, index: int) -> Tool:
        where = f"tools[{index}]"
        if not isinstance(raw, dict):
            raise ManifestError(f"{where}: expected a mapping")
        name = _required_name(raw.get("name"), f"{where}: name")
        where = f"tool {name!r}"

        effect = raw.get("effect")
        if effect not in EFFECTS:
            raise ManifestError(f"{where}: effect must be one of {', '.join(EFFECTS)}")

        principal = raw.get("principal", CALLER)
        if principal not in PRINCIPALS:
            raise ManifestError(f"{where}: principal must be one of {', '.join(PRINCIPALS)}")

        requires = raw.get("requires", [])
        if isinstance(requires, str):
            requires = [requires]
        if not isinstance(requires, list) or not all(
            isinstance(scope, str) and scope.strip() for scope in requires
        ):
            raise ManifestError(f"{where}: requires must be a list of scope names")

        produces = raw.get("produces")
        if produces is not None and (not isinstance(produces, str) or not produces.strip()):
            raise ManifestError(f"{where}: produces must be a scope name")

        ceiling = None
        if "ceiling" in raw:
            ceiling = Quantity.parse(raw["ceiling"], f"{where}.ceiling")

        value_arg = raw.get("value_arg")
        if value_arg is not None and (not isinstance(value_arg, str) or not value_arg.strip()):
            raise ManifestError(f"{where}: value_arg must be an argument name")
        if (value_arg is None) != (ceiling is None):
            raise ManifestError(
                f"{where}: value_arg and ceiling must be declared together, "
                "otherwise the ceiling bounds nothing"
            )

        quantity = raw.get("quantity")
        if ceiling is not None:
            quantity = _quantity_name(quantity, f"{where}: quantity")
        elif quantity is not None:
            raise ManifestError(f"{where}: quantity requires value_arg and ceiling")

        scope_key = raw.get("scope_key")
        if scope_key is not None and (not isinstance(scope_key, str) or not scope_key.strip()):
            raise ManifestError(f"{where}: scope_key must be a scope name")
        if value_arg is not None and scope_key is None:
            raise ManifestError(
                f"{where}: scope_key is required when a ceiling is declared, "
                "so the analysis knows what the ceiling is measured against"
            )

        unbounded = raw.get("unbounded", False)
        if not isinstance(unbounded, bool):
            raise ManifestError(f"{where}: unbounded must be true or false")
        requires_approval = raw.get("requires_approval", False)
        if not isinstance(requires_approval, bool):
            raise ManifestError(f"{where}: requires_approval must be true or false")

        return cls(
            name=name,
            effect=effect,
            principal=principal,
            requires=tuple(requires),
            produces=produces,
            unbounded=unbounded,
            value_arg=value_arg,
            ceiling=ceiling,
            quantity=quantity,
            scope_key=scope_key,
            requires_approval=requires_approval,
        )


@dataclass(frozen=True)
class Limits:
    """Bounds that apply to a whole run rather than to a single call."""

    quantities: Mapping[str, Quantity] = field(default_factory=dict)
    depth: int = DEFAULT_DEPTH
    # Reviewed maximum calls per effect class in one run. Declared only: an
    # absent class is unbounded, because inventing a ceiling is the same
    # mistake as inventing a reversibility label. See DESIGN.md, "Counting
    # effects, not only value".
    effects: Mapping[str, int] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: Any) -> Limits:
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ManifestError("limits: expected a mapping")
        if "total" in raw:
            raise ManifestError("limits.total is unsupported; use named limits.quantities")
        if set(raw) - {"quantities", "depth", "effects"}:
            raise ManifestError("limits: unknown field; use quantities, depth or effects")
        declared = raw.get("quantities", {})
        if not isinstance(declared, dict):
            raise ManifestError("limits.quantities: expected a mapping")
        quantities = {
            _quantity_name(name, "quantity name"): Quantity.parse(
                value, f"limits.quantities.{name}"
            )
            for name, value in declared.items()
        }
        depth = raw.get("depth", DEFAULT_DEPTH)
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            raise ManifestError("limits.depth must be a positive integer")
        return cls(quantities=quantities, depth=depth, effects=cls._parse_effects(raw))

    @staticmethod
    def _parse_effects(raw: dict[str, Any]) -> Mapping[str, int]:
        """Read `limits.effects`, refusing a class or a count it cannot honour."""
        declared = raw.get("effects")
        if declared is None:
            return {}
        if not isinstance(declared, dict):
            raise ManifestError("limits.effects: expected a mapping")
        budgets: dict[str, int] = {}
        for name, value in declared.items():
            if name not in EFFECTS:
                raise ManifestError(
                    f"limits.effects.{name}: unknown effect class; expected one "
                    f"of {', '.join(sorted(EFFECTS))}"
                )
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ManifestError(
                    f"limits.effects.{name} must be a whole number of calls, zero or more"
                )
            budgets[name] = value
        return budgets


@dataclass(frozen=True)
class Mandate:
    """The full declared authority of one agent."""

    agent: str
    tools: tuple[Tool, ...]
    identity: str | None = None
    limits: Limits = field(default_factory=Limits)
    roles: dict[str, tuple[str, ...]] = field(default_factory=dict)
    source: str | None = None

    def tool(self, name: str) -> Tool | None:
        for candidate in self.tools:
            if candidate.name == name:
                return candidate
        return None

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    @classmethod
    def parse(cls, raw: Any, source: str | None = None) -> Mandate:
        if not isinstance(raw, dict):
            raise ManifestError("manifest: expected a mapping at the top level")

        version = raw.get("version", SCHEMA_VERSION)
        if isinstance(version, bool) or version != SCHEMA_VERSION:
            raise ManifestError(
                f"manifest: unsupported schema version {version!r}, "
                f"this build reads version {SCHEMA_VERSION}"
            )

        agent = _required_name(raw.get("agent"), "manifest: agent")

        raw_tools = raw.get("tools")
        if not isinstance(raw_tools, list) or not raw_tools:
            raise ManifestError("manifest: tools must be a non-empty list")

        tools = tuple(Tool.parse(entry, i) for i, entry in enumerate(raw_tools))
        seen: set[str] = set()
        for tool in tools:
            if tool.name in seen:
                raise ManifestError(f"manifest: duplicate tool {tool.name!r}")
            seen.add(tool.name)

        # Defaulting with `or {}` would silently accept a malformed empty list,
        # so only a genuinely absent key gets the default.
        raw_roles = raw.get("roles")
        if raw_roles is None:
            raw_roles = {}
        if not isinstance(raw_roles, dict):
            raise ManifestError("roles: expected a mapping of role name to tools")
        roles: dict[str, tuple[str, ...]] = {}
        for role, members in raw_roles.items():
            role = _required_name(role, "roles: role name")
            if isinstance(members, str):
                members = [members]
            if not isinstance(members, list) or not all(
                isinstance(member, str) and member.strip() for member in members
            ):
                raise ManifestError(f"roles.{role}: expected a list of tool names")
            unknown = [m for m in members if m not in seen]
            if unknown:
                raise ManifestError(f"roles.{role}: unknown tool(s) {', '.join(sorted(unknown))}")
            roles[role] = tuple(members)

        identity = raw.get("identity")
        if identity is not None and not isinstance(identity, str):
            raise ManifestError("manifest: identity must be a string")

        return cls(
            agent=agent,
            tools=tools,
            identity=identity,
            limits=Limits.parse(raw.get("limits")),
            roles=roles,
            source=source,
        )


def loads(text: str, source: str | None = None) -> Mandate:
    """Parse a manifest from JSON or YAML text.

    JSON needs no dependency. YAML is accepted when PyYAML is installed, which
    is the documented format because a manifest is a hand-authored file that
    lives beside CI config.
    """
    stripped = text.lstrip()
    json_error = None
    if stripped.startswith("{"):
        try:
            raw = json.loads(text, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            # A quoted first key selects JSON. Never reinterpret malformed
            # JSON numbers or tags using YAML's implicit scalar conversions.
            if stripped[1:].lstrip().startswith('"'):
                raise ManifestError(f"manifest: invalid JSON: {exc}") from exc
            json_error = exc  # A YAML flow mapping also starts with '{'.
        else:
            return Mandate.parse(raw, source=source)
    try:
        import yaml
    except ImportError as exc:
        if json_error is not None:
            raise ManifestError(
                f"manifest: invalid JSON: {json_error}. "
                "Reading YAML flow mappings needs PyYAML: pip install 'agentmandate[yaml]'."
            ) from exc
        raise ManifestError(
            "reading a YAML manifest needs PyYAML: pip install 'agentmandate[yaml]'. "
            "A JSON manifest works with no extra dependency."
        ) from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        if json_error is not None:
            raise ManifestError(f"manifest: invalid JSON: {json_error}") from exc
        raise ManifestError(f"manifest: invalid YAML: {exc}") from exc
    return Mandate.parse(raw, source=source)


def load(path: str | Path) -> Mandate:
    """Read a manifest from disk."""
    resolved = Path(path)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {resolved}: {exc}") from exc
    return loads(text, source=str(resolved))


def _quantity_units(mandate: Mandate) -> dict[str, str]:
    """Resolve named units, refusing undeclared dimensions and incompatible sums."""
    if not isinstance(mandate.limits.quantities, Mapping) or any(
        not isinstance(name, str) or not name.strip() or not isinstance(value, Quantity)
        for name, value in mandate.limits.quantities.items()
    ):
        raise ManifestError("quantities must map nonblank names to Quantity values")
    units = {
        _quantity_name(name, "quantity name"): value.unit
        for name, value in mandate.limits.quantities.items()
    }
    for tool in mandate.tools:
        if tool.ceiling is None:
            if tool.quantity is not None:
                raise ManifestError(f"tool {tool.name!r}: quantity requires a ceiling")
            continue
        name = _quantity_name(tool.quantity, f"tool {tool.name!r}: quantity")
        if name in units and units[name] != tool.ceiling.unit:
            raise ManifestError(
                f"quantity {name!r} has incompatible units: "
                f"{units[name]!r} and {tool.ceiling.unit!r}"
            )
        units[name] = tool.ceiling.unit
    return units
