import copy
import hashlib
import json
from dataclasses import replace
from decimal import MAX_EMAX, ROUND_DOWN, Decimal, Inexact, localcontext
from itertools import product
from pathlib import Path

import pytest

from agentmandate import Mandate, load
from agentmandate._remediation import plan
from agentmandate._required_workflows import _assessment, _Call, _Requirements, _Workflow
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]


def call(tool, *, value=None, binding=0, approved=True, principal="caller"):
    raw = {"tool": tool, "principal": principal, "approved": approved}
    if value is not None:
        raw.update(value=str(value), currency="GBP", binding=binding)
    return raw


def profile(source, steps=None, *, digest="a" * 64):
    return {
        "schema": "agentmandate.required-workflows/v1",
        "agent": source.agent,
        "manifest_sha256": digest,
        "reviewer": "synthetic-reviewer",
        "reason": "Retain the explicitly supplied normal refund path in this model.",
        "workflows": [
            {
                "name": "normal-refund",
                "steps": steps
                or [
                    call("search_cases"),
                    call("issue_refund", value="100"),
                ],
            }
        ],
    }


def requirements(source, steps=None):
    raw = profile(source, steps)
    return _Requirements.load(json.dumps(raw).encode(), source, raw["manifest_sha256"])


def refund():
    return load(ROOT / "examples/dispute-resolver-v2.yaml")


def small(*, unbounded=True, total=5, budget=None, approved=True):
    return Mandate.parse(
        {
            "agent": "required-path",
            "limits": {
                "depth": 4,
                "total": {"amount": str(total), "currency": "GBP"},
                "effects": {} if budget is None else {"irreversible": budget},
            },
            "tools": [
                {"name": "seed", "effect": "read", "produces": "item", "unbounded": unbounded},
                {"name": "inspect", "effect": "read"},
                {
                    "name": "pay",
                    "effect": "irreversible",
                    "requires": ["item"],
                    "scope_key": "item",
                    "value_arg": "amount",
                    "requires_approval": approved,
                    "ceiling": {"amount": "3", "currency": "GBP"},
                },
            ],
        }
    )


def test_required_refund_rejects_zero_or_insufficient_ceilings_with_tools_still_reachable():
    source = refund()
    original = copy.deepcopy(source)
    required = requirements(source)
    unconstrained = plan(
        source, keep_tools=source.tool_names, ceiling_options=("issue_refund=0", "issue_refund=50")
    )
    assert len(unconstrained["candidates"]) == 2
    constrained = plan(
        source,
        keep_tools=source.tool_names,
        required_workflows=required,
        ceiling_options=("issue_refund=0", "issue_refund=50", "issue_refund=125"),
    )
    assert source == original
    assert constrained["schema"] == "agentmandate.remediation/v3"
    assert constrained["baseline"] == unconstrained["baseline"]
    assert constrained["search"]["required_workflow_rejections"] == 2
    assert constrained["search"]["candidates_analyzed"] == 1
    assert constrained["search"]["candidates_found"] == 1
    candidate = constrained["candidates"][0]
    assert candidate["edits"][0]["after"]["amount"] == "125"
    assert candidate["required_workflows"] == constrained["requirements"]["baseline"]
    assert all(
        r["assessments"][0]["failure"]["rule"] == "workflow.ceiling-exceeded"
        for r in constrained["requirement_rejections"]
    )
    assert all(
        r["stage"] == "required_workflow_screen" for r in constrained["requirement_rejections"]
    )
    assert candidate["authority"]["truncated"] and constrained["baseline"]["breaches"]
    assert constrained["requirements"]["scope"].startswith("caller-supplied annotations;")


def test_requirements_reject_removal_of_a_needed_tool_without_keep_flags():
    source = refund()
    result = plan(source, required_workflows=requirements(source), max_candidates=100)
    assert not result["candidates"]
    failures = [
        a["failure"]["rule"]
        for r in result["requirement_rejections"]
        for a in r["assessments"]
        if a["failure"]
    ]
    assert failures and set(failures) == {"workflow.undeclared-tool"}


