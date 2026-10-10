import hashlib
import json
from pathlib import Path

import pytest

from agentmandate import loads
from agentmandate.reach import _analyse_with_trace
from scripts import benchmark_search as study

ROOT = Path(__file__).resolve().parents[1]
BASELINES = json.loads(study.BASELINES.read_text())


@pytest.mark.parametrize(
    "case", BASELINES["cases"], ids=lambda case: f"{case['name']}-depth-{case['depth']}"
)
def test_pre_change_authority_and_provenance_are_unchanged(case):
    data = (ROOT / case["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == case["input_sha256"]
    mandate = loads(data.decode(), source=case["path"])
    metrics = {}
    authority, trace = _analyse_with_trace(
        mandate, depth=case["depth"], producer_caps=case["producer_caps"], _metrics=metrics
    )
    assert study.fingerprint(authority, trace) == {
        key: case[key] for key in ("authority_sha256", "trace_sha256")
    }
    assert authority.truncated == case["truncated"]
    assert [len(b.path) for b in authority.breaches] == case["witness_lengths"]
    assert metrics["states_discovered"] == metrics["states_expanded"] + metrics["depth_cutoffs"]
    assert metrics["tool_checks"] == metrics["states_expanded"] * len(mandate.tools)
    assert metrics["states_discovered"] - 1 == (
        metrics["generated_transitions"] - metrics["duplicate_transitions"]
    )
    assert 1 <= metrics["frontier_peak"] <= metrics["states_discovered"]
    assert bool(metrics["depth_cutoffs"]) == authority.truncated


def test_no_progress_calls_and_duplicate_states_are_not_new_work():
    metrics = {}
    raw = (ROOT / "probes/search/duplicate-binding.json").read_text()
    _, trace = _analyse_with_trace(loads(raw), _metrics=metrics)
    assert metrics == {
        "states_discovered": 2,
        "states_expanded": 2,
        "tool_checks": 6,
        "generated_transitions": 2,
        "duplicate_transitions": 1,
        "frontier_peak": 1,
        "depth_cutoffs": 0,
    }
    assert trace.path_for("read")[0].tool == "first"
    _analyse_with_trace(
        loads('{"agent":"a","tools":[{"name":"read","effect":"read"}]}'), _metrics=metrics
    )
    assert metrics["states_discovered"] == 1
    assert metrics["tool_checks"] == 1
    assert metrics["duplicate_transitions"] == 0


def test_metrics_do_not_change_authority_or_shortest_paths():
    data = (ROOT / "probes/search/wide-mint.json").read_text()
    mandate = loads(data)
    assert _analyse_with_trace(mandate, depth=5, _metrics={}) == _analyse_with_trace(
        mandate, depth=5
    )


def test_replay_uses_current_code_without_git_and_does_not_assert_timing_thresholds():
    result = study.benchmark(repeat=1, names=["pure-read"])
    assert len(result["cases"]) == 1
    row = result["cases"][0]
    assert row["state_bound"] == 1
    assert row["measurements"]["current"]["elapsed_ns_median"] > 0
    assert row["measurements"]["current"]["peak_traced_bytes"] > 0
    assert "baseline" not in row["measurements"]


def test_baseline_source_digest_is_checked_before_execution(monkeypatch):
    source = b'def _analyse_with_trace(*args, **kwargs): return "baseline-sentinel"\n'
    monkeypatch.setattr(study.subprocess, "check_output", lambda *a, **kw: source)
    baselines = {"baseline_ref": "pinned", "baseline_source_sha256": "0" * 64}
    with pytest.raises(ValueError, match="pinned digest"):
        study._baseline_kernel(baselines)
    baselines["baseline_source_sha256"] = hashlib.sha256(source).hexdigest()
    assert study._baseline_kernel(baselines)() == "baseline-sentinel"


def test_benchmark_refuses_changed_inputs_without_partial_output(tmp_path, monkeypatch, capsys):
    fixture = json.loads(study.BASELINES.read_text())
    fixture["cases"][0]["input_sha256"] = "0" * 64
    path = tmp_path / "baselines.json"
    path.write_text(json.dumps(fixture))
    monkeypatch.setattr(study, "BASELINES", path)
    assert study.main(["--case", "agentkit", "--repeat", "1"]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "input digest changed" in output.err


@pytest.mark.parametrize("args", [["--repeat", "0"], ["--case", "unknown"]])
def test_benchmark_rejects_bad_selections(args, capsys):
    assert study.main(args) == 2
    assert not capsys.readouterr().out


def test_machine_report_is_written_only_after_success(tmp_path):
    path = tmp_path / "result.json"
    assert study.main(["--case", "pure-read", "--repeat", "1", "--output", str(path)]) == 0
    result = json.loads(path.read_text())
    assert result["real_graph_runs"] == 0
    assert result["cases"][0]["metrics"]["states_discovered"] == 1
