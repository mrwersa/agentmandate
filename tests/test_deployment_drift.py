"""Exact export joins, conservative absence claims and independent Authority."""

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentmandate._deployment_drift import evaluate, render
from agentmandate._rego_export import export as export_rego
from agentmandate.cli import main
from agentmandate.manifest import loads
from agentmandate.reach import analyse

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/deployment-drift"
MANIFEST = (EXAMPLE / "manifest.json").read_bytes()


def config(target="rego"):
    return json.loads((EXAMPLE / f"{target}-aligned.json").read_text())


def run(value=None, *, source=MANIFEST, root=ROOT, as_of="2026-10-11"):
    return evaluate(
        source, json.dumps(config() if value is None else value).encode(), root=root, as_of=as_of
    )


def codes(report):
    return {row["code"] for row in report["findings"]}


def local_files(tmp_path, target="rego"):
    value = config(target)
    for field in ("mapping", "receipt"):
        name = field + ".json"
        (tmp_path / name).write_bytes((ROOT / value["export"][field]).read_bytes())
        value["export"][field] = name
    for name, locator in value["policy"]["files"].items():
        (tmp_path / name).write_bytes((ROOT / locator).read_bytes())
        value["policy"]["files"][name] = name
    return value


@pytest.mark.parametrize("target", ["cedar", "rego"])
def test_aligned_configuration_has_pinned_scoped_result(target):
    value = config(target)
    report = evaluate(
        MANIFEST, (EXAMPLE / f"{target}-aligned.json").read_bytes(), root=ROOT, as_of="2026-10-11"
    )
    assert report == json.loads(
        (ROOT / f"tests/fixtures/deployment-drift-{target}-v1.json").read_text()
    )
    assert report["configuration_consistent"] and not report["findings"]
    assert report["status"] == "consistent_with_declared_configuration"
    assert report["runtime_continuity"] == "not_assessed"
    assert report["native_validation"] == "not_run"
    assert report["authority"] == analyse(loads(MANIFEST.decode())).as_dict()
    assert "not authenticated live enforcement" in render(report)
    assert "ARTIFACT schema.json: matches" in render(report)
    assert {row["tool"] for row in report["tools"]} == set(value["inventory"]["tools"])


@pytest.mark.parametrize("target", ["cedar", "rego"])
@pytest.mark.parametrize("field", ["action", "resource", "approval_context", "policy_revision"])
def test_route_mismatches_are_specific_without_reset_claim(target, field):
    value = config(target)
    row = next(r for r in value["gateway"]["routes"] if r["tool"] == "publish_release")
    row[field] = {**row[field], "id": "wrong"} if isinstance(row[field], dict) else "wrong"
    report = run(value)
    assert codes(report) == {"deployment.route-mismatch"}
    assert report["findings"][0]["subject"] == f"publish_release.{field}"
    assert report["authority"] == run(config(target))["authority"]
    assert report["runtime_continuity"] == "not_assessed"


@pytest.mark.parametrize("target", ["cedar", "rego"])
def test_principal_widening_narrowing_and_class_swap_are_distinct(target):
    value = config(target)
    row = value["gateway"]["routes"][0]
    extra = {"type": "ReleaseGate::User", "id": "outsider"} if target == "cedar" else "outsider"
    row["principals"].append(extra)
    assert codes(run(value)) == {"deployment.principal-widened"}
    row["principals"] = []
    assert codes(run(value)) == {"deployment.principal-narrowed"}
    row["principals"] = value["gateway"]["routes"][1]["principals"]
    assert codes(run(value)) == {"deployment.principal-widened", "deployment.principal-narrowed"}


@pytest.mark.parametrize("mediation", ["bypassed", "unknown"])
def test_mediation_never_succeeds_without_required_evaluation(mediation):
    value = config()
    value["gateway"]["routes"][0]["mediation"] = mediation
    report = run(value)
    assert codes(report) == {"deployment.mediation-" + mediation}
    assert "FINDING" in render(report)