def test_adding_approval_cannot_claim_to_preserve_an_unapproved_required_path():
    source = small(approved=False)
    path = [call("seed"), call("pay", value=1, approved=False)]
    result = plan(
        source,
        required_workflows=requirements(source, path),
        ceiling_options=("pay=1",),
        max_candidates=100,
    )
    assert not result["candidates"]
    assert any(
        a["failure"] and a["failure"]["rule"] == "workflow.approval-missing"
        for r in result["requirement_rejections"]
        for a in r["assessments"]
    )
    approved = plan(
        source,
        required_workflows=requirements(
            source,
            [
                call("seed"),
                call("pay", value=1),
            ],
        ),
        ceiling_options=("pay=1",),
        max_candidates=100,
    )
    assert any(
        {e["kind"] for e in c["edits"]} == {"require_approval", "tighten_ceiling"}
        for c in approved["candidates"]
    )


@pytest.mark.parametrize(
    "steps,rule",
    [
        ([call("absent")], "workflow.undeclared-tool"),
        ([call("pay", value=1)], "workflow.scope-unavailable"),
        ([call("seed", principal="service")], "workflow.principal-mismatch"),
        ([call("seed"), call("pay", value=1, approved=False)], "workflow.approval-missing"),
        ([call("inspect", value=0)], "workflow.unexpected-spend"),
        ([call("seed"), call("pay")], "workflow.spend-missing"),
        ([call("seed"), call("pay", value=1, binding=1)], "workflow.binding-unavailable"),
        ([call("seed"), call("pay", value=2), call("pay", value=2)], "workflow.ceiling-exceeded"),
        ([call("inspect")] * 5, "workflow.depth-exceeded"),
    ],
)
def test_invalid_baseline_paths_report_exact_failure_and_are_not_ignored(steps, rule):
    source = small()
    required = requirements(source, steps)
    result = required.assess(source, 4)
    assert result[0]["status"] == "not_conformant_within_manifest_model"
    assert result[0]["failure"]["rule"] == rule
    with pytest.raises(ValueError, match=rule):
        plan(source, required_workflows=required)


def test_money_fields_require_a_binding_even_when_amount_is_zero():
    source = small()
    path = [call("seed"), call("pay", value=0)]
    path[1].pop("binding")
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.spend-missing"
    )


def test_nonspending_calls_cannot_select_a_monetary_binding():
    source = small()
    path = [call("inspect")]
    path[0]["binding"] = 0
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.unexpected-spend"
    )


def test_workflow_spend_accounts_are_per_tool_and_binding_not_shared_scope():
    source = small(total=6)
    source = replace(source, tools=source.tools + (replace(source.tool("pay"), name="pay_other"),))
    path = [call("seed"), call("pay", value=3), call("pay_other", value=3)]
    assert requirements(source, path).assess(source, 4)[0]["failure"] is None
    source = replace(
        source,
        limits=replace(
            source.limits,
            total=replace(
                source.limits.total,
                amount=Decimal(5),
            ),
        ),
    )
    assert (
        requirements(source, path).assess(source, 4)[0]["failure"]["rule"]
        == "workflow.total-exceeded"
    )


def test_bounded_producer_repeated_calls_do_not_create_an_extra_binding():
    path = [call("seed"), call("seed"), call("pay", value=1, binding=1)]
    assert requirements(small(), path).assess(small(), 4)[0]["failure"] is None
    source = small(unbounded=False)
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.binding-unavailable"
    )


def test_self_producing_spender_mints_before_its_monetary_binding_selection():
    source = small()
    source = replace(source, tools=(replace(source.tool("pay"), requires=(), produces="item"),))
    assert requirements(source, [call("pay", value=2)]).assess(source, 4)[0]["failure"] is None
    path = [call("pay", value=2), call("pay", value=2, binding=1)]
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.binding-unavailable"
    )


