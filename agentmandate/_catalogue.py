"""Local protocol inventory extraction, never reviewed mandate intent.

Reuse scan proposals and the existing dynamic-inventory v1 profile. Protocol
metadata cannot supply effects, deployment membership, or authorization.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from ._inventory import DynamicInventory
from .scan import Proposal, _scope_for, _value_arg_for, propose

_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


@dataclass(frozen=True)
class Catalogue:
    proposals: tuple[Proposal, ...]
    notes: tuple[str, ...]
    format_version: str
    producer: str
    confidence: str
    partial: bool = False


def _object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    return value


def _text(value: Any, location: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{location} must be a non-empty string without control characters")
    return value


def _array(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{location} must be an array")
    return value


def _unique(items: list[str], location: str) -> None:
    if len(set(items)) != len(items):
        raise ValueError(f"{location} contains duplicate names")


def _json(content: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("catalogue JSON contains a duplicate object key")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise ValueError("catalogue JSON contains a non-finite number")

    def number(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("catalogue JSON contains a non-finite number")
        return result

    return json.loads(
        content.decode("utf-8"),
        object_pairs_hook=pairs,
        parse_constant=constant,
        parse_float=number,
    )


def read_catalogue(content: bytes, format: str, *, dispatch_tool: str | None = None) -> Catalogue:
    """Extract one local JSON document. URLs remain inert strings."""
    if format not in {"mcp", "a2a", "openapi"}:
        raise ValueError("choose catalogue format mcp, a2a, or openapi")
    if dispatch_tool is not None and format != "a2a":
        raise ValueError("--dispatch-tool applies only to an A2A Agent Card")
    raw = _json(content)
    digest = hashlib.sha256(content).hexdigest()
    if format == "mcp":
        result = _mcp(raw)
    elif format == "a2a":
        result = _a2a(_object(raw, "A2A Agent Card"), dispatch_tool)
    else:
        result = _openapi(_object(raw, "OpenAPI document"))
    if not result.proposals:
        raise ValueError("catalogue contains no importable tools or operations")
    return Catalogue(
        result.proposals,
        (f"Source format: {result.format_version}; content SHA-256: {digest}.", *result.notes),
        result.format_version,
        result.producer,
        result.confidence,
        result.partial,
    )


def _mcp(raw: Any) -> Catalogue:
    partial = False
    if isinstance(raw, dict):
        if "error" in raw:
            raise ValueError("MCP error response cannot establish tool membership")
        if "result" in raw:
            if raw.get("jsonrpc") != "2.0" or "tools" in raw:
                raise ValueError("expected one unambiguous MCP JSON-RPC 2.0 result")
            raw = _object(raw["result"], "MCP result")
        if "nextCursor" in raw:
            _text(raw["nextCursor"], "MCP nextCursor")
            partial = True
        raw = raw.get("tools")
    tools = _array(raw, "MCP tools")
    for entry in tools:
        entry = _object(entry, "MCP tool")
        _text(entry.get("name"), "MCP tool name")
        if "inputSchema" in entry:
            _object(entry["inputSchema"], "MCP inputSchema")
    proposals = tuple(propose(tools))
    notes = [
        "Tool annotations and argument schemas do not establish effects, approvals, "
        "identity, ceilings, or deployment completeness. Review every tool, including reads.",
    ]
    if partial:
        notes.append("MCP nextCursor is present: this is a partial page. No pages are fetched.")
    return Catalogue(proposals, tuple(notes), "MCP tools/list", "MCP tools/list", "exact", partial)


def _a2a(raw: dict[str, Any], dispatch_tool: str | None) -> Catalogue:
    if "supportedInterfaces" in raw:
        if "protocolVersion" in raw or "url" in raw:
            raise ValueError("A2A card mixes legacy and supportedInterfaces declarations")
        interfaces = _array(raw["supportedInterfaces"], "A2A supportedInterfaces")
        if not interfaces:
            raise ValueError("A2A supportedInterfaces must not be empty")
        for interface in interfaces:
            interface = _object(interface, "A2A interface")
            if interface.get("protocolVersion") != "1.0":
                raise ValueError("only A2A supportedInterfaces protocolVersion 1.0 is supported")
            _text(interface.get("url"), "A2A interface URL")
            _text(interface.get("protocolBinding"), "A2A protocol binding")
        version = "1.0"
    else:
        if raw.get("protocolVersion") != "0.3.0":
            raise ValueError("only legacy A2A Agent Cards with protocolVersion 0.3.0 are supported")
        _text(raw.get("url"), "A2A agent URL")
        version = "0.3.0"
    name = _text(raw.get("name"), "A2A agent name")
    if dispatch_tool is None:
        raise ValueError("A2A skills are not callable tools; supply --dispatch-tool NAME")
    tool = _text(dispatch_tool, "A2A dispatch tool")
    skills = _array(raw.get("skills"), "A2A skills")
    ids: list[str] = []
    for skill in skills:
        skill = _object(skill, "A2A skill")
        ids.append(_text(skill.get("id"), "A2A skill ID"))
        _text(skill.get("name"), "A2A skill name")
    _unique(ids, "A2A skills")
    notes = (
        f"A2A agent {name!r} advertises skill IDs {ids!r}. Skills are not separate callable tools.",
        f"Dispatch tool {tool!r} is supplied by the application, not established by the card. "
        "Review its registration, input mapping, selection, and delegated authority.",
        "Card URLs, security declarations, signatures, and skill descriptions are not "
        "verified. The remote agent's internal tools, effects, and limits remain unknown.",
        "No interface is selected or invoked. Review the wrapper's transport, URL, protocol "
        "version, tenant, and any authenticated extended-card selection separately.",
    )
    return Catalogue(
        (Proposal(tool, "irreversible", True, description=f"Dispatch to A2A agent {name}"),),
        notes,
        f"A2A {version}",
        name,
        "heuristic",
    )


def _path_item(raw: Any, document: dict[str, Any]) -> dict[str, Any]:
    """Resolve document-local Path Items, refusing ambiguous merges and cycles."""
    item = _object(raw, "OpenAPI Path Item")
    seen: set[str] = set()
    while "$ref" in item:
        if len(item) != 1:
            raise ValueError(
                "OpenAPI Path Item $ref siblings require review; merging is unsupported"
            )
        reference = _text(item["$ref"], "OpenAPI Path Item $ref")
        if not reference.startswith("#/"):
            raise ValueError(
                "OpenAPI Path Item requires a document-local $ref; no files or URLs read"
            )
        if reference in seen:
            raise ValueError("OpenAPI Path Item $ref cycle")
        seen.add(reference)
        target: Any = document
        for part in reference[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                raise ValueError("OpenAPI Path Item $ref target is missing")
            target = target[part]
        item = _object(target, "OpenAPI Path Item $ref target")
    return item


def _openapi(raw: dict[str, Any]) -> Catalogue:
    version = raw.get("openapi")
    if not isinstance(version, str) or not re.fullmatch(r"3\.(0|1)\.\d+", version):
        raise ValueError("only OpenAPI 3.0.x and 3.1.x documents are supported")
    info = _object(raw.get("info"), "OpenAPI info")
    producer = _text(info.get("title"), "OpenAPI title")
    paths = _object(raw.get("paths", {}), "OpenAPI paths")
    proposals: list[Proposal] = []
    names: list[str] = []
    notes = [
        "OpenAPI path operations are candidate application tools. Review adapter names and "
        "which operations this agent can actually call; API presence is not permission.",
        "All operation effects default to irreversible, including GET and read-like names. "
        "Security declarations, schema maxima, and responses do not supply mandate limits.",
        "Only inline parameter and application/json body properties supply argument hints. "
        "Schema/parameter/body references, composition, callbacks, webhooks, and links are "
        "not expanded; internal calls and delegated authority remain unknown.",
    ]
    for path, raw_item in sorted(paths.items()):
        if path.startswith("x-"):
            continue
        _text(path, "OpenAPI path")
        if not path.startswith("/"):
            raise ValueError("OpenAPI path must start with /")
        item = _path_item(raw_item, raw)
        for method in _METHODS:
            if method not in item:
                continue
            operation = _object(item[method], "OpenAPI operation")
            name = _text(operation.get("operationId", f"{method.upper()} {path}"), "operation name")
            names.append(name)
            properties = _operation_properties(item, operation)
            proposals.append(
                Proposal(
                    name,
                    "irreversible",
                    True,
                    scope=_scope_for(properties),
                    value_arg=_value_arg_for(properties),
                    description=f"{method.upper()} {path}",
                )
            )
    _unique(names, "OpenAPI operations")
    return Catalogue(tuple(proposals), tuple(notes), f"OpenAPI {version}", producer, "heuristic")


def _operation_properties(item: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    # Qualified parameter keys preserve override rules before extracting hints.
    parameters: dict[tuple[str, str], Any] = {}
    for owner in (item, operation):
        for parameter in _array(owner.get("parameters", []), "OpenAPI parameters"):
            parameter = _object(parameter, "OpenAPI parameter")
            if "$ref" in parameter:
                continue
            name = _text(parameter.get("name"), "OpenAPI parameter name")
            location = _text(parameter.get("in"), "OpenAPI parameter location")
            parameters[(location, name)] = parameter.get("schema", {})
    properties = {name: schema for (_location, name), schema in parameters.items()}
    body = _object(operation.get("requestBody", {}), "OpenAPI requestBody")
    if "$ref" in body:
        return properties
    content = _object(body.get("content", {}), "OpenAPI requestBody content")
    media = _object(content.get("application/json", {}), "OpenAPI JSON media type")
    schema = media.get("schema", {})
    if isinstance(schema, dict) and not {"$ref", "allOf", "anyOf", "oneOf"} & schema.keys():
        properties.update(_object(schema.get("properties", {}), "OpenAPI body properties"))
    return properties


def import_inventory(
    content: bytes,
    format: str,
    *,
    boundary: str,
    target_source: str,
    target_binding: str,
    locator: str,
    selection: Any,
    dispatch_tool: str | None = None,
) -> DynamicInventory:
    """Create a draft in the existing v1 contract, without granting trust."""
    catalogue = read_catalogue(content, format, dispatch_tool=dispatch_tool)
    raw = {
        "inventory_version": 1,
        "boundary": {
            "id": boundary,
            "kind": "provider",
            "target": {"source": target_source, "binding": target_binding},
        },
        "selection": selection,
        "source": {
            "kind": f"{format}-catalogue",
            "locator": locator,
            "format_version": catalogue.format_version,
            "producer": catalogue.producer,
            "producer_version": "unknown",
            "content_sha256": hashlib.sha256(content).hexdigest(),
        },
        "membership": {
            "relation": "contains_tool",
            "completeness": "partial" if catalogue.partial else "unknown",
            "members": [proposal.name for proposal in catalogue.proposals],
        },
        "evidence": {
            "confidence": catalogue.confidence,
            "review": "unreviewed",
            "reviewer": None,
            "expires": None,
        },
    }
    return DynamicInventory.from_json(json.dumps(raw))
