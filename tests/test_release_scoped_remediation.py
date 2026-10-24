"""Independent release comparisons remain binding on evidence-scoped repairs."""

import copy
import hashlib
import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import test_conditional_remediation as conditional
import test_delegated_remediation as delegated

from agentmandate import Mandate, Quantity, analyse, compare, load
from agentmandate._conditions import analyse_conditions
from agentmandate._remediation import _manifest, plan
from agentmandate._remediation_conditions import _ConditionScope
from agentmandate._remediation_delegations import _DelegationScope
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/release-scoped-remediation"


def inputs(kind):
    module = conditional if kind == "condition" else delegated
    released = load(EXAMPLE / f"{kind}-released.json")
    proposed = load(module.EXAMPLE / "manifest.json")
    scope = (_ConditionScope if kind == "condition" else _DelegationScope).from_inputs(
        *module.inputs(),
    )
    required = _Requirements.load(
        (EXAMPLE / f"{kind}-required.json").read_bytes(), released,
        hashlib.sha256((EXAMPLE / f"{kind}-released.json").read_bytes()).hexdigest(),
    )
    return released, proposed, scope, required


def options(kind, discovery=False):
    return {
        "keep_tools": ("run_query" if kind == "condition" else "select_rows", "export_rows"),
        **({"discover_ceilings": ("export_rows=1",)} if discovery else {
            "ceiling_grids": ("export_rows=0:2:1",), "pareto": True,
        }),
    }


def repin(required, reference):
    content = json.dumps(_manifest(reference), sort_keys=True).encode()
    raw = {
        "schema": "agentmandate.required-workflows/v2", "agent": reference.agent,
        "manifest_sha256": hashlib.sha256(content).hexdigest(),
        "reviewer": required.reviewer, "reason": required.reason,
        "workflows": [
            {"name": workflow.name, "steps": [
                {"tool": step.tool, "principal": step.principal, "approved": step.approved,
                 **({"value": str(step.value.amount), "unit": step.value.unit,
                     "binding": step.binding, "quantity": step.quantity}
                    if step.value is not None else {})}
                for step in workflow.steps
            ]} for workflow in required.workflows
        ],
    }
    return _Requirements.load(json.dumps(raw).encode(), reference, raw["manifest_sha256"])


def direct(kind, mandate):
    if kind == "condition":
        records = conditional.inputs()
        return analyse_conditions(mandate, *records[:3], as_of=records[3])
    return delegated.direct(mandate, delegated.inputs(), candidate=True)


@pytest.mark.parametrize("kind", ["condition", "delegation"])
@pytest.mark.parametrize("discovery", [False, True])
def test_joint_repairs_keep_independent_comparisons_and_reviewed_scope(kind, discovery):
    released, proposed, scope, required = inputs(kind)
    saved = copy.deepcopy((released, proposed, scope))
    result = plan(proposed, released=released, **{f"{kind}_scope": scope},
                  required_workflows=required, **options(kind, discovery))
    assert saved == (released, proposed, scope)
    assert result["release"]["comparison"] == compare(
        released, proposed, depth=4, required_workflows=required,
    ).as_dict()
    assert result["baseline"] == direct(kind, proposed).authority.as_dict()
    assert not result["release"]["gate_passed"]
    assert "proposal analysis within reviewed scope only" in result["scope"]
    if discovery and kind == "delegation":
        assert not result["candidates"]  # Retained purge exceeds the fixed grant.
        assert result["discovery"]["frontier_complete_within_domain"]
        return
    candidate, = result["candidates"]
    restored = Mandate.parse(candidate["manifest"])
    assert candidate["status"] == "no_declared_widening_or_breach_within_reviewed_scope"
    assert restored.tool("export_rows").ceiling.amount == 2
    assert candidate["release"]["gate_passed"]
    delta = compare(released, restored, depth=4, required_workflows=required)
    assert candidate["release"]["comparison"] == delta.as_dict()
    assert not delta.widened and not delta.workflow_regressions
    assert candidate["authority"] == direct(kind, restored).authority.as_dict()
    assert not candidate["authority"]["breaches"]
    reviewed = candidate["release"]["reviewed_analysis"]
    assert reviewed["authority"] == candidate["authority"]
    assert reviewed["evidence"]["inputs"] == result[scope.kind]["inputs"]
    assert reviewed["evidence"]["findings"] == []
    assert candidate["lint"] == reviewed["lint"] == []
    if kind == "condition":
        assert restored.tool("run_query").effect == "irreversible"
        assert delta.after.breaches  # The scoped pass must not erase this result.
        assert not candidate["release"]["unconditional_gate_passed"]
        assert candidate["conditions"]["unconditional_authority"] == delta.after.as_dict()
        assert delta.before.as_dict() == analyse(released, depth=4).as_dict()
    else:
        assert restored.tool("purge_rows") is None
        assert candidate["release"]["unconditional_gate_passed"]
    if discovery:
        assert result["discovery"]["frontier_complete_within_domain"]


