"""Compare the effective authority of two releases.

The distinction this module exists to make: a configuration diff shows what
somebody typed, and an authority diff shows what the agent can now do. They
come apart often enough to matter. Adding one read-only tool is two lines of
YAML and can open a path that did not exist, because reachability composes and
text does not.

The output is deliberately shaped for CI. A widening change exits non-zero so a
pull request stops, and the change record it prints is the artefact a change
advisory board actually wants.
"""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import EFFECT_RANK, Mandate, Money, Tool
from .reach import Authority, analyse

WIDENING = "widening"
NARROWING = "narrowing"
NEUTRAL = "neutral"


@dataclass(frozen=True)
class Change:
    direction: str
    kind: str
    detail: str

    def render(self) -> str:
        marker = {WIDENING: "+", NARROWING: "-", NEUTRAL: "="}[self.direction]
        return f"  {marker} {self.kind}: {self.detail}"


@dataclass(frozen=True)
class Delta:
    before: Authority
    after: Authority
    changes: tuple[Change, ...]
    after_agent: str = "agent"

    @property
    def direction(self) -> str:
        if any(c.direction == WIDENING for c in self.changes):
            return WIDENING
        if any(c.direction == NARROWING for c in self.changes):
            return NARROWING
        return NEUTRAL

    @property
    def widened(self) -> bool:
        return self.direction == WIDENING

    def render(self, before_label: str = "before", after_label: str = "after") -> str:
        lines = [f"authority diff  {before_label} -> {after_label}"]
        if not self.changes:
            lines.append("  = no change in effective authority")
        else:
            lines.extend(change.render() for change in self.changes)
        lines.append("")
        lines.append(f"verdict: {self.direction.upper()}")
        if self.widened:
            lines.append("a widening change needs named review before release")
        return "\n".join(lines)

    def record(self, before_label: str = "before", after_label: str = "after") -> str:
        """A change record in the shape a change advisory board asks for.

        The point of emitting this from the tool rather than leaving it to a
        human is that the authority section is then derived rather than
        asserted. A change record where somebody typed "no permission changes"
        is worth very little.
        """
        widening = [c for c in self.changes if c.direction == WIDENING]
        narrowing = [c for c in self.changes if c.direction == NARROWING]
        lines = [
            "# Agent authority change record",
            "",
            f"- **Agent:** {self.after_agent}",
            f"- **Compared:** `{before_label}` against `{after_label}`",
            f"- **Verdict:** {self.direction.upper()}",
            f"- **Search depth:** {self.after.depth}"
            + (" (truncated)" if self.after.truncated else ""),
            "",
            "## Authority gained",
            "",
        ]
        lines.extend([f"- {c.kind}: {c.detail}" for c in widening] or ["- none"])
        lines.extend(["", "## Authority removed", ""])
        lines.extend([f"- {c.kind}: {c.detail}" for c in narrowing] or ["- none"])
        lines.extend(["", "## Reachable breaches after this change", ""])
        lines.extend(
            [f"- {b.detail}" for b in self.after.breaches]
            or ["- none within the search depth"]
        )
        lines.extend(["", "## Review", ""])
        if self.widened:
            lines.append(
                "This change widens what the agent is permitted to do. It needs a "
                "named reviewer who accepts the gained authority above."
            )
        else:
            lines.append(
                "This change does not widen what the agent is permitted to do."
            )
        lines.append("")
        lines.append(
            "Authority is computed from the manifests by bounded reachability. "
            "An unchanged manifest does not prove unchanged authority if a tool "
            "implementation, connector, or downstream role changed."
        )
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "direction": self.direction,
            "changes": [
                {"direction": c.direction, "kind": c.kind, "detail": c.detail}
                for c in self.changes
            ],
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
        }


