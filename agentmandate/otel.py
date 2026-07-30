"""Read OpenTelemetry traces into the replay format `verify` expects.

`verify` is the command that keeps a manifest honest, and until now it needed a
bespoke JSON Lines file nobody had. Teams have traces. This converts them.

The mapping is deliberately partial, and the gap is the point.

OpenTelemetry's GenAI semantic conventions describe what a tool call *was*:
``gen_ai.operation.name`` is ``execute_tool`` and ``gen_ai.tool.name`` carries
the name. They do not describe what a mandate needs in order to check a
control: which resource the call acted on, how much value it spent, whose
authority it spent, and whether anyone approved it. Those are application
facts, and an exporter either recorded them or did not.

So this module maps the standard fields automatically and requires an explicit
``--map`` for the rest. It never guesses. A trace missing the approval
attribute produces an observation with no approval, and `verify` then fails
closed on it, which is the correct outcome: the evidence genuinely does not
establish that the control held.

Input is OTLP JSON, the format produced by the OTLP/HTTP exporter and by
`otel-cli`, and accepted by every collector.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .verify import Observation

# The conventions carry Development stability badges, so these names can move
# without a major version bump. Pinning them in one place makes that a
# one-line change rather than a search.
OP_ATTR = "gen_ai.operation.name"
TOOL_OP = "execute_tool"
TOOL_NAME_ATTR = "gen_ai.tool.name"
TOOL_CALL_ID_ATTR = "gen_ai.tool.call.id"

# OTLP encodes span status as either the enum name or its ordinal.
ERROR_STATUS = {"STATUS_CODE_ERROR", 2, "2"}

# Fields a mandate needs that no GenAI convention supplies. Each must be
# pointed at an attribute by the caller, or it stays absent.
MAPPABLE = ("scope", "value", "currency", "principal", "approved")


class TraceError(ValueError):
    """Raised when a trace cannot be read as a sequence of tool calls."""


def _unwrap(value: Any) -> Any:
    """Flatten one OTLP AnyValue into a plain Python value."""
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if key in value:
            # OTLP encodes 64-bit ints as strings. Returned as-is so a value
            # like "500" reaches Decimal intact rather than via float.
            return value[key]
    if "arrayValue" in value:
        return [_unwrap(v) for v in value["arrayValue"].get("values", [])]
    return None


def attributes(span: dict) -> dict[str, Any]:
    """Return a span's attributes as a flat mapping."""
    flat: dict[str, Any] = {}
    for entry in span.get("attributes", []) or []:
        if isinstance(entry, dict) and "key" in entry:
            flat[entry["key"]] = _unwrap(entry.get("value"))
    return flat


def iter_spans(payload: Any) -> list[dict]:
    """Walk one OTLP request object and return every span in document order."""
    if not isinstance(payload, dict):
        raise TraceError("trace root must be an OTLP JSON object")
    spans: list[dict] = []
    resource_spans = payload.get("resourceSpans")
    if not isinstance(resource_spans, list):
        raise TraceError(
            "no 'resourceSpans' in the document. This reader expects an OTLP "
            "ExportTraceServiceRequest in JSON, either as one object or as "
            "newline-delimited objects."
        )
    for resource in resource_spans:
        for scope in (resource or {}).get("scopeSpans", []) or []:
            for span in (scope or {}).get("spans", []) or []:
                if isinstance(span, dict):
                    spans.append(span)
    return spans


