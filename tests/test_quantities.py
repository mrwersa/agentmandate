"""Named accounting pools across the complete manifest workflow."""

import json
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from itertools import product

import pytest

import agentmandate
from agentmandate import Mandate, ManifestError, Quantity, analyse, compare, loads, replay
from agentmandate._ir import AuthorityIR, _analyse_ir, _from_mandate, _to_mandate
from agentmandate._remediation import plan
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main
from agentmandate.lint import check
from agentmandate.verify import parse_observations


def model(*, shared=False, same_unit=False, unbounded=True, cap="3", budget="4", depth=4):
    names = ("records", "records" if shared else "tokens")
    units = ("record", "record" if shared or same_unit else "token")
    return Mandate.parse(
        {
            "version": 2,
            "agent": "generic",
            "limits": {
                "depth": depth,
                "quantities": {
                    name: {"amount": budget, "unit": unit}
                    for name, unit in zip(names, units, strict=True)
                },
            },
            "tools": [
                {"name": "seed", "effect": "read", "produces": "batch", "unbounded": unbounded}
            ]
            + [
                {
                    "name": name,
                    "effect": "read",
                    "requires": ["batch"],
                    "scope_key": "batch",
                    "value_arg": "amount",
                    "quantity": quantity,
                    "ceiling": {"amount": cap, "unit": unit},
                }
                for name, quantity, unit in zip(("export", "generate"), names, units, strict=True)
            ],
        }
    )