@pytest.mark.parametrize("currency_change", ["call", "total"])
def test_currency_mismatch_is_a_baseline_failure(currency_change):
    source = small()
    path = [call("seed"), call("pay", value=1)]
    if currency_change == "call":
        path[-1]["currency"] = "USD"
    else:
        source = replace(
            source,
            limits=replace(
                source.limits,
                total=replace(
                    source.limits.total,
                    currency="USD",
                ),
            ),
        )
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.currency-mismatch"
    )


def test_zero_spend_and_exhausted_headroom_calls_still_count_against_effect_budget():
    source = small(budget=1)
    path = [call("seed"), call("pay", value=3), call("pay", value=0)]
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.effect-budget-exceeded"
    )
    source = replace(source, limits=replace(source.limits, effects={"read": 0}))
    assert requirements(source, [call("inspect")]).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.effect-budget-exceeded"
    )


def test_all_scope_requirements_must_precede_the_call():
    source = small()
    source = replace(
        source,
        tools=source.tools + (replace(source.tool("seed"), name="seed_other", produces="other"),),
    )
    source = replace(
        source,
        tools=tuple(
            replace(t, requires=("item", "other")) if t.name == "pay" else t for t in source.tools
        ),
    )
    path = [call("seed"), call("pay", value=1)]
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.scope-unavailable"
    )
    path.insert(1, call("seed_other"))
    assert requirements(source, path).assess(source, 4)[0]["failure"] is None


def test_no_total_limit_still_preserves_per_binding_constraints():
    source = small()
    source = replace(source, limits=replace(source.limits, total=None))
    path = [call("seed"), call("pay", value=2), call("seed"), call("pay", value=2, binding=1)]
    assert requirements(source, path).assess(source, 4)[0]["failure"] is None


@pytest.mark.parametrize(
    "level,field,value,message",
    [
        ("top", "extra", 1, "unsupported fields"),
        ("top", "schema", "other", "unsupported"),
        ("top", "manifest_sha256", "bad", "lowercase SHA-256"),
        ("top", "manifest_sha256", "b" * 64, "exact baseline"),
        ("top", "manifest_sha256", "A" * 64, "lowercase SHA-256"),
        ("top", "agent", "different", "exact baseline"),
        ("top", "reviewer", "", "nonblank"),
        ("top", "reason", " \t", "nonblank"),
        ("top", "reviewer", "name\nother", "nonblank"),
        ("top", "agent", 5, "nonblank"),
        ("top", "workflows", [], "at least one"),
        ("top", "workflows", {}, "at least one"),
        ("workflow", "steps", [], "nonempty"),
        ("workflow", "steps", {}, "nonempty"),
        ("workflow", "name", "", "nonblank"),
        ("workflow", "extra", True, "unsupported"),
        ("step", "tool", "", "nonblank"),
        ("step", "principal", None, "nonblank"),
        ("step", "approved", 1, "true or false"),
        ("step", "approved", "yes", "true or false"),
        ("step", "binding", True, "nonnegative integer"),
        ("step", "binding", -1, "nonnegative integer"),
        ("step", "binding", 0.5, "nonnegative integer"),
        ("step", "value", 100, "string with a currency"),
        ("step", "value", "NaN", "finite"),
        ("step", "value", "-1", "negative"),
        ("step", "value", "bad", "number"),
        ("step", "currency", "LONG", "three-letter"),
        ("step", "extra", False, "unsupported"),
    ],
)
def test_strict_requirements_reader_refuses_ambiguous_annotations(level, field, value, message):
    source = refund()
    raw = profile(source)
    row = (
        raw
        if level == "top"
        else raw["workflows"][0]
        if level == "workflow"
        else (raw["workflows"][0]["steps"][1])
    )
    row[field] = value
    with pytest.raises(ValueError, match=message):
        _Requirements.load(json.dumps(raw).encode(), source, "a" * 64)


