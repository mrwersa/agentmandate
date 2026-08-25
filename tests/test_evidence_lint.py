from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "evidence_lint", ROOT / "scripts" / "evidence_lint.py"
)
assert _spec is not None and _spec.loader is not None
evidence_lint = importlib.util.module_from_spec(_spec)
sys.modules["evidence_lint"] = evidence_lint
_spec.loader.exec_module(evidence_lint)


def _make(directory: Path, files: dict[str, bytes], readme: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
    (directory / "README.md").write_text(readme, encoding="utf-8")
    return directory


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_matching_citation_passes(tmp_path: Path):
    capture = b"SELECT 1;\n"
    d = _make(
        tmp_path,
        {"capture.json": capture},
        f"**Capture:** `capture.json`, SHA-256 `{_digest(capture)}`\n",
    )
    errors, unchecked = evidence_lint.lint_directory(d)

    assert errors == []
    assert unchecked == []


def test_stale_citation_is_an_error(tmp_path: Path):
    capture = b"SELECT 1;\n"
    stale = _digest(b"old bytes")
    d = _make(
        tmp_path,
        {"capture.json": capture},
        f"**Capture:** `capture.json`, SHA-256 `{stale}`\n",
    )
    errors, _ = evidence_lint.lint_directory(d)

    assert len(errors) == 1
    assert "stale" in errors[0]
    assert "capture.json" in errors[0]


def test_prose_pins_are_skipped_and_strict_pins_fail_closed(tmp_path: Path):
    capture = b"raw"
    digest = _digest(capture)
    d = _make(
        tmp_path,
        {"capture.json": capture},
        f"**Capture:** `capture.json`, SHA-256 `{digest}`\n"
        "Upstream archive SHA-256 is `708effb774be8237570d0add163225abb"
        "dfaf4fca28b2611df167beba4feef89`.\n",
    )
    errors, unchecked = evidence_lint.lint_directory(d)

    assert errors == []
    assert unchecked == []

    # Deleting the cited artifact must fail closed, never pass silently.
    (d / "capture.json").unlink()
    errors, _ = evidence_lint.lint_directory(d)
    assert len(errors) == 1
    assert "not committed in this directory" in errors[0]


def test_misspelled_citation_target_fails_closed(tmp_path: Path):
    capture = b"raw"
    d = _make(
        tmp_path,
        {"capture.json": capture},
        f"**Capture:** `capture.jsoon`, SHA-256 `{_digest(capture)}`\n",
    )
    errors, _ = evidence_lint.lint_directory(d)

    assert len(errors) == 1
    assert "not committed in this directory" in errors[0]


def test_directory_without_readme_is_an_error(tmp_path: Path):
    d = tmp_path / "lonely"
    d.mkdir()

    errors, _ = evidence_lint.lint_directory(d)

    assert errors == [f"{d}: no README.md to lint"]


def test_main_reports_failure_and_success(tmp_path: Path, capsys):
    good = _make(
        tmp_path / "good",
        {"a.bin": b"A"},
        f"`a.bin`, SHA-256 `{_digest(b'A')}`\n",
    )
    assert evidence_lint.main(["--root", str(good)]) == 0

    _make(
        tmp_path / "bad",
        {"b.bin": b"B"},
        "`b.bin`, SHA-256 `" + "0" * 64 + "`\n",
    )
    assert evidence_lint.main(["--root", str(tmp_path)]) == 1
    assert "stale citation(s)" in capsys.readouterr().err


def test_missing_root_is_a_usage_error():
    assert evidence_lint.main(["--root", str(ROOT / "no" / "such" / "dir")]) == 1
