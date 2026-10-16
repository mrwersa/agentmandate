"""Compare condition-aware repairs with direct reader and graph rechecks."""

import copy
import hashlib
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from agentmandate import Mandate, Quantity, analyse, load
from agentmandate import _ceiling_discovery as discovery_runtime
from agentmandate import _remediation as remediation_runtime
from agentmandate._conditions import ConditionContext, ToolCondition, analyse_conditions
from agentmandate._remediation import plan
from agentmandate._remediation_conditions import _ConditionScope
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/conditional-remediation"
AS_OF = date(2026, 10, 16)


def inputs(*, condition_change=None, context_change=None, capture=None):
    condition = json.loads((EXAMPLE / "condition.json").read_text())
    context = json.loads((EXAMPLE / "context.json").read_text())
    if condition_change:
        condition_change(condition)
    if context_change:
        context_change(context)
    return (
        (ToolCondition.from_json(json.dumps(condition)),),
        (ConditionContext.from_json(json.dumps(context)),),
        {context["id"]: (EXAMPLE / "capture.sql").read_bytes() if capture is None else capture},
        AS_OF,
    )


def requirements(mandate=None):
    mandate = load(EXAMPLE / "manifest.json") if mandate is None else mandate
    content = (EXAMPLE / "manifest.json").read_bytes()
    return _Requirements.load(
        (EXAMPLE / "required-export.json").read_bytes(), mandate,
        hashlib.sha256(content).hexdigest(),
    )


def options(discovery=False):
    return {"discover_ceilings": ("export_rows=1",)} if discovery else {
        "ceiling_grids": ("export_rows=0:2:1",), "pareto": True,
    }


@pytest.mark.parametrize("discovery", [False, True])
def test_repair_preserves_workflows_effects_and_unconditional_findings(discovery):
    mandate = load(EXAMPLE / "manifest.json")
    before = copy.deepcopy(mandate)
    records = inputs()
    scope = _ConditionScope.from_inputs(*records)
    result = plan(
        mandate, condition_scope=scope, required_workflows=requirements(),
        keep_tools=mandate.tool_names, max_candidates=100, **options(discovery),
    )
    direct = analyse_conditions(mandate, *records[:3], as_of=AS_OF)
    assert result["baseline"] == direct.authority.as_dict()
    assert {b["kind"] for b in result["baseline"]["breaches"]} == {"quantity_budget"}
    assert result["conditions"]["unconditional_authority"] == analyse(mandate).as_dict()
    assert {b["kind"] for b in result["conditions"]["unconditional_authority"]["breaches"]} == {
        "quantity_budget", "ungated_effect", "effect_count",
    }
    assert result["conditions"]["unconditional_lint"] and not result["baseline_lint"]
    candidate, = result["candidates"]
    assert candidate["edits"][0]["after"] == {"amount": "2", "unit": "record"}
    restored = Mandate.parse(candidate["manifest"])
    assert restored.tool("run_query").effect == "irreversible"
    assert restored.limits == mandate.limits and restored.roles == mandate.roles
    assert candidate["conditions"]["unconditional_authority"] == analyse(restored).as_dict()
    assert analyse(restored).breaches and not candidate["authority"]["breaches"]
    assert candidate["authority"] == analyse_conditions(
        restored, *records[:3], as_of=AS_OF,
    ).authority.as_dict()
    assert candidate["conditions"]["inputs"] == result["conditions"]["inputs"]
    assert candidate["conditions"]["findings"] == []
    assert all(row["failure"] is None for row in candidate["required_workflows"])
    assert result["search"]["required_workflow_rejections"] > 0
    with pytest.raises(ValueError, match="invalid in the baseline"):
        plan(mandate, required_workflows=requirements())
    assert mandate == before


@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("defect", [
    "unreviewed", "expired", "approximate", "representative", "mixed_classes",
    "wrong_source", "tampered_capture", "missing_capture", "unknown_tool",
    "duplicate_condition", "duplicate_context",
])
def test_uncertain_evidence_blocks_all_recommendations(discovery, defect):
    records = list(inputs())
    if defect in {"unreviewed", "expired", "approximate"}:
        field, value = {
            "unreviewed": ("review", "unreviewed"),
            "expired": ("expires", "2026-10-15"),
            "approximate": ("confidence", "heuristic"),
        }[defect]
        raw = json.loads(records[0][0].to_json())
        raw["evidence"][field] = value
        if defect == "unreviewed":
            raw["evidence"]["reviewer"] = None
            raw["evidence"]["expires"] = None
        records[0] = (ToolCondition.from_json(json.dumps(raw)),)
    elif defect in {"representative", "mixed_classes", "wrong_source"}:
        raw = json.loads(records[1][0].to_json())
        if defect == "representative":
            raw["completeness"] = "representative"
        elif defect == "mixed_classes":
            raw["domain"]["classes"] = ["ddl", "select-only"]
        else:
            raw["target"]["source"] = "other.py"
        records[1] = (ConditionContext.from_json(json.dumps(raw)),)
    elif defect == "tampered_capture":
        records[2] = {records[1][0].id: b"SELECT changed;\n"}
    elif defect == "missing_capture":
        records[2] = {}
    elif defect == "unknown_tool":
        raw = json.loads(records[0][0].to_json())
        raw["target"]["tool"] = "absent"
        records[0] = (ToolCondition.from_json(json.dumps(raw)),)
    elif defect == "duplicate_condition":
        records[0] *= 2
    else:
        records[1] *= 2
    result = plan(
        load(EXAMPLE / "manifest.json"), condition_scope=_ConditionScope.from_inputs(*records),
        **options(discovery),
    )
    assert result["status"] == "input_requires_review"
    assert result["conditions"]["findings"]
    assert result["baseline"] == result["conditions"]["unconditional_authority"]
    assert result["candidates"] == [] and result["search"]["combinations_examined"] == 0
    if discovery:
        assert not result["discovery"]["frontier_complete_within_domain"]


