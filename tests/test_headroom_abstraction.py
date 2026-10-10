import json
from dataclasses import replace
from decimal import (
    MAX_EMAX,
    ROUND_DOWN,
    ROUND_UP,
    Decimal,
    DefaultContext,
    Inexact,
    Rounded,
    localcontext,
)
from fractions import Fraction
from pathlib import Path

import pytest

from agentmandate import Mandate, analyse, reach
from agentmandate.cli import main
from scripts import check_headroom_abstraction as study

ROOT = Path(__file__).resolve().parents[1]


def money_manifest(ceilings, *, total="1", unbounded=False, depth=2):
    return Mandate.parse({
        "agent": "exact-headroom",
        "limits": {"depth": depth, "total": {"amount": total, "currency": "GBP"}},
        "tools": [{"name": "seed", "effect": "read", "produces": "case",
                   "unbounded": unbounded}] + [
            {"name": f"pay_{index}", "effect": "irreversible", "requires": ["case"],
             "scope_key": "case", "value_arg": "amount", "requires_approval": True,
             "ceiling": {"amount": amount, "currency": "GBP"}}
            for index, amount in enumerate(ceilings)
        ],
    })


@pytest.mark.parametrize("case", list(study.cases()), ids=lambda case: case["name"])
def test_greedy_matches_exhaustive_amount_and_binding_search(case):
    result = study.comparison(Mandate.parse(case["manifest"]), case["depth"],
                              producer_caps=case["producer_caps"])
    assert not result["mismatches"], result


@pytest.mark.parametrize("quantum", [Fraction(1, 10), Fraction(1, 100)])
def test_reference_checks_fractional_units_without_decimal_arithmetic(quantum):
    ceiling = "0.3" if quantum == Fraction(1, 10) else "0.03"
    total = "0.5" if quantum == Fraction(1, 10) else "0.05"
    source = money_manifest([ceiling], total=total, unbounded=True, depth=4)
    assert not study.comparison(source, 4, quantum=quantum)["mismatches"]
    concrete = study.reference(source, 4, quantum=quantum)
    assert concrete["maximum"] == 6 * quantum
    assert concrete["shortest_breaches"] == {("cumulative_value", None): 4}


def test_reference_rejects_amounts_outside_its_discrete_domain():
    with pytest.raises(ValueError, match="multiples of the quantum"):
        study.reference(money_manifest(["0.3"]), 2)


def test_reference_rejects_mixed_currency_sums():
    source = money_manifest(["3"])
    source = replace(source, limits=replace(source.limits, total=replace(
        source.limits.total, currency="USD",
    )))
    with pytest.raises(ValueError, match="require one currency"):
        study.reference(source, 2)


@pytest.mark.parametrize("mutation,total,unbounded,depth", [
    ("under-spend", "2", False, 2), ("ignore-fresh-bindings", "5", True, 4),
])
def test_oracle_detects_amount_and_binding_selection_mutations(
    mutation, total, unbounded, depth, monkeypatch,
):
    original = reach._best_binding

    def weakened_selection(tool, state):
        choice = original(tool, state)
        if choice is None:
            return None
        if mutation == "under-spend":
            return choice[0], min(choice[1], Decimal(1))
        return choice if choice[0] == 0 else None

    monkeypatch.setattr(reach, "_best_binding", weakened_selection)
    source = money_manifest(["3"], total=total, unbounded=unbounded, depth=depth)
    result = study.comparison(source, depth)
    assert set(result["mismatches"]) == {"maximum", "shortest_breaches"}


def test_recorded_study_reproduces_and_reference_exercises_partial_amounts():
    recorded = json.loads((ROOT / "docs/headroom-abstraction-results.json").read_text())
    current = study.study()
    # The report records a pinned kernel run; later implementation changes
    # must retain semantic agreement, not retroactively change that source hash.
    assert {k: v for k, v in current.items() if k != "kernel_sha256"} == {
        k: v for k, v in recorded.items() if k != "kernel_sha256"
    }
    assert current["cases"] == 879
    assert not current["failures"]
    assert current["positive_amount_choices"] > 0


@pytest.mark.parametrize("rounding", [ROUND_DOWN, ROUND_UP])
def test_high_precision_breach_does_not_depend_on_the_callers_decimal_context(rounding):
    ceiling = "1.0000000000000000000000000001"
    source = money_manifest([ceiling])
    with localcontext() as caller:
        caller.prec = 3
        caller.rounding = rounding
        caller.Emax = 2
        caller.Emin = -2
        caller.traps[Inexact] = True
        before = (caller.prec, caller.rounding, caller.Emax, caller.Emin,
                  dict(caller.flags), dict(caller.traps))
        result = analyse(source)
        assert result.max_extractable.amount == Decimal(ceiling)
        assert [(b.kind, len(b.path)) for b in result.breaches] == [("cumulative_value", 2)]
        assert result.breaches[0].path[-1].spent == Decimal(ceiling)
        assert before == (caller.prec, caller.rounding, caller.Emax, caller.Emin,
                          dict(caller.flags), dict(caller.traps))


