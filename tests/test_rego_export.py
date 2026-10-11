"""Strict mappings, loss refusal, CLI integration and independent native decisions."""

import copy
import hashlib
import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agentmandate._rego_export import export, render
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/rego-export"
MANIFEST = json.loads((EXAMPLE / "manifest.json").read_text())
MAPPING = json.loads((EXAMPLE / "mapping.json").read_text())


def compile_manifest(manifest=None, mapping=None, **kwargs):
    return export(
        json.dumps(MANIFEST if manifest is None else manifest).encode(),
        json.dumps(MAPPING if mapping is None else mapping).encode(),
        **kwargs,
    )


def test_complete_bundle_is_pinned_and_deterministic():
    result = export(
        (EXAMPLE / "manifest.json").read_bytes(), (EXAMPLE / "mapping.json").read_bytes()
    )
    assert result == json.loads((EXAMPLE / "generated/export.json").read_text())
    assert result["status"] == "exported" and not result["losses"]
    assert result["native_validation"] == "not_run"
    assert "not deployment activation" in result["scope"]
    assert "default allow := false" in result["policy"]
    assert 'input.context["approved"] == true' in result["policy"]
    assert "REGO exported" in render(result)
    assert "count(data.cases) > 0" in result["native_tests"]
    assert len(result["tests"]) == 21
    reordered = copy.deepcopy(MANIFEST)
    reordered["tools"].reverse()
    assert compile_manifest(reordered)["policy"] == result["policy"]


def test_multiple_principals_and_escaped_mapping_literals():
    mapping = copy.deepcopy(MAPPING)
    mapping["package"] = "platform.release"
    mapping["principals"]["caller"] += ['operator"\\secondary', "__agentmandate_unmapped__"]
    mapping["resource"] = "__agentmandate_unmapped__"
    mapping["actions"]["read_release"] = "__agentmandate_unmapped__"
    mapping["approval_context"] = 'approved"\\flag'
    result = compile_manifest(mapping=mapping)
    assert json.dumps('operator"\\secondary') in result["policy"]
    assert json.dumps(mapping["approval_context"]) in result["policy"]
    assert "publish_release:allowed-2" in {row["name"] for row in result["tests"]}
    negatives = {row["name"]: row for row in result["tests"]}
    assert negatives["read_release:unmapped-action"]["request"]["action"].endswith("___")
    assert negatives["read_release:unmapped-principal"]["request"]["principal"].endswith("___")
    assert negatives["read_release:other-resource"]["request"]["resource"].endswith("___")


def test_stateful_loss_refusal_and_partial_candidate():
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
    result = compile_manifest(manifest)
    assert result["status"] == "refused" and result["policy"] is None
    assert {row["code"] for row in result["losses"]} == {
        "limits.total",
        "limits.effects",
        "roles",
        "tool.produces",
        "tool.requires",
        "tool.ceiling",
    }
    assert "per-call amount check is not equivalent" in render(result)
    partial = compile_manifest(manifest, allow_partial=True)
    assert partial["status"] == "partial_export" and partial["policy"] is not None
    assert partial["losses"] == result["losses"]


@pytest.mark.parametrize(
    "path,value",
    [
        ([], []),
        (["rego_export_version"], True),
        (["rego_export_version"], 2),
        (["agent"], "other"),
        (["identity"], "other"),
        (["package"], "release.if"),
        (["package"], "release."),
        (["package"], "bad-name"),
        (["package"], "input"),
        (["approval_context"], ""),
        (["approval_context"], "é"),
        (["approval_context"], " approved"),
        (["approval_context"], "bad\nkey"),
        (["resource"], 2),
        (["principals"], []),
        (["principals"], {}),
        (["principals", "caller"], []),
        (["principals", "caller"], {}),
        (["principals", "caller", 0], None),
        (["actions"], []),
        (["actions"], {}),
        (["actions", "read_release"], ""),
    ],
)
def test_invalid_mapping_cannot_emit_policy(path, value):
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
        mapping["actions"]["read_release"] = mapping["actions"]["publish_release"]
    else:
        mapping["principals"]["service"] = mapping["principals"]["caller"]
    with pytest.raises(ValueError):
        compile_manifest(mapping=mapping)


def test_duplicate_keys_and_wrong_target_mapping_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        export(json.dumps(MANIFEST).encode(), b'{"agent":"a","agent":"b"}')
    with pytest.raises(ValueError, match="exactly"):
        export(
            json.dumps(MANIFEST).encode(),
            (ROOT / "examples/cedar-export/mapping.json").read_bytes(),
        )


def cli_args(mapping=EXAMPLE / "mapping.json"):
    return ["rego", "export", str(EXAMPLE / "manifest.json"), "--mapping", str(mapping)]


def test_cli_emits_json_and_complete_files_with_no_overwrite(tmp_path, capsys):
    destination = tmp_path / "bundle"
    args = cli_args() + ["--output-dir", str(destination), "--json"]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert json.loads((destination / "export.json").read_text()) == result
    assert (destination / "policy.rego").read_text() == result["policy"]
    assert (destination / "policy_test.rego").read_text() == result["native_tests"]
    assert main(args) == 2
    output = capsys.readouterr()
    assert not output.out and "already exists" in output.err
    assert not list(tmp_path.glob(".agentmandate-export-*"))