def test_removed_tools_deactivate_only_their_validated_attachments():
    mandate = Mandate.parse({"agent": "synthetic-independent", "tools": [
        {"name": "run_query", "effect": "irreversible"},
        {"name": "delete", "effect": "irreversible"},
        {"name": "inspect", "effect": "irreversible"},
    ]})
    records = list(inputs())
    other = replace(records[0][0], id="conditions/synthetic/inspect",
                    target=replace(records[0][0].target, tool="inspect"))
    records[0] += (other,)
    scope = _ConditionScope.from_inputs(*records)
    result = plan(mandate, condition_scope=scope, max_candidates=100)
    removed = next(
        c for c in result["candidates"]
        if c["conditions"]["inactive_conditions"] == ["conditions/synthetic/select-only"]
    )
    assert "run_query" not in {t["name"] for t in removed["manifest"]["tools"]}
    assert removed["conditions"]["inactive_conditions"] == ["conditions/synthetic/select-only"]
    assert [item["tool"] for item in removed["conditions"]["applied"]] == ["inspect"]
    assert removed["conditions"]["inputs"] == result["conditions"]["inputs"]


def test_snapshot_owns_records_and_captures_without_changing_canonical_identity():
    records = inputs()
    identity = hashlib.sha256(records[0][0].to_json().encode()).hexdigest()
    scope = _ConditionScope.from_inputs(*records)
    records[2].clear()
    # Even a caller bypassing frozen dataclasses cannot alter the owned snapshot.
    object.__setattr__(records[0][0].target, "tool", "absent")
    object.__setattr__(records[1][0].evidence, "review", "rejected")
    result = scope.resolve(load(EXAMPLE / "manifest.json"))
    assert not result.findings
    assert result.report["inputs"]["conditions"] == [identity]
    assert "not original file bytes" in result.report["inputs"]["artifact_identity"]


@pytest.mark.parametrize("discovery", [False, True])
def test_workflow_screen_still_precedes_candidate_graph_search(monkeypatch, discovery):
    runtime = discovery_runtime if discovery else remediation_runtime
    original = runtime.analyse
    analyzed = []

    def counted(mandate, **kwargs):
        analyzed.append(mandate.tool("export_rows").ceiling.amount)
        return original(mandate, **kwargs)

    monkeypatch.setattr(runtime, "analyse", counted)
    result = plan(
        load(EXAMPLE / "manifest.json"), required_workflows=requirements(),
        condition_scope=_ConditionScope.from_inputs(*inputs()),
        keep_tools=("run_query", "export_rows"), **options(discovery),
    )
    assert result["search"]["required_workflow_rejections"] > 0
    assert result["search"]["candidates_analyzed"] == len(analyzed) - 1
    assert all(amount >= 2 for amount in analyzed)


@pytest.mark.parametrize("empty", [0, 1])
def test_empty_scope_configuration_is_a_usage_error(empty):
    records = list(inputs())
    records[empty] = ()
    with pytest.raises(ValueError, match="requires conditions and contexts"):
        _ConditionScope.from_inputs(*records)


@pytest.mark.parametrize("discovery", [False, True])
def test_changed_trust_cannot_be_interpreted_as_a_clean_repair(monkeypatch, discovery):
    original = _ConditionScope.resolve
    invalid = _ConditionScope.from_inputs(*inputs(capture=b"changed"))

    def changed(self, mandate, *, candidate=False):
        return original(invalid if candidate else self, mandate, candidate=candidate)

    monkeypatch.setattr(_ConditionScope, "resolve", changed)
    with pytest.raises(ValueError, match="eligibility changed"):
        plan(
            load(EXAMPLE / "manifest.json"),
            condition_scope=_ConditionScope.from_inputs(*inputs()), **options(discovery),
        )


def argv():
    return ["remediate", str(EXAMPLE / "manifest.json"),
            "--condition", str(EXAMPLE / "condition.json"),
            "--condition-context", str(EXAMPLE / "context.json"),
            "--condition-capture", str(EXAMPLE / "capture.sql"),
            "--condition-as-of", AS_OF.isoformat()]