@pytest.mark.parametrize("kind", ["condition", "delegation"])
@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("defect", ["expired", "missing_capture", "tampered", "wrong_binding"])
def test_bad_evidence_retains_release_findings_without_enumerating(kind, discovery, defect):
    released, proposed, scope, required = inputs(kind)
    if defect == "expired":
        scope = replace(scope, as_of=date(2040, 1, 1) if kind == "condition"
                        else "2040-01-01T00:00:00Z")
    elif defect == "missing_capture":
        scope = replace(scope, captures=())
    elif defect == "tampered":
        scope = replace(scope, captures=tuple((k, v + b" ") for k, v in scope.captures))
    elif kind == "delegation":
        scope = replace(scope, target_binding="another-agent")
    else:
        scope = replace(scope, contexts=tuple(replace(c, target_binding="another-agent")
                                              for c in scope.contexts))
    result = plan(proposed, released=released, **{f"{kind}_scope": scope},
                  required_workflows=required, **options(kind, discovery))
    assert result["status"] == "input_requires_review"
    assert result["search"]["combinations_examined"] == 0 and not result["candidates"]
    assert result[scope.kind]["findings"]
    assert result["release"]["comparison"] == compare(
        released, proposed, depth=4, required_workflows=required,
    ).as_dict()
    assert not result["release"]["gate_passed"]
    assert result["release"]["reviewed_analysis"]["evidence"]["findings"]
    if discovery:
        assert not result["discovery"]["frontier_complete_within_domain"]


@pytest.mark.parametrize("kind", ["condition", "delegation"])
@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("widening", ["budget", "identity"])
def test_reviewed_evidence_cannot_waive_fixed_declared_widening(kind, discovery, widening):
    released, proposed, scope, required = inputs(kind)
    if widening == "budget":
        proposed = replace(proposed, limits=replace(proposed.limits, quantities={
            "exported_rows": Quantity(Decimal(6), "record"),
        }))
    else:
        released = replace(released, identity="released-workload")
        required = repin(required, released)
        proposed = replace(proposed, identity="another-workload")
    result = plan(proposed, released=released, **{f"{kind}_scope": scope},
                  required_workflows=required, **options(kind, discovery))
    assert not result["candidates"] and not result["release"]["gate_passed"]
    assert result["release"]["comparison"]["direction"] == "widening"
    if not (discovery and kind == "delegation"):
        assert result["release_rejections"]
        assert all(row["comparison"]["direction"] == "widening"
                   for row in result["release_rejections"])


@pytest.mark.parametrize("discovery", [False, True])
def test_proposal_condition_is_not_applied_to_reference(discovery):
    released, proposed, scope, _ = inputs("condition")
    released = replace(released, tools=tuple(
        replace(t, effect="read") if t.name == "run_query" else t for t in released.tools
    ))
    result = plan(proposed, released=released, condition_scope=scope,
                  **options("condition", discovery))
    assert not result["candidates"]
    assert result["release"]["comparison"]["direction"] == "widening"
    assert not result["conditions"]["findings"]
    assert result["release"]["comparison"]["before"] == analyse(released, depth=4).as_dict()


@pytest.mark.parametrize("discovery", [False, True])
def test_scoped_workflow_cannot_waive_ordinary_release_regression(discovery):
    released, proposed, scope, _ = inputs("condition")
    released = replace(released, limits=replace(released.limits, effects={"irreversible": 4}))
    required = repin(conditional.requirements(proposed), released)
    result = plan(proposed, released=released, condition_scope=scope,
                  required_workflows=required, **options("condition", discovery))
    assert all(row["failure"] is None for row in result["requirements"]["baseline"])
    assert result["release"]["workflow_regressions"] == ["two-batch-export"]
    assert not result["release"]["gate_passed"] and not result["candidates"]
    assert result["release_rejections"]


def test_reference_workflow_must_conform_without_borrowing_proposal_evidence():
    released, proposed, scope, _ = inputs("condition")
    with pytest.raises(ValueError, match="invalid in the baseline manifest"):
        plan(proposed, released=released, condition_scope=scope,
             required_workflows=repin(conditional.requirements(), released), **options("condition"))


