"""Export refusal, exact identities, CLI writes and independent native decisions."""

import copy
import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentmandate._cedar_export import export, render
from agentmandate._cedar_export_files import write_bundle
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/cedar-export"
MANIFEST = json.loads((EXAMPLE / "manifest.json").read_text())
MAPPING = json.loads((EXAMPLE / "mapping.json").read_text())


def compile_manifest(manifest=None, mapping=None, **kwargs):
    return export(
        json.dumps(MANIFEST if manifest is None else manifest).encode(),
        json.dumps(MAPPING if mapping is None else mapping).encode(),
        **kwargs,
    )


def test_complete_export_is_deterministic_and_scoped():
    result = export(
        (EXAMPLE / "manifest.json").read_bytes(), (EXAMPLE / "mapping.json").read_bytes()
    )
    assert result == json.loads((EXAMPLE / "generated/export.json").read_text())
    assert result["status"] == "exported" and result["losses"] == []
    assert result["native_validation"] == "not_run"
    assert "not deployment activation" in result["scope"]
    assert "principal in" not in result["policies"]
    assert "context has approved && context.approved" in result["policies"]
    assert len(result["tests"]) == 18
    assert "CEDAR exported" in render(result)
    assert "principal == ReleaseGate::User" in render(result)
    second = copy.deepcopy(MANIFEST)
    second["tools"].reverse()
    assert compile_manifest(second)["policies"] == result["policies"]


def test_multiple_explicit_principals_and_collision_free_negative_cases():
    mapping = copy.deepcopy(MAPPING)
    mapping["namespace"] = "App::Release"
    mapping["principals"]["caller"].append({"type": "User", "id": "__agentmandate_unmapped__"})
    mapping["resource"]["id"] = "__agentmandate_unmapped__"
    result = compile_manifest(mapping=mapping)
    assert " || principal == " in result["policies"]
    assert any(row["name"] == "publish_release:allowed-1" for row in result["tests"])
    negative = next(
        row for row in result["tests"] if row["name"] == "publish_release:unmapped-principal"
    )
    assert negative["request"]["principal"]["id"] == "__agentmandate_unmapped___"


def test_stateful_controls_are_refused_and_partial_never_says_clean():
    manifest = copy.deepcopy(MANIFEST)
    manifest["limits"] = {
        "total": {"amount": 10, "currency": "GBP"},
        "effects": {"irreversible": 3},
    }
    manifest["roles"] = {"proposer": ["publish_release"]}
    manifest["tools"][0]["produces"] = "case"
    manifest["tools"][1].update(
        requires=["case"],
        value_arg="amount",
        scope_key="case",
        ceiling={"amount": 5, "currency": "GBP"},
    )
    refused = compile_manifest(manifest)
    assert refused["status"] == "refused" and refused["policies"] is None
    assert {row["code"] for row in refused["losses"]} == {
        "limits.total",
        "limits.effects",
        "roles",
        "tool.produces",
        "tool.requires",
        "tool.ceiling",
    }
    assert "per-call amount check is not equivalent" in render(refused)
    partial = compile_manifest(manifest, allow_partial=True)
    assert partial["status"] == "partial_export" and partial["policies"] is not None
    assert partial["losses"] == refused["losses"]
    assert partial["native_validation"] == "not_run"


@pytest.mark.parametrize(
    "path,value",
    [
        ([], []),
        (["cedar_export_version"], True),
        (["cedar_export_version"], 2),
        (["agent"], "other"),
        (["identity"], "other"),
        (["namespace"], "App::if"),
        (["namespace"], "App::"),
        (["namespace"], "unsafe-type"),
        (["approval_context"], "a.b"),
        (["approval_context"], "context"),
        (["approval_context"], "é"),
        (["approval_context"], ""),
        (["approval_context"], " approved"),
        (["approval_context"], "bad\nname"),
        (["principals"], []),
        (["principals"], {}),
        (["principals", "caller"], []),
        (["principals", "caller"], {}),
        (["principals", "caller", 0], []),
        (["principals", "caller", 0, "type"], "Action"),
        (["principals", "caller", 0, "id"], None),
        (["resource", "type"], "Resource::Type"),
        (["resource", "id"], 2),
        (["actions"], []),
        (["actions"], {}),
        (["actions", "read_release"], ""),
    ],
)
def test_malformed_mapping_cannot_emit_a_policy(path, value):
    mapping = copy.deepcopy(MAPPING)
    if not path:
        mapping = value
    else:
        parent = mapping
        for item in path[:-1]:
            parent = parent[item]
        parent[path[-1]] = value
    with pytest.raises(ValueError):
        compile_manifest(mapping=mapping)


