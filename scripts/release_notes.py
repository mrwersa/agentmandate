#!/usr/bin/env python3
"""Extract one version's section from the changelog.

The release notes and the changelog used to be written twice, by hand, and
they drifted. This makes the changelog the only place the prose lives: the
release workflow reads the section for the version being released and uses it
as the GitHub Release body.

A missing or undated section is an error rather than an empty release note,
because publishing a version nobody described is worse than not publishing.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# "## 0.5.0 - 2026-07-31". The date is required. An undated heading means the
# section is still being drafted, and a draft is not a release.
HEADING = re.compile(r"^## (?P<version>\d+\.\d+\.\d+) - (?P<date>\d{4}-\d{2}-\d{2})\s*$")
ANY_HEADING = re.compile(r"^## ")


class ChangelogError(Exception):
    """The changelog does not describe the version being released."""


def extract(text: str, version: str) -> str:
    """Return the body of the section for ``version``.

    Raises ``ChangelogError`` when the section is absent, undated, or empty.
    """
    lines = text.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        match = HEADING.match(line)
        if match and match.group("version") == version:
            start = index + 1
            break

    if start is None:
        if re.search(rf"^## {re.escape(version)}\b", text, flags=re.MULTILINE):
            raise ChangelogError(
                f"the changelog section for {version} has no release date. "
                f"Use '## {version} - YYYY-MM-DD'."
            )
        raise ChangelogError(
            f"the changelog has no section for {version}. Add one before "
            f"releasing, because the section is the release note."
        )

    end = len(lines)
    for index in range(start, len(lines)):
        if ANY_HEADING.match(lines[index]):
            end = index
            break

    body = "\n".join(lines[start:end]).strip()
    if not body:
        raise ChangelogError(
            f"the changelog section for {version} is empty, so the release "
            f"would describe no change"
        )
    return body


def read_version(init: Path) -> str:
    """Read ``__version__`` from the package, the single source of the number."""
    match = re.search(
        r"^__version__ = \"(?P<version>[^\"]+)\"$",
        init.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if match is None:
        raise ChangelogError(f"{init} does not define __version__")
    return match.group("version")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version",
        nargs="?",
        help="version to extract, for example 0.5.0",
    )
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="print the packaged version instead of a changelog section",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=Path("CHANGELOG.md"),
        help="path to the changelog (default: CHANGELOG.md)",
    )
    parser.add_argument(
        "--init",
        type=Path,
        default=Path("agentmandate") / "__init__.py",
        help="path to the module holding __version__",
    )
    args = parser.parse_args(argv)

    if args.print_version:
        try:
            print(read_version(args.init))
        except ChangelogError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.version is None:
        parser.error("give a version, or use --print-version")

    try:
        body = extract(args.changelog.read_text(encoding="utf-8"), args.version)
    except ChangelogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(body)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
