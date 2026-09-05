"""Command-line entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from ._conditions import (
    ConditionalAnalysis,
    ConditionContext,
    ConditionFormatError,
    ToolCondition,
    analyse_conditions,
    reconcile_condition_drift,
)
from ._continuity import (
    AgentCoreContinuity,
    AnthropicContinuity,
    ContinuityAnalysis,
    ContinuityBinding,
    ContinuityFormatError,
    _refuse_continuity_composition,
    analyse_continuity,
)
from ._delegation import (
    DelegationAnalysis,
    DelegationAttachment,
    DelegationChain,
    DelegationFormatError,
    _chain_locators,
    _timestamp,
    analyse_delegations,
)
from ._inventory import DynamicInventory, InventoryFormatError, InventoryReconciliation
from ._inventory import reconcile as reconcile_inventory
from ._ir import AuthorityIR, IRFormatError, _analyse_ir, _from_mandate, _to_mandate
from ._managed_cedar import (
    ManagedAnalysis,
    ManagedDiff,
    ManagedOracle,
    ManagedOracleFormatError,
    analyse_managed_cedar,
    compare_managed_cedar,
)
from ._producer import (
    ProducerAnalysis,
    ProducerBoundary,
    ProducerBoundaryFormatError,
    ProducerSelection,
    analyse_producers,
)
from .diff import compare
from .drift import compare as compare_drift
from .findings import render_sarif, to_mermaid
from .inventory import Inventory, collect
from .lint import ERROR, check
from .manifest import ManifestError, load, loads
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


def _add_condition_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--condition",
        action="append",
        default=None,
        metavar="CONDITION",
        help="reviewed tool-condition artifact; repeatable",
    )
    parser.add_argument(
        "--condition-context",
        action="append",
        default=None,
        metavar="CONTEXT",
        help="reviewed condition-context artifact; repeatable",
    )
    parser.add_argument(
        "--condition-capture",
        action="append",
        default=None,
        metavar="CAPTURE",
        help="captured bytes paired by order with --condition-context",
    )
    parser.add_argument(
        "--condition-as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="explicit evaluation date for condition review expiry",
    )


def _add_delegation_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--delegation-attachment",
        action="append",
        default=None,
        metavar="ATTACHMENT",
        help="reviewed tool-to-delegation attachment; repeatable",
    )
    parser.add_argument(
        "--delegation-chain",
        action="append",
        default=None,
        metavar="CHAIN",
        help="reviewed delegation-chain artifact; repeatable",
    )
    parser.add_argument(
        "--delegation-capture",
        action="append",
        default=None,
        metavar="LOCATOR=PATH",
        help="captured bytes for one reviewed source locator; repeatable",
    )
    parser.add_argument(
        "--delegation-as-of",
        default=None,
        metavar="UTC_TIMESTAMP",
        help="canonical UTC timestamp used for delegation validity",
    )
    parser.add_argument(
        "--delegation-target-source",
        default=None,
        metavar="SOURCE",
        help="selected repository-relative source addressed by attachments",
    )
    parser.add_argument(
        "--delegation-target-binding",
        default=None,
        metavar="BINDING",
        help="selected source binding addressed by attachments",
    )


def _add_producer_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--producer-boundary",
        action="append",
        default=None,
        metavar="BOUNDARY",
        help="reviewed finite-producer boundary; repeatable",
    )
    parser.add_argument(
        "--producer-source",
        action="append",
        default=None,
        metavar="LOCATOR=PATH",
        help="captured bytes for one producer source locator; repeatable",
    )
    parser.add_argument(
        "--producer-selection",
        action="append",
        default=None,
        metavar="JSON",
        help="selected deployment and reviewed partition JSON; repeatable",
    )
    parser.add_argument(
        "--producer-as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="explicit evaluation date for producer review expiry",
    )


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
    reach_source = reach_parser.add_mutually_exclusive_group(required=True)
    reach_source.add_argument(
        "manifest",
        nargs="?",
        help="path to a mandate manifest (YAML or JSON)",
    )
    reach_source.add_argument(
        "--ir",
        dest="ir_snapshot",
        metavar="SNAPSHOT",
        help="an Authority IR source snapshot to validate and analyze",
    )
    reach_parser.add_argument(
        "--depth",
        type=_positive_int,
        default=None,
        help="override the manifest search depth",
    )
    reach_parser.add_argument("--json", action="store_true", help="machine-readable output")
    reach_parser.add_argument(
        "--sarif",
        action="store_true",
        help="emit SARIF 2.1.0 for GitHub code scanning",
    )
    reach_parser.add_argument(
        "--graph",
        action="store_true",
        help="emit a Mermaid diagram of the authority graph and the breaching path",
    )
    _add_condition_options(reach_parser)
    _add_delegation_options(reach_parser)
    _add_producer_options(reach_parser)

    ir_parser = subparsers.add_parser(
        "ir",
        help="export or structurally validate canonical Authority IR",
    )
    ir_subparsers = ir_parser.add_subparsers(dest="ir_command", required=True)
    ir_export = ir_subparsers.add_parser(
        "export",
        help="export a manifest as one canonical source snapshot",
    )
    _add_manifest(ir_export)
    ir_validate = ir_subparsers.add_parser(
        "validate",
        help="validate snapshot structure without accepting it as authority",
    )
    ir_validate.add_argument("snapshot", help="path to an Authority IR snapshot")

    inventory_parser = subparsers.add_parser(
        "inventory",
        help="structurally validate reviewed dynamic-inventory declarations",
    )
    inventory_subparsers = inventory_parser.add_subparsers(
        dest="inventory_command", required=True
    )
    inventory_validate = inventory_subparsers.add_parser(
        "validate",
        help="validate declaration structure without accepting it as authority",
    )
    inventory_validate.add_argument("declaration", help="path to a declaration")

    conditions_parser = subparsers.add_parser(
        "conditions",
        help="structurally validate conditional-authority artifacts",
    )
    conditions_subparsers = conditions_parser.add_subparsers(
        dest="conditions_command", required=True
    )
    conditions_validate = conditions_subparsers.add_parser(
        "validate",
        help="validate artifact structure without accepting it as authority",
    )
    conditions_input = conditions_validate.add_mutually_exclusive_group(required=True)
    conditions_input.add_argument(
        "--condition", help="path to one tool-condition artifact"
    )
    conditions_input.add_argument(
        "--context", help="path to one condition-context artifact"
    )

    delegations_parser = subparsers.add_parser(
        "delegations",
        help="structurally validate delegation artifacts",
    )
    delegations_subparsers = delegations_parser.add_subparsers(
        dest="delegations_command", required=True
    )
    delegations_validate = delegations_subparsers.add_parser(
        "validate",
        help="validate artifact structure without accepting it as authority",
    )
    delegations_input = delegations_validate.add_mutually_exclusive_group(required=True)
    delegations_input.add_argument("--attachment", help="path to one attachment artifact")
    delegations_input.add_argument("--chain", help="path to one delegation-chain artifact")

    producers_parser = subparsers.add_parser(
        "producers",
        help="structurally validate finite-producer boundaries",
    )
    producers_subparsers = producers_parser.add_subparsers(
        dest="producers_command", required=True
    )
    producers_validate = producers_subparsers.add_parser(
        "validate",
        help="validate a boundary structurally without trusting its sources",
    )
    producers_validate.add_argument("boundary", help="path to one producer boundary")

    continuity_parser = subparsers.add_parser(
        "continuity",
        help="validate or reconcile reviewed authority-continuity evidence",
    )
    continuity_subparsers = continuity_parser.add_subparsers(
        dest="continuity_command", required=True
    )
    continuity_validate = continuity_subparsers.add_parser(
        "validate",
        help="validate one continuity artifact without trusting its evidence",
    )
    continuity_validate.add_argument("artifact", help="path to one continuity artifact")
    continuity_reconcile = continuity_subparsers.add_parser(
        "reconcile",
        help="reconcile reviewed lifecycle transitions with manifest authority",
    )
    _add_manifest(continuity_reconcile)
    continuity_reconcile.add_argument(
        "--continuity-provider", required=True, metavar="PROVIDER_RECORD"
    )
    continuity_reconcile.add_argument(
        "--continuity-source",
        action="append",
        default=None,
        metavar="LOCATOR=CAPTURE",
        help="captured bytes for one provider source locator; repeatable",
    )
    continuity_reconcile.add_argument("--continuity-binding", metavar="BINDING")
    continuity_reconcile.add_argument(
        "--continuity-binding-source",
        action="append",
        default=None,
        metavar="LOCATOR=CAPTURE",
        help="captured bytes for one binding source locator; repeatable",
    )
    continuity_reconcile.add_argument(
        "--continuity-as-of",
        required=True,
        metavar="UTC_TIMESTAMP",
        help="whole-second UTC timestamp used for evidence validity",
    )
    continuity_reconcile.add_argument("--depth", type=_positive_int, default=None)
    continuity_reconcile.add_argument(
        "--json", action="store_true", help="canonical machine-readable output"
    )
    for option in (
        "--cedar",
        "--condition",
        "--delegation",
        "--ir",
        "--graph",
        "--otel",
        "--producer",
        "--sarif",
    ):
        continuity_reconcile.add_argument(option, action="store_true", help=argparse.SUPPRESS)

    cedar_parser = subparsers.add_parser(
        "cedar",
        help="validate or compare reviewed managed Cedar evidence",
    )
    cedar_subparsers = cedar_parser.add_subparsers(dest="cedar_command", required=True)
    cedar_validate = cedar_subparsers.add_parser(
        "validate",
        help="validate a managed oracle structurally without trusting its sources",
    )
    cedar_validate.add_argument("oracle", help="path to a managed Cedar oracle")
    cedar_align = cedar_subparsers.add_parser(
        "align",
        help="align one managed oracle with reviewed manifest authority",
    )
    _add_manifest(cedar_align)
    cedar_align.add_argument("--oracle", required=True, help="managed Cedar oracle")
    cedar_align.add_argument(
        "--source-root",
        required=True,
        help="directory containing every source declared by the oracle",
    )
    cedar_align.add_argument(
        "--as-of",
        required=True,
        metavar="YYYY-MM-DD",
        help="explicit evaluation date for reviewed mapping evidence",
    )
    cedar_align.add_argument("--json", action="store_true", help="machine-readable output")
    cedar_diff = cedar_subparsers.add_parser(
        "diff",
        help="compare exact managed requests across two policy revisions",
    )
    _add_manifest(cedar_diff)
    cedar_diff.add_argument("--baseline-oracle", required=True)
    cedar_diff.add_argument("--baseline-root", required=True)
    cedar_diff.add_argument("--candidate-oracle", required=True)
    cedar_diff.add_argument("--candidate-root", required=True)
    cedar_diff.add_argument(
        "--as-of",
        required=True,
        metavar="YYYY-MM-DD",
        help="explicit evaluation date for both reviewed mappings",
    )
    cedar_diff.add_argument("--json", action="store_true", help="machine-readable output")

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

    drift_parser = subparsers.add_parser(
        "drift",
        help="compare the declared mandate against the agent's source",
    )
    drift_parser.add_argument("manifest", help="path to a mandate manifest (YAML or JSON)")
    drift_parser.add_argument(
        "--source",
        required=True,
        help="Python file or directory declaring the agent's tools",
    )
    drift_parser.add_argument(
        "--binding",
        help="the tool list to compare against, when the source builds several agents",
    )
    drift_parser.add_argument(
        "--union-bindings",
        action="store_true",
        help="compare against every agent's tools merged",
    )
    drift_parser.add_argument("--json", action="store_true", help="machine-readable output")
    drift_parser.add_argument(
        "--inventory-declaration",
        action="append",
        default=None,
        metavar="DECLARATION",
        help="reviewed dynamic-inventory declaration; repeatable",
    )
    drift_parser.add_argument(
        "--inventory-capture",
        action="append",
        default=None,
        metavar="CAPTURE",
        help="captured bytes paired by order with --inventory-declaration",
    )
    drift_parser.add_argument(
        "--inventory-selection",
        default=None,
        metavar="JSON",
        help="reviewed deployment selection as a JSON object",
    )
    drift_parser.add_argument(
        "--inventory-as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="explicit evaluation date for inventory review expiry",
    )
    _add_condition_options(drift_parser)

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
    scan_parser.add_argument(
        "--binding",
        help=(
            "with --source, the tool list to take the inventory from, when the "
            "source builds more than one agent"
        ),
    )
    scan_parser.add_argument(
        "--union-bindings",
        action="store_true",
        help=(
            "with --source, merge every agent's tools into one manifest. Only "
            "correct when they genuinely share authority"
        ),
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


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _run_ir(args: argparse.Namespace) -> int:
    try:
        if args.ir_command == "export":
            path = Path(args.manifest)
            content = path.read_bytes()
            mandate = loads(content.decode("utf-8"), source=str(path))
            output = _from_mandate(mandate, content=content).to_json()
        else:
            snapshot = AuthorityIR.from_json(_read_text(args.snapshot))
            output = f"valid authority IR v{snapshot.ir_version}\n"
    except (IRFormatError, ManifestError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(output)
    return EXIT_OK


def _run_inventory(args: argparse.Namespace) -> int:
    try:
        declaration = DynamicInventory.from_json(_read_text(args.declaration))
    except (InventoryFormatError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"valid dynamic inventory v{declaration.inventory_version}")
    return EXIT_OK


def _run_conditions(args: argparse.Namespace) -> int:
    try:
        if args.condition is not None:
            value = ToolCondition.from_json(_read_text(args.condition))
            output = f"valid tool condition v{value.version}\n"
        else:
            value = ConditionContext.from_json(_read_text(args.context))
            output = f"valid condition context v{value.version}\n"
    except (ConditionFormatError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(output)
    return EXIT_OK


def _run_delegations(args: argparse.Namespace) -> int:
    try:
        if args.attachment is not None:
            value = DelegationAttachment.from_json(_read_text(args.attachment))
            output = f"valid delegation attachment v{value.version}\n"
        else:
            value = DelegationChain.from_json(_read_text(args.chain))
            output = f"valid delegation chain v{value.version}\n"
    except (DelegationFormatError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(output)
    return EXIT_OK


def _run_producers(args: argparse.Namespace) -> int:
    try:
        value = ProducerBoundary.from_json(_read_text(args.boundary))
        output = f"valid producer boundary v{value.producer_boundary_version}\n"
    except (ProducerBoundaryFormatError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(output)
    return EXIT_OK


def _continuity_artifact(
    text: str,
) -> ContinuityBinding | AgentCoreContinuity | AnthropicContinuity:
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContinuityFormatError("continuity artifact is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ContinuityFormatError("continuity artifact must be an object")
    readers = {
        "continuity_binding_version": ContinuityBinding,
        "agentcore_continuity_version": AgentCoreContinuity,
        "anthropic_continuity_version": AnthropicContinuity,
    }
    matches = [reader for field, reader in readers.items() if field in raw]
    if len(matches) != 1:
        raise ContinuityFormatError(
            "continuity artifact must declare exactly one supported artifact version"
        )
    return matches[0].from_json(text)


def _continuity_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ContinuityFormatError(
            "--continuity-as-of must be YYYY-MM-DDTHH:MM:SSZ"
        ) from exc
    return parsed


def _continuity_source_paths(values: list[str] | None, option: str) -> dict[str, str]:
    paths: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ContinuityFormatError(f"{option} must be LOCATOR=PATH")
        locator, path = value.split("=", 1)
        if not locator or not path:
            raise ContinuityFormatError(f"{option} must be LOCATOR=PATH")
        if locator in paths:
            raise ContinuityFormatError(f"{option} repeats locator {locator}")
        paths[locator] = path
    return paths


def _continuity_sources(
    paths: dict[str, str],
    declared: tuple,
    option: str,
) -> dict[str, bytes]:
    expected = {source.locator for source in declared}
    if set(paths) != expected:
        missing = sorted(expected - set(paths))
        extra = sorted(set(paths) - expected)
        locator = (missing or extra)[0]
        relation = "required for" if missing else "not declared by"
        raise ContinuityFormatError(f"{option} locator {locator} is {relation} the artifact")
    return {locator: Path(path).read_bytes() for locator, path in paths.items()}


def _continuity_composition(args: argparse.Namespace) -> frozenset[str]:
    names = {
        "cedar": "cedar",
        "condition": "conditions",
        "delegation": "delegations",
        "ir": "ir",
        "graph": "mermaid",
        "otel": "otel",
        "producer": "producers",
        "sarif": "sarif",
    }
    return frozenset(value for name, value in names.items() if getattr(args, name))


def _render_continuity(analysis: ContinuityAnalysis) -> str:
    lines = [f"authority continuity  evaluated as of {analysis.as_of}"]
    for outcome in analysis.outcomes:
        lines.extend(
            (
                f"{outcome.safe_continuation.upper():<10}  {outcome.transition}",
                f"  provider={outcome.provider} kind={outcome.kind}",
                f"  state={outcome.state} authority={outcome.authority_change} "
                f"admission={outcome.admission}",
                f"  comparability={outcome.comparability} "
                f"issuer_amendment={outcome.issuer_amendment}",
            )
        )
        for alignment in outcome.alignments:
            lines.append(
                f"  alignment {alignment.check}={alignment.status} ({alignment.strength})"
            )
        lines.extend(f"  assumption: {item}" for item in outcome.assumptions)
    for finding in analysis.findings:
        subject = "" if finding.transition is None else f" [{finding.transition}]"
        lines.append(f"FINDING     {finding.code}{subject}: {finding.message}")
    lines.append("AUTHORITY")
    authority = json.dumps(analysis.authority.as_dict(), indent=2)
    lines.extend(f"  {line}" for line in authority.splitlines())
    return "\n".join(lines)


def _run_continuity(args: argparse.Namespace) -> int:
    try:
        if args.continuity_command == "validate":
            artifact = _continuity_artifact(_read_text(args.artifact))
            labels = {
                ContinuityBinding: "continuity binding",
                AgentCoreContinuity: "AgentCore continuity profile",
                AnthropicContinuity: "Anthropic continuity profile",
            }
            print(f"valid {labels[type(artifact)]} v{artifact.version}")
            return EXIT_OK

        composition = _continuity_composition(args)
        _refuse_continuity_composition(composition)
        as_of = _continuity_timestamp(args.continuity_as_of)
        provider_paths = _continuity_source_paths(
            args.continuity_source, "--continuity-source"
        )
        binding_paths = _continuity_source_paths(
            args.continuity_binding_source, "--continuity-binding-source"
        )
        if args.continuity_binding is None and binding_paths:
            raise ContinuityFormatError(
                "--continuity-binding is required with --continuity-binding-source"
            )
        if args.continuity_binding is not None and not binding_paths:
            raise ContinuityFormatError(
                "--continuity-binding-source is required with --continuity-binding"
            )

        provider = _continuity_artifact(_read_text(args.continuity_provider))
        if isinstance(provider, ContinuityBinding):
            raise ContinuityFormatError("--continuity-provider requires a provider profile")
        binding = None
        if args.continuity_binding is not None:
            candidate = _continuity_artifact(_read_text(args.continuity_binding))
            if not isinstance(candidate, ContinuityBinding):
                raise ContinuityFormatError("--continuity-binding requires a binding artifact")
            binding = candidate
        provider_sources = _continuity_sources(
            provider_paths, provider.sources, "--continuity-source"
        )
        binding_sources = (
            None
            if binding is None
            else _continuity_sources(
                binding_paths, binding.sources, "--continuity-binding-source"
            )
        )
        manifest_path = Path(args.manifest)
        mandate_bytes = manifest_path.read_bytes()
        mandate = loads(mandate_bytes.decode("utf-8"), source=str(manifest_path))
        analysis = analyse_continuity(
            mandate,
            provider,
            provider_sources,
            as_of=as_of,
            binding=binding,
            binding_source_bytes=binding_sources,
            mandate_bytes=mandate_bytes,
            depth=args.depth,
            composition=composition,
        )
    except (ContinuityFormatError, ManifestError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        sys.stdout.write(analysis.to_result().to_json())
    else:
        print(_render_continuity(analysis))
    return EXIT_OK if analysis.clean else EXIT_FINDING


def _cedar_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ManagedOracleFormatError("--as-of must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ManagedOracleFormatError("--as-of must be YYYY-MM-DD")
    return parsed


def _managed_sources(oracle: ManagedOracle, root: str) -> dict[str, bytes]:
    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ManagedOracleFormatError("managed Cedar source root must be a directory")
    contents = {}
    for source in oracle.sources:
        path = (root_path / source.locator).resolve(strict=True)
        if not path.is_relative_to(root_path) or not path.is_file():
            raise ManagedOracleFormatError(
                f"managed Cedar source locator '{source.locator}' is outside the source root"
            )
        contents[source.locator] = path.read_bytes()
    return contents


def _oracle_input(path: str, root: str) -> tuple[ManagedOracle, dict[str, bytes], str]:
    content = Path(path).read_bytes()
    oracle = ManagedOracle.from_json(content.decode("utf-8"))
    sources = _managed_sources(oracle, root)
    return oracle, sources, hashlib.sha256(content).hexdigest()


def _oracle_digests(
    oracle: ManagedOracle,
    contents: dict[str, bytes],
    content_sha256: str,
) -> dict[str, Any]:
    source_digests = {
        locator: hashlib.sha256(content).hexdigest()
        for locator, content in sorted(contents.items())
    }
    return {
        "oracle_sha256": content_sha256,
        "profile_sha256": oracle.to_ir().sources[0].semantic_sha256,
        "mapping_sha256": source_digests[oracle.mapping.source],
        "source_sha256": source_digests,
    }


def _managed_alignment_payload(
    analysis: ManagedAnalysis,
    *,
    manifest_sha256: str,
    analysis_oracle: ManagedOracle,
    analysis_contents: dict[str, bytes],
    oracle_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "agentmandate.cedar-alignment/v1",
        "inputs": {
            "manifest_sha256": manifest_sha256,
            "oracle": _oracle_digests(
                analysis_oracle,
                analysis_contents,
                oracle_sha256,
            ),
        },
        **analysis.as_dict(),
    }


def _managed_diff_payload(
    result: ManagedDiff,
    *,
    manifest_sha256: str,
    baseline_oracle: ManagedOracle,
    baseline_contents: dict[str, bytes],
    baseline_sha256: str,
    candidate_oracle: ManagedOracle,
    candidate_contents: dict[str, bytes],
    candidate_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": "agentmandate.cedar-effective-diff/v1",
        "inputs": {
            "manifest_sha256": manifest_sha256,
            "baseline": _oracle_digests(
                baseline_oracle,
                baseline_contents,
                baseline_sha256,
            ),
            "candidate": _oracle_digests(
                candidate_oracle,
                candidate_contents,
                candidate_sha256,
            ),
        },
        **result.as_dict(),
    }


def _render_managed_analysis(analysis: ManagedAnalysis) -> str:
    lines = [f"managed Cedar  evaluated as of {analysis.as_of}"]
    for item in analysis.alignments:
        status = {
            "aligned_allow": "ALIGNED",
            "enforcement_narrows_request": "NARROWS",
            "unresolved": "UNRESOLVED",
        }[item.alignment]
        lines.append(f"  {status:<10} {item.tool or '<unmapped>'} ({item.decision})")
        lines.append(f"      {item.reason}: {item.request_key}")
    for item in analysis.findings:
        lines.append(f"  FINDING     {item.code}")
        lines.append(f"      {item.message}")
    return "\n".join(lines)


def _render_managed_diff(result: ManagedDiff) -> str:
    lines = [f"managed Cedar diff  evaluated as of {result.baseline.as_of}"]
    for item in result.changes:
        lines.append(
            f"  {item.classification.upper():<12} {item.tool or '<unmapped>'}: "
            f"{item.baseline} -> {item.candidate}"
        )
        lines.append(f"      {item.request_key}")
    for item in result.findings:
        lines.append(f"  FINDING       {item.code}")
        lines.append(f"      {item.message}")
    return "\n".join(lines)


def _run_cedar(args: argparse.Namespace) -> int:
    try:
        if args.cedar_command == "validate":
            oracle = ManagedOracle.from_json(_read_text(args.oracle))
            output = f"valid managed Cedar oracle v{oracle.managed_oracle_version}\n"
            result_clean = True
        else:
            manifest_content = Path(args.manifest).read_bytes()
            mandate = loads(manifest_content.decode("utf-8"), source=args.manifest)
            as_of = _cedar_date(args.as_of)
            manifest_sha256 = hashlib.sha256(manifest_content).hexdigest()
            if args.cedar_command == "align":
                oracle, contents, oracle_sha256 = _oracle_input(
                    args.oracle, args.source_root
                )
                analysis = analyse_managed_cedar(
                    mandate,
                    oracle,
                    contents,
                    as_of=as_of,
                )
                payload = _managed_alignment_payload(
                    analysis,
                    manifest_sha256=manifest_sha256,
                    analysis_oracle=oracle,
                    analysis_contents=contents,
                    oracle_sha256=oracle_sha256,
                )
                output = (
                    json.dumps(payload, indent=2, sort_keys=True) + "\n"
                    if args.json
                    else _render_managed_analysis(analysis) + "\n"
                )
                result_clean = analysis.clean
            else:
                baseline, baseline_contents, baseline_sha256 = _oracle_input(
                    args.baseline_oracle, args.baseline_root
                )
                candidate, candidate_contents, candidate_sha256 = _oracle_input(
                    args.candidate_oracle, args.candidate_root
                )
                result = compare_managed_cedar(
                    mandate,
                    baseline,
                    baseline_contents,
                    candidate,
                    candidate_contents,
                    as_of=as_of,
                )
                payload = _managed_diff_payload(
                    result,
                    manifest_sha256=manifest_sha256,
                    baseline_oracle=baseline,
                    baseline_contents=baseline_contents,
                    baseline_sha256=baseline_sha256,
                    candidate_oracle=candidate,
                    candidate_contents=candidate_contents,
                    candidate_sha256=candidate_sha256,
                )
                output = (
                    json.dumps(payload, indent=2, sort_keys=True) + "\n"
                    if args.json
                    else _render_managed_diff(result) + "\n"
                )
                result_clean = result.clean
    except (
        ManagedOracleFormatError,
        ManifestError,
        OSError,
        UnicodeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    sys.stdout.write(output)
    return EXIT_OK if result_clean else EXIT_FINDING


def _delegations_supplied(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "delegation_attachment", None)
        or getattr(args, "delegation_chain", None)
        or getattr(args, "delegation_capture", None)
        or getattr(args, "delegation_as_of", None)
        or getattr(args, "delegation_target_source", None)
        or getattr(args, "delegation_target_binding", None)
    )


def _delegation_inputs(
    args: argparse.Namespace,
) -> tuple[
    tuple[DelegationAttachment, ...],
    tuple[DelegationChain, ...],
    dict[str, bytes],
    str,
    str,
    str,
] | None:
    if not _delegations_supplied(args):
        return None
    attachment_paths = args.delegation_attachment or []
    chain_paths = args.delegation_chain or []
    capture_values = args.delegation_capture or []
    if not attachment_paths:
        raise DelegationFormatError("--delegation-attachment is required")
    if not chain_paths:
        raise DelegationFormatError("--delegation-chain is required")
    if args.delegation_as_of is None:
        raise DelegationFormatError("--delegation-as-of is required")
    _timestamp(
        {"as_of": args.delegation_as_of},
        "as_of",
        "command_line",
    )
    if args.delegation_target_source is None:
        raise DelegationFormatError("--delegation-target-source is required")
    if args.delegation_target_binding is None:
        raise DelegationFormatError("--delegation-target-binding is required")
    attachments = tuple(
        DelegationAttachment.from_json(_read_text(path)) for path in attachment_paths
    )
    chains = tuple(DelegationChain.from_json(_read_text(path)) for path in chain_paths)
    source_bytes: dict[str, bytes] = {}
    for value in capture_values:
        if "=" not in value:
            raise DelegationFormatError(
                "--delegation-capture must be LOCATOR=PATH"
            )
        locator, path = value.split("=", maxsplit=1)
        if not locator or not path:
            raise DelegationFormatError(
                "--delegation-capture must be LOCATOR=PATH"
            )
        content = Path(path).read_bytes()
        previous = source_bytes.get(locator)
        if previous is not None and previous != content:
            raise DelegationFormatError(
                "one delegation locator supplied different capture bytes"
            )
        source_bytes[locator] = content
    required_locators = set().union(*(_chain_locators(chain) for chain in chains))
    missing = sorted(required_locators - source_bytes.keys())
    if missing:
        raise DelegationFormatError(
            f"--delegation-capture is required for reviewed locator {missing[0]}"
        )
    if source_bytes.keys() - required_locators:
        raise DelegationFormatError(
            "--delegation-capture includes an undeclared locator"
        )
    return (
        attachments,
        chains,
        source_bytes,
        args.delegation_as_of,
        args.delegation_target_source,
        args.delegation_target_binding,
    )


def _delegation_payload(analysis: DelegationAnalysis) -> dict[str, Any]:
    return {
        "schema": "agentmandate.delegations/v1",
        "as_of": analysis.as_of,
        "attenuated": [
            {
                "attachment": item.attachment,
                "tool": item.tool,
                "delegation": item.delegation,
                "hop": item.hop,
                "support": list(item.support),
            }
            for item in analysis.attenuated
        ],
        "findings": [
            {
                "code": item.code,
                "attachment": item.attachment,
                "tool": item.tool,
                "hop": item.hop,
                "dimension": item.dimension,
                "message": item.message,
                "support": list(item.support),
            }
            for item in analysis.findings
        ],
    }


def _render_delegations(analysis: DelegationAnalysis) -> str:
    lines = [f"delegations  evaluated as of {analysis.as_of}"]
    for item in analysis.attenuated:
        lines.append(
            f"  ATTENUATED  {item.tool} ({item.attachment} -> {item.delegation}#{item.hop})"
        )
    for item in analysis.findings:
        status = "WIDENS" if item.code == "delegation.widens" else "UNRESOLVED"
        location = "" if item.hop is None else f" at {item.hop}"
        if item.dimension is not None:
            location += f"/{item.dimension}"
        lines.append(f"  {status:<10} {item.tool} ({item.attachment}){location}")
        lines.append(f"      {item.message}")
    return "\n".join(lines)


def _producers_supplied(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "producer_boundary", None)
        or getattr(args, "producer_source", None)
        or getattr(args, "producer_selection", None)
        or getattr(args, "producer_as_of", None)
    )


def _producer_selection_key(selection: ProducerSelection) -> tuple[str, ...]:
    return (
        selection.source,
        selection.binding,
        selection.producer,
        selection.producer_version,
        selection.partition_argument,
        selection.partition_binding,
        selection.output_scope,
    )


def _producer_boundary_key(boundary: ProducerBoundary) -> tuple[str, ...]:
    return (
        boundary.target.source,
        boundary.target.binding,
        boundary.target.producer,
        boundary.target.producer_version,
        boundary.partition.argument,
        boundary.partition.binding,
        boundary.output.scope,
    )


def _producer_inputs(
    args: argparse.Namespace,
) -> tuple[
    tuple[ProducerBoundary, ...],
    dict[str, bytes],
    tuple[ProducerSelection, ...],
    date,
] | None:
    if not _producers_supplied(args):
        return None
    boundary_paths = args.producer_boundary or []
    source_values = args.producer_source or []
    selection_values = args.producer_selection or []
    if not boundary_paths:
        raise ProducerBoundaryFormatError("--producer-boundary is required")
    if not source_values:
        raise ProducerBoundaryFormatError("--producer-source is required")
    if not selection_values:
        raise ProducerBoundaryFormatError("--producer-selection is required")
    if args.producer_as_of is None:
        raise ProducerBoundaryFormatError("--producer-as-of is required")
    try:
        as_of = date.fromisoformat(args.producer_as_of)
    except ValueError as exc:
        raise ProducerBoundaryFormatError(
            "--producer-as-of must be YYYY-MM-DD"
        ) from exc
    if as_of.isoformat() != args.producer_as_of:
        raise ProducerBoundaryFormatError("--producer-as-of must be YYYY-MM-DD")

    boundaries = tuple(
        ProducerBoundary.from_json(_read_text(path)) for path in boundary_paths
    )
    selections = tuple(
        ProducerSelection.from_json(value) for value in selection_values
    )
    boundary_keys = {_producer_boundary_key(boundary) for boundary in boundaries}
    if any(_producer_selection_key(selection) not in boundary_keys for selection in selections):
        raise ProducerBoundaryFormatError(
            "--producer-selection does not match any --producer-boundary"
        )

    source_bytes: dict[str, bytes] = {}
    for value in source_values:
        if "=" not in value:
            raise ProducerBoundaryFormatError(
                "--producer-source must be LOCATOR=PATH"
            )
        locator, path = value.split("=", maxsplit=1)
        if not locator or not path:
            raise ProducerBoundaryFormatError(
                "--producer-source must be LOCATOR=PATH"
            )
        content = Path(path).read_bytes()
        previous = source_bytes.get(locator)
        if previous is not None and previous != content:
            raise ProducerBoundaryFormatError(
                "one producer locator supplied different source bytes"
            )
        source_bytes[locator] = content
    required_locators = {
        source.locator for boundary in boundaries for source in boundary.sources
    }
    missing = sorted(required_locators - source_bytes.keys())
    if missing:
        raise ProducerBoundaryFormatError(
            f"--producer-source is required for reviewed locator {missing[0]}"
        )
    if source_bytes.keys() - required_locators:
        raise ProducerBoundaryFormatError(
            "--producer-source includes an undeclared locator"
        )
    return boundaries, source_bytes, selections, as_of


def _render_producers(analysis: ProducerAnalysis) -> str:
    lines = [f"producers  evaluated as of {analysis.as_of}"]
    for item in analysis.applied:
        lines.append(
            f"  BOUNDED     {item.tool}: {item.capacity_kind} maximum "
            f"{item.maximum} ({item.boundary})"
        )
    for item in analysis.findings:
        lines.append(f"  UNRESOLVED  {item.tool} ({item.code})")
        lines.append(f"      {item.message}")
    return "\n".join(lines)


def _conditions_supplied(args: argparse.Namespace) -> bool:
    return bool(
        getattr(args, "condition", None)
        or getattr(args, "condition_context", None)
        or getattr(args, "condition_capture", None)
        or getattr(args, "condition_as_of", None)
    )


def _condition_inputs(
    args: argparse.Namespace,
) -> tuple[
    tuple[ToolCondition, ...],
    tuple[ConditionContext, ...],
    dict[str, bytes],
    date,
] | None:
    if not _conditions_supplied(args):
        return None
    condition_paths = args.condition or []
    context_paths = args.condition_context or []
    captures = args.condition_capture or []
    if not condition_paths:
        raise ConditionFormatError("--condition is required")
    if not context_paths:
        raise ConditionFormatError("--condition-context is required")
    if len(context_paths) != len(captures):
        raise ConditionFormatError(
            "supply one --condition-capture for each --condition-context"
        )
    if args.condition_as_of is None:
        raise ConditionFormatError("--condition-as-of is required")
    try:
        as_of = date.fromisoformat(args.condition_as_of)
    except ValueError as exc:
        raise ConditionFormatError("--condition-as-of must be YYYY-MM-DD") from exc
    if as_of.isoformat() != args.condition_as_of:
        raise ConditionFormatError("--condition-as-of must be YYYY-MM-DD")

    conditions = tuple(
        ToolCondition.from_json(_read_text(path)) for path in condition_paths
    )
    contexts: list[ConditionContext] = []
    source_bytes: dict[str, bytes] = {}
    for context_path, capture_path in zip(context_paths, captures, strict=True):
        context = ConditionContext.from_json(_read_text(context_path))
        content = Path(capture_path).read_bytes()
        previous = source_bytes.get(context.id)
        if previous is not None and previous != content:
            raise ConditionFormatError(
                "contexts with one id supplied different capture bytes"
            )
        source_bytes[context.id] = content
        contexts.append(context)
    return conditions, tuple(contexts), source_bytes, as_of


def _condition_payload(analysis: ConditionalAnalysis) -> dict[str, Any]:
    return {
        "schema": "agentmandate.conditions/v1",
        "as_of": analysis.as_of,
        "applied": [
            {
                "condition": item.condition,
                "context": item.context,
                "tool": item.tool,
                "default_effect": item.default_effect,
                "effective_effect": item.effective_effect,
                "support": list(item.support),
            }
            for item in analysis.applied
        ],
        "findings": [
            {
                "condition": item.condition,
                "tool": item.tool,
                "message": item.message,
            }
            for item in analysis.findings
        ],
    }


def _render_conditions(analysis: ConditionalAnalysis) -> str:
    lines = [f"conditions  evaluated as of {analysis.as_of}"]
    for item in analysis.applied:
        lines.append(
            f"  APPLIED     {item.tool}: {item.default_effect} -> "
            f"{item.effective_effect} ({item.condition})"
        )
    for item in analysis.findings:
        lines.append(f"  UNRESOLVED  {item.tool} ({item.condition})")
        lines.append(f"      {item.message}")
    return "\n".join(lines)


def _dynamic_inventory(
    args: argparse.Namespace, inventory: Inventory
) -> InventoryReconciliation | None:
    paths = args.inventory_declaration or []
    captures = args.inventory_capture or []
    supplied = bool(paths or captures or args.inventory_selection or args.inventory_as_of)
    if not supplied:
        return None
    if not paths:
        raise InventoryFormatError("--inventory-declaration is required")
    if len(paths) != len(captures):
        raise InventoryFormatError(
            "supply one --inventory-capture for each --inventory-declaration"
        )
    if args.inventory_selection is None:
        raise InventoryFormatError("--inventory-selection is required")
    if args.inventory_as_of is None:
        raise InventoryFormatError("--inventory-as-of is required")
    try:
        selection = json.loads(args.inventory_selection)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InventoryFormatError("--inventory-selection must be valid JSON") from exc
    if not isinstance(selection, dict):
        raise InventoryFormatError("--inventory-selection must be a JSON object")
    try:
        as_of = date.fromisoformat(args.inventory_as_of)
    except ValueError as exc:
        raise InventoryFormatError("--inventory-as-of must be YYYY-MM-DD") from exc
    if as_of.isoformat() != args.inventory_as_of:
        raise InventoryFormatError("--inventory-as-of must be YYYY-MM-DD")

    declarations = []
    source_contents: dict[str, bytes] = {}
    for declaration_path, capture_path in zip(paths, captures, strict=True):
        declaration = DynamicInventory.from_json(_read_text(declaration_path))
        content = Path(capture_path).read_bytes()
        previous = source_contents.get(declaration.source.locator)
        if previous is not None and previous != content:
            raise InventoryFormatError(
                "declarations with one source locator supplied different capture bytes"
            )
        source_contents[declaration.source.locator] = content
        declarations.append(declaration)
    return reconcile_inventory(
        inventory,
        declarations,
        source_contents,
        selection=selection,
        as_of=as_of,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "ir":
        return _run_ir(args)

    if args.command == "inventory":
        return _run_inventory(args)

    if args.command == "conditions":
        return _run_conditions(args)

    if args.command == "delegations":
        return _run_delegations(args)

    if args.command == "producers":
        return _run_producers(args)

    if args.command == "continuity":
        return _run_continuity(args)

    if args.command == "cedar":
        return _run_cedar(args)

    if args.command == "scan":
        try:
            if args.source is not None:
                print(
                    scan_source(
                        args.source,
                        args.agent,
                        binding=args.binding,
                        union=args.union_bindings,
                    ),
                    end="",
                )
            else:
                if args.binding is not None or args.union_bindings:
                    raise ValueError(
                        "--binding and --union-bindings apply to --source. An "
                        "MCP catalogue holds one tool list already."
                    )
                print(scan_file(args.catalogue, args.agent), end="")
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        return EXIT_OK

    if args.command == "reach":
        chosen = [name for name in ("json", "sarif", "graph") if getattr(args, name)]
        if len(chosen) > 1:
            # Each writes to standard output. Emitting two would produce a
            # file that is neither.
            print(
                f"error: choose one output format, not {', '.join('--' + f for f in chosen)}",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _conditions_supplied(args) and args.ir_snapshot is not None:
            print(
                "error: conditional artifacts require a manifest; standalone "
                "condition profiles cannot be composed with --ir",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _conditions_supplied(args) and (args.sarif or args.graph):
            print(
                "error: conditional findings currently support human or --json "
                "output, not --sarif or --graph",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _delegations_supplied(args) and args.ir_snapshot is not None:
            print(
                "error: delegation artifacts require a manifest; standalone "
                "delegation profiles cannot be composed with --ir",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _delegations_supplied(args) and (args.sarif or args.graph):
            print(
                "error: delegation findings currently support human or --json "
                "output, not --sarif or --graph",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _delegations_supplied(args) and _conditions_supplied(args):
            print(
                "error: conditional and delegation findings cannot yet be composed safely",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _producers_supplied(args) and args.ir_snapshot is not None:
            print(
                "error: producer boundaries require a manifest and cannot be "
                "composed with --ir",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _producers_supplied(args) and (args.sarif or args.graph):
            print(
                "error: producer findings currently support human or --json "
                "output, not --sarif or --graph",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _producers_supplied(args) and _conditions_supplied(args):
            print(
                "error: producer and conditional findings cannot yet be composed safely",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if _producers_supplied(args) and _delegations_supplied(args):
            print(
                "error: producer and delegation findings cannot yet be composed safely",
                file=sys.stderr,
            )
            return EXIT_USAGE

    ir_result = None
    ir_json = None
    condition_inputs = None
    delegation_inputs = None
    producer_inputs = None
    try:
        if args.command == "diff":
            before = load(args.before)
            after = load(args.after)
        elif args.command == "reach" and args.ir_snapshot is not None:
            snapshot = AuthorityIR.from_json(_read_text(args.ir_snapshot))
            ir_result = _analyse_ir(snapshot, depth=args.depth)
            ir_json = ir_result.to_json() if args.json else None
            mandate = _to_mandate(snapshot)
        else:
            mandate = load(args.manifest)
        if args.command in {"reach", "drift"}:
            condition_inputs = _condition_inputs(args)
        if args.command == "reach":
            delegation_inputs = _delegation_inputs(args)
            producer_inputs = _producer_inputs(args)
    except (
        ConditionFormatError,
        DelegationFormatError,
        IRFormatError,
        ManifestError,
        OSError,
        ProducerBoundaryFormatError,
        UnicodeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "drift":
        try:
            inventory = collect(
                args.source, binding=args.binding, union=args.union_bindings
            )
            dynamic = _dynamic_inventory(args, inventory)
            if condition_inputs is None:
                drift = compare_drift(mandate, inventory, dynamic=dynamic)
                conditional_drift = None
            else:
                conditions, contexts, contents, as_of = condition_inputs
                conditional_drift = reconcile_condition_drift(
                    mandate,
                    inventory,
                    conditions,
                    contexts,
                    contents,
                    as_of=as_of,
                    dynamic=dynamic,
                )
                drift = conditional_drift.drift
        except (
            ConditionFormatError,
            InventoryFormatError,
            OSError,
            UnicodeError,
            ValueError,
        ) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if args.json:
            payload = drift.as_dict()
            if conditional_drift is not None:
                payload["conditions"] = _condition_payload(conditional_drift.analysis)
                payload["source_drift_clean"] = drift.clean
                payload["clean"] = conditional_drift.clean
            print(json.dumps(payload, indent=2))
        else:
            text = drift.render()
            if conditional_drift is not None:
                text = f"{_render_conditions(conditional_drift.analysis)}\n\n{text}"
            print(text)
        clean = drift.clean if conditional_drift is None else conditional_drift.clean
        return EXIT_OK if clean else EXIT_FINDING

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
        if producer_inputs is not None:
            boundaries, contents, selections, as_of = producer_inputs
            producer_analysis = analyse_producers(
                mandate,
                boundaries,
                contents,
                selections,
                as_of=as_of,
                depth=args.depth,
            )
            delegation_analysis = None
            conditional_analysis = None
            authority = producer_analysis.authority
        elif delegation_inputs is not None:
            (
                attachments,
                chains,
                contents,
                as_of,
                target_source,
                target_binding,
            ) = delegation_inputs
            delegation_analysis = analyse_delegations(
                mandate,
                attachments,
                chains,
                contents,
                as_of=as_of,
                depth=args.depth,
                target_source=target_source,
                target_binding=target_binding,
            )
            conditional_analysis = None
            producer_analysis = None
            authority = delegation_analysis.authority
        elif condition_inputs is not None:
            conditions, contexts, contents, as_of = condition_inputs
            conditional_analysis = analyse_conditions(
                mandate,
                conditions,
                contexts,
                contents,
                as_of=as_of,
                depth=args.depth,
            )
            delegation_analysis = None
            producer_analysis = None
            authority = conditional_analysis.authority
        else:
            conditional_analysis = None
            delegation_analysis = None
            producer_analysis = None
            authority = (
                ir_result.authority
                if ir_result is not None
                else analyse(mandate, depth=args.depth)
            )
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
        if args.sarif:
            source_path = args.ir_snapshot or args.manifest
            print(render_sarif(authority, source_path, __version__))
        elif args.graph:
            print(to_mermaid(authority, mandate))
        elif args.json and ir_result is not None:
            assert ir_json is not None
            sys.stdout.write(ir_json)
        elif args.json and producer_analysis is not None:
            sys.stdout.write(producer_analysis.to_result().to_json())
        else:
            payload = authority.as_dict()
            if conditional_analysis is not None:
                payload["conditions"] = _condition_payload(conditional_analysis)
                text = f"{_render_conditions(conditional_analysis)}\n\n{text}"
            if delegation_analysis is not None:
                payload["delegations"] = _delegation_payload(delegation_analysis)
                text = f"{_render_delegations(delegation_analysis)}\n\n{text}"
            if producer_analysis is not None:
                text = f"{_render_producers(producer_analysis)}\n\n{text}"
            _emit(payload, args.json, text)
        finding = bool(authority.breaches) or bool(
            conditional_analysis is not None and conditional_analysis.findings
        ) or bool(
            delegation_analysis is not None and delegation_analysis.findings
        ) or bool(
            producer_analysis is not None and producer_analysis.findings
        )
        return EXIT_FINDING if finding else EXIT_OK

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