@pytest.mark.parametrize("level", ["top", "workflow", "step"])
def test_required_fields_cannot_be_omitted(level):
    source = refund()
    raw = profile(source)
    row = (
        raw
        if level == "top"
        else raw["workflows"][0]
        if level == "workflow"
        else (raw["workflows"][0]["steps"][0])
    )
    row.pop(next(iter(row)))
    with pytest.raises(ValueError, match="missing required fields"):
        _Requirements.load(json.dumps(raw).encode(), source, "a" * 64)


@pytest.mark.parametrize("level", ["top", "workflow", "step"])
def test_objects_cannot_be_replaced_by_arrays(level):
    source = refund()
    raw = profile(source)
    if level == "top":
        raw = []
    elif level == "workflow":
        raw["workflows"][0] = []
    else:
        raw["workflows"][0]["steps"][0] = []
    with pytest.raises(ValueError, match="unsupported fields or shape"):
        _Requirements.load(json.dumps(raw).encode(), source, "a" * 64)


def test_duplicate_keys_and_workflow_names_are_refused():
    source = refund()
    with pytest.raises(ValueError, match="duplicate required-workflow field"):
        _Requirements.load(b'{"schema":1,"schema":2}', source, "a" * 64)
    raw = profile(source)
    raw["workflows"] *= 2
    with pytest.raises(ValueError, match="names must be unique"):
        _Requirements.load(json.dumps(raw).encode(), source, "a" * 64)


def test_value_and_currency_must_be_paired():
    source = refund()
    raw = profile(source)
    raw["workflows"][0]["steps"][1].pop("currency")
    with pytest.raises(ValueError, match="string with a currency"):
        _Requirements.load(json.dumps(raw).encode(), source, "a" * 64)


def test_every_workflow_is_required_and_assessments_stay_separate():
    source = refund()
    raw = profile(source)
    raw["workflows"].append(
        {
            "name": "larger-refund",
            "steps": [
                call("search_cases"),
                call("issue_refund", value=150),
            ],
        }
    )
    required = _Requirements.load(json.dumps(raw).encode(), source, raw["manifest_sha256"])
    result = plan(
        source,
        keep_tools=source.tool_names,
        required_workflows=required,
        ceiling_options=("issue_refund=125",),
    )
    assert not result["candidates"]
    assessed = result["requirement_rejections"][0]["assessments"]
    assert assessed[0]["failure"] is None and assessed[1]["failure"]["rule"] == (
        "workflow.ceiling-exceeded"
    )


def test_requirement_screen_and_enumeration_cutoffs_are_disclosed():
    source = refund()
    result = plan(
        source,
        keep_tools=source.tool_names,
        required_workflows=requirements(source),
        ceiling_options=("issue_refund=0", "issue_refund=125"),
        max_evaluations=1,
    )
    assert result["status"] == "no_candidate_found_within_limits"
    assert result["search"]["combinations_examined"] == 1
    assert not result["search"]["enumeration_complete"]
    assert result["search"]["required_workflow_rejections"] == 1
    assert result["search"]["candidates_analyzed"] == 0


def test_partial_amount_paths_do_not_inherit_caller_rounding_or_traps():
    source = small(total="0.3000000000000000000000000001")
    path = [
        call("seed"),
        call("pay", value="0.1000000000000000000000000001"),
        call("pay", value="0.2"),
    ]
    required = requirements(source, path)
    with localcontext() as ctx:
        ctx.prec = 2
        ctx.rounding = ROUND_DOWN
        ctx.traps[Inexact] = True
        saved = (dict(ctx.flags), dict(ctx.traps), ctx.prec, ctx.rounding)
        assert required.assess(source, 4)[0]["failure"] is None
        assert saved == (dict(ctx.flags), dict(ctx.traps), ctx.prec, ctx.rounding)
    path[-1]["value"] = "0.2000000000000000000000000001"
    assert requirements(source, path).assess(source, 4)[0]["failure"]["rule"] == (
        "workflow.total-exceeded"
    )