@pytest.mark.parametrize("discovery", [False, True])
def test_cli_reports_scoped_repairs_with_original_findings(capsys, discovery):
    args = argv() + ["--required-workflows", str(EXAMPLE / "required-export.json"),
                     "--keep-tool", "run_query", "--keep-tool", "export_rows"]
    args += ["--discover-ceiling", "export_rows=1"] if discovery else [
        "--ceiling-grid", "export_rows=0:2:1", "--pareto",
    ]
    assert main([*args, "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["candidates"][0]["conditions"]["applied"]
    assert main(args) == 1
    text = capsys.readouterr().out
    assert "CONDITIONS" in text and "UNCONDITIONAL baseline retained" in text
    assert "manifest retains declared effects" in text and "CANDIDATE 1" in text


@pytest.mark.parametrize("discovery", [False, True])
def test_clean_scope_can_exit_zero_while_declared_authority_remains_visible(
    capsys, tmp_path, discovery,
):
    raw = json.loads((EXAMPLE / "manifest.json").read_text())
    raw["limits"]["quantities"]["exported_rows"]["amount"] = "6"
    path = tmp_path / "clean.json"
    path.write_text(json.dumps(raw))
    args = argv()
    args[1] = str(path)
    if discovery:
        args += ["--discover-ceiling", "export_rows=1"]
    assert main([*args, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert not report["baseline"]["breaches"] and not report["candidates"]
    assert report["conditions"]["unconditional_authority"]["breaches"]


def test_unresolved_evidence_alone_keeps_cli_blocked(capsys, tmp_path):
    raw = json.loads((EXAMPLE / "manifest.json").read_text())
    raw["tools"][0]["requires_approval"] = True
    raw["limits"]["quantities"]["exported_rows"]["amount"] = "6"
    raw["limits"]["effects"] = {}
    path = tmp_path / "clean.json"
    path.write_text(json.dumps(raw))
    capture = tmp_path / "tampered.sql"
    capture.write_bytes(b"changed")
    args = argv()
    args[1] = str(path)
    args[args.index("--condition-capture") + 1] = str(capture)
    assert main([*args, "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["baseline"]["breaches"] and not report["baseline_lint"]
    assert report["status"] == "input_requires_review" and report["conditions"]["findings"]
    assert main(args) == 1
    assert "UNRESOLVED CONDITION" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["--condition", "--condition-context",
                                    "--condition-capture", "--condition-as-of"])
def test_partial_cli_inputs_are_exit_two_without_output(capsys, missing):
    args = argv()
    index = args.index(missing)
    del args[index:index + 2]
    assert main([*args, "--json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "error:" in captured.err


@pytest.mark.parametrize("budget", ["4", "5", "6", "7"])
@pytest.mark.parametrize("minimum", ["1", "2"])
def test_discovery_matches_independent_full_lattice_rechecks(budget, minimum):
    mandate = load(EXAMPLE / "manifest.json")
    limits = replace(mandate.limits, quantities={"exported_rows": Quantity.parse(
        {"amount": budget, "unit": "record"}, "budget",
    )})
    mandate = replace(mandate, limits=limits)
    required = requirements(mandate)
    # Only amounts change; all principals, binding order and approval annotations stay fixed.
    workflows = tuple(replace(w, steps=tuple(
        replace(s, value=Quantity.parse({"amount": minimum, "unit": "record"}, "value"))
        if s.value is not None else s for s in w.steps
    )) for w in required.workflows)
    required = replace(required, workflows=workflows)
    records = inputs()
    scope = _ConditionScope.from_inputs(*records)
    result = plan(mandate, condition_scope=scope, required_workflows=required,
                  max_evaluations=100, discover_ceilings=("export_rows=1",))
    baseline = analyse_conditions(mandate, *records[:3], as_of=AS_OF)
    if not baseline.authority.breaches:
        assert not result["candidates"]
        return
    feasible = []
    for amount in range(4):
        changed = replace(mandate, tools=tuple(
            replace(t, ceiling=Quantity.parse({"amount": str(amount), "unit": "record"}, "cap"))
            if t.name == "export_rows" else t for t in mandate.tools
        ))
        direct = analyse_conditions(changed, *records[:3], as_of=AS_OF)
        projected = replace(changed, tools=tuple(
            replace(t, effect="read") if t.name == "run_query" else t for t in changed.tools
        ))
        if not direct.authority.breaches and all(
            row["failure"] is None for row in required.assess(projected, 4)
        ):
            feasible.append(amount)
    assert result["discovery"]["frontier_complete_within_domain"]
    assert [int(c["manifest"]["tools"][1]["ceiling"]["amount"])
            for c in result["candidates"]] == ([max(feasible)] if feasible else [])


@pytest.mark.parametrize(
    "case", json.loads((ROOT / "tests/fixtures/conditional-remediation-v1.json").read_text()),
    ids=lambda case: case["name"],
)
def test_current_cli_results_replay_exactly(case, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    assert main(case["argv"]) == case["exit"]
    captured = capsys.readouterr()
    assert captured.out == json.dumps(case["result"], indent=2, sort_keys=True) + "\n"
    assert not captured.err
