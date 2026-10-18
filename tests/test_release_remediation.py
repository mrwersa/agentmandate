"""Release repairs are checked against independent diff and path oracles."""

import copy
import hashlib
import json
from dataclasses import replace
from itertools import product
from pathlib import Path

import pytest

from agentmandate import Mandate, Quantity, analyse, compare, load
from agentmandate._remediation import _manifest, plan
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/release-remediation"


def inputs():
    return load(EXAMPLE / "released.json"), load(EXAMPLE / "proposed.json")


def requirements(released=None):
    content = (EXAMPLE / "released.json").read_bytes()
    annotation = json.loads((EXAMPLE / "required-export.json").read_bytes())
    if released is None:
        released = load(EXAMPLE / "released.json")
    else:
        content = json.dumps(_manifest(released), sort_keys=True).encode()
        annotation["manifest_sha256"] = hashlib.sha256(content).hexdigest()
        for workflow in annotation["workflows"]:
            for step in workflow["steps"]:
                step["approved"] = released.tool(step["tool"]).requires_approval
    return _Requirements.load(json.dumps(annotation).encode(), released,
                              hashlib.sha256(content).hexdigest())


def argv(proposed="proposed.json"):
    return ["remediate", str(EXAMPLE / proposed), "--released", str(EXAMPLE / "released.json"),
            "--required-workflows", str(EXAMPLE / "required-export.json"),
            "--keep-tool", "select_rows", "--keep-tool", "export_rows"]


def test_joint_release_repair_starts_without_a_breach_and_keeps_original_findings():
    released, proposed = inputs()
    saved = copy.deepcopy((released, proposed))
    result = plan(proposed, released=released, required_workflows=requirements(),
                  keep_tools=("select_rows", "export_rows"),
                  ceiling_grids=("export_rows=0:2:1",), pareto=True)
    assert (released, proposed) == saved
    assert result["baseline"] == analyse(proposed, depth=4).as_dict()
    assert not result["baseline"]["breaches"]
    assert not result["release"]["gate_passed"]
    assert result["release"]["comparison"] == compare(
        released, proposed, depth=4, required_workflows=requirements(),
    ).as_dict()
    candidate, = result["candidates"]
    assert candidate["status"] == "no_widening_or_reachable_breach_within_bound"
    changed = Mandate.parse(candidate["manifest"])
    assert changed.tool("purge_rows") is None
    assert changed.tool("export_rows").ceiling.amount == 2
    assert changed.limits == proposed.limits
    assert candidate["release"]["gate_passed"]
    assert candidate["release"]["comparison"] == compare(
        released, changed, depth=4, required_workflows=requirements(),
    ).as_dict()
    assert candidate["authority"] == analyse(changed, depth=4).as_dict()
    assert not candidate["authority"]["breaches"]
    assert all(row["failure"] is None for row in candidate["required_workflows"])
    assert result["release_rejections"] and result["requirement_rejections"]
    assert result["search"]["release_rejections"] == len(result["release_rejections"])
    for rejected in result["release_rejections"]:
        assert not rejected["gate_passed"]
        assert rejected["comparison"]["direction"] == "widening"


@pytest.mark.parametrize("discovery", [False, True])
def test_unchanged_clean_release_does_not_invent_a_repair(discovery):
    released, _ = inputs()
    result = plan(released, released=released, required_workflows=requirements(),
                  **({"discover_ceilings": ("export_rows=1",)} if discovery else {}))
    assert result["release"]["gate_passed"]
    assert not result["candidates"] and result["search"]["combinations_examined"] == 0
    if discovery:
        assert result["discovery"]["status"] == "not_needed_baseline_clean"


@pytest.mark.parametrize("discovery", [False, True])
def test_broken_proposed_workflow_is_a_finding_not_a_bad_released_requirement(discovery):
    released, _ = inputs()
    proposed = replace(released, tools=tuple(
        replace(t, ceiling=Quantity.parse({"amount": "0", "unit": "record"}, "cap"))
        if t.ceiling else t for t in released.tools
    ))
    result = plan(proposed, released=released, required_workflows=requirements(),
                  keep_tools=proposed.tool_names,
                  **({"discover_ceilings": ("export_rows=1",)} if discovery else {}))
    assert result["release"]["comparison"]["direction"] == "narrowing"
    assert result["release"]["workflow_regressions"] == ["two-exports"]
    assert not result["release"]["gate_passed"] and not result["candidates"]
    assert result["requirements"]["baseline"][0]["failure"]["step"] == 2