def test_ceiling_digits_and_small_cross_tool_addends_are_not_lost():
    amounts = ["9999999999999999999999999999", "0.000000001"]
    source = money_manifest(amounts, total=amounts[0], depth=3)
    result = analyse(source)
    assert Fraction(result.max_extractable.amount) == sum(map(Fraction, amounts))
    assert [(b.kind, len(b.path)) for b in result.breaches] == [("cumulative_value", 3)]
    assert sum(Fraction(s.spent) for s in result.breaches[0].path if s.spent is not None) == (
        Fraction(result.max_extractable.amount)
    )


def test_search_does_not_inherit_modified_global_default_traps(monkeypatch):
    source = money_manifest(["1e1000000"], total="0")
    monkeypatch.setitem(DefaultContext.traps, Rounded, True)
    result = analyse(source)
    assert result.max_extractable.amount == Decimal("1e1000000")
    assert result.breaches[0].kind == "cumulative_value"
    assert DefaultContext.traps[Rounded]


@pytest.mark.parametrize("amount", ["1e1000000", "1e-1000000"])
def test_exponents_outside_the_default_context_still_have_exact_search_values(amount):
    result = analyse(money_manifest([amount], total="0"))
    assert result.max_extractable.amount == Decimal(amount)
    assert result.breaches[0].kind == "cumulative_value"


def test_carry_digits_cover_many_spends_with_the_same_ceiling():
    amount = "9999999999999999999999999999"
    result = analyse(money_manifest([amount], total=amount, unbounded=True, depth=20))
    assert Fraction(result.max_extractable.amount) == 10 * Fraction(amount)
    assert len(result.breaches[0].path) == 4


@pytest.mark.parametrize("command", ["reach", "diff", "remediate"])
def test_exact_values_reach_cli_consumers(command, tmp_path, capsys):
    paths = []
    for name, amount in [("before", "1"), ("after", "1.0000000000000000000000000001")]:
        path = tmp_path / f"{name}.json"
        # The public candidate representation is already a loadable semantic manifest.
        source = money_manifest([amount])
        path.write_text(json.dumps({
            "agent": source.agent, "limits": {"depth": 2,
                "total": {"amount": "1", "currency": "GBP"}},
            "tools": [{"name": "seed", "effect": "read", "produces": "case"},
                      {"name": "pay", "effect": "irreversible", "requires": ["case"],
                       "scope_key": "case", "value_arg": "amount", "requires_approval": True,
                       "ceiling": {"amount": amount, "currency": "GBP"}}],
        }))
        paths.append(str(path))
    argv = [command, *paths] if command == "diff" else [command, paths[1]]
    assert main([*argv, "--json"]) == 1
    output = capsys.readouterr()
    assert not output.err
    result = json.loads(output.out)
    authority = result["after"] if command == "diff" else (
        result["baseline"] if command == "remediate" else result
    )
    assert authority["max_extractable"]["amount"] == "1.0000000000000000000000000001"
    assert authority["breaches"][0]["kind"] == "cumulative_value"


@pytest.mark.parametrize("command", ["reach", "obligations", "scenarios", "diff", "remediate"])
@pytest.mark.parametrize("failure", ["exponent-overflow", "precision-exhaustion"])
def test_decimal_exhaustion_is_a_usage_error_without_partial_output(
    command, failure, tmp_path, capsys,
):
    amount = f"9e{MAX_EMAX}"
    path = tmp_path / "extreme.json"
    raw = {
        "agent": "extreme", "limits": {"depth": 4},
        "tools": [{"name": "seed", "effect": "read", "produces": "case", "unbounded": True},
                  {"name": "pay", "effect": "irreversible", "requires": ["case"],
                   "scope_key": "case", "value_arg": "amount", "requires_approval": True,
                   "ceiling": {"amount": amount, "currency": "GBP"}}],
    }
    if failure == "precision-exhaustion":
        raw["tools"].append({**raw["tools"][1], "name": "tiny",
                             "ceiling": {"amount": f"1e{-MAX_EMAX}", "currency": "GBP"}})
    path.write_text(json.dumps(raw))
    argv = [command, str(path), str(path)] if command == "diff" else [command, str(path)]
    assert main([*argv, "--json"]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "supported exact decimal arithmetic" in output.err


def test_study_command_writes_complete_report_and_exposes_mismatches(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(study, "study", lambda: {"failures": []})
    path = tmp_path / "report.json"
    assert study.main(["--output", str(path)]) == 0
    assert json.loads(path.read_text()) == {"failures": []}
    monkeypatch.setattr(study, "study", lambda: {"failures": [{"case": "mutant"}]})
    assert study.main([]) == 1
    assert json.loads(capsys.readouterr().out)["failures"] == [{"case": "mutant"}]


def test_study_refuses_an_unwritable_output_path_without_stdout(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(study, "study", lambda: {"failures": []})
    assert study.main(["--output", str(tmp_path / "absent/report.json")]) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error:")