def test_extra_inventory_and_gateway_tools_are_retained_when_partial():
    value = config()
    value["inventory"].update(coverage="partial", tools=["new_inventory_tool"])
    value["gateway"]["coverage"] = "partial"
    row = copy.deepcopy(value["gateway"]["routes"][0])
    row["tool"] = "new_gateway_tool"
    value["gateway"]["routes"] = [row]
    report = run(value)
    assert codes(report) == {"deployment.coverage-incomplete", "deployment.tool-undeclared"}
    assert {
        r["subject"] for r in report["findings"] if r["code"] == "deployment.tool-undeclared"
    } == {
        "new_inventory_tool",
        "new_gateway_tool",
    }
    assert all(
        r["inventory_presence"] == "unresolved"
        for r in report["tools"]
        if r["tool"] not in value["inventory"]["tools"]
    )
    assert all(
        r["route_presence"] == "unresolved"
        for r in report["tools"]
        if r["tool"] != "new_gateway_tool"
    )


def test_complete_configuration_can_report_missing_inventory_and_route():
    value = config()
    value["inventory"]["tools"] = []
    value["gateway"]["routes"] = []
    report = run(value)
    assert codes(report) == {"deployment.tool-absent", "deployment.route-missing"}
    assert all(row["expected"] is not None for row in report["tools"])


@pytest.mark.parametrize("coverage", ["partial", "unknown"])
def test_partial_policy_does_not_establish_absence(coverage):
    value = config()
    value["policy"].update(coverage=coverage, files={})
    report = run(value)
    assert codes(report) == {"deployment.coverage-incomplete", "deployment.policy-unresolved"}
    assert {row["status"] for row in report["policy"]["artifacts"]} == {"unresolved"}


@pytest.mark.parametrize(
    "as_of,current",
    [
        ("2026-10-10", False),
        ("2026-10-11", True),
        ("2026-11-08", True),
        ("2026-11-09", False),
    ],
)
def test_observation_and_expiry_window_is_inclusive(as_of, current):
    report = run(as_of=as_of)
    assert report["snapshot_current"] is current
    assert report["configuration_consistent"] is current
    assert codes(report) == (set() if current else {"deployment.snapshot-not-current"})


def test_stale_complete_lists_do_not_authorize_absence_claims():
    value = config()
    value["inventory"]["tools"] = []
    value["gateway"]["routes"] = []
    value["policy"]["files"] = {}
    report = run(value, as_of="2026-11-09")
    assert codes(report) == {"deployment.snapshot-not-current", "deployment.policy-unresolved"}
    assert all(
        row["inventory_presence"] == row["route_presence"] == "unresolved"
        for row in report["tools"]
    )


@pytest.mark.parametrize("field", ["agent", "identity"])
def test_configuration_identity_mismatch_is_a_finding(field):
    value = config()
    value[field] = "different"
    assert codes(run(value)) == {"deployment.identity-mismatch"}


def test_null_declared_identity_remains_supported(tmp_path):
    value = local_files(tmp_path)
    manifest = json.loads(MANIFEST)
    manifest["identity"] = None
    source = json.dumps(manifest).encode()
    value["identity"] = None
    mapping = json.loads((tmp_path / "mapping.json").read_text())
    mapping["identity"] = None
    mapping_content = json.dumps(mapping).encode()
    (tmp_path / "mapping.json").write_bytes(mapping_content)
    (tmp_path / "receipt.json").write_text(json.dumps(export_rego(source, mapping_content)))
    assert run(value, source=source, root=tmp_path)["configuration_consistent"]


