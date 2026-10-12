import copy
import hashlib
import json
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from itertools import combinations, product
from pathlib import Path

import pytest

from agentmandate import Mandate, analyse, load
from agentmandate._remediation import _grid_domain, plan
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]


def model(*, approved=True, total='5', ceiling='5', second=False):
    tools = [
        {'name': 'seed', 'effect': 'read', 'produces': 'item', 'unbounded': True},
        {'name': 'pay', 'effect': 'irreversible', 'requires': ['item'],
         'scope_key': 'item', 'value_arg': 'amount', 'requires_approval': approved,
         'ceiling': {'amount': ceiling, 'currency': 'GBP'}},
    ]
    if second:
        tools.append({**tools[1], 'name': 'other'})
    return Mandate.parse({'agent': 'grid-repair', 'tools': tools,
                          'limits': {'depth': 4 if not second else 3,
                                     'total': {'amount': total, 'currency': 'GBP'}}})


def signature(candidate):
    return frozenset((e['tool'], e['kind'],
                      None if 'after' not in e else Fraction(e['after']['amount']))
                     for e in candidate['edits'])


def test_refund_grid_finds_two_incomparable_repairs_without_changing_intent():
    source = load(ROOT / 'examples/dispute-resolver-v2.yaml')
    original = copy.deepcopy(source)
    result = plan(source, ceiling_grids=('issue_refund=0:200:25',), pareto=True)
    assert source == original
    assert result['schema'] == 'agentmandate.remediation/v4'
    assert result['baseline'] == analyse(source).as_dict()
    assert result['search']['candidates_found'] == 33
    assert result['search']['enumeration_complete']
    assert result['frontier']['candidates_considered'] == 33
    assert result['frontier']['non_dominated'] == 2
    assert result['frontier']['display_complete']
    assert [signature(c) for c in result['candidates']] == [
        frozenset({('issue_refund', 'tighten_ceiling', Fraction(125))}),
        frozenset({('search_cases', 'remove_tool', None)}),
    ]
    assert result['candidates'][0]['authority']['truncated']
    assert not result['candidates'][1]['authority']['truncated']
    for candidate in result['candidates']:
        changed = Mandate.parse(candidate['manifest'])
        assert changed.limits == source.limits
        assert analyse(changed).as_dict() == candidate['authority']


def test_exact_grid_ignores_decimal_context_and_does_not_invent_an_endpoint():
    source = model(total='0.6')
    with localcontext() as context:
        context.prec = 1
        context.traps[Inexact] = True
        saved = dict(context.flags)
        result = plan(source, keep_tools=source.tool_names,
                      ceiling_grids=('pay=0.1:0.36:0.1',), pareto=True)
        assert dict(context.flags) == saved and context.prec == 1
    assert [Fraction(o['ceiling']['amount']) for o in result['ceiling_options']] == [
        Fraction(1, 10), Fraction(2, 10), Fraction(3, 10),
    ]
    assert result['ceiling_grids'][0]['points_generated'] == 3
    assert Fraction(result['candidates'][0]['edits'][0]['after']['amount']) == Fraction(3, 10)


def test_overlapping_grids_and_explicit_options_share_a_deterministic_domain():
    source = model()
    grids = ('pay=0:2:1', 'pay=1:2:0.5')
    first = plan(source, ceiling_grids=grids, ceiling_options=('pay=2',), pareto=True)
    assert first == plan(source, ceiling_grids=tuple(reversed(grids)),
                         ceiling_options=('pay=2',), pareto=True)
    assert len(first['ceiling_options']) == 4
    assert sum(g['points_generated'] for g in first['ceiling_grids']) == 6


def test_grid_names_use_the_last_equals_and_large_finite_points_are_bounded():
    source = model(ceiling='1000')
    source = replace(source, tools=tuple(replace(t, name='pay=fee') if t.name == 'pay'
                                         else t for t in source.tools))
    options, records = _grid_domain(source, ('pay=fee=0:511:1',))
    assert len(options) == 512 and records[0]['points_generated'] == 512
    assert options[-1] == 'pay=fee=511'


