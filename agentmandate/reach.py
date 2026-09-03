"""Bounded reachability over the authority graph.

This is the part of AgentMandate that other tools do not do. Scanners check one
tool at a time and report the ones that look dangerous on their own. That misses
the common real defect, where every individual tool respects its ceiling and a
legal sequence of them does not.

The search is an ordinary breadth-first walk over states, so a finding always
comes with the call sequence that produces it. A breach report without a
counterexample is an opinion, and nobody reworks a release on an opinion.

Semantics worth stating plainly, because the analysis is only as meaningful as
the reading of the manifest:

- A ceiling is the maximum *cumulative* value one tool may spend against one
  binding of its ``scope_key``. Per-call would be a weaker claim and would make
  a breach trivial rather than interesting.
- A tool marked ``unbounded`` can be called repeatedly to mint fresh bindings.
  This is the whole game. A per-scope ceiling bounds nothing when the agent can
  mint scopes at will, and that gap is invisible tool by tool.
- Search is bounded by ``limits.depth``. Results are therefore a lower bound on
  what the agent can reach: finding no breach at depth 8 is not proof that none
  exists at depth 20.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from .manifest import IRREVERSIBLE, Mandate, Money, Tool


# A single call in a counterexample path.
@dataclass(frozen=True)
class Step:
    tool: str
    binding: str | None = None
    spent: Decimal | None = None
    currency: str | None = None

    def render(self) -> str:
        parts = [self.tool]
        detail = []
        if self.binding:
            detail.append(self.binding)
        if self.spent is not None:
            detail.append(f"{self.spent} {self.currency}")
        if detail:
            parts.append("(" + ", ".join(detail) + ")")
        return "".join(parts)


@dataclass(frozen=True)
class Breach:
    """A reachable violation, with the sequence that produces it."""

    kind: str
    detail: str
    path: tuple[Step, ...]
    #: What the breach is about, when one kind can fire about several things.
    #: An effect budget reports per class, so the class discriminates. Used to
    #: report each subject once and deliberately not serialised: the JSON
    #: contract is kind, detail and path, and this is how the search decides
    #: it has already said something rather than a fact about the finding.
    subject: str | None = None

    def render(self) -> str:
        lines = [f"BREACH  {self.detail}"]
        for index, step in enumerate(self.path, start=1):
            lines.append(f"  {index}. {step.render()}")
        return "\n".join(lines)


@dataclass(frozen=True)
class Authority:
    """What the agent can actually reach, as opposed to what it declares.

    This is the object that ``diff`` compares. Two manifests with identical
    text produce identical authority, but the reverse does not hold, which is
    the reason a config diff is not an authority diff.
    """

    reachable_tools: frozenset[str] = frozenset()
    effects: frozenset[tuple[str, str]] = frozenset()
    ungated_irreversible: frozenset[str] = frozenset()
    service_principal_tools: frozenset[str] = frozenset()
    max_extractable: Money | None = None
    breaches: tuple[Breach, ...] = ()
    depth: int = 0
    truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "reachable_tools": sorted(self.reachable_tools),
            "effects": sorted([list(pair) for pair in self.effects]),
            "ungated_irreversible": sorted(self.ungated_irreversible),
            "service_principal_tools": sorted(self.service_principal_tools),
            "max_extractable": (
                None
                if self.max_extractable is None
                else {
                    "amount": str(self.max_extractable.amount),
                    "currency": self.max_extractable.currency,
                }
            ),
            "breaches": [
                {
                    "kind": b.kind,
                    "detail": b.detail,
                    "path": [s.render() for s in b.path],
                }
                for b in self.breaches
            ],
            "depth": self.depth,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class _ReachTrace:
    """Shortest enabling call path retained for later IR provenance."""

    reachable_paths: tuple[tuple[str, tuple[Step, ...]], ...] = ()

    def path_for(self, tool: str) -> tuple[Step, ...] | None:
        return next((path for name, path in self.reachable_paths if name == tool), None)


@dataclass(frozen=True)
class _State:
    """Bindings held and value already spent, canonicalised for memoisation."""

    # scope name -> how many distinct bindings the agent holds
    counts: tuple[tuple[str, int], ...] = ()
    # (tool, scope, binding index) -> cumulative spend
    spend: tuple[tuple[tuple[str, str, int], Decimal], ...] = ()
    # effect class -> calls made so far, tracked only for declared budgets
    effect_calls: tuple[tuple[str, int], ...] = ()

    def count(self, scope: str) -> int:
        for name, value in self.counts:
            if name == scope:
                return value
        return 0

    def spent_on(self, tool: str, scope: str, index: int) -> Decimal:
        for key, value in self.spend:
            if key == (tool, scope, index):
                return value
        return Decimal(0)

    @property
    def total(self) -> Decimal:
        return sum((value for _, value in self.spend), Decimal(0))

    def with_binding(self, scope: str) -> _State:
        counts = dict(self.counts)
        counts[scope] = counts.get(scope, 0) + 1
        return _State(
            counts=_freeze_counts(counts),
            spend=self.spend,
            effect_calls=self.effect_calls,
        )

    def calls(self, effect: str) -> int:
        return dict(self.effect_calls).get(effect, 0)

    def with_call(self, effect: str) -> _State:
        calls = dict(self.effect_calls)
        calls[effect] = calls.get(effect, 0) + 1
        return _State(
            counts=self.counts,
            spend=self.spend,
            effect_calls=tuple(sorted(calls.items())),
        )

    def with_spend(self, tool: str, scope: str, index: int, amount: Decimal) -> _State:
        spend = dict(self.spend)
        key = (tool, scope, index)
        spend[key] = spend.get(key, Decimal(0)) + amount
        return _State(
            counts=self.counts,
            spend=_freeze_spend(spend),
            effect_calls=self.effect_calls,
        )


def _freeze_counts(counts: dict[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((k, v) for k, v in counts.items() if v))


def _freeze_spend(
    spend: dict[tuple[str, str, int], Decimal],
) -> tuple[tuple[tuple[str, str, int], Decimal], ...]:
    return tuple(sorted((k, v) for k, v in spend.items() if v))


def _enabled(tool: Tool, state: _State) -> bool:
    return all(state.count(scope) >= 1 for scope in tool.requires)


def _mints(tool: Tool, state: _State) -> bool:
    """Whether calling this tool adds a binding the agent did not already hold."""
    if tool.produces is None:
        return False
    if tool.unbounded:
        return True
    return state.count(tool.produces) == 0


def _best_binding(tool: Tool, state: _State) -> tuple[int, Decimal] | None:
    """Pick the binding with the most headroom under this tool's ceiling."""
    if not tool.spends_value or tool.scope_key is None or tool.ceiling is None:
        return None
    held = state.count(tool.scope_key)
    best: tuple[int, Decimal] | None = None
    for index in range(held):
        spent = state.spent_on(tool.name, tool.scope_key, index)
        headroom = tool.ceiling.amount - spent
        if headroom > 0 and (best is None or headroom > best[1]):
            best = (index, headroom)
    return best


