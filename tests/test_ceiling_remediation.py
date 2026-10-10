import copy
import hashlib
import json
from contextlib import redirect_stdout
from dataclasses import replace
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction
from io import StringIO
from itertools import combinations, product
from pathlib import Path

import pytest

from agentmandate import Mandate, analyse, load
from agentmandate._remediation import _changed, _Edit, plan
from agentmandate.cli import main
from agentmandate.verify import Observation, parse_observations, replay

ROOT = Path(__file__).resolve().parents[1]


def refund():
    return load(ROOT / 'examples/dispute-resolver-v2.yaml')


def model(*, approved=True, effect='irreversible', total='5', depth=4):
    return Mandate.parse({
        'agent': 'ceiling-repair', 'identity': 'synthetic-caller',
        'limits': {'depth': depth, 'total': {'amount': total, 'currency': 'GBP'}},
        'roles': {'operator': ['seed', 'pay']},
        'tools': [
            {'name': 'seed', 'effect': 'read', 'produces': 'item', 'unbounded': True},
            {'name': 'pay', 'effect': effect, 'requires': ['item'],
             'scope_key': 'item', 'value_arg': 'amount',
             'ceiling': {'amount': '5', 'currency': 'GBP'},
             'requires_approval': approved},
        ],
    })


def test_refund_ceiling_retains_search_and_refund_and_source_intent():
    source = refund()
    unchanged = copy.deepcopy(source)
    result = plan(source, keep_tools=source.tool_names,
                  ceiling_options=('issue_refund=250', 'issue_refund=100', 'issue_refund=125'))
    assert source == unchanged
    assert result['schema'] == 'agentmandate.remediation/v2'
    assert result['baseline'] == analyse(source).as_dict()
    assert result['baseline']['max_extractable']['amount'] == '2000'
    assert result['search']['combinations_total'] == 6
    assert result['search']['combinations_examined'] == 6
    assert result['search']['candidates_analyzed'] == 3  # Alternative ceilings cannot combine.
    assert result['search']['candidates_found'] == 2
    assert result['search']['enumeration_complete']
    assert [c['edits'][0]['after']['amount'] for c in result['candidates']] == ['125', '100']
    candidate = result['candidates'][0]
    assert candidate['edits'] == [{'tool': 'issue_refund', 'kind': 'tighten_ceiling',
                                  'before': {'amount': '500', 'currency': 'GBP'},
                                  'after': {'amount': '125', 'currency': 'GBP'}}]
    restored = Mandate.parse(candidate['manifest'])
    assert restored.limits == source.limits and restored.roles == source.roles
    assert candidate['authority'] == analyse(restored, depth=8).as_dict()
    assert candidate['authority']['max_extractable'] == {'amount': '500', 'currency': 'GBP'}
    assert candidate['impact']['lost_reachable_tools'] == []
    assert not candidate['lint'] and not candidate['authority']['breaches']
    assert candidate['authority']['truncated']
    # A concrete normal refund remains conformant; this is not an execution or business proof.
    calls = [Observation('search_cases', principal='caller'),
             Observation('issue_refund', scope='synthetic-case', value=Decimal(100),
                         currency='GBP', approved=True, principal='caller')]
    assert replay(restored, calls).conformant
    # Depth-scoped repair: a fifth fresh binding restores the breach at depth 10.
    assert any(b.kind == 'cumulative_value' for b in analyse(restored, depth=10).breaches)


def test_approval_and_ceiling_on_the_same_tool_are_joint_independent_edits():
    source = model(approved=False)
    alone = plan(source, max_edits=1, keep_tools=source.tool_names, ceiling_options=('pay=2',))
    assert not alone['candidates']
    result = plan(source, max_edits=2, keep_tools=source.tool_names, ceiling_options=('pay=2',))
    assert result['search']['candidates_found'] == 1
    candidate = result['candidates'][0]
    assert [e['kind'] for e in candidate['edits']] == ['require_approval', 'tighten_ceiling']
    assert candidate['impact']['edit_count'] == 2
    assert not candidate['authority']['breaches']
    assert Mandate.parse(candidate['manifest']).tool('pay').requires_approval
    assert result['baseline']['breaches'] and len(result['baseline']['breaches']) == 2