@pytest.mark.parametrize("change", ["extra", "missing", "duplicate-action", "duplicate-principal"])
def test_ambiguous_mapping_is_rejected(change):
    mapping = copy.deepcopy(MAPPING)
    if change == "extra":
        mapping["unknown"] = True
    elif change == "missing":
        del mapping["identity"]
    elif change == "duplicate-action":
        mapping["actions"]["publish_release"] = mapping["actions"]["read_release"]
    else:
        mapping["principals"]["service"] = mapping["principals"]["caller"]
    with pytest.raises(ValueError):
        compile_manifest(mapping=mapping)


def test_duplicate_json_keys_are_not_overwritten():
    with pytest.raises(ValueError, match="duplicate"):
        export(json.dumps(MANIFEST).encode(), b'{"agent":"a","agent":"b"}')


def test_cli_writes_a_complete_bundle_and_does_not_overwrite(tmp_path, capsys):
    target = tmp_path / "bundle"
    args = [
        "cedar",
        "export",
        str(EXAMPLE / "manifest.json"),
        "--mapping",
        str(EXAMPLE / "mapping.json"),
        "--output-dir",
        str(target),
        "--json",
    ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert json.loads((target / "export.json").read_text()) == result
    assert (target / "policies.cedar").read_text() == result["policies"]
    assert main(args) == 2
    captured = capsys.readouterr()
    assert not captured.out and "already exists" in captured.err
    assert not list(tmp_path.glob(".agentmandate-export-*"))


def test_broken_symlink_output_is_not_replaced(tmp_path):
    link = tmp_path / "output"
    link.symlink_to(tmp_path / "absent")
    with pytest.raises(ValueError):
        write_bundle(compile_manifest(), link)
    assert link.is_symlink()


def test_export_io_failure_leaves_no_partial_output(tmp_path, monkeypatch, capsys):
    original = Path.write_text

    def fail_schema(path, *args, **kwargs):
        if path.name == "schema.json":
            raise OSError("simulated write failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_schema)
    destination = tmp_path / "bundle"
    assert (
        main(
            [
                "cedar",
                "export",
                str(EXAMPLE / "manifest.json"),
                "--mapping",
                str(EXAMPLE / "mapping.json"),
                "--output-dir",
                str(destination),
            ]
        )
        == 2
    )
    assert not capsys.readouterr().out
    assert not destination.exists() and not list(tmp_path.glob(".agentmandate-export-*"))


def test_cli_missing_or_malformed_inputs_fail_before_output(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    args = ["cedar", "export", str(missing), "--mapping", str(EXAMPLE / "mapping.json")]
    assert main(args) == 2 and not capsys.readouterr().out
    missing.write_bytes(b"\xff")
    assert main(args) == 2 and not capsys.readouterr().out


def test_cli_partial_bundle_retains_failure_and_refusal_creates_nothing(tmp_path, capsys):
    path = tmp_path / "manifest.json"
    manifest = copy.deepcopy(MANIFEST)
    manifest["limits"] = {"effects": {"irreversible": 1}}
    path.write_text(json.dumps(manifest))
    target = tmp_path / "bundle"
    args = [
        "cedar",
        "export",
        str(path),
        "--mapping",
        str(EXAMPLE / "mapping.json"),
        "--output-dir",
        str(target),
    ]
    assert main(args) == 1 and not target.exists()
    assert "CEDAR refused" in capsys.readouterr().out
    assert main([*args, "--allow-partial"]) == 1 and target.is_dir()
    assert "CEDAR partial_export" in capsys.readouterr().out


def test_native_policy_and_independent_cartesian_decisions(tmp_path):
    if not (EXAMPLE / "node_modules/@cedar-policy/cedar-wasm").is_dir():
        if os.environ.get("AGENTMANDATE_REQUIRE_CEDAR_NATIVE"):
            pytest.fail("the required pinned native Cedar implementation is missing")
        pytest.skip("native Cedar export check requires npm ci in examples/cedar-export")
    mapping = copy.deepcopy(MAPPING)
    mapping["namespace"] = "App::Release"
    mapping["principals"]["caller"].append({"type": "User", "id": 'other"\\operator'})
    mapping["actions"]["publish_release"] = 'Publish"\\Release'
    mapping["resource"]["id"] = 'repo"\\name'
    result = compile_manifest(mapping=mapping)
    # Expectations come from source tool declarations and explicit mappings,
    # independently of the compiler's generated cases and policy strings.
    cases = []
    namespace = mapping["namespace"]
    actors = [row for rows in mapping["principals"].values() for row in rows]
    actors.append({"type": "User", "id": "unmapped"})
    for tool, actor, resource_id, approval in itertools.product(
        MANIFEST["tools"], actors, [mapping["resource"]["id"], "unmapped"], [None, False, True]
    ):
        permitted = (
            actor in mapping["principals"][tool.get("principal", "caller")]
            and resource_id == mapping["resource"]["id"]
            and (not tool.get("requires_approval") or approval is True)
        )
        cases.append(
            {
                "name": f"independent-{len(cases)}",
                "request": {
                    "principal": {"type": f"{namespace}::{actor['type']}", "id": actor["id"]},
                    "action": {
                        "type": f"{namespace}::Action",
                        "id": mapping["actions"][tool["name"]],
                    },
                    "resource": {
                        "type": f"{namespace}::{mapping['resource']['type']}",
                        "id": resource_id,
                    },
                    "context": {} if approval is None else {mapping["approval_context"]: approval},
                },
                "expected": "allow" if permitted else "deny",
            }
        )
    result["tests"] = cases
    directory = tmp_path / "native"
    write_bundle(result, directory)
    run = subprocess.run(
        [shutil.which("node") or "node", str(EXAMPLE / "check.mjs"), str(directory)],
        capture_output=True,
        text=True,
        check=True,
    )
    native = json.loads(run.stdout)
    assert len(native["decisions"]) == 72
    assert native["validation"]["validationErrors"] == []
    assert native["descendant_principal"] == "deny"


def test_bundle_rename_failure_cleans_its_reservation(tmp_path, monkeypatch):
    def fail_rename(*args):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "rename", fail_rename)
    target = tmp_path / "bundle"
    with pytest.raises(OSError):
        write_bundle(compile_manifest(), target)
    assert not target.exists() and not list(tmp_path.glob(".agentmandate-export-*"))


def test_destination_created_during_staging_is_not_overwritten(tmp_path, monkeypatch):
    target = tmp_path / "bundle"
    original = Path.write_text

    def competing_directory(path, *args, **kwargs):
        if path.name == "schema.json":
            target.mkdir()
            (target / "keep").write_bytes(b"another process")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", competing_directory)
    with pytest.raises(FileExistsError):
        write_bundle(compile_manifest(), target)
    assert (target / "keep").read_bytes() == b"another process"


def test_non_replacing_platform_rename_does_not_need_a_reservation(tmp_path, monkeypatch):
    from agentmandate import _cedar_export_files as files

    monkeypatch.setattr(files, "_RESERVE_RENAME", False)
    target = tmp_path / "bundle"
    write_bundle(compile_manifest(), target)
    assert (target / "export.json").is_file()


def test_non_replacing_platform_failure_keeps_a_competing_path(tmp_path, monkeypatch):
    from agentmandate import _cedar_export_files as files

    monkeypatch.setattr(files, "_RESERVE_RENAME", False)
    target = tmp_path / "bundle"

    def non_replacing_rename(stage, destination):
        destination.mkdir()
        (destination / "keep").write_bytes(b"other process")
        raise FileExistsError("Windows rename does not replace a destination")

    monkeypatch.setattr(Path, "rename", non_replacing_rename)
    with pytest.raises(FileExistsError):
        write_bundle(compile_manifest(), target)
    assert (target / "keep").read_bytes() == b"other process"
