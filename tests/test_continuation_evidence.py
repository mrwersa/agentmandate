import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTCORE = ROOT / "docs" / "evidence" / "agentcore-refund-policy"
ANTHROPIC = ROOT / "docs" / "evidence" / "anthropic-managed-budget"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agentcore_projector = _module(AGENTCORE / "project_continuation.py", "agentcore_continuation")
managed_projector = _module(ANTHROPIC / "project_continuation.py", "managed_continuation")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_managed_agents_classifications_rederive_from_sanitised_trials():
    protocol = _read(ANTHROPIC / "continuation-protocol.json")
    evidence = _read(ANTHROPIC / "continuation-confirmation.json")
    summary = _read(ANTHROPIC / "continuation-summary.json")

    assert evidence["protocol_sha256"] == _sha256(ANTHROPIC / "continuation-protocol.json")
    assert evidence["stopped"] is None
    assert evidence["cleanup"]["complete"] is True
    assert evidence["trials_per_cell_observed"] == dict.fromkeys(managed_projector.CELLS, 10)
    counts: dict[str, dict[str, int]] = {cell: {} for cell in managed_projector.CELLS}
    for trial in evidence["trials"]:
        classification = managed_projector._classify(trial, protocol)
        assert classification == trial["classification"]
        key = classification or "nonconforming"
        counts[trial["cell"]][key] = counts[trial["cell"]].get(key, 0) + 1
    assert {cell: result["classifications"] for cell, result in summary["results"].items()} == {
        cell: dict(sorted(values.items())) for cell, values in counts.items()
    }


def test_agentcore_matrix_summary_rederives_from_sanitised_events():
    protocol = _read(AGENTCORE / "continuation-protocol.json")
    events = _read(AGENTCORE / "continuation-events.json")
    summary = _read(AGENTCORE / "continuation-summary.json")

    assert summary["arms"] == agentcore_projector._summary(protocol, events["trials"])
    assert summary["controls"] == {"preflight": True, "postflight": True}
    assert summary["stopped"] is None
    assert len(events["trials"]) == 6 * protocol["trials_per_arm"]


def test_agentcore_recorded_statements_are_pinned_templates():
    protocol = _read(AGENTCORE / "continuation-protocol.json")
    events = _read(AGENTCORE / "continuation-events.json")
    marker = agentcore_projector.MARKER

    def check(statement):
        if statement is None:
            return
        template = (AGENTCORE / statement["template"]).read_text(encoding="utf-8").rstrip("\n")
        assert statement["template"] in protocol["templates"]
        if statement["variant"] == "whitespace":
            template = template.replace(marker, marker + "\n", 1)
        assert hashlib.sha256(template.encode()).hexdigest() == statement["sha256"]

    for trial in events["trials"]:
        for update in (trial.get("reset"), trial.get("update")):
            if update is None:
                continue
            check(update["submitted"]["statement"])
            for snapshot in (update["before"], update["after"], *update["polls"]):
                check(snapshot["statement"])


def test_agentcore_diagnostic_summary_rederives_from_sanitised_blocks():
    diagnostic = _read(AGENTCORE / "continuation-diagnostic-protocol.json")
    events = _read(AGENTCORE / "continuation-diagnostic-events.json")
    summary = _read(AGENTCORE / "continuation-diagnostic-summary.json")

    assert events["diagnostic_protocol_sha256"] == _sha256(
        AGENTCORE / "continuation-diagnostic-protocol.json"
    )
    assert sorted(events["block_order"]) == sorted(diagnostic["configurations"])
    assert summary["configurations"] == agentcore_projector._diagnostic_summary(events["blocks"])