def test_ceiling_and_tool_removal_conflict_and_alternative_ceilings_do_not_stack():
    source = model()
    cap = _Edit('pay', 'tighten_ceiling', source.tool('pay').ceiling)
    assert _changed(source, (_Edit('pay', 'remove_tool'), cap)) is None
    assert _changed(source, (cap, cap)) is None
    assert _changed(source, (_Edit('pay', 'require_approval'), cap)) is not None


@pytest.mark.parametrize('effect', ['read', 'write', 'irreversible'])
def test_zero_ceiling_is_explicit_and_does_not_erase_effect_budget_breaches(effect):
    source = model(effect=effect)
    source = replace(source, limits=replace(source.limits, effects={effect: 0}))
    result = plan(source, keep_tools=source.tool_names, ceiling_options=('pay=0',))
    assert not result['candidates']
    assert any(b['kind'] == 'effect_count' for b in result['baseline']['breaches'])
    changed = _changed(source, (_Edit('pay', 'tighten_ceiling',
                                   replace(source.tool('pay').ceiling, amount=Decimal(0))),))
    authority = analyse(changed)
    assert any(b.kind == 'effect_count' for b in authority.breaches)
    assert not any(b.kind == 'cumulative_value' for b in authority.breaches)


def test_exact_fractional_and_high_precision_candidate_domain_and_ranking():
    source = model(total='0.6666666666666666666666666666')
    amounts = ('0.3333333333333333333333333333', '0.3333333333333333333333333334', '0.3')
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.traps[Inexact] = True
        saved = dict(ctx.flags)
        result = plan(source, keep_tools=source.tool_names,
                      ceiling_options=tuple(f'pay={a}' for a in amounts))
        assert ctx.prec == 2 and dict(ctx.flags) == saved and ctx.traps[Inexact]
    assert [c['edits'][0]['after']['amount'] for c in result['candidates']] == [amounts[0], '0.3']
    assert Fraction(result['candidates'][0]['authority']['max_extractable']['amount']) == (
        2 * Fraction(amounts[0])
    )


def test_numeric_duplicates_and_option_order_have_one_deterministic_domain():
    source = model()
    options = ('pay=2.00', 'pay=2', 'pay=2e0', 'pay=1')
    before = plan(source, ceiling_options=options, max_candidates=100)
    after = plan(source, ceiling_options=tuple(reversed(options)), max_candidates=100)
    assert before == after
    assert before['ceiling_options'] == [
        {'tool': 'pay', 'ceiling': {'amount': '1', 'currency': 'GBP'}},
        {'tool': 'pay', 'ceiling': {'amount': '2', 'currency': 'GBP'}},
    ]


def test_tool_names_with_equals_use_the_last_separator():
    source = model()
    source = replace(source, tools=tuple(replace(t, name='pay=fee') if t.name == 'pay'
                                         else t for t in source.tools), roles={})
    result = plan(source, ceiling_options=('pay=fee=2',), keep_tools=('pay=fee',))
    assert result['candidates'][0]['edits'][0]['tool'] == 'pay=fee'