def _set_change(
    kind: str, before: frozenset[str], after: frozenset[str]
) -> list[Change]:
    changes: list[Change] = []
    for gained in sorted(after - before):
        changes.append(Change(WIDENING, kind, f"gained {gained}"))
    for lost in sorted(before - after):
        changes.append(Change(NARROWING, kind, f"lost {lost}"))
    return changes


def _money_change(kind: str, before: Money | None, after: Money | None) -> list[Change]:
    if before is None and after is None:
        return []
    if before is None:
        return [Change(NARROWING, kind, f"added limit {after}")]
    if after is None:
        return [Change(WIDENING, kind, f"removed limit {before}")]
    if before.currency != after.currency:
        return [
            Change(
                WIDENING,
                kind,
                f"currency changed {before.currency} -> {after.currency}; "
                "amounts are not comparable",
            )
        ]
    if before.amount == after.amount:
        return []
    direction = WIDENING if after.amount > before.amount else NARROWING
    return [
        Change(
            direction,
            kind,
            f"{before.amount} -> {after.amount} {after.currency}",
        )
    ]


def _money_quantity_change(
    kind: str, before: Money | None, after: Money | None
) -> list[Change]:
    if before is None and after is None:
        return []
    if before is None:
        return [Change(WIDENING, kind, f"gained {after}")]
    if after is None:
        return [Change(NARROWING, kind, f"removed {before}")]
    if before.currency != after.currency:
        return [
            Change(
                WIDENING,
                kind,
                f"currency changed {before.currency} -> {after.currency}; "
                "amounts are not comparable",
            )
        ]
    if before.amount == after.amount:
        return []
    direction = WIDENING if after.amount > before.amount else NARROWING
    return [
        Change(
            direction,
            kind,
            f"{before.amount} -> {after.amount} {after.currency}",
        )
    ]


def _optional_value_change(
    kind: str, before: str | None, after: str | None
) -> list[Change]:
    if before == after:
        return []
    if before is None:
        return [Change(WIDENING, kind, f"added {after}")]
    if after is None:
        return [Change(NARROWING, kind, f"removed {before}")]
    return [
        Change(
            WIDENING,
            kind,
            f"changed {before} -> {after}; the new scope needs review",
        )
    ]


def _tool_contract_changes(before: Tool, after: Tool) -> list[Change]:
    """Compare controls on one reachable tool, independent of graph shape."""
    changes: list[Change] = []
    subject = before.name

    if before.effect != after.effect:
        direction = (
            WIDENING
            if EFFECT_RANK[after.effect] > EFFECT_RANK[before.effect]
            else NARROWING
        )
        changes.append(
            Change(
                direction,
                "effect class",
                f"{subject}: {before.effect} -> {after.effect}",
            )
        )

    removed_requirements = set(before.requires) - set(after.requires)
    added_requirements = set(after.requires) - set(before.requires)
    for scope in sorted(removed_requirements):
        changes.append(
            Change(WIDENING, "precondition", f"{subject}: removed required scope {scope}")
        )
    for scope in sorted(added_requirements):
        changes.append(
            Change(NARROWING, "precondition", f"{subject}: added required scope {scope}")
        )

    changes.extend(
        _optional_value_change(
            f"produced scope on {subject}", before.produces, after.produces
        )
    )

    if before.unbounded != after.unbounded:
        direction = WIDENING if after.unbounded else NARROWING
        detail = (
            "can now mint fresh bindings"
            if after.unbounded
            else "can no longer mint fresh bindings"
        )
        changes.append(Change(direction, "scope minting", f"{subject}: {detail}"))

    if before.requires_approval != after.requires_approval:
        direction = NARROWING if after.requires_approval else WIDENING
        detail = "approval added" if after.requires_approval else "approval removed"
        changes.append(Change(direction, "approval", f"{subject}: {detail}"))

    if before.scope_key != after.scope_key and (
        before.ceiling is not None or after.ceiling is not None
    ):
        changes.append(
            Change(
                WIDENING,
                "ceiling scope",
                f"{subject}: changed {before.scope_key or 'none'} -> "
                f"{after.scope_key or 'none'}; limits are not comparable",
            )
        )
    else:
        changes.extend(
            _money_change(f"ceiling on {subject}", before.ceiling, after.ceiling)
        )

    if before.value_arg != after.value_arg:
        changes.append(
            Change(
                WIDENING,
                "value argument",
                f"{subject}: changed {before.value_arg or 'none'} -> "
                f"{after.value_arg or 'none'}; controls need review",
            )
        )

    return changes


