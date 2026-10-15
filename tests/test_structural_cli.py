import json
from pathlib import Path

import pytest

from agentmandate._ir import AuthorityIR, IRFormatError
from agentmandate.cli import main

ROOT = Path(__file__).resolve().parents[1]
VALIDATORS = [
    (["ir", "validate"], "tests/fixtures/authority-ir-v2.json", "authority-ir"),
    (
        ["inventory", "validate"],
        "tests/fixtures/dynamic-inventory-agentkit-v1.json",
        "dynamic-inventory",
    ),
    (
        ["conditions", "validate", "--condition"],
        "tests/fixtures/condition-statement-v1.json",
        "tool-condition",
    ),
    (
        ["conditions", "validate", "--context"],
        "tests/fixtures/condition-context-select-only-complete-v1.json",
        "condition-context",
    ),
    (
        ["delegations", "validate", "--attachment"],
        "tests/fixtures/delegation-attachment-v2.json",
        "delegation-attachment",
    ),
    (
        ["delegations", "validate", "--chain"],
        "tests/fixtures/delegation-chain-authorizer-v1.json",
        "delegation-chain",
    ),
    (
        ["producers", "validate"],
        "tests/fixtures/producer-accepted-synthetic/boundary.json",
        "producer-boundary",
    ),
    (
        ["continuity", "validate"],
        "tests/fixtures/agentcore-continuity-v1.json",
        "agentcore-continuity-profile",
    ),
    (
        ["cedar", "validate"],
        "docs/evidence/agentcore-refund-policy/managed-oracle-v1.json",
        "managed-cedar-oracle",
    ),
]


@pytest.mark.parametrize("argv,path,kind", VALIDATORS)
def test_structural_validators_support_scoped_json(argv, path, kind, capsys):
    assert main([*argv, str(ROOT / path), "--json"]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    result = json.loads(captured.out)
    assert result["schema"] == "agentmandate.validation/v1"
    assert result["status"] == "valid" and result["artifact"] == kind
    assert isinstance(result["version"], int)
    assert "structure only" in result["scope"] and "not assessed" in result["scope"]


@pytest.mark.parametrize("argv,path,kind", VALIDATORS)
@pytest.mark.parametrize("body", ["{", "[" * 200000 + "]" * 200000])
def test_structural_bad_inputs_fail_without_partial_json_or_tracebacks(
    argv,
    path,
    kind,
    body,
    tmp_path,
    capsys,
):
    invalid = tmp_path / "invalid.json"
    invalid.write_text(body)
    assert main([*argv, str(invalid), "--json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err.startswith("error: ")
    assert "Traceback" not in captured.err


def test_public_ir_reader_wraps_excessive_nesting():
    with pytest.raises(IRFormatError, match="not valid JSON"):
        AuthorityIR.from_json("[" * 200000 + "]" * 200000)


@pytest.mark.parametrize("command", ["lint", "reach", "obligations", "scenarios", "remediate"])
def test_manifest_commands_treat_excessive_nesting_as_malformed(command, tmp_path, capsys):
    path = tmp_path / "deep.json"
    path.write_text('{"nested":' + "[" * 200000 + "]" * 200000 + "}")
    assert main([command, str(path), "--json"]) == 2
    captured = capsys.readouterr()
    assert not captured.out and captured.err.startswith("error: ")
    assert "Traceback" not in captured.err


def test_validation_baselines_are_byte_identical(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    cases = json.loads((ROOT / "tests/fixtures/structural-validation-v1.json").read_text())
    assert len(cases) == len(VALIDATORS)
    for case in cases:
        assert main(case["argv"]) == case["exit"] == 0
        captured = capsys.readouterr()
        assert captured.out == case["stdout"] and captured.err == ""