def _analyse_with_trace(
    mandate: Mandate,
    depth: int | None = None,
    *,
    producer_caps: Mapping[str, int] | None = None,
) -> tuple[Authority, _ReachTrace]:
    """Walk the graph and retain shortest enabling paths for provenance.

    Returns the effective authority summary plus any cumulative-value breach
    found within the depth bound, shortest counterexample first.
    """
    limit = depth if depth is not None else mandate.limits.depth
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("depth must be a positive integer")
    total_cap = mandate.limits.total
    effect_caps = mandate.limits.effects
    bounded_producers = producer_caps or {}

    reachable: set[str] = set()
    effects: set[tuple[str, str]] = set()
    ungated: set[str] = set()
    service: set[str] = set()
    breaches: list[Breach] = []
    reachable_paths: dict[str, tuple[Step, ...]] = {}
    max_total = Decimal(0)
    truncated = False

    start = _State()
    seen: set[_State] = {start}
    queue: deque[tuple[_State, tuple[Step, ...]]] = deque([(start, ())])

    while queue:
        state, path = queue.popleft()
        if len(path) >= limit:
            truncated = True
            continue

        for tool in mandate.tools:
            if not _enabled(tool, state):
                continue
            producer_cap = bounded_producers.get(tool.name)
            if (
                producer_cap is not None
                and tool.produces is not None
                and state.count(tool.produces) >= producer_cap
            ):
                # The reviewed producer rejected this transition before the
                # effect succeeded, so it contributes neither a binding nor
                # an effect call to the reachable path.
                continue

            first_reach = tool.name not in reachable_paths
            reachable.add(tool.name)
            for scope in tool.requires or ((tool.produces,) if tool.produces else ()):
                if scope:
                    effects.add((tool.effect, scope))
            if tool.effect == IRREVERSIBLE and not tool.requires_approval:
                ungated.add(tool.name)
                # Reported as a path rather than a bare name. Knowing an
                # ungated irreversible tool exists is a lint finding. Knowing
                # the agent can actually get to it, and how, is the thing that
                # decides whether it matters.
                if not any(
                    b.kind == "ungated_effect" and b.path[-1].tool == tool.name
                    for b in breaches
                ):
                    breaches.append(
                        Breach(
                            kind="ungated_effect",
                            detail=(
                                f"{tool.name} is irreversible and needs no approval, "
                                f"reachable in {len(path) + 1} call(s)"
                            ),
                            path=path + (Step(tool=tool.name),),
                        )
                    )
            if tool.principal == "service":
                service.add(tool.name)

            next_state = state
            step_binding = None
            step_spent = None
            step_currency = None
            progressed = False

            # A budgeted call moves the walk forward the way spending does.
            # Without this, an irreversible tool that neither mints nor spends
            # is skipped as reaching no new state, so the search cannot
            # represent calling it twice and no budget over it could ever be
            # exceeded. See DESIGN.md, "Counting effects, not only value".
            if tool.effect in effect_caps:
                next_state = next_state.with_call(tool.effect)
                progressed = True

            if _mints(tool, state):
                next_state = next_state.with_binding(tool.produces)  # type: ignore[arg-type]
                step_binding = f"{tool.produces}#{state.count(tool.produces) + 1}"
                progressed = True

            choice = _best_binding(tool, next_state)
            if choice is not None:
                index, headroom = choice
                next_state = next_state.with_spend(
                    tool.name, tool.scope_key, index, headroom  # type: ignore[arg-type]
                )
                step_binding = f"{tool.scope_key}#{index + 1}"
                step_spent = headroom
                step_currency = tool.ceiling.currency  # type: ignore[union-attr]
                progressed = True

            step = Step(
                tool=tool.name,
                binding=step_binding,
                spent=step_spent,
                currency=step_currency,
            )
            next_path = path + (step,)
            if first_reach:
                reachable_paths[tool.name] = next_path

            if not progressed:
                # A pure read that changes nothing. It is reachable, which is
                # recorded above, but exploring it again only inflates the
                # search without reaching a state the walk cannot already hit.
                continue

            if next_state in seen:
                continue
            seen.add(next_state)

            running = next_state.total
            max_total = max(max_total, running)

            if (
                total_cap is not None
                and running > total_cap.amount
                and not any(b.kind == "cumulative_value" for b in breaches)
            ):
                breaches.append(
                    Breach(
                        kind="cumulative_value",
                        detail=(
                            f"cumulative value {running} {total_cap.currency} "
                            f"exceeds limit {total_cap.amount} {total_cap.currency}"
                        ),
                        path=next_path,
                    )
                )

            cap = effect_caps.get(tool.effect)
            if cap is not None:
                made = next_state.calls(tool.effect)
                # Keyed on the subject rather than on the message. Matching a
                # prefix of `detail` worked only while every message happened
                # to open with the effect name, so a reworded message would
                # have quietly produced one breach per extra call.
                if made > cap and not any(
                    b.kind == "effect_count" and b.subject == tool.effect
                    for b in breaches
                ):
                    breaches.append(
                        Breach(
                            kind="effect_count",
                            detail=(
                                f"{tool.effect} calls reach {made}, above the "
                                f"declared budget of {cap} in one run"
                            ),
                            path=next_path,
                            subject=tool.effect,
                        )
                    )

            queue.append((next_state, next_path))

    currency = total_cap.currency if total_cap else _sole_currency(mandate)
    authority = Authority(
        reachable_tools=frozenset(reachable),
        effects=frozenset(effects),
        ungated_irreversible=frozenset(ungated),
        service_principal_tools=frozenset(service),
        max_extractable=(
            Money(amount=max_total, currency=currency) if currency else None
        ),
        breaches=tuple(breaches),
        depth=limit,
        truncated=truncated,
    )
    trace = _ReachTrace(tuple(sorted(reachable_paths.items())))
    return authority, trace


def analyse(mandate: Mandate, depth: int | None = None) -> Authority:
    """Walk the authority graph and report what the agent can reach."""
    return _analyse_with_trace(mandate, depth=depth)[0]


def _sole_currency(mandate: Mandate) -> str | None:
    currencies = {t.ceiling.currency for t in mandate.tools if t.ceiling}
    return currencies.pop() if len(currencies) == 1 else None