def test_cli_refuses_losses_and_partial_stays_a_finding(tmp_path, capsys):
    manifest = copy.deepcopy(MANIFEST)
    manifest["limits"] = {"effects": {"irreversible": 3}}
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(manifest))
    args = cli_args()
    args[2] = str(source)
    destination = tmp_path / "bundle"
    args += ["--output-dir", str(destination)]
    assert main(args) == 1
    assert "REGO refused" in capsys.readouterr().out and not destination.exists()
    assert main(args + ["--allow-partial"]) == 1
    assert "REGO partial_export" in capsys.readouterr().out and destination.exists()


@pytest.mark.parametrize("content", [None, b"{", b"\xff", b"[]"])
def test_cli_io_and_malformed_mapping_are_usage_errors(content, tmp_path, capsys):
    mapping = tmp_path / "mapping.json"
    if content is not None:
        mapping.write_bytes(content)
    assert main(cli_args(mapping) + ["--json"]) == 2
    output = capsys.readouterr()
    assert not output.out and "error:" in output.err


def test_cli_staging_failure_does_not_publish_partial_output(tmp_path, monkeypatch, capsys):
    original = Path.write_text

    def fail(path, *args, **kwargs):
        if path.name == "schema.json":
            raise OSError("simulated write failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail)
    destination = tmp_path / "bundle"
    assert main(cli_args() + ["--output-dir", str(destination)]) == 2
    assert "simulated write failure" in capsys.readouterr().err
    assert not destination.exists() and not list(tmp_path.glob(".agentmandate-export-*"))


@pytest.fixture
def opa():
    path = os.environ.get("AGENTMANDATE_OPA") or shutil.which("opa")
    if not path:
        if os.environ.get("AGENTMANDATE_REQUIRE_OPA_NATIVE") == "1":
            pytest.fail("the required pinned OPA engine is not installed")
        pytest.skip("optional pinned native OPA engine not installed")
    target = json.loads((EXAMPLE / "opa-target.json").read_text())
    executable = Path(path).resolve()
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == target["sha256"]
    assert subprocess.check_output([str(executable), "version"], text=True).splitlines()[0] == (
        f"Version: {target['version']}"
    )
    return str(executable)


def test_native_validation_and_independent_request_matrix(opa, tmp_path):
    mapping = copy.deepcopy(MAPPING)
    mapping["package"] = "platform.release"
    mapping["principals"]["caller"].append('second"\\operator')
    mapping["resource"] = 'repository"\\id'
    mapping["actions"]["publish_release"] = 'publish"\\release'
    mapping["approval_context"] = 'approval"\\key'
    result = compile_manifest(mapping=mapping)
    policy = tmp_path / "policy.rego"
    policy.write_text(result["policy"])
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(result["input_schema"]))
    subprocess.run([opa, "check", "--strict", "--schema", str(schema), str(policy)], check=True)
    requests, expected = [], []
    actors = [*mapping["principals"]["caller"], *mapping["principals"]["service"], "outsider"]
    for tool, actor, resource, approval in itertools.product(
        MANIFEST["tools"],
        actors,
        [mapping["resource"], "other"],
        [None, False, True, "true", 1],
    ):
        requests.append(
            {
                "principal": actor,
                "action": mapping["actions"][tool["name"]],
                "resource": resource,
                "context": {} if approval is None else {mapping["approval_context"]: approval},
            }
        )
        # Expectations come from the source contract, never generated request cases or policy text.
        expected.append(
                actor in mapping["principals"][tool.get("principal", "caller")]
            and resource == mapping["resource"]
            and (not tool.get("requires_approval", False) or approval is True)
        )
    assert len(requests) == 120 and any(expected) and not all(expected)
    allowed = {
        "principal": actors[0],
        "action": mapping["actions"]["publish_release"],
        "resource": mapping["resource"],
        "context": {mapping["approval_context"]: True},
    }
    malformed = [None, True, 1, "input", [], {}, {**allowed, "action": "unknown"}]
    for key in allowed:
        missing = dict(allowed)
        del missing[key]
        malformed.append(missing)
        for value in [None, False, 1, [], {}]:
            malformed.append({**allowed, key: value})
    requests += malformed
    expected += [False] * len(malformed)
    data = tmp_path / "requests.json"
    data.write_text(json.dumps({"requests": requests}))
    probe = tmp_path / "probe.rego"
    probe.write_text("""package native_probe
import rego.v1
decisions := [decision |
    some request in data.requests
    decision := data.platform.release.allow with input as request
]
""")
    answer = json.loads(
        subprocess.check_output(
            [
                opa,
                "eval",
                "--format=json",
                "--strict-builtin-errors",
                "--data",
                str(policy),
                "--data",
                str(probe),
                "--data",
                str(data),
                "data.native_probe.decisions",
            ],
            text=True,
        )
    )
    assert answer["result"][0]["expressions"][0]["value"] == expected


def test_native_generated_bundle_can_be_reproduced(opa, tmp_path):
    assert main(cli_args() + ["--output-dir", str(tmp_path / "bundle"), "--json"]) == 0
    subprocess.run(
        [
            opa,
            "test",
            str(tmp_path / "bundle/policy.rego"),
            str(tmp_path / "bundle/policy_test.rego"),
            str(tmp_path / "bundle/tests.json"),
        ],
        check=True,
    )
