"""Verify that digests cited in evidence READMEs match the committed files.

Evidence directories pin artifacts by SHA-256. When an artifact changes and
its README citation goes stale, every downstream claim built on the old bytes
becomes unverifiable. This script catches that rot: for every citation of the
form ```<file>`, SHA-256 `<digest>`` the named file must be committed in the
same directory and hash to `<digest>`. Missing files and paths outside that
directory fail. External provenance pins use prose rather than this strict
machine-checked form.

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


def lint_directory(directory: Path) -> list[str]:
    """Return citation errors for one evidence directory."""
    readme = directory / "README.md"
    if not readme.exists():
        return [f"{directory}: no README.md to lint"]

    text = readme.read_text(encoding="utf-8")
    errors: list[str] = []
    for match in CITATION.finditer(text):
        name = match.group("name").strip()
        digest = match.group("digest")
        if "/" in name or "\\" in name or name in {".", ".."}:
            errors.append(f"{readme.name}: cited file {name} must be a file name in this directory")
            continue
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

    return errors


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
        errors = lint_directory(directory)
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
            failures += 1

    if failures:
        print(f"evidence lint: {failures} citation error(s)", file=sys.stderr)
        return 1
    print("evidence lint: all cited digests match committed files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
