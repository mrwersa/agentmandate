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
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

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


@dataclass(frozen=True)
class Money:
    """An amount in a single currency.

    Decimal rather than float because these values are compared against
    ceilings and summed across a call sequence. Binary floating point would
    make a breach report arguable, and an arguable breach report is useless.
    """

    amount: Decimal
    currency: str

    @classmethod
    def parse(cls, raw: Any, where: str) -> Money:
        if not isinstance(raw, dict):
            raise ManifestError(f"{where}: expected a mapping with amount and currency")
        missing = {"amount", "currency"} - set(raw)
        if missing:
            raise ManifestError(f"{where}: missing {', '.join(sorted(missing))}")
        try:
            amount = Decimal(str(raw["amount"]))
        except InvalidOperation as exc:
            raise ManifestError(f"{where}: amount is not a number") from exc
        if amount < 0:
            raise ManifestError(f"{where}: amount must not be negative")
        currency = str(raw["currency"]).upper()
        if len(currency) != 3:
            raise ManifestError(f"{where}: currency must be a three-letter code")
        return cls(amount=amount, currency=currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"


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
    ceiling: Money | None = None
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
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestError(f"{where}: name is required")
        where = f"tool {name!r}"

        effect = raw.get("effect")
        if effect not in EFFECTS:
            raise ManifestError(f"{where}: effect must be one of {', '.join(EFFECTS)}")

        principal = raw.get("principal", CALLER)
        if principal not in PRINCIPALS:
            raise ManifestError(
                f"{where}: principal must be one of {', '.join(PRINCIPALS)}"
            )

        requires = raw.get("requires", [])
        if isinstance(requires, str):
            requires = [requires]
        if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
            raise ManifestError(f"{where}: requires must be a list of scope names")

        produces = raw.get("produces")
        if produces is not None and not isinstance(produces, str):
            raise ManifestError(f"{where}: produces must be a scope name")

        ceiling = None
        if "ceiling" in raw:
            ceiling = Money.parse(raw["ceiling"], f"{where}.ceiling")

        value_arg = raw.get("value_arg")
        if value_arg is not None and not isinstance(value_arg, str):
            raise ManifestError(f"{where}: value_arg must be an argument name")
        if (value_arg is None) != (ceiling is None):
            raise ManifestError(
                f"{where}: value_arg and ceiling must be declared together, "
                "otherwise the ceiling bounds nothing"
            )

        scope_key = raw.get("scope_key")
        if scope_key is not None and not isinstance(scope_key, str):
            raise ManifestError(f"{where}: scope_key must be a scope name")
        if value_arg is not None and scope_key is None:
            raise ManifestError(
                f"{where}: scope_key is required when a ceiling is declared, "
                "so the analysis knows what the ceiling is measured against"
            )

        return cls(
            name=name,
            effect=effect,
            principal=principal,
            requires=tuple(requires),
            produces=produces,
            unbounded=bool(raw.get("unbounded", False)),
            value_arg=value_arg,
            ceiling=ceiling,
            scope_key=scope_key,
            requires_approval=bool(raw.get("requires_approval", False)),
        )


@dataclass(frozen=True)
class Limits:
    """Bounds that apply to a whole run rather than to a single call."""

    total: Money | None = None
    depth: int = DEFAULT_DEPTH

    @classmethod
    def parse(cls, raw: Any) -> Limits:
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ManifestError("limits: expected a mapping")
        total = Money.parse(raw["total"], "limits.total") if "total" in raw else None
        depth = raw.get("depth", DEFAULT_DEPTH)
        if not isinstance(depth, int) or depth < 1:
            raise ManifestError("limits.depth must be a positive integer")
        return cls(total=total, depth=depth)


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
        if version != SCHEMA_VERSION:
            raise ManifestError(
                f"manifest: unsupported schema version {version!r}, "
                f"this build reads version {SCHEMA_VERSION}"
            )

        agent = raw.get("agent")
        if not isinstance(agent, str) or not agent:
            raise ManifestError("manifest: agent is required")

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
            if isinstance(members, str):
                members = [members]
            if not isinstance(members, list):
                raise ManifestError(f"roles.{role}: expected a list of tool names")
            unknown = [m for m in members if m not in seen]
            if unknown:
                raise ManifestError(
                    f"roles.{role}: unknown tool(s) {', '.join(sorted(unknown))}"
                )
            roles[str(role)] = tuple(str(m) for m in members)

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
    if stripped.startswith("{"):
        return Mandate.parse(json.loads(text), source=source)
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised via the CLI path
        raise ManifestError(
            "reading a YAML manifest needs PyYAML: pip install 'agentmandate[yaml]'. "
            "A JSON manifest works with no extra dependency."
        ) from exc
    return Mandate.parse(yaml.safe_load(text), source=source)


def load(path: str | Path) -> Mandate:
    """Read a manifest from disk."""
    resolved = Path(path)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read manifest {resolved}: {exc}") from exc
    return loads(text, source=str(resolved))
