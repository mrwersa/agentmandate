"""Derive a manifest skeleton from a tool catalogue.

Manifests being hand-authored is the largest obstacle to using this package at
all, and this removes most of the typing. It does not remove the thinking, and
the output is deliberately shaped to make that obvious.

A tool schema carries a name, a description, and an argument shape. It does not
carry the three facts the analysis needs: whether the effect is reversible,
which argument spends value, and what a ceiling is measured against. Those are
judgements about the system behind the tool, and no amount of parsing recovers
them. So this emits a skeleton with a guess and a ``REVIEW`` marker against
every guess, and the guesses are conservative: anything not clearly a read is
proposed as irreversible, because the cost of under-calling an effect is much
higher than the cost of over-calling one.

Extract then annotate. Never extract and trust.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Verb prefixes that reliably indicate a read. Everything outside this set is
# proposed as irreversible and left for a human to downgrade.
READ_VERBS = (
    "get",
    "list",
    "search",
    "fetch",
    "read",
    "find",
    "lookup",
    "query",
    "describe",
    "show",
    "check",
    "view",
)

WRITE_VERBS = ("create", "update", "set", "put", "patch", "add", "save", "post")

VALUE_HINTS = ("amount", "value", "total", "price", "sum", "quantity", "limit")


@dataclass(frozen=True)
class Proposal:
    """One tool as extracted, with everything uncertain marked."""

    name: str
    effect: str
    guessed_effect: bool
    scope: str | None = None
    value_arg: str | None = None
    description: str = ""


def _effect_for(name: str) -> tuple[str, bool]:
    lowered = name.lower()
    for verb in READ_VERBS:
        if lowered.startswith(verb) or f"_{verb}" in lowered:
            return "read", False
    for verb in WRITE_VERBS:
        if lowered.startswith(verb) or f"_{verb}" in lowered:
            return "write", True
    return "irreversible", True


def _properties(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    return properties if isinstance(properties, dict) else {}


def _scope_for(properties: dict[str, Any]) -> str | None:
    """An argument ending in `_id` is the resource the call acts on."""
    for argument in properties:
        lowered = argument.lower()
        if lowered.endswith("_id") or lowered.endswith("id") and len(lowered) > 2:
            return lowered.removesuffix("_id").removesuffix("id").strip("_") or None
    return None


def _value_arg_for(properties: dict[str, Any]) -> str | None:
    for argument, spec in properties.items():
        lowered = argument.lower()
        kind = spec.get("type") if isinstance(spec, dict) else None
        if any(hint in lowered for hint in VALUE_HINTS) and kind in {
            "number",
            "integer",
            None,
        }:
            return argument
    return None


def propose(catalogue: Any) -> list[Proposal]:
    """Read an MCP-style ``tools/list`` payload into proposals."""
    tools = catalogue.get("tools") if isinstance(catalogue, dict) else catalogue
    if not isinstance(tools, list):
        raise ValueError(
            "expected an MCP tools/list payload: either a list of tools or an "
            "object with a 'tools' array"
        )

    proposals: list[Proposal] = []
    seen: set[str] = set()
    for entry in tools:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        name = entry["name"]
        if not isinstance(name, str) or not name.strip():
            continue
        if any(character in name for character in "\r\n\x00"):
            raise ValueError(f"tool name {name!r} contains a control character")
        if name in seen:
            raise ValueError(f"tool catalogue contains duplicate name {name!r}")
        seen.add(name)
        effect, guessed = _effect_for(name)
        properties = _properties(entry.get("inputSchema") or entry.get("input_schema"))
        proposals.append(
            Proposal(
                name=name,
                effect=effect,
                guessed_effect=guessed,
                scope=_scope_for(properties),
                value_arg=_value_arg_for(properties),
                description=str(entry.get("description", "")).strip(),
            )
        )
    return proposals


def _yaml_scalar(value: str) -> str:
    """Render an inert quoted scalar accepted by JSON and YAML parsers."""
    return json.dumps(value, ensure_ascii=True)


def _comment(value: str, limit: int = 96) -> str:
    """Collapse untrusted catalogue prose to one comment line."""
    return " ".join(value.split())[:limit]


def _wrap(text: str, prefix: str, width: int = 76) -> list[str]:
    """Wrap a note into comment lines, so a long one stays readable.

    Continuation lines are indented rather than repeating the marker, because
    a repeated ``REVIEW:`` reads as several findings instead of one.
    """
    continuation = "#" + " " * (len(prefix) - 1)
    lines: list[str] = []
    current = prefix
    head = prefix
    for word in text.split():
        if current != head and len(current) + 1 + len(word) > width:
            lines.append(current)
            head = continuation
            current = continuation
        current = f"{current} {word}" if current != head else f"{head} {word}"
    lines.append(current)
    return lines


def render(
    proposals: list[Proposal],
    agent: str,
    notes: list[str] | None = None,
    origin: str = "tool catalogue",
) -> str:
    """Emit a YAML manifest skeleton with a review marker on every guess.

    Written by hand rather than through a YAML dumper because the comments are
    the point. A dumper would strip exactly the part a reader needs.

    ``notes`` carries what the source of the inventory could not establish.
    They lead the file because a reader has to know the list is incomplete
    before they start trusting the list.
    """
    if not proposals:
        raise ValueError("tool catalogue contains no named tools")
    if not isinstance(agent, str) or not agent.strip():
        raise ValueError("agent name must be a non-empty string")
    if any(character in agent for character in "\r\n\x00"):
        raise ValueError("agent name must not contain control characters")

    lines = [
        "# Generated by `mandate scan`. This is a starting point, not a manifest.",
        "#",
        f"# Every REVIEW line is a judgement the {origin} could not supply.",
        "# Effects were guessed from the tool name and default to irreversible,",
        "# because under-calling an effect is the more expensive mistake.",
        "#",
        "# Delete each REVIEW comment once you have confirmed the line under it.",
        "",
    ]

    for note in notes or []:
        lines.extend(_wrap(_comment(note, limit=400), "# REVIEW:"))
        lines.append("#")

    lines += [
        "version: 1",
        f"agent: {_yaml_scalar(agent)}",
        "",
        "# REVIEW: set the workload identity this agent runs as.",
        "# identity: spiffe://example/agents/" + _comment(agent),
        "",
        "limits:",
        "  # REVIEW: the most one run may spend. Without this, `reach` has no",
        "  # cumulative limit to search for a way to exceed.",
        "  # total: { amount: 0, currency: GBP }",
        "  depth: 8",
        "",
        "tools:",
    ]

    scopes = sorted({p.scope for p in proposals if p.scope})
    for proposal in proposals:
        if proposal.description:
            lines.append(f"  # {_comment(proposal.description)}")
        lines.append(f"  - name: {_yaml_scalar(proposal.name)}")
        if proposal.guessed_effect:
            lines.append(
                "    # REVIEW: effect guessed from the name. "
                "read | write | irreversible"
            )
        lines.append(f"    effect: {proposal.effect}")
        lines.append(
            "    # REVIEW: does this spend the caller's authority or a service account?"
        )
        lines.append("    principal: caller")
        if proposal.scope:
            lines.append(f"    requires: [{_yaml_scalar(proposal.scope)}]")
        if proposal.value_arg:
            lines.append(
                f"    # REVIEW: {_comment(proposal.value_arg)} looks like a value argument. "
                "A ceiling needs scope_key too."
            )
            lines.append(f"    # value_arg: {_yaml_scalar(proposal.value_arg)}")
            lines.append(f"    # scope_key: {_yaml_scalar(proposal.scope or 'REVIEW')}")
            lines.append("    # ceiling: { amount: 0, currency: GBP }")
        if proposal.effect == "irreversible":
            lines.append("    requires_approval: true")
        lines.append("")

    if scopes:
        lines.extend(
            [
                "# REVIEW: no tool was detected as producing a scope, so every",
                "# `requires` above is currently unreachable. Mark whichever tool",
                "# mints each scope with `produces:`, and set `unbounded: true`",
                "# where the agent can obtain them at will. That flag is what",
                "# decides whether a per-scope ceiling means anything.",
                "# Scopes referenced: " + ", ".join(_comment(scope) for scope in scopes),
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def scan_file(path: str | Path, agent: str) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return render(propose(payload), agent)


def scan_source(
    root: str | Path,
    agent: str,
    *,
    binding: str | None = None,
    union: bool = False,
) -> str:
    """Derive a skeleton from agent source rather than from a catalogue."""
    from .inventory import collect, notes_for

    inventory = collect(root, binding=binding, union=union)
    if not inventory.proposals:
        raise ValueError(
            "no tool declarations were found. This reads decorators such as "
            "@tool, @function_tool, and @ai_function. A tool registered at "
            "runtime is invisible to it."
        )
    return render(inventory.proposals, agent, notes_for(inventory), origin="source")
