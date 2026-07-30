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
    """Walk an OTLP JSON document and yield every span, in document order."""
    if not isinstance(payload, dict):
        raise TraceError("trace root must be an OTLP JSON object")
    spans: list[dict] = []
    resource_spans = payload.get("resourceSpans")
    if not isinstance(resource_spans, list):
        raise TraceError(
            "no 'resourceSpans' in the document. This reader expects OTLP JSON, "
            "the format the OTLP/HTTP exporter and otel-cli produce."
        )
    for resource in resource_spans:
        for scope in (resource or {}).get("scopeSpans", []) or []:
            for span in (scope or {}).get("spans", []) or []:
                if isinstance(span, dict):
                    spans.append(span)
    return spans


@dataclass(frozen=True)
class Conversion:
    """The observations recovered, and what was left behind.

    The counts matter as much as the observations. A trace that produced two
    observations from four hundred spans is usually a mapping mistake, and
    reporting only the two would let it pass as success.
    """

    observations: tuple[Observation, ...]
    total_spans: int
    tool_spans: int
    unmapped: tuple[str, ...]

    @property
    def summary(self) -> str:
        lines = [
            f"read {self.total_spans} span(s), {self.tool_spans} tool call(s), "
            f"{len(self.observations)} observation(s)"
        ]
        if self.unmapped:
            lines.append(
                "  no attribute mapped for: " + ", ".join(self.unmapped)
                + ". verify will fail closed on any control that needs them."
            )
        return "\n".join(lines)


def convert(payload: Any, mapping: dict[str, str] | None = None) -> Conversion:
    """Convert an OTLP document into observations.

    Args:
        payload: A parsed OTLP JSON document.
        mapping: Attribute names for the fields the conventions do not carry,
            for example ``{"scope": "app.case.id", "value": "app.refund.amount"}``.

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

    spans = iter_spans(payload)
    tool_spans = []
    for index, span in enumerate(spans):
        attrs = attributes(span)
        name = attrs.get(TOOL_NAME_ATTR)
        # Accept either the operation marker or a bare tool name, because
        # exporters vary in whether they set the operation on tool spans.
        is_tool = attrs.get(OP_ATTR) == TOOL_OP or bool(name)
        if not is_tool:
            continue
        if not isinstance(name, str) or not name.strip():
            raise TraceError(
                f"a span marked {TOOL_OP} has no {TOOL_NAME_ATTR}. "
                "The tool cannot be identified, so the call cannot be checked."
            )
        start = span.get("startTimeUnixNano")
        try:
            order = int(start)
        except (TypeError, ValueError):
            order = 0
        tool_spans.append((order, index, name, attrs))

    tool_spans.sort(key=lambda row: (row[0], row[1]))

    observations = []
    for line, (_, _, name, attrs) in enumerate(tool_spans, start=1):
        record: dict[str, Any] = {"tool": name}
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
        observations.append(Observation.parse(record, line))

    unmapped = tuple(f for f in MAPPABLE if f not in mapping)
    return Conversion(
        observations=tuple(observations),
        total_spans=len(spans),
        tool_spans=len(tool_spans),
        unmapped=unmapped,
    )


def load_trace(path: str | Path, mapping: dict[str, str] | None = None) -> Conversion:
    """Read an OTLP JSON file from disk."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TraceError(f"cannot load trace: {exc}") from exc
    return convert(payload, mapping)


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