@pytest.mark.parametrize("discovery", [False, True])
def test_invalid_released_requirement_is_a_usage_error(discovery):
    released, proposed = inputs()
    annotation = json.loads((EXAMPLE / "required-export.json").read_bytes())
    annotation["workflows"][0]["steps"][1]["value"] = "3"
    req = _Requirements.load(json.dumps(annotation).encode(), released,
                             hashlib.sha256((EXAMPLE / "released.json").read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="invalid in the baseline manifest"):
        plan(proposed, released=released, required_workflows=req,
             **({"discover_ceilings": ("export_rows=1",)} if discovery else {}))


@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("kind", ["quantity", "effect", "depth", "identity"])
def test_fixed_declared_widening_cannot_be_hidden_by_numeric_repairs(discovery, kind):
    released, _ = inputs()
    if kind == "quantity":
        proposed = replace(released, limits=replace(released.limits, quantities={
            "exported_rows": Quantity.parse({"amount": "30", "unit": "record"}, "budget"),
        }))
    elif kind == "effect":
        released = replace(released, limits=replace(released.limits, effects={"write": 5}))
        proposed = replace(released, limits=replace(released.limits, effects={"write": 6}))
    elif kind == "depth":
        released = replace(released, limits=replace(released.limits, depth=6))
        proposed = replace(released, limits=replace(released.limits, depth=4))
    else:
        released = replace(released, identity="released-workload")
        proposed = replace(released, identity="different-workload")
    result = plan(proposed, released=released, keep_tools=proposed.tool_names,
                  **({"discover_ceilings": ("export_rows=1",)} if discovery else
                     {"ceiling_grids": ("export_rows=0:1:1",)}))
    assert not result["candidates"] and result["release_rejections"]
    assert not result["release"]["gate_passed"]
    assert result["search"]["depth"] == max(released.limits.depth, proposed.limits.depth)
    assert result["release"]["comparison"]["before"]["depth"] == result["search"]["depth"]
    if discovery:
        assert result["status"] == "no_feasible_candidate_in_declared_domain"
        assert result["discovery"]["frontier_complete_within_domain"]


@pytest.mark.parametrize("discovery", [False, True])
def test_existing_released_breach_is_not_a_release_allowance(discovery):
    released, _ = inputs()
    released = replace(released, limits=replace(released.limits, quantities={
        "exported_rows": Quantity.parse({"amount": "2", "unit": "record"}, "budget"),
    }))
    result = plan(released, released=released, keep_tools=released.tool_names,
                  **({"discover_ceilings": ("export_rows=1",)} if discovery else
                     {"ceiling_options": ("export_rows=1",)}))
    assert result["release"]["comparison"]["direction"] == "neutral"
    assert result["release"]["comparison"]["before"]["breaches"]
    assert not result["release"]["gate_passed"]
    candidate, = result["candidates"]
    assert candidate["release"]["gate_passed"] and not candidate["authority"]["breaches"]


@pytest.mark.parametrize("discovery", [False, True])
def test_release_limits_and_display_limits_stay_separate(discovery):
    released, _ = inputs()
    proposed = load(EXAMPLE / "ceiling-only.json")
    result = plan(proposed, released=released, max_evaluations=1,
                  keep_tools=proposed.tool_names, required_workflows=requirements(),
                  **({"discover_ceilings": ("export_rows=0.01",)} if discovery else
                     {"ceiling_grids": ("export_rows=0:2:1",)}))
    assert result["search"]["truncated_by_limit"] and not result["candidates"]
    assert result["status"] == "no_candidate_found_within_limits"
    if discovery:
        assert not result["discovery"]["frontier_complete_within_domain"]
        assert result["discovery"]["probes"][0]["status"] == "release_rejected"
    else:
        result = plan(proposed, released=released, max_candidates=1,
                      keep_tools=proposed.tool_names, ceiling_grids=("export_rows=1:2:1",))
        assert not result["search"]["truncated_by_limit"]
        assert not result["frontier"]["display_complete"] and len(result["candidates"]) == 1


def test_explicit_depth_is_used_for_both_sides_and_every_candidate():
    released, proposed = inputs()
    result = plan(proposed, released=released, depth=5)
    assert result["search"]["depth"] == 5
    assert result["release"]["comparison"]["before"]["depth"] == 5
    for candidate in result["candidates"]:
        assert candidate["authority"]["depth"] == 5
        assert candidate["release"]["comparison"]["after"]["depth"] == 5


def test_a_neutral_comparison_cannot_hide_a_lint_error(tmp_path, capsys):
    released, _ = inputs()
    proposed = replace(released, roles={"proposer": ("select_rows",),
                                        "approver": ("export_rows",)})
    assert not analyse(proposed).breaches and not compare(released, proposed).widened
    result = plan(proposed, released=released, ceiling_options=("export_rows=1",))
    assert not result["release"]["gate_passed"]
    assert result["release"]["comparison"]["direction"] == "neutral"
    assert result["release_rejections"]
    assert all(not c["release"]["lint"] for c in result["candidates"])
    path = tmp_path / "roles.json"
    path.write_text(json.dumps(_manifest(proposed)))
    assert main(["remediate", str(path), "--released", str(EXAMPLE / "released.json"),
                 "--ceiling", "export_rows=1"]) == 1
    assert "LINT sod.single-identity" in capsys.readouterr().out


@pytest.mark.parametrize("shared", [False, True])
@pytest.mark.parametrize("discovery", [False, True])
def test_two_tool_repairs_compare_named_pools_without_combining_their_units(shared, discovery):
    released, _ = inputs()
    second = replace(released.tools[1], name="archive_rows",
                     quantity="exported_rows" if shared else "archived_rows",
                     ceiling=Quantity.parse({"amount": "1", "unit": "record"}, "cap"))
    budgets = dict(released.limits.quantities)
    if not shared:
        budgets["archived_rows"] = Quantity.parse({"amount": "20", "unit": "record"}, "budget")
    released = replace(released, tools=(*released.tools, second),
                       limits=replace(released.limits, quantities=budgets))
    proposed = replace(released, tools=tuple(
        replace(t, ceiling=Quantity.parse({"amount": "3", "unit": "record"}, "cap"))
        if t.ceiling else t for t in released.tools
    ))
    result = plan(proposed, released=released, keep_tools=proposed.tool_names, max_evaluations=200,
                  **({"discover_ceilings": ("export_rows=1", "archive_rows=1")} if discovery else
                     {"ceiling_grids": ("export_rows=0:2:1", "archive_rows=0:2:1"),
                      "pareto": True}))
    assert result["candidates"]
    for c in result["candidates"]:
        changed = Mandate.parse(c["manifest"])
        assert c["release"]["gate_passed"]
        assert not compare(released, changed, depth=4).widened
        assert changed.limits == proposed.limits
        assert set(c["authority"]["max_quantities"]) == set(budgets)
    if discovery:
        assert result["discovery"]["frontier_complete_within_domain"]


@pytest.mark.parametrize("case", json.loads(
    (ROOT / "tests/fixtures/release-remediation-v1.json").read_text(),
)["cases"], ids=lambda case: case["name"])
def test_complete_cli_replays(case, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    assert main(case["argv"]) == case["exit"]
    captured = capsys.readouterr()
    assert hashlib.sha256(captured.out.encode()).hexdigest() == case["stdout_sha256"]
    assert captured.err == case["stderr"]


@pytest.mark.parametrize("defect", ["agent", "structure"])
def test_unusable_released_reference_is_refused(defect):
    released, proposed = inputs()
    if defect == "agent":
        released = replace(released, agent="another-agent")
        match = "same agent"
    else:
        released = replace(released, tools=(released.tools[1],))
        match = "structural findings"
    with pytest.raises(ValueError, match=match):
        plan(proposed, released=released)


@pytest.mark.parametrize("flag,scope", [("--condition", "condition_scope"),
                                      ("--delegation-attachment", "delegation_scope")])
def test_scoped_composition_is_refused_before_input_reads(flag, scope, capsys):
    assert main(["remediate", "absent", "--released", "absent", flag, "absent"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "cannot be combined" in captured.err
    released, proposed = inputs()
    with pytest.raises(ValueError, match="cannot be combined"):
        plan(proposed, released=released, **{scope: object()})


def test_cli_retains_failing_release_exit_and_pins_both_inputs(capsys):
    args = argv() + ["--ceiling-grid", "export_rows=0:2:1", "--pareto"]
    assert main([*args, "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert len(result["candidates"]) == 1 and not result["release"]["gate_passed"]
    assert result["input"] == {
        "manifest_sha256": hashlib.sha256((EXAMPLE / "proposed.json").read_bytes()).hexdigest(),
        "released_sha256": hashlib.sha256((EXAMPLE / "released.json").read_bytes()).hexdigest(),
    }
    assert result["requirements"]["manifest_sha256"] == result["input"]["released_sha256"]
    assert main(args) == 1
    output = capsys.readouterr().out
    assert "RELEASE widening gate_passed=False" in output
    assert "release=neutral gate_passed=True" in output and "REJECTED RELEASE" in output
    assert main(argv("released.json")) == 0
    assert "RELEASE neutral gate_passed=True" in capsys.readouterr().out


def test_cli_workflow_regression_is_a_finding_with_failure_step(tmp_path, capsys):
    raw = json.loads((EXAMPLE / "released.json").read_text())
    raw["tools"][1]["ceiling"]["amount"] = "0"
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(raw))
    args = argv()
    args[1] = str(path)
    assert main(args) == 1
    text = capsys.readouterr().out
    assert "RELEASE narrowing gate_passed=False" in text
    assert "RELEASE REQUIRED two-exports fails at step 2 workflow.ceiling-exceeded" in text


@pytest.mark.parametrize("defect", ["missing", "malformed", "wrong_pin", "changed_bytes"])
def test_cli_bad_release_inputs_exit_two_without_partial_output(defect, tmp_path, capsys):
    args = argv()
    path = tmp_path / "released.json"
    content = (EXAMPLE / "released.json").read_bytes()
    if defect != "missing":
        path.write_bytes(b"{" if defect == "malformed" else content + b" ")
    if defect == "wrong_pin":
        index = args.index("--released")
        args[index + 1] = str(EXAMPLE / "proposed.json")
    else:
        args[args.index("--released") + 1] = str(path)
    assert main([*args, "--json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "error:" in captured.err


@pytest.mark.parametrize("released_cap", [1, 2])
@pytest.mark.parametrize("budget", [2, 4, 8])
@pytest.mark.parametrize("approval", [False, True])
@pytest.mark.parametrize("extra", [False, True])
@pytest.mark.parametrize("discovery", [False, True])
def test_frontier_matches_independent_full_release_edit_enumeration(
    released_cap, budget, approval, extra, discovery,
):
    released, proposed = inputs()
    released = replace(released, tools=(released.tools[0], replace(
        released.tools[1], effect="irreversible" if approval else "write",
        requires_approval=approval,
        ceiling=Quantity.parse({"amount": str(released_cap), "unit": "record"}, "cap"),
    )), limits=replace(released.limits, quantities={
        "exported_rows": Quantity.parse({"amount": str(budget), "unit": "record"}, "budget"),
    }))
    proposed = replace(released, tools=(released.tools[0], replace(
        released.tools[1], requires_approval=False,
        ceiling=Quantity.parse({"amount": "3", "unit": "record"}, "cap"),
    ), *((proposed.tools[-1],) if extra else ())))
    req = requirements(released)
    result = plan(proposed, released=released, required_workflows=req,
                  keep_tools=("select_rows", "export_rows"), max_evaluations=500,
                  max_candidates=100,
                  **({"discover_ceilings": ("export_rows=1",)} if discovery else
                     {"ceiling_grids": ("export_rows=0:2:1",), "pareto": True}))
    feasible = []
    # Independent edit construction, public comparison and explicit path checks;
    # no planner domain, dominance or pruning helper is used by the oracle.
    for cap, gate, remove in product(range(4), (False, True) if approval else (False,),
                                    (False, True) if extra and not discovery else (False,)):
        edits = int(cap != 3) + int(gate) + int(remove)
        if not 1 <= edits <= 2:
            continue
        candidate = replace(proposed, tools=tuple(
            replace(t, requires_approval=gate, ceiling=Quantity.parse(
                {"amount": str(cap), "unit": "record"}, "cap",
            )) if t.name == "export_rows" else t for t in proposed.tools
            if not (remove and t.name == "purge_rows")
        ))
        delta = compare(released, candidate, depth=4)
        if not delta.widened and not delta.after.breaches and all(
            row["failure"] is None for row in req.assess(candidate, 4)
        ):
            feasible.append((cap, gate, remove, edits))
    expected = {p[:3] for p in feasible if not any(
        q != p and q[0] >= p[0] and q[1] <= p[1] and q[2] <= p[2] and q[3] <= p[3]
        for q in feasible
    )}
    actual = {(int(c["manifest"]["tools"][1]["ceiling"]["amount"]),
               c["manifest"]["tools"][1]["requires_approval"],
               extra and "purge_rows" not in {t["name"] for t in c["manifest"]["tools"]})
              for c in result["candidates"]}
    assert actual == expected
    assert not result["search"]["truncated_by_limit"]
    if discovery:
        assert result["discovery"]["frontier_complete_within_domain"]