@pytest.mark.parametrize('options,message', [
    ((None,), 'TOOL=AMOUNT'), ((True,), 'TOOL=AMOUNT'),
    (('pay',), 'TOOL=AMOUNT'), (('=2',), 'TOOL=AMOUNT'), (('pay=',), 'TOOL=AMOUNT'),
    (('absent=2',), 'declared spending tool'), (('seed=2',), 'declared spending tool'),
    (('pay=-1',), 'not be negative'), (('pay=NaN',), 'finite'),
    (('pay=Infinity',), 'finite'), (('pay=broken',), 'not a number'),
    (('pay=5',), 'strictly below'), (('pay=5.00',), 'strictly below'),
    (('pay=6',), 'strictly below'),
])
def test_invalid_domains_fail_before_reachability(options, message, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('invalid domain reached the analyzer')
    monkeypatch.setattr('agentmandate._remediation.analyse', unexpected)
    with pytest.raises(ValueError, match=message):
        plan(model(), ceiling_options=options)


def test_domain_is_retained_for_clean_or_structurally_unreviewed_baselines():
    source = model(total='10')
    result = plan(source, ceiling_options=('pay=2',))
    assert result['schema'] == 'agentmandate.remediation/v2'
    assert result['status'] == 'no_reachable_breach_within_bound'
    assert not result['candidates'] and result['ceiling_options']
    assert result['search']['enumeration_complete'] is None
    source = replace(source, tools=(source.tool('pay'),), roles={})
    result = plan(source, ceiling_options=('pay=2',))
    assert result['status'] == 'input_requires_review'
    assert not result['candidates'] and result['ceiling_options']


def test_cutoffs_include_rejected_ceiling_pairs_and_retained_tool_options():
    source = model()
    result = plan(source, keep_tools=source.tool_names, ceiling_options=('pay=1', 'pay=2'),
                  max_evaluations=1, max_candidates=1)
    assert result['search']['combinations_total'] == 3
    assert result['search']['combinations_examined'] == 1
    assert not result['search']['enumeration_complete']
    assert result['candidates'][0]['edits'][0]['after']['amount'] == '1'
    complete = plan(source, keep_tools=source.tool_names, ceiling_options=('pay=1', 'pay=2'),
                    max_candidates=1)
    assert complete['search']['enumeration_complete']
    assert complete['search']['candidates_found'] == 2
    assert len(complete['candidates']) == 1
    assert complete['candidates'][0]['edits'][0]['after']['amount'] == '2'


@pytest.mark.parametrize('approved,total,kept', list(product([False, True], ['0', '3', '5'],
                                                       [(), ('pay',), ('seed', 'pay')])))
def test_candidates_equal_an_exhaustive_edit_oracle_with_independent_mutation(
    approved, total, kept,
):
    source = model(approved=approved, total=total)
    # This oracle constructs manifests itself; it does not use _Edit, _changed or plan helpers.
    actions = [(t.name, 'remove_tool', None) for t in source.tools if t.name not in kept]
    if not approved:
        actions.append(('pay', 'require_approval', None))
    actions += [('pay', 'tighten_ceiling', a) for a in ('0', '1', '2')]
    expected = set()
    for count in (1, 2):
        for edits in combinations(actions, count):
            removed = {name for name, kind, _ in edits if kind == 'remove_tool'}
            gates = {name for name, kind, _ in edits if kind == 'require_approval'}
            ceilings = [(name, amount) for name, kind, amount in edits if kind == 'tighten_ceiling']
            if (len({n for n, _ in ceilings}) < len(ceilings)
                    or removed & (gates | {n for n, _ in ceilings}) or len(removed) == 2
                    or ('seed' in removed and 'pay' not in removed)):
                continue
            caps = dict(ceilings)
            tools = tuple(replace(t, requires_approval=t.requires_approval or t.name in gates,
                                  ceiling=replace(t.ceiling, amount=Decimal(caps[t.name]))
                                  if t.name in caps else t.ceiling)
                          for t in source.tools if t.name not in removed)
            authority = analyse(replace(source, tools=tools, roles={}))
            if not authority.breaches and not set(kept) - authority.reachable_tools:
                expected.add(frozenset(edits))
    report = plan(source, keep_tools=kept, ceiling_options=('pay=0', 'pay=1', 'pay=2'),
                  max_candidates=100, max_evaluations=100)
    actual = {frozenset((e['tool'], e['kind'], e.get('after', {}).get('amount'))
                       for e in c['edits']) for c in report['candidates']}
    assert actual == expected and report['search']['enumeration_complete']
    for candidate in report['candidates']:
        restored = Mandate.parse(candidate['manifest'])
        assert restored.limits == source.limits
        assert analyse(restored).as_dict() == candidate['authority']


@pytest.mark.parametrize('option', ['bad', 'issue_refund=500', 'issue_refund=nan', 'missing=0'])
def test_cli_invalid_ceiling_options_are_usage_errors_without_output(option, capsys):
    assert main(['remediate', str(ROOT / 'examples/dispute-resolver-v2.yaml'),
                 '--ceiling', option, '--json']) == 2
    output = capsys.readouterr()
    assert not output.out and output.err.startswith('error: ')


def test_cli_text_names_amounts_and_keeps_baseline_findings(capsys):
    args = ['remediate', str(ROOT / 'examples/dispute-resolver-v2.yaml'),
            '--keep-tool', 'issue_refund', '--keep-tool', 'search_cases',
            '--ceiling', 'issue_refund=125']
    assert main(args) == 1
    text = capsys.readouterr().out
    assert 'CEILING OPTION issue_refund: 125 GBP' in text
    assert 'tighten_ceiling issue_refund 500 -> 125 GBP' in text
    assert 'BREACH cumulative_value' in text and 'truncated=True' in text
    assert 'lost reachable tools=[]' in text


@pytest.mark.parametrize('fixture', ['kept', 'joint', 'limited', 'clean'])
def test_v2_cli_baselines_and_source_digests(fixture, capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    case = json.loads((ROOT / f'tests/fixtures/remediation-ceiling-{fixture}-v2.json').read_text())
    before = (ROOT / case['argv'][1]).read_bytes()
    assert main(case['argv']) == case['exit']
    output = capsys.readouterr()
    assert not output.err and json.loads(output.out) == case['result']
    assert (ROOT / case['argv'][1]).read_bytes() == before
    assert case['result']['input']['manifest_sha256'] == hashlib.sha256(before).hexdigest()


def test_no_ceiling_flags_preserve_every_legacy_result_byte(monkeypatch):
    monkeypatch.chdir(ROOT)
    for name in ('breached', 'kept', 'limited', 'clean'):
        case = json.loads((ROOT / f'tests/fixtures/remediation-{name}-v1.json').read_text())
        stream = StringIO()
        with redirect_stdout(stream):
            assert main(case['argv']) == case['exit']
        assert stream.getvalue() == json.dumps(case['result'], indent=2, sort_keys=True) + '\n'


def test_explicit_v1_to_v2_compatibility_case_preserves_existing_candidate_semantics():
    migration = json.loads((ROOT / 'tests/fixtures/remediation-v1-to-v2.json').read_text())
    before = json.loads((ROOT / migration['before']).read_text())
    after = json.loads((ROOT / migration['after']).read_text())
    assert before['exit'] == after['exit'] == 1
    assert before['result']['schema'] == 'agentmandate.remediation/v1'
    assert after['result']['schema'] == 'agentmandate.remediation/v2'
    for field in migration['preserved_fields']:
        assert before['result'][field] == after['result'][field]
    retained = [c for c in after['result']['candidates']
                if all(e['kind'] != migration['added_edit_kind'] for e in c['edits'])]
    assert retained and all(c in before['result']['candidates'] for c in retained)
    complete = plan(refund(), keep_tools=tuple(before['result']['keep_tools']),
                    ceiling_options=('issue_refund=125',), max_candidates=100)
    assert [c for c in complete['candidates'] if all(
        e['kind'] != migration['added_edit_kind'] for e in c['edits']
    )] == before['result']['candidates']
    assert after['argv'] == [*before['argv'], '--ceiling', 'issue_refund=125']


def test_documented_synthetic_joint_candidate_preserves_only_supplied_trace_conformance():
    source = load(ROOT / 'examples/remediation/ungated-refund.json')
    result = plan(source, keep_tools=source.tool_names, ceiling_options=('pay=2',))
    candidate = Mandate.parse(result['candidates'][0]['manifest'])
    observations = parse_observations(
        (ROOT / 'examples/remediation/normal-refund.jsonl').read_text()
    )
    assert replay(candidate, observations).conformant
    assert not replay(candidate, [replace(o, approved=False) for o in observations]).conformant
    assert not replay(candidate, [replace(o, value=Decimal(2)) if o.value is not None
                                  else o for o in observations]).conformant


def test_retained_value_handles_compact_extreme_exponents_without_expanding_integers():
    from decimal import MAX_EMAX
    source = model(depth=2, total=f'1e{MAX_EMAX}')
    source = replace(source, tools=tuple(
        replace(t, unbounded=False) if t.name == 'seed'
        else replace(t, ceiling=replace(t.ceiling, amount=Decimal(f'9e{MAX_EMAX}')))
        for t in source.tools
    ))
    result = plan(source, keep_tools=source.tool_names, ceiling_options=(f'pay=1e{MAX_EMAX}',))
    assert len(result['candidates']) == 1
    assert Decimal(result['candidates'][0]['authority']['max_extractable']['amount']) == (
        Decimal(f'1e{MAX_EMAX}')
    )


def test_retained_value_handles_coefficients_above_pythons_integer_string_limit():
    source = model(total='5' + '0' * 5000)
    source = replace(source, tools=tuple(
        replace(t, ceiling=replace(t.ceiling, amount=Decimal('5' + '0' * 5000)))
        if t.name == 'pay' else t for t in source.tools
    ))
    result = plan(source, keep_tools=source.tool_names,
                  ceiling_options=('pay=1' + '0' * 5000, 'pay=2' + '0' * 5000))
    assert len(result['candidates']) == 2
    assert result['candidates'][0]['edits'][0]['after']['amount'] == '2' + '0' * 5000


def test_ceiling_search_can_still_report_a_nonmonetary_removal_candidate():
    source = model(approved=False)
    source = replace(source, limits=replace(source.limits, total=None))
    result = plan(source, ceiling_options=('pay=2',), max_candidates=100)
    removal = next(c for c in result['candidates'] if c['edits'] == [
        {'tool': 'pay', 'kind': 'remove_tool'},
    ])
    assert removal['authority']['max_extractable'] is None


def test_two_spending_tools_need_joint_ceilings_without_relaxing_the_total():
    source = model(depth=3, total='4')
    pay = source.tool('pay')
    source = replace(source, tools=(replace(source.tool('seed'), unbounded=False), pay,
                                    replace(pay, name='pay_other')))
    assert not plan(source, keep_tools=source.tool_names, max_edits=1,
                    ceiling_options=('pay=2', 'pay_other=2'))['candidates']
    result = plan(source, keep_tools=source.tool_names,
                  ceiling_options=('pay=2', 'pay_other=2'))
    assert len(result['candidates']) == 1
    candidate = result['candidates'][0]
    assert [e['tool'] for e in candidate['edits']] == ['pay', 'pay_other']
    assert candidate['authority']['max_extractable'] == {'amount': '4', 'currency': 'GBP'}
    assert Mandate.parse(candidate['manifest']).limits == source.limits


def test_mixed_currency_input_retains_its_structural_error_and_generates_no_repairs():
    source = model()
    source = replace(source, tools=tuple(replace(t, ceiling=replace(t.ceiling, currency='USD'))
                                         if t.name == 'pay' else t for t in source.tools))
    result = plan(source, ceiling_options=('pay=2',))
    assert result['status'] == 'input_requires_review' and not result['candidates']
    assert result['ceiling_options'][0]['ceiling']['currency'] == 'USD'
    assert any(f['rule'] == 'ceiling.mixed-currency' for f in result['baseline_lint'])


def test_candidate_arithmetic_exhaustion_leaves_no_partial_cli_report(tmp_path, capsys):
    from decimal import MAX_EMAX
    source = {
        'agent': 'extreme-domain', 'limits': {'depth': 2,
                                           'total': {'amount': '1', 'currency': 'GBP'}},
        'tools': [{'name': 'seed', 'effect': 'read', 'produces': 'case'}] + [
            {'name': name, 'effect': 'irreversible', 'requires': ['case'],
             'scope_key': 'case', 'value_arg': 'amount', 'requires_approval': True,
             'ceiling': {'amount': f'1e{MAX_EMAX}', 'currency': 'GBP'}}
            for name in ('pay', 'pay_other')
        ],
    }
    path = tmp_path / 'extreme.json'
    path.write_text(json.dumps(source))
    assert main(['remediate', str(path), '--keep-tool', 'seed', '--keep-tool', 'pay',
                 '--keep-tool', 'pay_other', '--ceiling', f'pay=1e{-MAX_EMAX}', '--json']) == 2
    output = capsys.readouterr()
    assert not output.out and 'supported exact decimal arithmetic' in output.err
