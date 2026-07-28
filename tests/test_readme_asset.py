from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

ASSET = Path(__file__).resolve().parents[1] / "docs" / "assets" / "authority-path.svg"
SVG = {"svg": "http://www.w3.org/2000/svg"}


def test_authority_path_matches_the_executable_counterexample() -> None:
    source = ASSET.read_text(encoding="utf-8")

    assert "First breaching path £1,000 &gt; £500 run limit" in source
    assert "open_case → search_cases → issue_refund(case #1)" in source
    assert "→ issue_refund(case #2)" in source
    assert "Reachable total £1,000" not in source
    assert "new · read only" in source


def test_authority_path_uses_colour_for_change_type_not_path_risk() -> None:
    root = ET.parse(ASSET).getroot()
    added = root.find(".//svg:rect[@id='added-tool']", SVG)
    refund_1 = root.find(".//svg:rect[@id='existing-refund-1']", SVG)
    refund_2 = root.find(".//svg:rect[@id='existing-refund-2']", SVG)
    breach = root.find(".//svg:rect[@id='breach-summary']", SVG)

    assert added is not None and added.attrib["fill"] == "#fff0e8"
    assert refund_1 is not None and refund_1.attrib["fill"] == "#e9f6ef"
    assert refund_2 is not None and refund_2.attrib["fill"] == "#e9f6ef"
    assert breach is not None and breach.attrib["fill"] == "#fdecea"
