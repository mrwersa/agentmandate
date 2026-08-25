"""Verify that digests cited in evidence READMEs match the committed files.

Evidence directories pin artifacts by SHA-256. When an artifact changes and
its README citation goes stale, every downstream claim built on the old bytes
becomes unverifiable. This script catches that rot: for every citation of the
form ```<file>`, SHA-256 `<digest>`` where `<file>` exists in the same
directory, the committed file must hash to `<digest>`.

Citations whose file name does not resolve locally (external archives,
upstream source files) are reported as unchecked, not failed.

Usage::

    python scripts/evidence_lint.py [--root docs/evidence]

Exits 0 when clean, 1 when a stale or unreadable citation is found.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

CITATION = re.compile(r"`(?P<name>[^`\n]+)`, SHA-256 `(?P<digest>[0-9a-f]{64})`")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def lint_directory(directory: Path) -> tuple[list[str], list[str]]:
    """Return (errors, unchecked) for one evidence directory."""
    readme = directory / "README.md"
    if not readme.exists():
        return [f"{directory}: no README.md to lint"], []

    text = readme.read_text(encoding="utf-8")
    local_hashes: dict[str, str] = {}
    for item in sorted(directory.iterdir()):
        if item.is_file() and item.name != "README.md":
            local_hashes[_sha256(item.read_bytes())] = item.name

    errors: list[str] = []
    unchecked: list[str] = []
    seen_digests: set[str] = set()
    for match in CITATION.finditer(text):
        name = match.group("name").strip()
        digest = match.group("digest")
        seen_digests.add(digest)
        candidate = directory / name
        if not candidate.is_file():
            errors.append(
                f"{readme.name}: {name} is cited with SHA-256 {digest[:12]}… "
                "but is not committed in this directory. Commit the artifact, "
                "fix the file name, or rewrite the pin in prose (for example: "
                "'upstream archive SHA-256 is …') so it is not treated as a "
                "verifiable claim"
            )
            continue
        actual = _sha256(candidate.read_bytes())
        if actual != digest:
            errors.append(
                f"{readme.name}: cited SHA-256 for {name} is stale "
                f"(cited {digest[:12]}…, actual {actual[:12]}…)"
            )
        else:
            local_hashes.pop(actual, None)

    return errors, unchecked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default="docs/evidence", type=Path)
    args = parser.parse_args(argv)
    root: Path = args.root

    if not root.is_dir():
        print(f"error: evidence root {root} does not exist", file=sys.stderr)
        return 1

    failures = 0
    directories = sorted(p for p in root.iterdir() if p.is_dir())
    if (root / "README.md").exists():
        directories.append(root)
    for directory in directories:
        errors, unchecked = lint_directory(directory)
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
            failures += 1
        for note in unchecked:
            print(f"note: {note}", file=sys.stderr)

    if failures:
        print(f"evidence lint: {failures} stale citation(s)", file=sys.stderr)
        return 1
    print("evidence lint: all cited digests match committed files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