@pytest.mark.parametrize("conflict", ["budget", "tool"])
@pytest.mark.parametrize("json_output", [False, True])
def test_ir_structure_can_preserve_unit_conflicts_but_analysis_refuses_them(
    tmp_path, capsys, conflict, json_output
):
    source = model(shared=True)
    if conflict == "budget":
        source = replace(
            source,
            limits=replace(source.limits, quantities={"records": Quantity(Decimal(4), "USD")}),
        )
    else:
        source = replace(
            source,
            limits=replace(source.limits, quantities={}),
            tools=source.tools[:-1] + (
                replace(source.tools[-1], ceiling=Quantity(Decimal(3), "token")),
            ),
        )
    path = tmp_path / "conflicting-units.json"
    path.write_text(_from_mandate(source).to_json())
    flags = ["--json"] if json_output else []
    assert main(["ir", "validate", str(path), *flags]) == 0
    validated = capsys.readouterr()
    assert validated.err == ""
    if json_output:
        assert json.loads(validated.out)["status"] == "valid"
    else:
        assert validated.out == "valid authority IR v2\n"
    assert main(["reach", "--ir", str(path), *flags]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "incompatible units" in refused.err


@pytest.mark.parametrize("same_unit", [False, True])
def test_independent_named_pools_never_merge_even_with_matching_units(same_unit):
    source = model(same_unit=same_unit, unbounded=False)
    authority = analyse(source)
    assert authority.breaches == ()
    assert set(authority.max_quantities) == {"records", "tokens"}
    assert [q.amount for q in authority.max_quantities.values()] == [Decimal(3), Decimal(3)]
    assert authority.as_dict()["max_quantities"]["records"] == {"amount": "3", "unit": "record"}
    shared = analyse(model(shared=True, unbounded=False))
    assert shared.max_quantities["records"].amount == 6
    assert [(b.kind, b.subject) for b in shared.breaches] == [("quantity_budget", "records")]


@pytest.mark.parametrize(
    "shared,same_unit,unbounded,cap,budget,depth",
    list(
        product([False, True], [False, True], [False, True], ["0", "0.3"], ["0", "0.5"], [2, 3, 4])
    ),
)
def test_named_maxima_and_shortest_breaches_match_fraction_sequence_oracle(
    shared, same_unit, unbounded, cap, budget, depth
):
    source = model(
        shared=shared, same_unit=same_unit, unbounded=unbounded, cap=cap, budget=budget, depth=depth
    )
    maxima = dict.fromkeys(source.limits.quantities, Fraction(0))
    shortest = {}
    for length in range(1, depth + 1):
        for calls in product(range(3), repeat=length):
            bindings, spending, totals = 0, {}, dict.fromkeys(maxima, Fraction(0))
            legal = True
            for call in calls:
                if call == 0:
                    bindings += int(unbounded or bindings == 0)
                    continue
                if not bindings:
                    legal = False
                    break
                tool = source.tools[call]
                # Independent concrete choice: select the least-used binding and fill it.
                binding = min(range(bindings), key=lambda b: spending.get((call, b), Fraction(0)))
                prior = spending.get((call, binding), Fraction(0))
                amount = Fraction(cap) - prior
                spending[(call, binding)] = Fraction(cap)
                totals[tool.quantity] += amount
            if legal:
                for name, amount in totals.items():
                    maxima[name] = max(maxima[name], amount)
                    if amount > Fraction(budget):
                        shortest.setdefault(name, length)
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        actual = analyse(source)
    assert {name: Fraction(q.amount) for name, q in actual.max_quantities.items()} == maxima
    assert {b.subject: len(b.path) for b in actual.breaches} == shortest


def test_budget_changes_and_pool_reassignment_do_not_depend_on_a_breach_witness():
    before = model(unbounded=False, budget="40")
    changed = replace(
        before,
        limits=replace(
            before.limits,
            quantities={
                "records": Quantity(Decimal(50), "record"),
                "tokens": Quantity(Decimal(30), "token"),
            },
        ),
    )
    result = compare(before, changed)
    assert not result.before.breaches and not result.after.breaches
    assert {(c.kind, c.direction) for c in result.changes} == {
        ("quantity budget records", "widening"),
        ("quantity budget tokens", "narrowing"),
    }
    removed = replace(before, limits=replace(before.limits, quantities={}))
    assert compare(before, removed).widened
    assert compare(removed, before).direction == "narrowing"
    reassigned = replace(
        before,
        tools=(before.tools[0], replace(before.tools[1], quantity="another_pool"), before.tools[2]),
    )
    assert any(c.kind == "quantity assignment" for c in compare(before, reassigned).changes)


def test_inconsistent_units_fail_closed_but_distinct_currency_pools_are_ordinary_quantities():
    source = model()
    changed = replace(
        source,
        tools=(
            source.tools[0],
            replace(source.tools[1], ceiling=Quantity(Decimal(3), "kilo-record")),
            source.tools[2],
        ),
    )
    assert [f.rule for f in check(changed)] == ["quantity.unit-mismatch"]
    with pytest.raises(ValueError, match="incompatible units"):
        analyse(changed)
    separate = replace(
        source,
        tools=(
            source.tools[0],
            replace(source.tools[1], ceiling=Quantity(Decimal(3), "GBP")),
            replace(source.tools[2], ceiling=Quantity(Decimal(3), "USD")),
        ),
        limits=replace(
            source.limits,
            quantities={
                "records": Quantity(Decimal(4), "GBP"),
                "tokens": Quantity(Decimal(4), "USD"),
            },
        ),
    )
    assert set(analyse(separate).max_quantities) == {"records", "tokens"}


def test_replay_accumulates_only_the_named_pool_with_exact_context_independent_arithmetic():
    source = model(unbounded=False, cap="0.3", budget="0.5", same_unit=True)
    rows = [
        {
            "tool": "export",
            "scope": "batch-1",
            "value": "0.3",
            "quantity": "records",
            "unit": "record",
            "principal": "caller",
        },
        {
            "tool": "generate",
            "scope": "batch-1",
            "value": "0.3",
            "quantity": "tokens",
            "unit": "record",
            "principal": "caller",
        },
    ]
    observations = parse_observations("\n".join(json.dumps(row) for row in rows))
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        assert replay(source, observations).conformant
    rows[-1]["quantity"] = "records"
    wrong = replay(source, parse_observations("\n".join(json.dumps(row) for row in rows)))
    assert [v.kind for v in wrong.violations] == ["quantity_mismatch"]


def test_ir_round_trip_and_provenance_keep_all_quantity_assignments():
    source = model()
    graph = _from_mandate(source)
    restored = _to_mandate(AuthorityIR.from_json(graph.to_json()))
    assert restored == source
    assert _analyse_ir(graph).authority == analyse(source)
    names = {(f.predicate, f.subject) for f in graph.facts}
    assert ("quantity", "tool:export") in names
    assert ("quantity", "tool:generate") in names
    assert ("quantities", "constraint:run") in names


def test_discovery_rechecks_every_budget_and_preserves_required_paths():
    source = model()
    required = {
        "schema": "agentmandate.required-workflows/v2",
        "agent": source.agent,
        "manifest_sha256": "0" * 64,
        "reviewer": "synthetic-model-test",
        "reason": "Synthetic positive path, not business success",
        "workflows": [
            {
                "name": "export-and-generate",
                "steps": [
                    {"tool": "seed", "principal": "caller", "approved": False},
                    {
                        "tool": "export",
                        "principal": "caller",
                        "approved": False,
                        "binding": 0,
                        "value": "1",
                        "quantity": "records",
                        "unit": "record",
                    },
                    {
                        "tool": "generate",
                        "principal": "caller",
                        "approved": False,
                        "binding": 0,
                        "value": "1",
                        "quantity": "tokens",
                        "unit": "token",
                    },
                ],
            }
        ],
    }
    requirements = _Requirements.load(json.dumps(required).encode(), source, "0" * 64)
    report = plan(
        source,
        discover_ceilings=("export=1", "generate=1"),
        required_workflows=requirements,
        max_evaluations=1000,
    )
    assert report["discovery"]["frontier_complete_within_domain"]
    assert not report["search"]["truncated_by_limit"]
    (candidate,) = report["candidates"]
    assert {e["after"]["amount"] for e in candidate["edits"]} == {"2"}
    selected = Mandate.parse(candidate["manifest"])
    assert selected.limits == source.limits and not analyse(selected).breaches
    assert all(a["failure"] is None for a in requirements.assess(selected, source.limits.depth))


@pytest.mark.parametrize("amount", ["1_0", "+0.01", " 0.01", "01", ".1", "1."])
def test_new_quantity_contract_rejects_lenient_decimal_spellings(amount):
    with pytest.raises(ManifestError, match="decimal literal"):
        Quantity.parse({"amount": amount, "unit": "record"}, "quantity")


def test_current_model_has_no_money_alias_or_old_manifest_reader(tmp_path, capsys):
    assert "Quantity" in agentmandate.__all__ and not hasattr(agentmandate, "Money")
    for raw in ({"version": 1}, {"limits": {"total": {"amount": 5, "currency": "GBP"}}}):
        old = {"agent": "old", "tools": [{"name": "read", "effect": "read"}], **raw}
        path = tmp_path / "old.json"
        path.write_text(json.dumps(old))
        assert main(["reach", str(path), "--json"]) == 2
        assert capsys.readouterr().out == ""
    with pytest.raises(ManifestError, match="unit"):
        Quantity.parse({"amount": 5, "currency": "GBP"}, "quantity")


def test_json_decimal_digits_are_preserved_before_quantity_validation():
    source = (
        '{"agent":"exact","tools":[{"name":"read","effect":"read"}],"limits":'
        '{"quantities":{"records":{"amount":0.10000000000000000000000001,"unit":"record"}}}}'
    )
    assert loads(source).limits.quantities["records"].amount == Decimal(
        "0.10000000000000000000000001"
    )


def test_budget_for_an_unused_pool_does_not_invent_reachable_authority():
    before = Mandate.parse({"agent": "read", "tools": [{"name": "read", "effect": "read"}]})
    after = replace(
        before,
        limits=replace(before.limits, quantities={"records": Quantity(Decimal(5), "record")}),
    )
    assert compare(before, after).direction == "narrowing"
    assert compare(after, before).widened


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), Decimal(-1), 1])
def test_programmatic_quantity_refuses_invalid_amounts(amount):
    with pytest.raises(ValueError, match="finite non-negative Decimal"):
        Quantity(amount, "record")


