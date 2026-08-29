from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "evidence_summary", ROOT / "scripts" / "evidence_summary.py"
)
assert _spec is not None and _spec.loader is not None
evidence_summary = importlib.util.module_from_spec(_spec)
sys.modules["evidence_summary"] = evidence_summary
_spec.loader.exec_module(evidence_summary)


def test_committed_summary_is_current_and_resolves_capture_count() -> None:
    summary = evidence_summary.build_summary()

    assert summary["capture_count"] == 8
    assert summary["authority_graph_count"] == 7
    assert evidence_summary.render(summary) == evidence_summary.OUTPUT.read_text(encoding="utf-8")
    captures = {item["id"]: item for item in summary["captures"]}
    assert captures["authorizer-delegation"]["authority_graph"] is False
    assert captures["aws-iam-access-keys"]["captured_tool_count"] == 29
    assert captures["aws-iam-access-keys"]["analysed_tool_count"] == 1


def test_summary_refuses_to_invent_legacy_class_counts() -> None:
    classification = evidence_summary.build_summary()["correction_classification"]

    assert classification == {
        "complete": False,
        "canonical_records": 16,
        "total_records": 37,
        "class_counts": None,
        "reason": "legacy correction records lack canonical pre-study class labels",
    }


def test_live_comparison_is_extracted_from_committed_oracles() -> None:
    comparison = evidence_summary.build_summary()["live_comparisons"][0]

    assert comparison["baseline_revision"] == "RefundIamUnderLimit"
    assert comparison["candidate_revision"] == "RefundIamCandidate"
    assert [(item["arguments"], item["change"]) for item in comparison["requests"]] == [
        ({"amount": 2000}, "widens"),
        ({"amount": 500}, "stable_allow"),
    ]
    assert comparison["counterexample_length"] is None
    assert comparison["analysis_wall_clock_ms"] is None
    assert comparison["instrumentation_status"] == "missing"


def _one_capture(monkeypatch: pytest.MonkeyPatch) -> tuple:
    capture = ("sample", "Sample", "1", "domain", "pattern", 1, 1, "static-source", True)
    monkeypatch.setattr(evidence_summary, "CAPTURES", (capture,))
    return capture


def _write_record(root: Path, record: dict, *, envelope: dict | None = None) -> None:
    directory = root / "sample"
    directory.mkdir()
    (directory / "artifact.json").write_text("{}\n", encoding="utf-8")
    payload = envelope or {
        "corrections_version": 1,
        "capture": "sample",
        "corrections": [record],
    }
    (directory / "corrections.json").write_text(json.dumps(payload), encoding="utf-8")


def _record() -> dict:
    return {
        "id": "sample-001",
        "reported_class": "model gap",
        "classes": ["model gap"],
        "classification_status": "canonical",
        "affected_artifact": "artifact.json",
        "description": "A recorded correction.",
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda item: item.update(extra=True), "fields are not exact"),
        (lambda item: item.update(classes=["invented"]), "invalid canonical class"),
        (
            lambda item: item.update(classification_status="guessed"),
            "invalid classification status",
        ),
        (lambda item: item.update(classes=[]), "class and status disagree"),
        (lambda item: item.update(affected_artifact="missing.json"), "artifact is not committed"),
        (lambda item: item.update(description=""), "description is empty"),
    ],
)
def test_correction_records_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    message: str,
) -> None:
    _one_capture(monkeypatch)
    record = _record()
    mutate(record)
    _write_record(tmp_path, record)

    with pytest.raises(ValueError, match=message):
        evidence_summary._corrections(tmp_path)


def test_bad_envelope_and_duplicate_ids_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _one_capture(monkeypatch)
    _write_record(
        tmp_path,
        _record(),
        envelope={"corrections_version": 2, "capture": "sample", "corrections": []},
    )
    with pytest.raises(ValueError, match="invalid corrections envelope"):
        evidence_summary._corrections(tmp_path)

    record = _record()
    (tmp_path / "sample" / "corrections.json").write_text(
        json.dumps(
            {"corrections_version": 1, "capture": "sample", "corrections": [record, record]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not unique"):
        evidence_summary._corrections(tmp_path)


def test_cli_checks_writes_and_blocks_incomplete_classification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "summary.json"

    assert evidence_summary.main(["--output", str(output)]) == 0
    assert evidence_summary.main(["--output", str(output), "--check"]) == 0
    assert "current" in capsys.readouterr().out

    output.write_text("stale\n", encoding="utf-8")
    assert evidence_summary.main(["--output", str(output), "--check"]) == 1
    assert "stale" in capsys.readouterr().err

    assert evidence_summary.main(["--require-complete-classification"]) == 1
    assert "incomplete" in capsys.readouterr().err
