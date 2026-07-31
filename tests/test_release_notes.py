from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
INIT = ROOT / "agentmandate" / "__init__.py"

_spec = importlib.util.spec_from_file_location(
    "release_notes", ROOT / "scripts" / "release_notes.py"
)
assert _spec is not None and _spec.loader is not None
release_notes = importlib.util.module_from_spec(_spec)
sys.modules["release_notes"] = release_notes
_spec.loader.exec_module(release_notes)

SAMPLE = """# Changelog

## Unreleased

## 0.5.0 - 2026-07-31

### Added

- something worth saying

## 0.4.0 - 2026-07-30

### Added

- an older thing
"""


def test_extract_returns_only_the_requested_section() -> None:
    body = release_notes.extract(SAMPLE, "0.5.0")

    assert "something worth saying" in body
    assert "an older thing" not in body
    assert "Unreleased" not in body


def test_extract_reads_the_last_section_to_the_end_of_the_file() -> None:
    body = release_notes.extract(SAMPLE, "0.4.0")

    assert body.endswith("- an older thing")


def test_extract_refuses_a_version_with_no_section() -> None:
    with pytest.raises(release_notes.ChangelogError, match="no section for 9.9.9"):
        release_notes.extract(SAMPLE, "9.9.9")


def test_extract_refuses_an_undated_section() -> None:
    # An undated heading is a draft. Releasing a draft publishes prose that was
    # never finished, so this fails rather than falling back to the version.
    with pytest.raises(release_notes.ChangelogError, match="no release date"):
        release_notes.extract("# Changelog\n\n## 1.2.3\n\n- drafted\n", "1.2.3")


def test_extract_refuses_an_empty_section() -> None:
    with pytest.raises(release_notes.ChangelogError, match="is empty"):
        release_notes.extract("## 1.2.3 - 2026-01-01\n\n## 1.2.2 - 2025-01-01\n", "1.2.3")


def test_read_version_reads_the_package_literal() -> None:
    assert release_notes.read_version(INIT) == release_notes.read_version(INIT)
    with pytest.raises(release_notes.ChangelogError, match="__version__"):
        release_notes.read_version(ROOT / "README.md")


def test_main_prints_the_section(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(SAMPLE, encoding="utf-8")

    assert release_notes.main(["0.5.0", "--changelog", str(path)]) == 0
    assert "something worth saying" in capsys.readouterr().out


def test_main_reports_a_missing_section(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(SAMPLE, encoding="utf-8")

    assert release_notes.main(["9.9.9", "--changelog", str(path)]) == 1
    assert "no section for 9.9.9" in capsys.readouterr().err


def test_main_prints_the_packaged_version(capsys: pytest.CaptureFixture[str]) -> None:
    # The release workflow reads the version this way, so the flag it calls is
    # covered rather than assumed.
    assert release_notes.main(["--print-version", "--init", str(INIT)]) == 0
    assert capsys.readouterr().out.strip() == release_notes.read_version(INIT)


def test_main_reports_a_module_with_no_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    argv = ["--print-version", "--init", str(ROOT / "README.md")]

    assert release_notes.main(argv) == 1
    assert "__version__" in capsys.readouterr().err


def test_main_requires_a_version_or_the_flag() -> None:
    with pytest.raises(SystemExit):
        release_notes.main([])


def test_the_current_version_is_described_in_the_changelog() -> None:
    # This is the guard that the manual process did not have. 0.5.0 shipped a
    # wheel whose __version__ still said 0.4.0, because the number lived in two
    # files and only one was edited. The number now lives in one file, and this
    # fails the release pull request if its section was never written.
    version = release_notes.read_version(INIT)
    body = release_notes.extract(CHANGELOG.read_text(encoding="utf-8"), version)

    assert body