@pytest.mark.parametrize("failure", ["precision", "overflow"])
def test_required_workflow_arithmetic_exhaustion_fails_closed(failure):
    source = small(total=f"9e{MAX_EMAX}")
    source = replace(
        source,
        tools=tuple(
            replace(
                t,
                ceiling=replace(
                    t.ceiling,
                    amount=Decimal(f"9e{MAX_EMAX}"),
                ),
            )
            if t.name == "pay"
            else t
            for t in source.tools
        ),
    )
    values = [f"1e{-MAX_EMAX}"] if failure == "precision" else [f"9e{MAX_EMAX}"] * 2
    path = [call("seed")] + [call("pay", value=value) for value in values]
    with pytest.raises(ValueError, match="supported exact decimal arithmetic"):
        requirements(source, path).assess(source, 4)


def test_ordered_path_checks_match_an_independent_integer_reference():
    source = small(budget=2)
    choices = [call("seed"), call("inspect")] + [
        call("pay", value=value, binding=binding)
        for value, binding in [(0, 0), (1, 0), (3, 0), (4, 0), (1, 1), (3, 1)]
    ]
    for length in range(1, 5):
        for rows in product(choices, repeat=length):
            held = 0
            used = [0, 0, 0, 0]
            total = calls = 0
            valid = True
            for row in rows:
                if row["tool"] == "seed":
                    held += 1
                elif row["tool"] == "pay":
                    if row["binding"] >= held:
                        valid = False
                        break
                    calls += 1
                    used[row["binding"]] += int(row["value"])
                    total += int(row["value"])
                    if calls > 2 or used[row["binding"]] > 3 or total > 5:
                        valid = False
                        break
            workflow = _Workflow("enumerated-path", tuple(_Call.parse(row) for row in rows))
            assessment = _assessment(source, workflow, 4)
            assert (assessment["failure"] is None) == valid, rows