@pytest.mark.parametrize('grid,message', [
    (None, 'TOOL=MIN'), (True, 'TOOL=MIN'), ('pay', 'TOOL=MIN'),
    ('=0:1:1', 'TOOL=MIN'), ('pay=0:1', 'TOOL=MIN'), ('pay=0:1:1:1', 'TOOL=MIN'),
    ('missing=0:1:1', 'declared spending tool'), ('seed=0:1:1', 'declared spending tool'),
    ('pay=-1:1:1', 'not be negative'), ('pay=0:NaN:1', 'finite'),
    ('pay=0:1:Infinity', 'finite'), ('pay=0:1:broken', 'not a number'),
    ('pay=0:1:0', 'STEP > 0'), ('pay=2:1:1', 'MIN <= MAX'),
    ('pay=0:5:1', 'strictly below'), ('pay=0:6:1', 'strictly below'),
    ('pay=0:1:1e-101', 'exponent'), ('pay=0:1:1e101', 'exponent'),
    ('pay=0:1:' + '1' * 101, '100 digits'),
    ('pay=0:1:' + '1' * 129, '128 characters'),
    ('pay=0:1:0.001', '512 points'),
])
def test_invalid_grid_fails_before_analysis(grid, message, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('invalid domain reached analysis')
    monkeypatch.setattr('agentmandate._remediation.analyse', unexpected)
    with pytest.raises(ValueError, match=message):
        plan(model(), ceiling_grids=(grid,))


def test_total_grid_limit_counts_duplicates_before_expanding_them():
    with pytest.raises(ValueError, match='512 points'):
        plan(model(ceiling='1000'), ceiling_grids=('pay=0:300:1', 'pay=0:300:1'))


def test_only_real_boolean_enables_frontier():
    with pytest.raises(ValueError, match='boolean'):
        plan(model(), pareto=1)


@pytest.mark.parametrize('approved,total,kept,second', list(product(
    [True, False], ['0', '3', '5'], [(), ('pay',)], [False, True],
)))
def test_frontier_matches_independent_exhaustive_manifest_and_vector_oracle(
    approved, total, kept, second,
):
    source = model(approved=approved, total=total, second=second)
    amounts = ('0', '1', '2')
    actions = [(t.name, 'remove_tool', None) for t in source.tools if t.name not in kept]
    actions += [(t.name, 'require_approval', None) for t in source.tools
                if t.effect == 'irreversible' and not t.requires_approval]
    actions += [(t.name, 'tighten_ceiling', a) for t in source.tools if t.ceiling
                for a in amounts]
    baseline = analyse(source)
    passing = []
    for count in (1, 2):
        for edits in combinations(actions, count):
            removed = {n for n, kind, _ in edits if kind == 'remove_tool'}
            gates = {n for n, kind, _ in edits if kind == 'require_approval'}
            caps = [(n, a) for n, kind, a in edits if kind == 'tighten_ceiling']
            if (len(dict(caps)) != len(caps) or removed & (gates | set(dict(caps)))
                    or len(removed) == len(source.tools)
                    or ('seed' in removed and len(removed) < len(source.tools))):
                continue
            tools = tuple(replace(t, requires_approval=t.requires_approval or t.name in gates,
                                  ceiling=replace(t.ceiling, amount=Decimal(dict(caps)[t.name]))
                                  if t.name in dict(caps) else t.ceiling)
                          for t in source.tools if t.name not in removed)
            changed = replace(source, tools=tools)
            authority = analyse(changed)
            if authority.breaches or set(kept) - authority.reachable_tools:
                continue
            # Independent vector representation: each named capability is its own axis.
            vector = (count, *(int(t.name in baseline.reachable_tools - authority.reachable_tools)
                               for t in source.tools),
                      *(int(t.name in gates) for t in source.tools),
                      *(-Fraction(changed.tool(t.name).ceiling.amount)
                        if changed.tool(t.name) else Fraction(0)
                        for t in source.tools if t.ceiling))
            passing.append((frozenset((n, k, None if a is None else Fraction(a))
                                      for n, k, a in edits), vector))
    expected = {edits for edits, v in passing if not any(
        all(a <= b for a, b in zip(w, v, strict=True))
        and any(a < b for a, b in zip(w, v, strict=True)) for _, w in passing
    )}
    report = plan(source, keep_tools=kept, pareto=True, max_candidates=200,
                  max_evaluations=1000,
                  ceiling_grids=tuple(f'{t.name}=0:2:1' for t in source.tools if t.ceiling))
    assert report['search']['enumeration_complete']
    assert report['search']['candidates_found'] == len(passing)
    assert {signature(c) for c in report['candidates']} == expected
    assert report['frontier']['non_dominated'] == len(expected)


def test_two_ceilings_remain_separate_trade_off_axes():
    source = model(second=True)
    result = plan(source, keep_tools=source.tool_names, max_candidates=20,
                  max_evaluations=200, ceiling_grids=('pay=1:4:1', 'other=1:4:1'), pareto=True)
    assert len(result['candidates']) == 4
    assert {(Fraction(c['repair_cost']['retained_ceilings']['pay']['amount']),
             Fraction(c['repair_cost']['retained_ceilings']['other']['amount']))
            for c in result['candidates']} == {(1, 4), (2, 3), (3, 2), (4, 1)}


def test_cutoffs_disclose_three_independent_limits():
    source = load(ROOT / 'examples/dispute-resolver-v2.yaml')
    args = {'ceiling_grids': ('issue_refund=0:200:25',), 'pareto': True}
    complete = plan(source, max_candidates=1, **args)
    assert complete['search']['enumeration_complete']
    assert not complete['frontier']['display_complete']
    assert complete['frontier']['non_dominated'] == 2 and len(complete['candidates']) == 1
    assert complete['candidates'][0]['authority']['truncated']
    limited = plan(source, max_evaluations=1, **args)
    assert not limited['search']['enumeration_complete']
    assert limited['frontier']['candidates_considered'] == 0
    assert limited['frontier']['non_dominated'] == 0
    assert limited['frontier']['display_complete']
    grid_only = plan(source, ceiling_grids=args['ceiling_grids'], max_candidates=1)
    assert not grid_only['frontier']['enabled'] and grid_only['frontier']['status'] == 'disabled'
    assert not grid_only['frontier']['display_complete']
    assert 'repair_cost' not in grid_only['candidates'][0]


@pytest.mark.parametrize('structural', [True, False])
def test_early_returns_do_not_claim_a_computed_frontier(structural):
    source = model(total='10')
    if structural:
        source = replace(source, tools=(source.tool('pay'),))
    report = plan(source, ceiling_grids=('pay=0:2:1',), pareto=True)
    assert report['schema'] == 'agentmandate.remediation/v4'
    assert report['frontier']['status'] == 'not_computed'
    assert report['frontier']['non_dominated'] is None
    assert report['search']['enumeration_complete'] is None
    assert not report['candidates'] and report['ceiling_options']


def test_required_paths_screen_zero_and_small_grid_choices_before_frontier():
    content = (ROOT / 'examples/dispute-resolver-v2.yaml').read_bytes()
    source = load(ROOT / 'examples/dispute-resolver-v2.yaml')
    requirements = _Requirements.load(
        (ROOT / 'examples/remediation/required-refund.json').read_bytes(), source,
        hashlib.sha256(content).hexdigest(),
    )
    result = plan(source, ceiling_grids=('issue_refund=0:200:25',), pareto=True,
                  required_workflows=requirements)
    assert result['schema'] == 'agentmandate.remediation/v4'
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['edits'][0]['after']['amount'] == '125'
    assert result['search']['required_workflow_rejections'] > 0
    assert result['requirements']['baseline'][0]['status'] == 'conformant_within_manifest_model'
    assert all(row['failure'] is None for row in result['candidates'][0]['required_workflows'])


def test_effect_budgets_cannot_be_excused_by_zero_grid_choices():
    source = model()
    source = replace(source, limits=replace(source.limits, effects={'irreversible': 0}))
    result = plan(source, keep_tools=source.tool_names, ceiling_grids=('pay=0:2:1',), pareto=True)
    assert not result['candidates']
    assert any(b['kind'] == 'effect_count' for b in result['baseline']['breaches'])


def test_pareto_without_ceilings_preserves_incomparable_named_tool_removals():
    result = plan(load(ROOT / 'examples/dispute-resolver-v2.yaml'), pareto=True)
    assert result['schema'] == 'agentmandate.remediation/v4' and not result['ceiling_grids']
    assert {c['edits'][0]['tool'] for c in result['candidates']} == {'search_cases', 'issue_refund'}
    assert 'ceiling_options' not in result


def test_cli_names_frontier_scope_and_keeps_the_original_breach_exit(capsys):
    assert main(['remediate', str(ROOT / 'examples/dispute-resolver-v2.yaml'),
                 '--ceiling-grid', 'issue_refund=0:200:25', '--pareto']) == 1
    output = capsys.readouterr()
    assert not output.err
    assert 'FRONTIER enabled=True status=computed non_dominated=2' in output.out
    assert 'among examined, rechecked candidates only' in output.out
    assert 'BREACH cumulative_value' in output.out and 'truncated=True' in output.out


@pytest.mark.parametrize('grid', ['pay=0:1:0', 'pay=0:1:0.001', 'broken'])
def test_cli_invalid_grids_are_usage_errors(grid, capsys):
    assert main(['remediate', str(ROOT / 'examples/remediation/ungated-refund.json'),
                 '--ceiling-grid', grid, '--json']) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith('error: ')


@pytest.mark.parametrize('fixture', ['refund', 'limited', 'required', 'clean'])
def test_v4_cli_fixtures_and_source_integrity(fixture, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    case = json.loads((ROOT / f'tests/fixtures/remediation-frontier-{fixture}-v4.json').read_text())
    original = (ROOT / case['argv'][1]).read_bytes()
    assert main(case['argv']) == case['exit']
    output = capsys.readouterr()
    assert output.out == json.dumps(case['result'], indent=2, sort_keys=True) + '\n'
    assert not output.err and (ROOT / case['argv'][1]).read_bytes() == original


def test_v3_to_v4_case_preserves_baseline_and_required_path_conformance():
    case = json.loads((ROOT / 'tests/fixtures/remediation-v3-to-v4.json').read_text())
    before = json.loads((ROOT / case['before']).read_text())
    after = json.loads((ROOT / case['after']).read_text())
    assert before['exit'] == after['exit'] == 1
    assert before['result']['schema'] == 'agentmandate.remediation/v3'
    assert after['result']['schema'] == 'agentmandate.remediation/v4'
    for field in case['preserved_fields']:
        assert before['result'][field] == after['result'][field]