def test_signed_zero_has_a_loadable_unsigned_serialization():
    amount = Quantity(Decimal("-0.00"), "record")
    assert not amount.amount.is_signed()
    assert Quantity.parse({"amount": str(amount.amount), "unit": amount.unit}, "quantity") == amount


@pytest.mark.parametrize(
    "quantities", [None, [], {"records": None}, {0: Quantity(Decimal(1), "record")}]
)
def test_programmatic_budget_mappings_fail_at_the_model_boundary(quantities):
    source = model()
    with pytest.raises(ValueError, match="map nonblank names"):
        analyse(replace(source, limits=replace(source.limits, quantities=quantities)))


@pytest.mark.parametrize(
    "raw,message",
    [
        ({"quantities": []}, "expected a mapping"),
        ({"quantities": {"": {"amount": "1", "unit": "record"}}}, "non-empty"),
        ({"quantites": {}}, "unknown field"),
        (
            {"quantities": {"records": {"amount": "1", "unit": "record", "currency": "GBP"}}},
            "only amount and unit",
        ),
    ],
)
def test_malformed_named_budgets_are_not_silently_dropped(raw, message):
    with pytest.raises(ValueError, match=message):
        Mandate.parse(
            {"agent": "bad", "limits": raw, "tools": [{"name": "read", "effect": "read"}]}
        )


def test_programmatic_tool_cannot_name_a_pool_without_a_ceiling():
    source = model()
    with pytest.raises(ValueError, match="quantity requires a ceiling"):
        analyse(replace(source, tools=(replace(source.tools[0], quantity="records"),)))


def test_replay_numeric_exhaustion_is_a_typed_failure():
    from decimal import MAX_EMAX

    from agentmandate.verify import Observation

    source = model(cap=f"9e{MAX_EMAX}", budget=f"9e{MAX_EMAX}", unbounded=False)
    calls = [
        Observation(
            tool="export",
            principal="caller",
            scope="batch-1",
            quantity="records",
            unit="record",
            value=Decimal(f"9e{MAX_EMAX}"),
        )
    ] * 2
    with pytest.raises(ValueError, match="supported exact decimal arithmetic"):
        replay(source, calls)


