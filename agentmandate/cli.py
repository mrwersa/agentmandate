"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from . import __version__
from .diff import compare
from .lint import ERROR, check
from .manifest import ManifestError, load
from .reach import analyse
from .scan import scan_file
from .verify import replay_file

EXIT_OK = 0
EXIT_FINDING = 1
EXIT_USAGE = 2


def _add_manifest(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("manifest", help="path to a mandate manifest (YAML or JSON)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mandate",
        description=(
            "Analyse what an AI agent is permitted to do, and what changed "
            "between two releases."
        ),
    )
    parser.add_argument("--version", action="version", version=f"agentmandate {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint_parser = subparsers.add_parser(
        "lint", help="single-manifest control checks"
    )
    _add_manifest(lint_parser)
    lint_parser.add_argument("--json", action="store_true", help="machine-readable output")

    reach_parser = subparsers.add_parser(
        "reach",
        help="search for a legal call sequence that breaches a limit",
    )
    _add_manifest(reach_parser)
    reach_parser.add_argument(
        "--depth", type=int, default=None, help="override the manifest search depth"
    )
    reach_parser.add_argument("--json", action="store_true", help="machine-readable output")

    diff_parser = subparsers.add_parser(
        "diff", help="compare the effective authority of two manifests"
    )
    diff_parser.add_argument("before", help="the released manifest")
    diff_parser.add_argument("after", help="the proposed manifest")
    diff_parser.add_argument("--depth", type=int, default=None)
    diff_parser.add_argument("--json", action="store_true", help="machine-readable output")
    diff_parser.add_argument(
        "--record",
        action="store_true",
        help="emit a markdown change record for a change advisory board",
    )

    verify_parser = subparsers.add_parser(
        "verify", help="replay recorded calls against the manifest"
    )
    _add_manifest(verify_parser)
    verify_parser.add_argument(
        "--traces", required=True, help="JSON Lines file of observed tool calls"
    )
    verify_parser.add_argument("--json", action="store_true", help="machine-readable output")

    scan_parser = subparsers.add_parser(
        "scan",
        help="derive a manifest skeleton from an MCP tools/list catalogue",
    )
    scan_parser.add_argument("catalogue", help="JSON file holding an MCP tools/list payload")
    scan_parser.add_argument(
        "--agent", default="unnamed-agent", help="agent name to write into the skeleton"
    )

    return parser


def _emit(payload: dict, as_json: bool, text: str) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        try:
            print(scan_file(args.catalogue, args.agent), end="")
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        return EXIT_OK

    try:
        if args.command == "diff":
            before = load(args.before)
            after = load(args.after)
        else:
            mandate = load(args.manifest)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "lint":
        findings = check(mandate)
        payload = {
            "findings": [
                {
                    "rule": f.rule,
                    "severity": f.severity,
                    "subject": f.subject,
                    "message": f.message,
                }
                for f in findings
            ]
        }
        text = (
            "\n".join(f.render() for f in findings)
            if findings
            else "no single-manifest findings"
        )
        _emit(payload, args.json, text)
        return EXIT_FINDING if any(f.severity == ERROR for f in findings) else EXIT_OK

    if args.command == "reach":
        authority = analyse(mandate, depth=args.depth)
        if authority.breaches:
            text = "\n\n".join(b.render() for b in authority.breaches)
        else:
            reached = f"{len(authority.reachable_tools)} tool(s) reachable"
            bound = (
                f", most extractable {authority.max_extractable}"
                if authority.max_extractable
                else ""
            )
            depth_note = (
                f" within depth {authority.depth}"
                + (" (search truncated)" if authority.truncated else "")
            )
            text = f"no reachable breach{depth_note}. {reached}{bound}"
        _emit(authority.as_dict(), args.json, text)
        return EXIT_FINDING if authority.breaches else EXIT_OK

    if args.command == "diff":
        delta = compare(before, after, depth=args.depth)
        text = (
            delta.record(args.before, args.after)
            if args.record
            else delta.render(args.before, args.after)
        )
        _emit(delta.as_dict(), args.json, text)
        return EXIT_FINDING if delta.widened else EXIT_OK

    conformance = replay_file(mandate, args.traces)
    _emit(conformance.as_dict(), args.json, conformance.render())
    return EXIT_OK if conformance.conformant else EXIT_FINDING


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
