"""Fixed-grant repairs are compared with the unchanged public analysis reader."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agentmandate import Mandate, Quantity, analyse, load
from agentmandate._delegation import (
    DelegationAttachment,
    DelegationChain,
    analyse_delegations,
)
from agentmandate._remediation import _manifest, plan
from agentmandate._remediation_delegations import _DelegationScope
from agentmandate._required_workflows import _Requirements
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/delegated-remediation"
LOCATOR = "examples/delegated-remediation/capture.json"
AS_OF = "2026-10-17T12:00:00Z"
NAMES = ("select_rows", "export_rows", "purge_rows")


def inputs():
    return (
        tuple(DelegationAttachment.from_json((EXAMPLE / f"{name}-attachment.json").read_text())
              for name in NAMES),
        (DelegationChain.from_json((EXAMPLE / "chain.json").read_text()),),
        {LOCATOR: (EXAMPLE / "capture.json").read_bytes()},
        AS_OF, "src/export_service.py", "export_agent",
    )


def requirements(mandate=None):
    manifest_bytes = (EXAMPLE / "manifest.json").read_bytes()
    annotation_bytes = (EXAMPLE / "required-export.json").read_bytes()
    if mandate is None:
        mandate = load(EXAMPLE / "manifest.json")
    else:
        manifest_bytes = json.dumps(_manifest(mandate), sort_keys=True).encode()
        annotation = json.loads(annotation_bytes)
        annotation["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        annotation_bytes = json.dumps(annotation).encode()
    return _Requirements.load(annotation_bytes, mandate, hashlib.sha256(manifest_bytes).hexdigest())


def test_workflow_pin_for_a_modified_budget_cannot_be_reused_on_the_original_manifest():
    mandate = load(EXAMPLE / "manifest.json")
    modified = replace(mandate, limits=replace(mandate.limits, quantities={
        "exported_rows": Quantity.parse({"amount": "6", "unit": "record"}, "budget"),
    }))
    reviewed = requirements(modified)
    original_digest = hashlib.sha256((EXAMPLE / "manifest.json").read_bytes()).hexdigest()
    assert requirements().manifest_sha256 == original_digest
    assert reviewed.manifest_sha256 != original_digest
    assert reviewed.manifest_sha256 == hashlib.sha256(
        json.dumps(_manifest(modified), sort_keys=True).encode(),
    ).hexdigest()
    annotation = json.loads((EXAMPLE / "required-export.json").read_bytes())
    annotation["manifest_sha256"] = reviewed.manifest_sha256
    with pytest.raises(ValueError, match="exact baseline manifest"):
        _Requirements.load(json.dumps(annotation).encode(), mandate, original_digest)


def direct(mandate, records, *, candidate=False):
    attachments, chains, captures, as_of, source, binding = records
    active = tuple(a for a in attachments if not candidate or a.target.tool in mandate.tool_names)
    return analyse_delegations(mandate, active, chains, captures, as_of=as_of,
                               target_source=source, target_binding=binding)


def test_joint_tool_and_quantity_repair_keeps_grants_and_required_work():
    mandate = load(EXAMPLE / "manifest.json")
    records = inputs()
    scope = _DelegationScope.from_inputs(*records)
    original = tuple(item.to_json() for item in records[1])
    result = plan(
        mandate, delegation_scope=scope, required_workflows=requirements(),
        keep_tools=("select_rows", "export_rows"), ceiling_grids=("export_rows=0:2:1",),
        pareto=True,
    )
    assert result["baseline"] == analyse(mandate).as_dict()
    assert result["baseline"] == direct(mandate, records).authority.as_dict()
    assert len(result["delegations"]["findings"]) == 1
    assert result["delegations"]["repairable_tool_findings"] == result["delegations"]["findings"]
    candidate, = result["candidates"]
    assert [(e["tool"], e["kind"]) for e in candidate["edits"]] == [
        ("purge_rows", "remove_tool"), ("export_rows", "tighten_ceiling"),
    ]
    changed = Mandate.parse(candidate["manifest"])
    assert changed.tool("export_rows").ceiling.amount == 2
    assert changed.limits == mandate.limits
    assert not direct(changed, records, candidate=True).findings
    assert candidate["authority"] == analyse(changed).as_dict()
    assert candidate["delegations"]["inactive_attachments"] == ["attachments/synthetic/purge_rows"]
    assert candidate["delegations"]["inputs"] == result["delegations"]["inputs"]
    assert all(r["failure"] is None for r in candidate["required_workflows"])
    assert result["search"]["delegation_rejections"] > 0
    assert result["search"]["required_workflow_rejections"] > 0
    assert tuple(item.to_json() for item in records[1]) == original


@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize("defect", [
    "expired_attachment", "expired_hop", "incomplete_surface", "partial_history",
    "duration", "outside_window", "chain_widens", "incomparable", "wrong_binding",
    "duplicate_attachment", "duplicate_chain", "unknown_tool", "wrong_domain",
    "tamper", "missing_capture", "unreviewed",
])
def test_chain_and_trust_defects_stop_before_removal_can_hide_them(discovery, defect):
    records = list(inputs())
    chain = records[1][0].as_dict()
    attachment = records[0][0].as_dict()
    if defect == "expired_attachment":
        attachment["evidence"]["expires"] = "2026-10-16"
    elif defect == "expired_hop":
        chain["hops"][0]["evidence"]["expires"] = "2026-10-16"
    elif defect == "incomplete_surface":
        chain["hops"][0]["surface"]["effects"]["completeness"] = "partial"
    elif defect == "partial_history":
        chain["hops"][0]["actor_history"] = "partial"
    elif defect == "duration":
        chain["hops"][0]["validity"] = {"kind": "duration", "ttl_seconds": 300}
    elif defect == "outside_window":
        records[3] = "2026-11-01T00:00:00Z"
    elif defect == "chain_widens":
        chain["hops"][0]["surface"]["effects"]["members"] = ["read"]
    elif defect == "incomparable":
        chain["hops"][0]["surface"]["tools"]["domain"] = "other"
    elif defect == "wrong_binding":
        records[5] = "other_agent"
    elif defect == "unknown_tool":
        attachment["target"]["tool"] = "absent"
    elif defect == "wrong_domain":
        attachment["principal"]["domains"]["effects"] = "other"
    elif defect == "tamper":
        records[2] = {LOCATOR: b"{}"}
    elif defect == "missing_capture":
        records[2] = {}
    elif defect == "unreviewed":
        attachment["evidence"] = {"confidence": "exact", "review": "unreviewed"}
    records[0] = (DelegationAttachment.from_json(json.dumps(attachment)), *records[0][1:])
    records[1] = (DelegationChain.from_json(json.dumps(chain)),)
    if defect == "duplicate_attachment":
        records[0] += (records[0][0],)
    if defect == "duplicate_chain":
        records[1] *= 2
    result = plan(
        load(EXAMPLE / "manifest.json"), delegation_scope=_DelegationScope.from_inputs(*records),
        **({"discover_ceilings": ("export_rows=1",)} if discovery else {}),
    )
    assert result["status"] == "input_requires_review"
    assert result["delegations"]["findings"] and not result["candidates"]
    assert result["search"]["combinations_examined"] == 0
    assert result["baseline"] == direct(
        load(EXAMPLE / "manifest.json"), records,
    ).authority.as_dict()
    if discovery:
        assert not result["discovery"]["frontier_complete_within_domain"]


def test_grant_excess_alone_is_a_finding_and_starts_repair_search():
    mandate = load(EXAMPLE / "manifest.json")
    mandate = replace(mandate, limits=replace(mandate.limits, quantities={
        "exported_rows": Quantity.parse({"amount": "6", "unit": "record"}, "budget"),
    }))
    result = plan(mandate, delegation_scope=_DelegationScope.from_inputs(*inputs()),
                  keep_tools=("select_rows", "export_rows"))
    assert not result["baseline"]["breaches"] and not result["baseline_lint"]
    candidate, = result["candidates"]
    assert candidate["edits"] == [{"tool": "purge_rows", "kind": "remove_tool"}]


def test_discovery_cannot_repair_tool_surface_by_tightening_unrelated_quantities():
    result = plan(
        load(EXAMPLE / "manifest.json"), delegation_scope=_DelegationScope.from_inputs(*inputs()),
        discover_ceilings=("export_rows=1",), required_workflows=requirements(),
    )
    assert result["status"] == "no_feasible_candidate_in_declared_domain"
    assert result["discovery"]["frontier_complete_within_domain"]
    assert result["discovery"]["resolved_points"] == result["discovery"]["domain_points"]
    assert not result["candidates"] and result["search"]["candidates_analyzed"] == 0
    assert result["discovery"]["probes"][0]["status"] == "delegation_rejected"


def test_removing_an_excessive_sole_producer_cannot_manufacture_a_repair():
    mandate = load(EXAMPLE / "manifest.json")
    mandate = replace(mandate, tools=tuple(
        replace(t, effect="irreversible", requires_approval=True) if t.name == "select_rows"
        else replace(t, effect="write") if t.name == "purge_rows" else t
        for t in mandate.tools
    ))
    result = plan(
        mandate, delegation_scope=_DelegationScope.from_inputs(*inputs()),
        keep_tools=("export_rows",), ceiling_options=("export_rows=2",),
    )
    assert {f["tool"] for f in result["delegations"]["repairable_tool_findings"]} == {"select_rows"}
    assert not result["candidates"]


def test_snapshots_own_canonical_records_and_capture_mapping():
    records = inputs()
    scope = _DelegationScope.from_inputs(*records)
    identity = hashlib.sha256(records[1][0].to_json().encode()).hexdigest()
    records[2].clear()
    object.__setattr__(records[0][0].target, "tool", "absent")
    object.__setattr__(records[1][0].hops[0].evidence, "review", "rejected")
    result = scope.resolve(load(EXAMPLE / "manifest.json"))
    assert not result.findings and len(result.repairable_findings) == 1
    assert result.report["inputs"]["chains"] == [identity]


@pytest.mark.parametrize("empty", [0, 1])
def test_empty_evidence_configuration_is_refused(empty):
    records = list(inputs())
    records[empty] = ()
    with pytest.raises(ValueError, match="requires attachments and chains"):
        _DelegationScope.from_inputs(*records)


@pytest.mark.parametrize("discovery", [False, True])
def test_changed_trust_aborts_instead_of_returning_partial_candidates(monkeypatch, discovery):
    original = _DelegationScope.resolve
    invalid = list(inputs())
    invalid[2] = {LOCATOR: b"changed"}
    invalid = _DelegationScope.from_inputs(*invalid)

    def changed(self, mandate, *, candidate=False):
        return original(invalid if candidate else self, mandate, candidate=candidate)

    monkeypatch.setattr(_DelegationScope, "resolve", changed)
    with pytest.raises(ValueError, match="eligibility changed"):
        plan(
            load(EXAMPLE / "manifest.json"),
            delegation_scope=_DelegationScope.from_inputs(*inputs()),
            **({"discover_ceilings": ("export_rows=1",)} if discovery else {}),
        )


def argv():
    args = ["remediate", str(EXAMPLE / "manifest.json")]
    for name in NAMES:
        args += ["--delegation-attachment", str(EXAMPLE / f"{name}-attachment.json")]
    return args + [
        "--delegation-chain", str(EXAMPLE / "chain.json"),
        "--delegation-capture", f"{LOCATOR}={EXAMPLE / 'capture.json'}",
        "--delegation-as-of", AS_OF, "--delegation-target-source", "src/export_service.py",
        "--delegation-target-binding", "export_agent",
    ]


def test_cli_joint_repair_and_report_only_baseline_exit(capsys):
    args = argv() + ["--keep-tool", "select_rows", "--keep-tool", "export_rows",
                     "--required-workflows", str(EXAMPLE / "required-export.json"),
                     "--ceiling-grid", "export_rows=0:2:1", "--pareto"]
    assert main([*args, "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert len(report["candidates"]) == 1 and report["delegations"]["findings"]
    assert main(args) == 1
    text = capsys.readouterr().out
    assert "REJECTED DELEGATION" in text and "grants unchanged" in text
    assert "CANDIDATE 1" in text and "DELEGATIONS" in text


def test_cli_discovery_names_the_fixed_delegation_boundary(capsys):
    assert main([*argv(), "--discover-ceiling", "export_rows=1"]) == 1
    assert "ceiling or approval changes cannot resolve that excess" in capsys.readouterr().out


def test_cli_grant_finding_alone_exits_one_and_clean_binding_exits_zero(tmp_path, capsys):
    raw = json.loads((EXAMPLE / "manifest.json").read_text())
    raw["limits"]["quantities"]["exported_rows"]["amount"] = "6"
    path = tmp_path / "clean-authority.json"
    path.write_text(json.dumps(raw))
    args = argv()
    args[1] = str(path)
    assert main([*args, "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert not report["baseline"]["breaches"] and not report["baseline_lint"]
    raw["tools"][-1]["effect"] = "write"
    path.write_text(json.dumps(raw))
    assert main([*args, "--json"]) == 0
    assert not json.loads(capsys.readouterr().out)["delegations"]["findings"]


@pytest.mark.parametrize("missing", ["--delegation-attachment", "--delegation-chain",
                                    "--delegation-capture", "--delegation-as-of",
                                    "--delegation-target-source", "--delegation-target-binding"])
def test_partial_cli_inputs_exit_two_with_no_partial_output(missing, capsys):
    args = argv()
    while missing in args:
        index = args.index(missing)
        del args[index:index + 2]
    assert main([*args, "--json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "error:" in captured.err


def test_condition_composition_is_refused_before_any_input_read(capsys):
    assert main(["remediate", "absent", "--condition", "absent",
                 "--delegation-attachment", "absent"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and "cannot be combined" in captured.err
    with pytest.raises(ValueError, match="cannot be combined"):
        plan(load(EXAMPLE / "manifest.json"), condition_scope=object(), delegation_scope=object())


@pytest.mark.parametrize("budget", ["4", "5", "6", "7"])
@pytest.mark.parametrize("step", [1, 2])
@pytest.mark.parametrize("allow_purge", [False, True])
@pytest.mark.parametrize("discovery", [False, True])
def test_frontiers_match_full_direct_reader_enumeration(budget, step, allow_purge, discovery):
    mandate = load(EXAMPLE / "manifest.json")
    mandate = replace(mandate, limits=replace(mandate.limits, quantities={
        "exported_rows": Quantity.parse({"amount": budget, "unit": "record"}, "budget"),
    }))
    records = list(inputs())
    if allow_purge:
        chain = records[1][0].as_dict()
        for hop in chain["hops"]:
            hop["surface"]["effects"]["members"] = ["irreversible", "read", "write"]
        records[1] = (DelegationChain.from_json(json.dumps(chain)),)
    scope = _DelegationScope.from_inputs(*records)
    result = plan(
        mandate, delegation_scope=scope, required_workflows=requirements(mandate),
        keep_tools=("select_rows", "export_rows"), max_candidates=100, max_evaluations=100,
        **({"discover_ceilings": (f"export_rows={step}",)} if discovery else
           {"ceiling_grids": (f"export_rows=0:2:{step}",), "pareto": True}),
    )
    baseline = direct(mandate, records)
    if not baseline.authority.breaches and not baseline.findings:
        assert not result["candidates"]
        return
    domain = sorted({*range(0, 3, step), 3})
    feasible = []
    for cap in domain:
        for remove in ([False] if discovery else [False, True]):
            edits = int(cap != 3) + int(remove)
            if not 1 <= edits <= 2:
                continue
            candidate = replace(mandate, tools=tuple(
                replace(t, ceiling=Quantity.parse({"amount": str(cap), "unit": "record"}, "cap"))
                if t.name == "export_rows" else t for t in mandate.tools
                if not (remove and t.name == "purge_rows")
            ))
            analysis = direct(candidate, records, candidate=True)
            if not analysis.findings and not analysis.authority.breaches and all(
                row["failure"] is None for row in requirements(mandate).assess(candidate, 4)
            ):
                feasible.append((cap, remove, edits))
    expected = {p for p in feasible if not any(q != p and q[0] >= p[0] and q[1] <= p[1]
                                              and q[2] <= p[2] for q in feasible)}
    actual = {(int(c["manifest"]["tools"][1]["ceiling"]["amount"]),
               "purge_rows" not in {t["name"] for t in c["manifest"]["tools"]}, len(c["edits"]))
              for c in result["candidates"]}
    assert actual == expected
    if discovery:
        assert result["discovery"]["frontier_complete_within_domain"]


@pytest.mark.parametrize(
    "case", json.loads(
        (ROOT / "tests/fixtures/delegated-remediation-v1.json").read_text(),
    )["cases"],
    ids=lambda case: case["name"],
)
def test_complete_cli_results_replay_exactly(case, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    assert main(case["argv"]) == case["exit"]
    captured = capsys.readouterr()
    assert hashlib.sha256(captured.out.encode()).hexdigest() == case["stdout_sha256"]
    assert captured.err == case["stderr"]
