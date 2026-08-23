from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import agentmandate
import agentmandate.cli as cli
from agentmandate._ir import (
    AuthorityIR,
    Evidence,
    Fact,
    IRFormatError,
    _analyse_ir,
    _fact_id,
    _from_mandate,
    _IRAnalysis,
)
from agentmandate.cli import EXIT_FINDING, EXIT_OK, EXIT_USAGE, build_parser, main
from agentmandate.manifest import load

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
V1 = EXAMPLES / "dispute-resolver.yaml"
V2 = EXAMPLES / "dispute-resolver-v2.yaml"
INVALID = ROOT / "tests" / "fixtures" / "authority-ir-invalid"
MIGRATION = ROOT / "tests" / "fixtures" / "authority-ir-v1.json"
EVIDENCE = tuple(sorted((ROOT / "docs" / "evidence").glob("*/mandate.yaml")))


def write_snapshot(path: Path, manifest: Path) -> AuthorityIR:
    content = manifest.read_bytes()
    snapshot = _from_mandate(load(manifest), content=content)
    path.write_text(snapshot.to_json(), encoding="utf-8")
    return snapshot


def test_ir_export_writes_one_canonical_content_bound_snapshot(capsys) -> None:
    content = V1.read_bytes()
    expected = _from_mandate(load(V1), content=content)

    assert main(["ir", "export", str(V1)]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == expected.to_json()
    restored = AuthorityIR.from_json(captured.out)
    mandate_source = next(
        source for source in restored.sources if source.id == "source:mandate"
    )
    assert mandate_source.content_sha256 is not None


def test_ir_validate_is_structural_and_does_not_accept_evidence_as_authority(
    tmp_path: Path, capsys
) -> None:
    snapshot = _from_mandate(load(V1), content=V1.read_bytes())
    effect = next(fact for fact in snapshot.facts if fact.predicate == "effect")
    contested = replace(
        effect,
        evidence=(replace(effect.evidence[0], review="contested"),),
    )
    snapshot = replace(
        snapshot,
        facts=tuple(contested if fact == effect else fact for fact in snapshot.facts),
    )
    path = tmp_path / "contested.json"
    path.write_text(snapshot.to_json(), encoding="utf-8")

    assert main(["ir", "validate", str(path)]) == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == "valid authority IR v1\n"
    assert captured.err == ""

    assert main(["reach", "--ir", str(path)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "review is not accepted for analysis" in captured.err


@pytest.mark.parametrize("path", sorted(INVALID.glob("*.json")), ids=lambda path: path.name)
def test_ir_validate_rejects_every_malformed_fixture_without_partial_stdout(
    path: Path, capsys
) -> None:
    assert main(["ir", "validate", str(path)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: authority IR")


@pytest.mark.parametrize("command", ["export", "validate"])
def test_ir_commands_report_io_and_encoding_errors(
    command: str, tmp_path: Path, capsys
) -> None:
    missing = tmp_path / "missing"
    assert main(["ir", command, str(missing)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error:")

    invalid = tmp_path / "invalid"
    invalid.write_bytes(b"\xff")
    assert main(["ir", command, str(invalid)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error:")


def test_reach_ir_preserves_human_finding_and_canonical_result_output(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "source.json"
    snapshot = write_snapshot(path, V2)

    assert main(["reach", "--ir", str(path)]) == EXIT_FINDING
    captured = capsys.readouterr()
    assert "BREACH" in captured.out
    assert captured.err == ""

    assert main(["reach", "--ir", str(path), "--depth", "4", "--json"]) == EXIT_FINDING
    captured = capsys.readouterr()
    expected = _analyse_ir(snapshot, depth=4)
    assert captured.out == expected.to_json()
    assert captured.err == ""
    assert _IRAnalysis.from_json(captured.out) == expected
    assert "\n" not in captured.out.rstrip("\n")


def test_reach_ir_supports_sarif_and_graph_outputs(tmp_path: Path, capsys) -> None:
    path = tmp_path / "source.json"
    write_snapshot(path, V2)

    assert main(["reach", "--ir", str(path), "--sarif"]) == EXIT_FINDING
    assert json.loads(capsys.readouterr().out)["version"] == "2.1.0"

    assert main(["reach", "--ir", str(path), "--graph"]) == EXIT_FINDING
    assert "flowchart LR" in capsys.readouterr().out


def test_reach_ir_rejects_unknown_semantics_and_malformed_input(
    tmp_path: Path, capsys
) -> None:
    snapshot = _from_mandate(load(V1))
    extra = Fact(
        id=_fact_id("tool:open_case", "future"),
        subject="tool:open_case",
        predicate="future",
        value="opaque",
        evidence=(Evidence("source:mandate", "/tools/0/future"),),
    )
    unsupported = replace(snapshot, facts=snapshot.facts + (extra,))
    path = tmp_path / "unsupported.json"
    path.write_text(unsupported.to_json(), encoding="utf-8")

    assert main(["reach", "--ir", str(path), "--json"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "predicate is unsupported" in captured.err

    assert main(["reach", "--ir", str(INVALID / "malformed.json")]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: authority IR")

    source = next(item for item in snapshot.sources if item.id == "source:mandate")
    unsupported_source = replace(source, adapter="future.adapter")
    unsupported = replace(
        snapshot,
        sources=tuple(
            unsupported_source if item == source else item for item in snapshot.sources
        ),
    )
    path.write_text(unsupported.to_json(), encoding="utf-8")
    assert main(["reach", "--ir", str(path)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "outside the analyzable manifest-v1 profile" in captured.err


def test_ir_cli_rejects_future_versions_without_partial_output(
    tmp_path: Path, capsys
) -> None:
    raw = _from_mandate(load(V1)).as_dict()
    raw["ir_version"] = 2
    path = tmp_path / "future.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    for argv in (["ir", "validate", str(path)], ["reach", "--ir", str(path)]):
        assert main(argv) == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "unsupported authority IR version 2" in captured.err


def test_ir_commands_never_emit_partial_stdout_on_late_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    def fail_export(*args, **kwargs):
        raise IRFormatError("late export failure")

    monkeypatch.setattr(cli, "_from_mandate", fail_export)
    assert main(["ir", "export", str(V1)]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "late export failure" in captured.err

    monkeypatch.undo()
    path = tmp_path / "source.json"
    write_snapshot(path, V1)

    def fail_reach(*args, **kwargs):
        raise IRFormatError("late reach failure")

    monkeypatch.setattr(cli, "_analyse_ir", fail_reach)
    assert main(["reach", "--ir", str(path), "--json"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "late reach failure" in captured.err

    monkeypatch.undo()

    def fail_serialization(self):
        raise IRFormatError("late serialization failure")

    monkeypatch.setattr(_IRAnalysis, "to_json", fail_serialization)
    assert main(["reach", "--ir", str(path), "--json"]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "late serialization failure" in captured.err


def test_ir_parser_help_and_mutual_exclusion_are_public_contracts(capsys) -> None:
    choices = {
        name
        for action in build_parser()._subparsers._group_actions
        for name in action.choices
    }
    assert "ir" in choices

    with pytest.raises(SystemExit) as help_exit:
        main(["ir", "--help"])
    assert help_exit.value.code == EXIT_OK
    assert "export" in capsys.readouterr().out

    for argv in (
        ["ir", "export"],
        ["ir", "validate"],
        ["reach"],
        ["reach", str(V1), "--ir", str(MIGRATION)],
    ):
        with pytest.raises(SystemExit) as usage_exit:
            main(argv)
        assert usage_exit.value.code == EXIT_USAGE
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "error:" in captured.err


def test_public_package_exports_remain_unchanged() -> None:
    assert not hasattr(agentmandate, "AuthorityIR")
    assert not hasattr(agentmandate, "IRFormatError")


@pytest.mark.parametrize("manifest", EVIDENCE, ids=lambda path: path.parent.name)
def test_every_real_evidence_graph_crosses_the_public_ir_boundary(
    manifest: Path, tmp_path: Path, capsys
) -> None:
    assert main(["ir", "export", str(manifest)]) == EXIT_OK
    exported = capsys.readouterr().out
    snapshot = AuthorityIR.from_json(exported)
    path = tmp_path / f"{manifest.parent.name}.json"
    path.write_text(exported, encoding="utf-8")

    status = main(["reach", "--ir", str(path), "--json"])
    captured = capsys.readouterr()
    result = _IRAnalysis.from_json(captured.out)
    assert captured.err == ""
    assert result.source_graph_sha256
    assert status == (EXIT_FINDING if result.authority.breaches else EXIT_OK)
    assert result.graph.facts == snapshot.facts


def test_migration_fixture_crosses_validate_and_reach_cli(capsys) -> None:
    assert main(["ir", "validate", str(MIGRATION)]) == EXIT_OK
    assert capsys.readouterr().out == "valid authority IR v1\n"

    status = main(["reach", "--ir", str(MIGRATION), "--json"])
    captured = capsys.readouterr()
    assert status in {EXIT_OK, EXIT_FINDING}
    assert captured.err == ""
    assert _IRAnalysis.from_json(captured.out).result_version == 1
