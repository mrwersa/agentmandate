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
from decimal import Decimal

from .manifest import Mandate
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


def compare(before: Mandate, after: Mandate, depth: int | None = None) -> Delta:
    """Diff the reachable authority of two mandates."""
    lhs = analyse(before, depth=depth)
    rhs = analyse(after, depth=depth)
    changes: list[Change] = []

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

    before_effects = frozenset(f"{effect} on {scope}" for effect, scope in lhs.effects)
    after_effects = frozenset(f"{effect} on {scope}" for effect, scope in rhs.effects)
    changes.extend(_set_change("effect", before_effects, after_effects))

    lhs_max = lhs.max_extractable.amount if lhs.max_extractable else Decimal(0)
    rhs_max = rhs.max_extractable.amount if rhs.max_extractable else Decimal(0)
    if rhs_max != lhs_max:
        currency = (
            rhs.max_extractable.currency
            if rhs.max_extractable
            else (lhs.max_extractable.currency if lhs.max_extractable else "")
        )
        direction = WIDENING if rhs_max > lhs_max else NARROWING
        changes.append(
            Change(
                direction,
                "extractable value",
                f"{lhs_max} -> {rhs_max} {currency}".strip(),
            )
        )

    before_breaches = frozenset(b.kind for b in lhs.breaches)
    after_breaches = frozenset(b.kind for b in rhs.breaches)
    changes.extend(_set_change("reachable breach", before_breaches, after_breaches))

    return Delta(
        before=lhs, after=rhs, changes=tuple(changes), after_agent=after.agent
    )
