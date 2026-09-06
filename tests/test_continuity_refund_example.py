from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from agentmandate._continuity import AgentCoreContinuity, ContinuityBinding
from agentmandate.cli import EXIT_FINDING, EXIT_OK, main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "continuity-refund"
ASSET = ROOT / "docs" / "assets" / "continuity-refund.svg"


def _relative(name: str) -> str:
    return str((EXAMPLE / name).relative_to(ROOT))


def _command(*, reset: bool = False) -> list[str]:
    provider = "provider-reset.json" if reset else "provider.json"
    control = "provider-control-reset.json" if reset else "provider-control.json"
    return [
        "continuity",
        "reconcile",
        _relative("manifest.json"),
        "--continuity-provider",
        _relative(provider),
        "--continuity-source",
        f"{_relative(control)}={_relative(control)}",
        "--continuity-binding",
        _relative("binding.json"),
        "--continuity-binding-source",
        f"{_relative('binding-verification.json')}={_relative('binding-verification.json')}",
        "--continuity-binding-source",
        f"{_relative('policy.json')}={_relative('policy.json')}",
        "--continuity-as-of",
        "2026-09-06T12:00:00Z",
        "--json",
    ]


def test_refund_example_pins_every_claimed_source_byte() -> None:
    binding = ContinuityBinding.from_json((EXAMPLE / "binding.json").read_text())
    provider = AgentCoreContinuity.from_json((EXAMPLE / "provider.json").read_text())
    reset = AgentCoreContinuity.from_json((EXAMPLE / "provider-reset.json").read_text())

    assert binding.mandate_sha256 == hashlib.sha256(
        (EXAMPLE / "manifest.json").read_bytes()
    ).hexdigest()
    binding.verify_sources(
        {source.locator: (ROOT / source.locator).read_bytes() for source in binding.sources}
    )
    provider.verify_sources(
        {source.locator: (ROOT / source.locator).read_bytes() for source in provider.sources}
    )
    reset.verify_sources(
        {source.locator: (ROOT / source.locator).read_bytes() for source in reset.sources}
    )


def test_refund_example_preserves_consumed_authority_across_reconnect(capsys) -> None:
    assert main(["continuity", "validate", _relative("provider.json")]) == EXIT_OK
    assert main(["continuity", "validate", _relative("binding.json")]) == EXIT_OK
    capsys.readouterr()

    assert main(_command()) == EXIT_OK
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    outcome = result["outcomes"][0]

    assert captured.err == ""
    assert result["findings"] == []
    assert result["authority"]["reachable_tools"] == ["open_case", "process_refund"]
    assert result["authority"]["max_extractable"] == {"amount": "1000", "currency": "GBP"}
    assert outcome["transition"] == "refund-agent-reconnect"
    assert outcome["kind"] == "fresh_session"
    assert outcome["completed_values"] == [600]
    assert outcome["limit_before"] == outcome["limit_after"] == 1000
    assert outcome["state"] == "preserved"
    assert outcome["authority_change"] == "stable"
    assert outcome["admission"] == "within_bound"
    assert outcome["safe_continuation"] == "satisfied"


def test_refund_reset_counterfactual_reports_reset_and_overshoot(capsys) -> None:
    assert main(_command(reset=True)) == EXIT_FINDING
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    outcome = result["outcomes"][0]

    assert captured.err == ""
    assert outcome["completed_values"] == [1200]
    assert outcome["state"] == "reset"
    assert outcome["admission"] == "overshot"
    assert outcome["safe_continuation"] == "unresolved"
    assert {finding["code"] for finding in result["findings"]} >= {
        "continuity.state-reset",
        "continuity.admission-overshot",
    }


def test_refund_continuity_figure_matches_the_executable_examples() -> None:
    root = ET.parse(ASSET).getroot()
    source = ASSET.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert root.attrib["role"] == "img"
    assert root.find("{http://www.w3.org/2000/svg}title") is not None
    assert root.find(".//*[@id='session-b-safe']") is not None
    assert root.find(".//*[@id='counterfactual-breach']") is not None
    assert "Refund £600 → DENY" in source
    assert "Completed: £1,200" in source
    assert "reset + overshot findings" in source
    assert "docs/assets/continuity-refund.svg" in readme
    assert "examples/continuity-refund/manifest.json" in readme