def test_discovery_cannot_hide_a_breach_in_an_unselected_quantity():
    result = plan(model(), discover_ceilings=("export=1",), max_evaluations=1000)
    assert {b["kind"] for b in result["baseline"]["breaches"]} == {"quantity_budget"}
    assert result["discovery"]["frontier_complete_within_domain"]
    assert not result["candidates"]
    assert result["status"] == "no_feasible_candidate_in_declared_domain"


def test_parsed_tool_cannot_name_a_quantity_without_a_ceiling():
    with pytest.raises(ValueError, match="quantity requires value_arg and ceiling"):
        Mandate.parse(
            {"agent": "bad", "tools": [{"name": "read", "effect": "read", "quantity": "records"}]}
        )


@pytest.mark.parametrize("name", [" records", "records ", "records\nother"])
@pytest.mark.parametrize("location", ["budget", "tool", "programmatic"])
def test_quantity_names_have_the_same_trimmed_boundary_everywhere(name, location):
    source = model()
    if location == "programmatic":
        with pytest.raises(ValueError):
            analyse(
                replace(
                    source,
                    limits=replace(
                        source.limits, quantities={name: Quantity(Decimal(4), "record")}
                    ),
                )
            )
        return
    raw = {"agent": "names", "tools": [{"name": "read", "effect": "read"}]}
    if location == "budget":
        raw["limits"] = {"quantities": {name: {"amount": "4", "unit": "record"}}}
    else:
        raw["tools"] = [
            {
                "name": "pay",
                "effect": "read",
                "quantity": name,
                "value_arg": "records",
                "scope_key": "batch",
                "ceiling": {"amount": "3", "unit": "record"},
            }
        ]
    with pytest.raises(ValueError):
        Mandate.parse(raw)


@pytest.mark.parametrize(
    "subject,predicate,value,reason",
    [
        ("constraint:run", "quantities", [], "quantity_limits"),
        (
            "constraint:run",
            "quantities",
            {"": {"amount": "1", "unit": "record"}},
            "quantity_limits",
        ),
        ("constraint:run", "quantities", {"records": None}, "quantity_limits"),
        (
            "constraint:run",
            "quantities",
            {" records": {"amount": "1", "unit": "record"}},
            "quantity_limits",
        ),
        ("tool:export", "quantity", None, "quantity and ceiling"),
        ("tool:export", "quantity", " records ", "nullable_quantity_name"),
        ("tool:export", "ceiling", {"amount": "1_0", "unit": "record"}, "nullable_quantity"),
    ],
)
def test_ir_uses_the_manifest_quantity_boundary(subject, predicate, value, reason):
    from agentmandate._ir import IRFormatError

    graph = _from_mandate(model())
    facts = tuple(
        replace(f, value=value) if (f.subject, f.predicate) == (subject, predicate) else f
        for f in graph.facts
    )
    with pytest.raises(IRFormatError, match=reason):
        _to_mandate(replace(graph, facts=facts))


def test_structural_authority_reader_rejects_an_array_of_quantity_maxima():
    from agentmandate._result import validate_authority

    raw = analyse(model()).as_dict()
    raw["max_quantities"] = []
    with pytest.raises(ValueError, match="max_quantities must be an object"):
        validate_authority(
            raw, error_type=ValueError, result_name="test", whitespace_term="trimmed"
        )


def test_coarse_discovery_step_reports_its_domain_in_human_output(tmp_path, capsys):
    from agentmandate._remediation import _manifest

    path = tmp_path / "quantities.json"
    path.write_text(json.dumps(_manifest(model())))
    assert main(["remediate", str(path), "--discover-ceiling", "export=3"]) == 1
    text = capsys.readouterr().out
    assert "No candidate: the declared steps" in text and "finer steps may change" in text


def test_replay_refuses_currency_alias_and_checks_effect_call_budgets():
    with pytest.raises(ValueError, match="currency is unsupported"):
        parse_observations('{"tool":"read","currency":"GBP"}')
    source = Mandate.parse(
        {
            "agent": "calls",
            "limits": {"effects": {"read": 1}},
            "tools": [{"name": "read", "effect": "read"}],
        }
    )
    calls = parse_observations('{"tool":"read","principal":"caller"}\n' * 2)
    assert [v.kind for v in replay(source, calls).violations] == ["effect_budget_exceeded"]


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), Decimal(-1), 1])
def test_replay_programmatic_values_cannot_reduce_or_poison_a_pool(amount):
    from agentmandate.verify import Observation

    with pytest.raises(ValueError, match="observed quantity amounts"):
        replay(
            model(),
            [
                Observation(
                    tool="export",
                    principal="caller",
                    scope="b",
                    quantity="records",
                    unit="record",
                    value=amount,
                )
            ],
        )
