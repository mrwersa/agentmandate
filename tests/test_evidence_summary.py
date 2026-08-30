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
        "canonical_records": 21,
        "total_records": 42,
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
    assert comparison["counterexample_length"] == 1
    assert comparison["analysis_wall_clock_ms"] > 0
    assert comparison["instrumentation_status"] == "complete"
    assert comparison["measurement"]["repetitions"] == 1000
    assert comparison["measurement"]["warmups"] == 100


def test_managed_controls_and_permitted_sequence_are_in_the_summary() -> None:
    controls = evidence_summary.build_summary()["managed_controls"][0]

    assert controls["comparisons"] == {
        "noop": ["stable_deny", "stable_allow"],
        "narrow": ["stable_deny", "tightens"],
    }
    assert controls["permitted_sequence"]["aggregate_amount"] == 1200
    assert controls["permitted_sequence"]["per_request_threshold"] == 1000


def test_temporal_session_boundary_is_in_the_summary() -> None:
    temporal = evidence_summary.build_summary()["temporal_sessions"][0]

    assert temporal["threshold"] == 1000
    assert temporal["request_amount"] == 600
    assert [item["outcome"] for item in temporal["same_session"]["calls"]] == [
        "allow",
        "deny",
    ]
    assert [item["outcome"] for item in temporal["fresh_sessions"]["calls"]] == [
        "allow",
        "allow",
    ]
    assert temporal["conformance"] == {
        "within_session_accumulation": "observed",
        "fresh_session_reset": "observed",
        "authenticated_principal_binding": "configured-not-adversarially-tested",
        "multi_hop_continuity": "documented-not-live-tested",
    }


def test_mandate_binding_control_is_in_the_summary() -> None:
    binding = evidence_summary.build_summary()["mandate_bindings"][0]

    assert binding["threshold"] == 1000
    assert binding["request_amount"] == 600
    assert binding["same_signed_mandate"]["separate_client_processes"] == 2
    assert [item["outcome"] for item in binding["same_signed_mandate"]["calls"]] == [
        "allow",
        "deny",
    ]
    assert binding["different_signed_mandate"]["derived_session_id_distinct"] is True
    assert [item["result"] for item in binding["local_controls"]] == [
        "rejected-before-network",
        "rejected-before-network",
    ]
    assert binding["median_adapter_ms"] > 0
    latency = binding["live_latency"]
    assert latency["samples"] == latency["independent_signed_mandates"] == 30
    assert latency["outcomes"] == ["allow"] * 30
    assert latency["end_to_end_median_ms"] == 566.975384
    assert latency["ratio_of_adapter_only_median_to_end_to_end_median_percent"] == 2.399098
    assert latency["credential_path"] == "exclusive trusted adapter"
    assert latency["gateway_verified_binding"] is False


def test_repeated_temporal_controls_are_in_the_summary() -> None:
    result = evidence_summary.build_summary()["temporal_repetitions"][0]

    assert result["session_cells"] == {
        "concurrent_exactly_one_allow": 10,
        "concurrent_intervals_overlapped": 10,
        "fresh_sessions_allow_then_allow": 10,
        "same_session_allow_then_deny": 10,
    }
    assert result["policy_updates"]["old_session_rejected_as_stale"] == 10
    assert result["policy_updates"]["fresh_recovery_allowed"] == 10
    assert result["binding_cells"]["same_binding_allow_then_deny"] == 10
    assert result["paired_latency"] == {
        "pairs": 30,
        "median_bound_minus_unbound_ms": 0.8011319999999955,
        "q1_bound_minus_unbound_ms": -54.94211799999998,
        "q3_bound_minus_unbound_ms": 45.14932324999998,
        "claim_boundary": (
            "paired randomized reference-path timing on one host, region, gateway, and "
            "inert tool; not a population estimate"
        ),
    }
    assert result["semantic_noop_revision"] == {
        "byte_identical_same_session_second_call": "deny",
        "byte_identical_write_created_revision": False,
        "distinct_active_revision": 10,
        "fresh_recovery_allowed": 10,
        "old_session_rejected_as_stale": 10,
        "update_to_active_ms": {
            "maximum": 10514.814172,
            "median": 8217.953572,
            "minimum": 7076.166358,
        },
    }
    assert result["binding_policy_revision"] == {
        "old_binding_session_rejected_as_stale": 10,
        "same_mandate_across_revision_aggregate": 1200,
        "successor_binding_session_allowed": 10,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("extra", True, "fields are not exact"),
        ("counterexample_length", 2, "invalid counterexample_length"),
        ("analysis_wall_clock_ms", 0, "invalid timing"),
        ("environment", {}, "invalid environment"),
        ("result", {"classifications": ["stable_allow"]}, "does not match"),
    ],
)
def test_live_measurement_fails_closed(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    source = evidence_summary.EVIDENCE / "agentcore-refund-policy"
    target = tmp_path / "agentcore-refund-policy"
    target.mkdir()
    for name in (
        "managed-oracle-v1.json",
        "candidate-managed-oracle-v1.json",
        "analysis-measurement.json",
    ):
        (target / name).write_bytes((source / name).read_bytes())
    measurement = json.loads((target / "analysis-measurement.json").read_text(encoding="utf-8"))
    measurement[field] = value
    (target / "analysis-measurement.json").write_text(json.dumps(measurement), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        evidence_summary._managed_comparison(tmp_path)


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
