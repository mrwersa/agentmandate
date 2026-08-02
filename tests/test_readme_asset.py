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


def test_the_readme_names_no_version_that_can_go_stale() -> None:
    """A version in prose drifts, and this one already had.

    The README said "Alpha, version 0.4.0" while 0.7.0 was the live release,
    three minors behind, because nothing failed when the number stopped being
    true. The badge and PyPI carry the version; prose does not need to.
    """
    import re

    readme = (ASSET.parents[2] / "README.md").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in readme.splitlines() if not line.startswith("[![")
    )
    stale = re.findall(r"version \d+\.\d+\.\d+|agentmandate[~=]=\d+\.\d+", body)

    assert not stale, f"the README states a version that will drift: {stale}"


def test_prose_markdown_pins_the_current_minor_series() -> None:
    """The pin the README refuses lives in STABILITY.md, and must stay true.

    The README carries no version because the badge does that, but STABILITY.md
    tells users what to pin. That pin drifted in the sibling project because
    the guard scanned one file, so every prose markdown file must either pin
    the current series or stay silent. The changelog and the release notes
    legitimately carry other versions, so they are excluded.
    """
    import re

    from agentmandate import __version__

    root = ASSET.parents[2]
    major, minor, _ = __version__.split(".")
    expected = f"{major}.{minor}"

    stale = []
    for path in sorted(root.rglob("*.md")):
        if path.name in {"CHANGELOG.md", "RELEASING.md"}:
            continue
        pins = set(
            re.findall(r"agentmandate[~=]=(\d+\.\d+)", path.read_text(encoding="utf-8"))
        )
        if pins and pins != {expected}:
            stale.append(f"{path.relative_to(root)}: {sorted(pins)}")

    assert not stale, f"docs pin {', '.join(stale)}; this release is {__version__}"


def test_every_cli_command_is_discoverable_from_the_readme() -> None:
    """A command the README never names is a command nobody finds."""
    from agentmandate.cli import build_parser

    readme = (ASSET.parents[2] / "README.md").read_text(encoding="utf-8")
    commands = {
        name
        for action in build_parser()._subparsers._group_actions
        for name in action.choices
    }
    missing = sorted(c for c in commands if f"mandate {c}" not in readme)

    assert not missing, f"the README never mentions: {', '.join(missing)}"