@pytest.mark.parametrize("change", ["receipt", "mapping-whitespace", "cleared-losses"])
def test_receipt_cannot_override_recomputed_source_or_losses(change, tmp_path):
    value = local_files(tmp_path)
    source = MANIFEST
    if change == "mapping-whitespace":
        p = tmp_path / "mapping.json"
        p.write_bytes(p.read_bytes() + b" ")
    else:
        receipt = json.loads((tmp_path / "receipt.json").read_text())
        if change == "cleared-losses":
            manifest = json.loads(source)
            manifest["limits"] = {"effects": {"irreversible": 3}}
            source = json.dumps(manifest).encode()
            receipt = export_rego(
                source, (tmp_path / "mapping.json").read_bytes(), allow_partial=True
            )
            receipt.update(losses=[], status="exported")
        else:
            receipt["mapping"]["resource"] = "different"
        (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    report = run(value, source=source, root=tmp_path)
    assert "deployment.export-mismatch" in codes(report)
    if change == "cleared-losses":
        assert "deployment.control-uncompiled" in codes(report)
        assert report["authority"]["breaches"]
        assert report["export"]["status"] == "partial_export"


def test_valid_partial_receipt_keeps_baseline_breach_separate(tmp_path):
    value = local_files(tmp_path)
    manifest = json.loads(MANIFEST)
    manifest["limits"] = {"effects": {"irreversible": 3}}
    source = json.dumps(manifest).encode()
    receipt = export_rego(source, (tmp_path / "mapping.json").read_bytes(), allow_partial=True)
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    report = run(value, source=source, root=tmp_path)
    assert report["export"]["receipt_matches"]
    assert codes(report) == {"deployment.control-uncompiled"}
    assert report["authority"] == analyse(loads(source.decode())).as_dict()
    assert report["authority"]["breaches"]


@pytest.mark.parametrize(
    "change,code",
    [
        ("missing", "deployment.policy-missing"),
        ("changed", "deployment.policy-differs"),
        ("extra", "deployment.policy-extra"),
    ],
)
def test_policy_artifacts_are_checked_as_exact_bytes(change, code, tmp_path):
    value = local_files(tmp_path)
    if change == "missing":
        del value["policy"]["files"]["policy.rego"]
    elif change == "changed":
        p = tmp_path / "policy.rego"
        p.write_bytes(p.read_bytes() + b"\n")
    else:
        (tmp_path / "extra.rego").write_text("package release_gate\nallow if true\n")
        value["policy"]["files"]["extra.rego"] = "extra.rego"
    assert codes(run(value, root=tmp_path)) == {code}


@pytest.mark.parametrize(
    "path,value",
    [
        ([], []),
        (["deployment_version"], True),
        (["deployment_version"], 2),
        (["identity"], 3),
        (["agent"], ""),
        (["environment"], " x"),
        (["observed_at"], "20261011"),
        (["observed_at"], "2026-02-30"),
        (["expires"], "2026-10-10"),
        (["export", "target"], "unknown"),
        (["export", "mapping"], []),
        (["export", "receipt"], {}),
        (["inventory", "coverage"], "full"),
        (["inventory", "tools"], {}),
        (["inventory", "tools"], ["same", "same"]),
        (["policy", "files"], []),
        (["policy", "files"], {"": "file"}),
        (["policy", "files"], {"policy.rego": None}),
        (["gateway", "routes"], {}),
        (["gateway", "routes", 0], []),
        (["gateway", "routes", 0, "mediation"], "yes"),
        (["gateway", "routes", 0, "approval_context"], False),
        (["gateway", "routes", 0, "principals"], ["same", "same"]),
    ],
)
def test_malformed_configuration_is_rejected(path, value):
    original = config()
    if not path:
        original = value
    else:
        parent = original
        for part in path[:-1]:
            parent = parent[part]
        parent[path[-1]] = value
    with pytest.raises(ValueError):
        run(original)


def test_duplicate_routes_and_json_keys_are_rejected():
    value = config()
    value["gateway"]["routes"].append(value["gateway"]["routes"][0])
    with pytest.raises(ValueError, match="duplicate route"):
        run(value)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate(
            MANIFEST,
            b'{"deployment_version":1,"deployment_version":1}',
            root=ROOT,
            as_of="2026-10-11",
        )


def test_cedar_entities_have_closed_string_fields():
    value = config("cedar")
    value["gateway"]["routes"][0]["principals"][0]["id"] = 1
    with pytest.raises(ValueError):
        run(value)


@pytest.mark.parametrize(
    "locator", ["/etc/passwd", "../outside", "a//b", "./mapping.json", "a\\b", "C:relative"]
)
def test_paths_cannot_escape_or_reinterpret_the_artifact_root(locator, tmp_path):
    value = local_files(tmp_path)
    value["export"]["mapping"] = locator
    with pytest.raises(ValueError):
        run(value, root=tmp_path)


def test_escaping_symlink_and_non_directory_root_are_rejected(tmp_path):
    value = local_files(tmp_path)
    (tmp_path / "link.json").symlink_to(ROOT / "examples/rego-export/mapping.json")
    value["export"]["mapping"] = "link.json"
    with pytest.raises(ValueError, match="inside --root"):
        run(value, root=tmp_path)
    with pytest.raises(ValueError, match="directory"):
        run(root=tmp_path / "mapping.json")


@pytest.mark.parametrize("content", [b"[]", b"{", b"\xff"])
def test_bad_receipts_are_rejected(content, tmp_path):
    value = local_files(tmp_path)
    (tmp_path / "receipt.json").write_bytes(content)
    with pytest.raises((ValueError, UnicodeError)):
        run(value, root=tmp_path)


def cli_args(path=EXAMPLE / "rego-aligned.json"):
    return [
        "deployment",
        "drift",
        str(EXAMPLE / "manifest.json"),
        "--config",
        str(path),
        "--root",
        str(ROOT),
        "--as-of",
        "2026-10-11",
    ]


def test_cli_clean_and_drifted_results_use_analysis_exit_codes(capsys):
    assert main(cli_args() + ["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["configuration_consistent"]
    assert main(cli_args(EXAMPLE / "rego-drifted.json")) == 1
    output = capsys.readouterr().out
    assert "deployment.policy-extra" in output and "deployment.mediation-bypassed" in output
    assert "AUTHORITY" in output


@pytest.mark.parametrize("change", ["missing-config", "malformed-config", "bad-date", "io"])
def test_cli_usage_errors_have_empty_stdout(change, tmp_path, capsys, monkeypatch):
    args = cli_args()
    if change == "missing-config":
        args[4] = str(tmp_path / "absent.json")
    elif change == "malformed-config":
        p = tmp_path / "broken.json"
        p.write_text("{")
        args[4] = str(p)
    elif change == "bad-date":
        args[-1] = "today"
    else:

        def fail(*args, **kwargs):
            raise OSError("simulated read failure")

        monkeypatch.setattr(Path, "read_bytes", fail)
    assert main(args + ["--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and "error:" in output.err


def test_native_extra_module_actually_widens_while_the_drift_gate_refuses(tmp_path):
    opa = os.environ.get("AGENTMANDATE_OPA") or shutil.which("opa")
    if not opa:
        if os.environ.get("AGENTMANDATE_REQUIRE_OPA_NATIVE") == "1":
            pytest.fail("required native OPA is absent")
        pytest.skip("optional native OPA is absent")
    request = tmp_path / "input.json"
    request.write_text(
        json.dumps(
            {"principal": "outsider", "action": "unknown", "resource": "other", "context": {}}
        )
    )
    base = [
        opa,
        "eval",
        "--format=json",
        "--data",
        str(ROOT / "examples/rego-export/generated/policy.rego"),
        "--input",
        str(request),
        "data.release_gate.allow",
    ]
    before = json.loads(subprocess.check_output(base, text=True))["result"][0]["expressions"][0][
        "value"
    ]
    after_args = base[:-1] + ["--data", str(EXAMPLE / "unmanaged-allow.rego"), base[-1]]
    after = json.loads(subprocess.check_output(after_args, text=True))["result"][0]["expressions"][
        0
    ]["value"]
    assert before is False and after is True
    report = evaluate(
        MANIFEST, (EXAMPLE / "rego-drifted.json").read_bytes(), root=ROOT, as_of="2026-10-11"
    )
    assert not report["configuration_consistent"] and "deployment.policy-extra" in codes(report)