@pytest.mark.parametrize("kind", ["condition", "delegation"])
@pytest.mark.parametrize("discovery", [False, True])
def test_clean_scoped_reference_returns_no_unnecessary_edits(kind, discovery):
    released, _, scope, required = inputs(kind)
    if kind == "delegation":
        scope = replace(scope, attachments=tuple(a for a in scope.attachments
                                                if a.target.tool != "purge_rows"))
    domain = options(kind, discovery)
    if not discovery:
        domain["ceiling_grids"] = ("export_rows=0:1:1",)
    result = plan(released, released=released, **{f"{kind}_scope": scope},
                  required_workflows=required, **domain)
    assert result["release"]["gate_passed"]
    assert not result["candidates"] and result["search"]["combinations_examined"] == 0
    assert result["release"]["unconditional_gate_passed"] == (kind == "delegation")
    if discovery:
        assert result["discovery"]["status"] == "not_needed_baseline_clean"


@pytest.mark.parametrize("kind", ["condition", "delegation"])
@pytest.mark.parametrize("reference_cap", [1, 2, 3])
@pytest.mark.parametrize("budget", [2, 4])
@pytest.mark.parametrize("discovery", [False, True])
def test_frontier_matches_independent_full_integer_domain(kind, reference_cap, budget, discovery):
    released, proposed, scope, _ = inputs(kind)
    proposed = replace(proposed, tools=tuple(t for t in proposed.tools if t.name != "purge_rows"),
                       roles={}, limits=replace(proposed.limits, quantities={
                           "exported_rows": Quantity(Decimal(budget), "record"),
                       }))
    released = replace(proposed, tools=tuple(
        replace(t, ceiling=Quantity(Decimal(reference_cap), "record")) if t.ceiling else t
        for t in proposed.tools
    ))
    if kind == "delegation":
        scope = replace(scope, attachments=tuple(a for a in scope.attachments
                                                if a.target.tool != "purge_rows"))
    kwargs = {**options(kind, discovery), "keep_tools": proposed.tool_names, "max_candidates": 20}
    result = plan(proposed, released=released, **{f"{kind}_scope": scope}, **kwargs)
    feasible = []
    for cap in range(4):
        candidate = replace(proposed, tools=tuple(
            replace(t, ceiling=Quantity(Decimal(cap), "record")) if t.ceiling else t
            for t in proposed.tools
        ))
        observed = direct(kind, candidate)
        delta = compare(released, candidate, depth=4)
        if not observed.findings and not observed.authority.breaches and not delta.widened:
            feasible.append(cap)
    # A clean starting point deliberately returns no proposed edits.
    expected = [] if result["release"]["gate_passed"] else [max(feasible)]
    actual = [int(c["manifest"]["tools"][1]["ceiling"]["amount"])
              for c in result["candidates"]]
    assert actual == expected
    if discovery and not result["release"]["gate_passed"]:
        assert result["discovery"]["frontier_complete_within_domain"]


def argv(kind, discovery=False):
    module = conditional if kind == "condition" else delegated
    args = module.argv() + [
        "--released", str(EXAMPLE / f"{kind}-released.json"),
        "--required-workflows", str(EXAMPLE / f"{kind}-required.json"),
    ]
    for name in options(kind)["keep_tools"]:
        args += ["--keep-tool", name]
    return args + (["--discover-ceiling", "export_rows=1"] if discovery else [
        "--ceiling-grid", "export_rows=0:2:1", "--pareto",
    ])


@pytest.mark.parametrize("kind", ["condition", "delegation"])
@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("machine", [False, True])
def test_cli_scope_counts_input_pins_and_original_exit(kind, discovery, machine, capsys):
    args = argv(kind, discovery)
    assert main(args + (["--json"] if machine else [])) == 1
    output = capsys.readouterr()
    assert not output.err
    if machine:
        result = json.loads(output.out)
        assert result["input"]["released_sha256"] == hashlib.sha256(
            (EXAMPLE / f"{kind}-released.json").read_bytes(),
        ).hexdigest()
        assert "reviewed_analysis" in result["release"]
    else:
        assert f"RELEASE REVIEWED {kind}s" in output.out
        assert "proposal breach/lint checks only" in output.out
        if kind == "condition":
            assert "UNCONDITIONAL baseline retained" in output.out


def test_conditions_and_grants_still_cannot_compose_with_release(capsys):
    assert main(["remediate", "absent", "--released", "absent", "--condition", "absent",
                 "--delegation-attachment", "absent"]) == 2
    output = capsys.readouterr()
    assert not output.out and "cannot be combined" in output.err


@pytest.mark.parametrize("case", json.loads(
    (ROOT / "tests/fixtures/release-scoped-remediation-v1.json").read_text(),
)["cases"], ids=lambda case: case["name"])
def test_current_cli_replays(case, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    assert main(case["argv"]) == case["exit"]
    output = capsys.readouterr()
    assert hashlib.sha256(output.out.encode()).hexdigest() == case["stdout_sha256"]
    assert output.err == case["stderr"]
