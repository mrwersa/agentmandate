"""Compare greedy reachability with exhaustive integer-amount/binding choices.

Repository research tooling, not a runtime analyzer or authority artifact.
The reference model imports public manifest records but no search helpers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import deque
from fractions import Fraction
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentmandate import Mandate  # noqa: E402
from agentmandate.reach import _analyse_with_trace  # noqa: E402


def reference(mandate, depth, *, quantum=Fraction(1), producer_caps=None):
    """Try zero and every positive quantum-sized amount on every held binding."""
    currencies = {tool.ceiling.currency for tool in mandate.tools if tool.ceiling is not None}
    if mandate.limits.total is not None:
        currencies.add(mandate.limits.total.currency)
    if len(currencies) > 1:
        raise ValueError("reference cumulative amounts require one currency")
    caps = {} if producer_caps is None else producer_caps
    ceilings = {}
    for tool in mandate.tools:
        if tool.ceiling is not None:
            units = Fraction(tool.ceiling.amount) / quantum
            if units.denominator != 1 or units < 0:
                raise ValueError("reference ceilings must be nonnegative multiples of the quantum")
            ceilings[tool.name] = int(units)
    total_limit = None if mandate.limits.total is None else Fraction(mandate.limits.total.amount)
    # Each state independently records resource counts, integer slot spend and
    # budgeted call counts. No greedy state, binding selector or transition is reused.
    start = ((), (), ())
    queue = deque([(start, 0)])
    seen = {start}
    reachable = set()
    effects = set()
    ungated = set()
    service = set()
    shortest = {}
    first_reach = {}
    maximum = 0
    transitions = 0
    amount_choices = 0

    while queue:
        (held_rows, spent_rows, call_rows), length = queue.popleft()
        if length == depth:
            continue
        held, spent, calls = dict(held_rows), dict(spent_rows), dict(call_rows)
        for tool in mandate.tools:
            if any(held.get(scope, 0) == 0 for scope in tool.requires):
                continue
            if (tool.produces is not None and tool.name in caps
                    and held.get(tool.produces, 0) >= caps[tool.name]):
                continue
            reachable.add(tool.name)
            first_reach.setdefault(tool.name, length + 1)
            scopes = tool.requires or (() if tool.produces is None else (tool.produces,))
            effects.update((tool.effect, scope) for scope in scopes)
            if tool.effect == "irreversible" and not tool.requires_approval:
                ungated.add(tool.name)
                shortest.setdefault(("ungated_effect", tool.name), length + 1)
            if tool.principal == "service":
                service.add(tool.name)
            next_held, next_calls = dict(held), dict(calls)
            if tool.effect in mandate.limits.effects:
                next_calls[tool.effect] = calls.get(tool.effect, 0) + 1
            if tool.produces is not None and (
                tool.unbounded or held.get(tool.produces, 0) == 0
            ):
                next_held[tool.produces] = held.get(tool.produces, 0) + 1

            choices = [(None, 0)]
            if tool.ceiling is not None:
                for binding in range(next_held.get(tool.scope_key, 0)):
                    key = (tool.name, tool.scope_key, binding)
                    remaining = ceilings[tool.name] - spent.get(key, 0)
                    choices.extend((key, amount) for amount in range(1, remaining + 1))
            for key, amount in choices:
                amount_choices += int(amount > 0)
                next_spent = dict(spent)
                if amount:
                    next_spent[key] = spent.get(key, 0) + amount
                successor = (
                    tuple(sorted(next_held.items())),
                    tuple(sorted(next_spent.items())),
                    tuple(sorted(next_calls.items())),
                )
                transitions += 1
                total = sum(next_spent.values())
                maximum = max(maximum, total)
                if total_limit is not None and total * quantum > total_limit:
                    shortest.setdefault(("cumulative_value", None), length + 1)
                budget = mandate.limits.effects.get(tool.effect)
                if budget is not None and next_calls[tool.effect] > budget:
                    shortest.setdefault(("effect_count", tool.effect), length + 1)
                if successor not in seen:
                    seen.add(successor)
                    queue.append((successor, length + 1))
    return {
        "reachable_tools": reachable,
        "effects": effects,
        "ungated_irreversible": ungated,
        "service_principal_tools": service,
        "maximum": maximum * quantum,
        "shortest_breaches": shortest,
        "first_reach": first_reach,
        "states": len(seen),
        "transitions": transitions,
        "positive_amount_choices": amount_choices,
    }


def comparison(mandate, depth, *, quantum=Fraction(1), producer_caps=None):
    concrete = reference(mandate, depth, quantum=quantum, producer_caps=producer_caps)
    authority, trace = _analyse_with_trace(mandate, depth, producer_caps=producer_caps)
    greedy = {
        "reachable_tools": set(authority.reachable_tools),
        "effects": set(authority.effects),
        "ungated_irreversible": set(authority.ungated_irreversible),
        "service_principal_tools": set(authority.service_principal_tools),
        "maximum": Fraction(0) if authority.max_extractable is None
        else Fraction(authority.max_extractable.amount),
        "shortest_breaches": {
            (b.kind, b.path[-1].tool if b.kind == "ungated_effect" else b.subject): len(b.path)
            for b in authority.breaches
        },
        "first_reach": {name: len(path) for name, path in trace.reachable_paths},
    }
    mismatches = [field for field in greedy if greedy[field] != concrete[field]]
    return {
        "mismatches": mismatches,
        "reference_states": concrete["states"],
        "reference_transitions": concrete["transitions"],
        "positive_amount_choices": concrete["positive_amount_choices"],
    }


def cases():
    """A fixed Cartesian grid and finite-cap cases; all are synthetic model checks."""
    for topology, ceiling, total, budget, depth in product(
        ("bounded", "unbounded", "two-spenders", "producer-spender",
         "chain", "shared-producers", "two-scopes", "cycle"),
        (0, 1, 3), (0, 2, 5), (None, 0, 2), (1, 2, 3, 4),
    ):
        seed = {"name": "seed", "effect": "read", "produces": "case"}
        pay = {
            "name": "pay", "effect": "irreversible", "principal": "service",
            "requires": ["case"], "value_arg": "amount", "scope_key": "case",
            "ceiling": {"amount": ceiling, "currency": "GBP"},
            "requires_approval": False,
        }
        tools = [seed, pay]
        if topology in {"unbounded", "two-spenders", "shared-producers", "two-scopes"}:
            seed["unbounded"] = True
        if topology in {"two-spenders", "two-scopes"}:
            tools.append({**pay, "name": "pay_other", "effect": "write", "principal": "caller",
                          "ceiling": {"amount": ceiling + 1, "currency": "GBP"}})
        if topology == "two-scopes":
            tools.append({"name": "seed_other", "effect": "read", "produces": "other"})
            tools[2].update({"requires": ["case", "other"], "scope_key": "other"})
        if topology == "producer-spender":
            pay.update({"produces": "case", "unbounded": True})
        if topology == "chain":
            seed.update({"produces": "ticket"})
            tools.append({"name": "resolve", "effect": "write", "requires": ["ticket"],
                          "produces": "case"})
        if topology == "shared-producers":
            tools.append({"name": "seed_again", "effect": "write", "produces": "case"})
        if topology == "cycle":
            seed.update({"requires": ["other"]})
            tools.append({"name": "cycle", "effect": "read", "requires": ["case"],
                          "produces": "other"})
        raw = {"agent": "headroom-check", "limits": {
            "depth": depth, "total": {"amount": total, "currency": "GBP"},
            "effects": {} if budget is None else dict.fromkeys(
                ("read", "write", "irreversible"), budget,
            ),
        }, "tools": tools}
        name = f"{topology}-c{ceiling}-total{total}-budget{budget}-depth{depth}"
        yield {"name": name, "manifest": raw, "depth": depth, "producer_caps": {}}
    for cap, depth in product((0, 1, 2), (1, 2, 3, 4, 5)):
        yield {"name": f"finite-cap-{cap}-depth{depth}", "depth": depth,
               "producer_caps": {"seed": cap}, "manifest": {
                   "agent": "finite-cap-check", "limits": {
                       "total": {"amount": 2, "currency": "GBP"}},
                   "tools": [
                       {"name": "seed", "effect": "read", "produces": "case",
                        "unbounded": True},
                       {"name": "pay", "effect": "irreversible", "requires": ["case"],
                        "scope_key": "case", "value_arg": "amount",
                        "ceiling": {"amount": 3, "currency": "GBP"},
                        "requires_approval": True},
                   ],
               }}


def study():
    inputs = list(cases())
    failures = []
    states = transitions = positive_amount_choices = 0
    for case in inputs:
        result = comparison(Mandate.parse(case["manifest"]), case["depth"],
                            producer_caps=case["producer_caps"])
        states += result["reference_states"]
        transitions += result["reference_transitions"]
        positive_amount_choices += result["positive_amount_choices"]
        if result["mismatches"]:
            failures.append({"case": case["name"], "fields": result["mismatches"]})
    return {
        "scope": "synthetic manifest-v1 checks; exhaustive integer amounts and binding choices",
        "cases": len(inputs), "failures": failures, "reference_states": states,
        "reference_transitions": transitions, "positive_amount_choices": positive_amount_choices,
        "inputs_sha256": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
        "reference_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "kernel_sha256": hashlib.sha256((ROOT / "agentmandate/reach.py").read_bytes()).hexdigest(),
        "excluded": ["concrete state identity", "truncation equivalence", "provider execution",
                     "arbitrary request constraints", "amount-dependent enablement"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write a complete report after all checks")
    args = parser.parse_args(argv)
    try:
        result = study()
        output = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.output is None:
            print(output, end="")
        else:
            args.output.write_text(output)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