def read_document(text: str) -> list[dict]:
    """Parse one OTLP request, or newline-delimited requests.

    OpenTelemetry's file exporter writes one request per line, so a reader
    that only accepts a single object rejects its output.
    """
    stripped = text.strip()
    if not stripped:
        raise TraceError("the trace file is empty")
    try:
        return [json.loads(stripped)]
    except json.JSONDecodeError:
        pass
    requests = []
    for number, line in enumerate(stripped.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            requests.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise TraceError(
                f"line {number} is not valid JSON: {exc}. Expected an OTLP "
                "ExportTraceServiceRequest, or one per line."
            ) from exc
    return requests


@dataclass(frozen=True)
class Conversion:
    """The observations recovered, and what was left behind.

    The counts matter as much as the observations. A trace that produced two
    observations from four hundred spans is usually a mapping mistake, and
    reporting only the two would let it pass as success.
    """

    runs: tuple[tuple[str, tuple[Observation, ...]], ...]
    total_spans: int
    tool_spans: int
    unmapped: tuple[str, ...]
    errored: int = 0
    duplicates: int = 0

    @property
    def observations(self) -> tuple[Observation, ...]:
        """Every observation across every run, for callers that want one list.

        Replaying this flattened list would accumulate one run's spending
        against another's, so `runs` is what `verify` uses.
        """
        return tuple(o for _, group in self.runs for o in group)

    @property
    def summary(self) -> str:
        lines = [
            f"read {self.total_spans} span(s), {self.tool_spans} tool call(s), "
            f"{len(self.observations)} observation(s) across "
            f"{len(self.runs)} trace(s)"
        ]
        if len(self.runs) > 1:
            lines.append(
                "  each trace is verified separately, because a cumulative "
                "limit bounds one run rather than a whole export."
            )
        if self.errored:
            lines.append(
                f"  {self.errored} tool call(s) ended in an error and are "
                "carried as incomplete evidence. An error means the operation "
                "failed, not that the effect was not applied."
            )
        if self.duplicates:
            lines.append(
                f"  {self.duplicates} duplicate span(s) collapsed by "
                f"{TOOL_CALL_ID_ATTR}. One call instrumented at both client "
                "and server is one call."
            )
        if self.unmapped:
            lines.append(
                "  no attribute mapped for: " + ", ".join(self.unmapped)
                + ". verify will fail closed on any control that needs them."
            )
        return "\n".join(lines)


def convert(
    payload: Any,
    mapping: dict[str, str] | None = None,
    *,
    lenient: bool = False,
) -> Conversion:
    """Convert an OTLP document into observations.

    Args:
        payload: A parsed OTLP JSON document.
        mapping: Attribute names for the fields the conventions do not carry,
            for example ``{"scope": "app.case.id", "value": "app.refund.amount"}``.
        lenient: Also treat a span carrying ``gen_ai.tool.name`` but no
            operation attribute as a tool execution. The convention requires
            both on a tool span, so this is off by default and exists for
            older instrumentation.

    Spans are ordered by start time so cumulative ceilings accumulate in the
    order the calls actually happened. Ties keep document order.
    """
    mapping = dict(mapping or {})
    unknown = sorted(set(mapping) - set(MAPPABLE))
    if unknown:
        raise TraceError(
            "cannot map " + ", ".join(unknown)
            + ". mappable fields are: " + ", ".join(MAPPABLE)
        )

    documents = payload if isinstance(payload, list) else [payload]
    if not documents:
        raise TraceError("the trace contains no OTLP requests")
    spans = [s for document in documents for s in iter_spans(document)]
    tool_spans = []
    errored = 0
    duplicates = 0
    # Scoped per trace, because the same call id in two runs is two calls.
    seen_call_ids: set[tuple[str, str]] = set()
    for index, span in enumerate(spans):
        attrs = attributes(span)
        name = attrs.get(TOOL_NAME_ATTR)
        operation = attrs.get(OP_ATTR)
        if operation is not None:
            # An explicit operation is authoritative. Instrumentations often
            # attach the tool name to the chat span that REQUESTED the call,
            # and treating that as an execution double-counts its value and
            # reports a ceiling breach that never happened.
            if operation != TOOL_OP:
                continue
        elif not (lenient and name):
            # The convention requires both attributes on a tool-execution
            # span. Inferring one from a bare name is a guess, and this module
            # does not guess unless asked.
            continue
        if not isinstance(name, str) or not name.strip():
            raise TraceError(
                f"a span marked {TOOL_OP} has no {TOOL_NAME_ATTR}. "
                "The tool cannot be identified, so the call cannot be checked."
            )
        trace_id = span.get("traceId") or ""
        if not isinstance(trace_id, str):
            trace_id = ""

        status = span.get("status") or {}
        span_errored = isinstance(status, dict) and status.get("code") in ERROR_STATUS
        if span_errored:
            errored += 1

        call_id = attrs.get(TOOL_CALL_ID_ATTR)
        if isinstance(call_id, str) and call_id:
            key = (trace_id, call_id)
            if key in seen_call_ids:
                duplicates += 1
                continue
            seen_call_ids.add(key)

        start = span.get("startTimeUnixNano")
        try:
            order = int(start)
        except (TypeError, ValueError):
            order = 0
        tool_spans.append((trace_id, order, index, name, attrs, span_errored))

    # Ordered within a trace. Cumulative ceilings accumulate in call order,
    # and calls from different runs never share a budget.
    tool_spans.sort(key=lambda row: (row[0], row[1], row[2]))

    grouped: dict[str, list[Observation]] = {}
    for trace_id, _, _, name, attrs, span_errored in tool_spans:
        group = grouped.setdefault(trace_id, [])
        record: dict[str, Any] = {"tool": name}
        if span_errored:
            record["errored"] = True
        for field in MAPPABLE:
            key = mapping.get(field)
            if key is None:
                continue
            if key not in attrs:
                continue
            value = attrs[key]
            if value is None:
                continue
            if field == "approved":
                # A string "true" from an exporter is still a boolean claim.
                if isinstance(value, str):
                    value = value.strip().lower() in {"true", "1", "yes"}
                record[field] = bool(value)
            else:
                record[field] = value
        group.append(Observation.parse(record, len(group) + 1))

    unmapped = tuple(f for f in MAPPABLE if f not in mapping)
    return Conversion(
        runs=tuple((trace, tuple(group)) for trace, group in grouped.items()),
        total_spans=len(spans),
        tool_spans=len(tool_spans),
        unmapped=unmapped,
        errored=errored,
        duplicates=duplicates,
    )


def load_trace(
    path: str | Path,
    mapping: dict[str, str] | None = None,
    *,
    lenient: bool = False,
) -> Conversion:
    """Read an OTLP JSON file from disk."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise TraceError(f"cannot load trace: {exc}") from exc
    return convert(read_document(text), mapping, lenient=lenient)


def parse_mapping(pairs: list[str] | None) -> dict[str, str]:
    """Parse ``field=attribute`` arguments from the command line."""
    mapping: dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise TraceError(
                f"malformed mapping {pair!r}. Expected field=attribute, "
                "for example scope=app.case.id"
            )
        field, attribute = pair.split("=", 1)
        field, attribute = field.strip(), attribute.strip()
        if not field or not attribute:
            raise TraceError(f"malformed mapping {pair!r}")
        mapping[field] = attribute
    return mapping