def _tool_effects(tool: Tool) -> set[str]:
    scopes = set(tool.requires)
    if tool.produces is not None:
        scopes.add(tool.produces)
    return {f"{tool.effect} on {scope}" for scope in scopes}


def compare(before: Mandate, after: Mandate, depth: int | None = None) -> Delta:
    """Diff the reachable authority of two mandates."""
    if before.agent != after.agent:
        raise ValueError(
            f"cannot compare different agents: {before.agent!r} and {after.agent!r}"
        )

    comparison_depth = (
        depth if depth is not None else max(before.limits.depth, after.limits.depth)
    )
    lhs = analyse(before, depth=comparison_depth)
    rhs = analyse(after, depth=comparison_depth)
    changes: list[Change] = []

    if after.limits.depth < before.limits.depth:
        changes.append(
            Change(
                WIDENING,
                "analysis depth",
                f"reduced {before.limits.depth} -> {after.limits.depth}; "
                "future default scans could miss longer paths",
            )
        )

    if before.identity != after.identity:
        if before.identity is None:
            changes.append(
                Change(NARROWING, "workload identity", f"declared {after.identity}")
            )
        elif after.identity is None:
            changes.append(
                Change(WIDENING, "workload identity", f"removed {before.identity}")
            )
        else:
            changes.append(
                Change(
                    WIDENING,
                    "workload identity",
                    f"changed {before.identity} -> {after.identity}; needs review",
                )
            )

    changes.extend(_set_change("tool", lhs.reachable_tools, rhs.reachable_tools))
    changes.extend(
        _set_change(
            "ungated irreversible",
            lhs.ungated_irreversible,
            rhs.ungated_irreversible,
        )
    )
    changes.extend(
        _set_change(
            "service principal",
            lhs.service_principal_tools,
            rhs.service_principal_tools,
        )
    )

    for name in sorted(rhs.reachable_tools - lhs.reachable_tools):
        tool = after.tool(name)
        if tool is not None:
            existing = {f"{effect} on {scope}" for effect, scope in lhs.effects}
            for effect in sorted(_tool_effects(tool) - existing):
                changes.append(Change(WIDENING, "effect", f"gained {effect}"))
    for name in sorted(lhs.reachable_tools - rhs.reachable_tools):
        tool = before.tool(name)
        if tool is not None:
            remaining = {f"{effect} on {scope}" for effect, scope in rhs.effects}
            for effect in sorted(_tool_effects(tool) - remaining):
                changes.append(Change(NARROWING, "effect", f"lost {effect}"))

    common_tools = lhs.reachable_tools & rhs.reachable_tools
    for name in sorted(common_tools):
        before_tool = before.tool(name)
        after_tool = after.tool(name)
        if before_tool is not None and after_tool is not None:
            changes.extend(_tool_contract_changes(before_tool, after_tool))

    changes.extend(
        _money_quantity_change(
            "extractable value", lhs.max_extractable, rhs.max_extractable
        )
    )
    changes.extend(
        _money_change("run limit", before.limits.total, after.limits.total)
    )

    before_breaches = frozenset(b.kind for b in lhs.breaches)
    after_breaches = frozenset(b.kind for b in rhs.breaches)
    changes.extend(_set_change("reachable breach", before_breaches, after_breaches))

    return Delta(
        before=lhs, after=rhs, changes=tuple(changes), after_agent=after.agent
    )
