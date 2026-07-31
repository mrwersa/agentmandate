"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .diff import compare
from .lint import ERROR, check
from .manifest import ManifestError, load
from .obligations import (
    derive,
    load_obligations,
    reconcile,
    to_decision_suite,
)
from .otel import MAPPABLE, TraceError, load_trace, parse_mapping
from .reach import analyse
from .scan import scan_file, scan_source
from .scenarios import (
    derive_scenarios,
    load_scenarios,
    reconcile_scenarios,
    save_scenarios,
)
from .verify import replay, replay_file

EXIT_OK = 0
EXIT_FINDING = 1
EXIT_USAGE = 2


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


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
        "--depth",
        type=_positive_int,
        default=None,
        help="override the manifest search depth",
    )
    reach_parser.add_argument("--json", action="store_true", help="machine-readable output")

    diff_parser = subparsers.add_parser(
        "diff", help="compare the effective authority of two manifests"
    )
    diff_parser.add_argument("before", help="the released manifest")
    diff_parser.add_argument("after", help="the proposed manifest")
    diff_parser.add_argument("--depth", type=_positive_int, default=None)
    diff_parser.add_argument("--json", action="store_true", help="machine-readable output")
    diff_parser.add_argument(
        "--record",
        action="store_true",
        help="emit a markdown change record for a change advisory board",
    )

    obligations_parser = subparsers.add_parser(
        "obligations",
        help="derive reviewable test obligations from reachable authority",
    )
    _add_manifest(obligations_parser)
    obligations_parser.add_argument("--depth", type=_positive_int, default=None)
    obligations_parser.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )
    obligations_parser.add_argument(
        "--suite",
        action="store_true",
        help="render reviewed obligations as an AgentVerity decision suite",
    )
    obligations_parser.add_argument(
        "--reviewed",
        default=None,
        help="an obligations file whose decisions have been filled in",
    )

    scenarios_parser = subparsers.add_parser(
        "scenarios",
        help="export reachable breaches as reviewed scenario-test skeletons",
    )
    _add_manifest(scenarios_parser)
    scenarios_parser.add_argument("--depth", type=_positive_int, default=None)
    scenarios_parser.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )
    scenarios_parser.add_argument(
        "--reviewed",
        default=None,
        help="a scenario file whose application-specific fields were reviewed",
    )
    scenarios_parser.add_argument(
        "--output",
        default=None,
        help="write the reconciled JSON scenario skeleton to this path",
    )

    verify_parser = subparsers.add_parser(
        "verify", help="replay recorded calls against the manifest"
    )
    _add_manifest(verify_parser)
    # Exactly one source, so a run can never silently verify the wrong file.
    verify_source = verify_parser.add_mutually_exclusive_group(required=True)
    verify_source.add_argument(
        "--traces", help="JSON Lines file of observed tool calls"
    )
    verify_source.add_argument(
        "--otel", help="OTLP JSON trace, converted to observations before replay"
    )
    verify_parser.add_argument(
        "--map",
        dest="mapping",
        action="append",
        default=None,
        metavar="FIELD=ATTRIBUTE",
        help=(
            "where a control field lives in the trace, for example "
            "scope=app.case.id. repeatable. fields: "
            + ", ".join(MAPPABLE)
        ),
    )
    verify_parser.add_argument(
        "--lenient-tool-spans",
        action="store_true",
        help=(
            "also treat a span with a tool name but no operation attribute as "
            "a tool call. off by default because the convention requires both"
        ),
    )
    verify_parser.add_argument(
        "--emit",
        default=None,
        help="write the converted observations here, for inspection",
    )
    verify_parser.add_argument("--json", action="store_true", help="machine-readable output")

    scan_parser = subparsers.add_parser(
        "scan",
        help="derive a manifest skeleton from a tool catalogue or agent source",
    )
    scan_source_group = scan_parser.add_mutually_exclusive_group(required=True)
    scan_source_group.add_argument(
        "catalogue",
        nargs="?",
        help="JSON file holding an MCP tools/list payload",
    )
    scan_source_group.add_argument(
        "--source",
        help=(
            "Python file or directory declaring the agent's tools. Read "
            "statically: nothing is imported or executed."
        ),
    )
    scan_parser.add_argument(
        "--agent", default="unnamed-agent", help="agent name to write into the skeleton"
    )

    return parser


def _merge(per_run: list) -> Any:
    """Combine per-trace results, keeping every violation.

    Each trace is checked against its own limits. The combined object exists
    so one exit code and one report cover the whole file.
    """
    from .verify import Conformance

    observed = sum(result.observed for _, result in per_run)
    violations = tuple(v for _, result in per_run for v in result.violations)
    return Conformance(observed=observed, violations=violations)


