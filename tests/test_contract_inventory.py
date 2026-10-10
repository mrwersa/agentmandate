import copy
import hashlib
import json
import runpy
import sys
from pathlib import Path

import pytest

import agentmandate
from agentmandate import check, load
from agentmandate.cli import build_parser, main
from scripts import audit_contracts as audit

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/legacy-json-results.json").read_text())


def test_current_inventory_matches_all_pinned_surfaces():
    assert audit.snapshot() == json.loads(audit.BASELINE.read_text())


def test_coverage_inventory_names_every_presentation_and_real_replay_test():
    coverage = json.loads(audit.COVERAGE.read_text())
    schemas = {schema for row in audit.artifact_markers().values() for schema in row["schemas"]}
    assert {schema for row in coverage for schema in row["schemas"]} == schemas
    assert len({row["id"] for row in coverage}) == len(coverage)
    for row in coverage:
        assert (ROOT / row["doc"]).is_file()
        assert row["fixtures"] and row["tests"]
        assert row["kind"] in {"baseline", "historical_replay"}
        for path in row["fixtures"] + row["tests"]:
            assert (ROOT / path).is_file(), path
    current = audit.snapshot()
    assert set(current["public_python"]) == set(agentmandate.__all__)
    assert current["public_python"]["ManifestError"]["bases"] == ["ValueError"]
    assert "mandate inventory import" in current["cli"]
    assert "mandate continuity handover" in current["cli"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_legacy_output_and_exit_codes_remain_byte_exact(case, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    for path, digest in case["inputs"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    assert main(case["argv"]) == case["exit"]
    captured = capsys.readouterr()
    assert captured.out == case["stdout"]
    assert captured.err == case["stderr"]


def test_preserved_raw_skeletons_keep_their_expected_missing_producers():
    expected = {
        "aws-iam-access-keys": (2, {"access_key", "version"}),
        "aws-postgres-mcp": (1, {"job"}),
        "initiative-mcp": (22, {"guild", "calendar"}),
        "sentry-mcp": (3, {"resource", "projectslugor", "issue"}),
    }
    observed = {}
    for path in sorted((ROOT / "docs/evidence").glob("*/scan-skeleton.yaml")):
        findings = [f for f in check(load(path)) if f.rule == "scope.missing-producer"]
        count, scopes = expected[path.parent.name]
        assert len(findings) == count
        assert all(f.severity == "error" for f in findings)
        reported = {
            scope for scope in scopes if any(f"requires {scope!r}" in f.message for f in findings)
        }
        assert reported == scopes
        observed[path.parent.name] = (len(findings), reported)
    assert observed == expected
    for path in (ROOT / "docs/evidence").glob("*/mandate.yaml"):
        assert not [f for f in check(load(path)) if f.rule == "scope.missing-producer"]


@pytest.mark.parametrize("change", ["default", "choices", "required", "new-option"])
def test_cli_argument_changes_are_detected(change):
    parser = build_parser()
    before = audit.cli_surface(parser)
    if change == "new-option":
        parser.add_argument("--new-option")
    else:
        action = next(a for a in parser._actions if a.dest == "command")
        scan = action.choices["scan"]
        flag = next(a for a in scan._actions if a.dest == "format")
        setattr(flag, change, {"default": "mcp", "choices": ["mcp"], "required": True}[change])
    assert audit.differences(before, audit.cli_surface(parser))


def test_python_signature_change_is_detected(monkeypatch):
    before = audit.python_surface()
    monkeypatch.setattr(agentmandate, "analyse", lambda mandate, *, new_argument=None: None)
    assert audit.differences(before, audit.python_surface()) == ["/analyse/signature"]


def test_class_member_signature_change_is_detected(monkeypatch):
    before = audit.python_surface()
    monkeypatch.setattr(agentmandate.Authority, "as_dict", lambda self, *, new_argument=None: {})
    assert audit.differences(before, audit.python_surface()) == [
        "/Authority/members/as_dict/signature"
    ]


def test_accidentally_public_unlisted_root_import_is_rejected(monkeypatch):
    monkeypatch.setattr(agentmandate, "unlisted_name", 123, raising=False)
    with pytest.raises(ValueError, match="unlisted root exports: unlisted_name"):
        audit.python_surface()


def test_inline_version_checks_and_new_schema_markers_are_detected(tmp_path):
    (tmp_path / "new.py").write_text("""
ARTIFACT_VERSION = 3
SCHEMA = "agentmandate.new/v3"
if integer(raw["new_version"], "new_version") != 3:
    raise ValueError()
""")
    markers = audit.artifact_markers(tmp_path)["new.py"]
    assert markers["constants"] == {"ARTIFACT_VERSION": 3}
    assert markers["schemas"] == ["agentmandate.new/v3"]
    assert markers["version_fields"] == ["new_version"]
    assert markers["inline_versions"] == {"new_version": [3]}


def test_changed_inventory_returns_finding_with_useful_locations(tmp_path, monkeypatch, capsys):
    baseline = json.loads(audit.BASELINE.read_text())
    baseline["cli"].pop("mandate inventory import")
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(baseline))
    monkeypatch.setattr(audit, "BASELINE", path)
    assert audit.main([]) == 1
    captured = capsys.readouterr()
    assert "/cli/mandate inventory import" in captured.out and not captured.err


def test_a_candidate_cannot_renew_or_rewrite_the_baseline(tmp_path, capsys):
    before = audit.BASELINE.read_bytes()
    candidate = tmp_path / "candidate.json"
    assert audit.main(["--candidate", str(candidate)]) == 0
    assert candidate.read_bytes() == before
    assert audit.BASELINE.read_bytes() == before
    assert audit.main([]) == 0
    assert "inventory matches" in capsys.readouterr().out


@pytest.mark.parametrize("target", [audit.BASELINE, audit.COVERAGE])
def test_candidate_refuses_to_overwrite_a_baseline(target, capsys):
    before = target.read_bytes()
    with pytest.raises(SystemExit) as error:
        audit.main(["--candidate", str(target)])
    assert error.value.code == 2
    assert target.read_bytes() == before
    assert "must not overwrite" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["missing", "malformed", "array", "section"])
def test_invalid_baseline_is_a_tool_error_with_no_partial_report(
    kind, tmp_path, monkeypatch, capsys
):
    path = tmp_path / "baseline.json"
    if kind == "malformed":
        path.write_text("{")
    elif kind == "array":
        path.write_text("[]")
    elif kind == "section":
        baseline = json.loads(audit.BASELINE.read_text())
        baseline["cli"] = []
        path.write_text(json.dumps(baseline))
    monkeypatch.setattr(audit, "BASELINE", path)
    assert audit.main([]) == 2
    output = capsys.readouterr()
    assert not output.out and "error:" in output.err


def test_missing_fixture_fails_before_a_candidate_is_written(tmp_path, monkeypatch, capsys):
    coverage = copy.deepcopy(json.loads(audit.COVERAGE.read_text()))
    coverage[0]["fixtures"].append("missing-contract.json")
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(coverage))
    monkeypatch.setattr(audit, "COVERAGE", path)
    candidate = tmp_path / "candidate.json"
    assert audit.main(["--candidate", str(candidate)]) == 2
    assert not candidate.exists()
    captured = capsys.readouterr()
    assert not captured.out and "missing-contract.json" in captured.err


def test_one_byte_fixture_change_is_detected_without_touching_archival_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    source = tmp_path / "fixture.json"
    source.write_bytes(b"{}")
    coverage = [{"fixtures": ["fixture.json"]}]
    before = audit.snapshot(coverage)
    source.write_bytes(b"{} ")
    assert audit.differences(before, audit.snapshot(coverage)) == ["/fixture_sha256/fixture.json"]


def test_script_entrypoint_checks_without_writing(monkeypatch, capsys):
    before = audit.BASELINE.read_bytes()
    monkeypatch.setattr(sys, "argv", ["audit_contracts.py"])
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(ROOT / "scripts/audit_contracts.py"), run_name="__main__")
    assert error.value.code == 0
    assert "inventory matches" in capsys.readouterr().out
    assert audit.BASELINE.read_bytes() == before