@pytest.mark.parametrize("bad", ["missing", "json", "utf8", "join", "path"])
def test_cli_bad_requirements_fail_with_empty_stdout(bad, tmp_path, capsys):
    path = tmp_path / "requirements.json"
    source = refund()
    content = (ROOT / "examples/dispute-resolver-v2.yaml").read_bytes()
    raw = profile(source, digest=hashlib.sha256(content).hexdigest())
    if bad == "json":
        path.write_bytes(b"{bad")
    elif bad == "utf8":
        path.write_bytes(b"\xff")
    elif bad != "missing":
        if bad == "join":
            raw["manifest_sha256"] = "0" * 64
        else:
            raw["workflows"][0]["steps"].reverse()
        path.write_text(json.dumps(raw))
    assert (
        main(
            [
                "remediate",
                str(ROOT / "examples/dispute-resolver-v2.yaml"),
                "--required-workflows",
                str(path),
                "--json",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")


@pytest.mark.parametrize("fixture", ["monetary", "joint", "limited", "clean"])
def test_v3_cli_fixtures_and_required_source_digest(fixture, capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    case = json.loads((ROOT / f"tests/fixtures/remediation-workflow-{fixture}-v3.json").read_text())
    assert main(case["argv"]) == case["exit"]
    output = capsys.readouterr()
    assert not output.err and json.loads(output.out) == case["result"]
    requirements_path = case["argv"][case["argv"].index("--required-workflows") + 1]
    assert (
        case["result"]["requirements"]["source_sha256"]
        == hashlib.sha256((ROOT / requirements_path).read_bytes()).hexdigest()
    )


def test_cli_text_names_conformant_paths_and_rejection_reasons(capsys):
    assert (
        main(
            [
                "remediate",
                str(ROOT / "examples/dispute-resolver-v2.yaml"),
                "--keep-tool",
                "search_cases",
                "--keep-tool",
                "issue_refund",
                "--required-workflows",
                str(ROOT / "examples/remediation/required-refund.json"),
                "--ceiling",
                "issue_refund=0",
                "--ceiling",
                "issue_refund=125",
            ]
        )
        == 1
    )
    text = capsys.readouterr().out
    assert "caller-supplied annotations; manifest-v1 model only" in text
    assert "REQUIRED normal-refund: conformant_within_manifest_model" in text
    assert "REJECTED normal-refund: workflow.ceiling-exceeded at step 2" in text
    assert "BREACH cumulative_value" in text


def test_opt_in_v2_to_v3_case_preserves_the_baseline_and_surviving_candidates():
    migration = json.loads((ROOT / "tests/fixtures/remediation-v2-to-v3.json").read_text())
    before = json.loads((ROOT / migration["before"]).read_text())
    after = json.loads((ROOT / migration["after"]).read_text())
    assert before["exit"] == after["exit"] == 1
    assert before["result"]["schema"] == "agentmandate.remediation/v2"
    assert after["result"]["schema"] == "agentmandate.remediation/v3"
    for field in migration["preserved_fields"]:
        assert before["result"][field] == after["result"][field]
    for candidate in after["result"]["candidates"]:
        candidate = copy.deepcopy(candidate)
        assessments = candidate.pop("required_workflows")
        assert all(row["failure"] is None for row in assessments)
        assert candidate in before["result"]["candidates"]
    assert after["result"]["search"]["required_workflow_rejections"] > 0


def test_compatibility_v3_case_is_executed_not_just_a_snapshot(capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    case = json.loads(
        (ROOT / "tests/fixtures/remediation-workflow-compatibility-v3.json").read_text()
    )
    assert main(case["argv"]) == case["exit"]
    assert json.loads(capsys.readouterr().out) == case["result"]


def test_required_workflow_sources_remain_exact_and_read_only(capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    case = json.loads((ROOT / "tests/fixtures/remediation-workflow-monetary-v3.json").read_text())
    paths = [ROOT / case["argv"][1], ROOT / "examples/remediation/required-refund.json"]
    before = [path.read_bytes() for path in paths]
    assert main(case["argv"]) == 1
    capsys.readouterr()
    assert before == [path.read_bytes() for path in paths]


def test_comment_only_manifest_change_invalidates_the_requirements_join(tmp_path, capsys):
    path = tmp_path / "manifest.yaml"
    path.write_bytes(
        (ROOT / "examples/dispute-resolver-v2.yaml").read_bytes() + b"\n# changed bytes\n"
    )
    assert (
        main(
            [
                "remediate",
                str(path),
                "--required-workflows",
                str(ROOT / "examples/remediation/required-refund.json"),
                "--json",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert not output.out and "exact baseline manifest" in output.err


def test_requirements_without_ceiling_options_preserve_a_valid_removal_repair():
    source = refund()
    result = plan(
        source,
        required_workflows=requirements(
            source,
            [
                call("open_case"),
                call("issue_refund", value=100),
            ],
        ),
        max_candidates=100,
    )
    assert result["schema"] == "agentmandate.remediation/v3"
    assert "ceiling_options" not in result
    assert result["candidates"][0]["edits"] == [{"tool": "search_cases", "kind": "remove_tool"}]
    assert result["candidates"][0]["required_workflows"][0]["failure"] is None


def test_valid_requirements_do_not_bypass_structural_refusal():
    source = small()
    source = replace(source, tools=tuple(t for t in source.tools if t.name != "seed"))
    result = plan(source, required_workflows=requirements(source, [call("inspect")]))
    assert result["status"] == "input_requires_review" and not result["candidates"]
    assert result["requirements"]["baseline"][0]["failure"] is None
    assert any(f["rule"] == "scope.missing-producer" for f in result["baseline_lint"])


def test_an_accepted_provider_profile_cannot_be_used_as_workflow_intent(capsys):
    assert (
        main(
            [
                "remediate",
                str(ROOT / "examples/dispute-resolver-v2.yaml"),
                "--required-workflows",
                str(ROOT / ("docs/continuity-reviews/agentcore-continuation-2026-10-09.json")),
                "--json",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert not output.out and output.err.startswith("error: ")