def _observation_to_dict(observation: Any) -> dict:
    """Render one observation back to the replay format, omitting absences.

    An absent field must stay absent rather than becoming null, so the emitted
    file means exactly what the trace supported.
    """
    record: dict[str, Any] = {"tool": observation.tool}
    if observation.scope is not None:
        record["scope"] = observation.scope
    if observation.value is not None:
        record["value"] = str(observation.value)
    if observation.currency is not None:
        record["currency"] = observation.currency
    if observation.principal is not None:
        record["principal"] = observation.principal
    if observation.approved:
        record["approved"] = True
    if observation.errored:
        record["errored"] = True
    return record


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
            if args.source is not None:
                print(scan_source(args.source, args.agent), end="")
            else:
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

    if args.command == "obligations":
        obligations = derive(mandate, depth=args.depth)
        if args.reviewed:
            # Reconciled against the live manifest rather than trusted on its
            # own. A stale review would otherwise generate a suite for
            # authority the agent no longer has.
            try:
                obligations = reconcile(obligations, load_obligations(args.reviewed))
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_USAGE
        if args.suite:
            try:
                print(json.dumps(to_decision_suite(obligations), indent=2))
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_FINDING
            return EXIT_OK
        _emit(obligations.to_dict(), args.json, obligations.render())
        return EXIT_FINDING if obligations.unreviewed else EXIT_OK

    if args.command == "scenarios":
        scenarios = derive_scenarios(mandate, depth=args.depth)
        if args.reviewed:
            try:
                scenarios = reconcile_scenarios(
                    scenarios,
                    load_scenarios(args.reviewed),
                )
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return EXIT_USAGE
        if args.output:
            try:
                save_scenarios(scenarios, args.output)
            except OSError as exc:
                print(f"error: cannot write scenarios: {exc}", file=sys.stderr)
                return EXIT_USAGE
            print(
                f"wrote {len(scenarios.scenarios)} scenario(s) to {args.output}; "
                f"{len(scenarios.unreviewed)} need review"
            )
        else:
            _emit(scenarios.to_dict(), args.json, scenarios.render())
        return EXIT_FINDING if scenarios.scenarios else EXIT_OK

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
        try:
            delta = compare(before, after, depth=args.depth)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        text = (
            delta.record(args.before, args.after)
            if args.record
            else delta.render(args.before, args.after)
        )
        _emit(delta.as_dict(), args.json, text)
        return EXIT_FINDING if delta.widened else EXIT_OK

    try:
        if args.otel:
            conversion = load_trace(
                args.otel,
                parse_mapping(args.mapping),
                lenient=args.lenient_tool_spans,
            )
            # Printed before the verdict, because two observations recovered
            # from four hundred spans is usually a mapping mistake, and a
            # clean report on almost no evidence should not read as success.
            if not args.json:
                print(conversion.summary)
                print()
            if args.emit:
                Path(args.emit).write_text(
                    "".join(
                        json.dumps(_observation_to_dict(o)) + "\n"
                        for o in conversion.observations
                    ),
                    encoding="utf-8",
                )
            # One replay per trace. Flattening them would accumulate one
            # run's spending against another's and report a breach that
            # neither run committed.
            per_run = [
                (trace, replay(mandate, list(group)))
                for trace, group in conversion.runs
            ] or [("", replay(mandate, []))]
            conformance = _merge(per_run)
        else:
            if args.mapping or args.emit or args.lenient_tool_spans:
                print(
                    "error: --map, --emit and --lenient-tool-spans apply to "
                    "--otel only",
                    file=sys.stderr,
                )
                return EXIT_USAGE
            conformance = replay_file(mandate, args.traces)
    except (OSError, ValueError, TraceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    payload = conformance.as_dict()
    if args.otel:
        # CI reads the JSON. Omitting the conversion counts there would hide
        # exactly the warnings that explain a suspiciously clean result.
        payload = {
            "schema": "agentmandate.verify/v1",
            "conversion": {
                "total_spans": conversion.total_spans,
                "tool_calls": conversion.tool_spans,
                "observations": len(conversion.observations),
                "traces": len(conversion.runs),
                "errored": conversion.errored,
                "duplicates": conversion.duplicates,
                "unmapped": list(conversion.unmapped),
            },
            "conformance": payload,
        }
    _emit(payload, args.json, conformance.render())
    return EXIT_OK if conformance.conformant else EXIT_FINDING


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
