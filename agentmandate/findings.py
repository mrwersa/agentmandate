"""Render findings where developers already look.

A counterexample in a log nobody opens is a counterexample nobody acts on.
GitHub reads SARIF and annotates the pull request that introduced a finding;
it reads Mermaid and draws a graph inline in a comment. Both are output
formats over analysis that already happened, and neither changes a verdict.

Two deliberate choices about the SARIF.

Every result is anchored to the **manifest**, at the line declaring the tool
the path ends on. A compound breach has no single guilty line, so pointing at
the last tool is a convention rather than a truth, and the message says so.
Anchoring to nothing at all would put the finding in a place the code-scanning
UI cannot show.

And the level is `error`, not `warning`. These findings already exit non-zero;
downgrading them in the UI would say something different from what the exit
code says, and the two disagreeing is how a gate stops being believed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .manifest import READ, Mandate
from .reach import Authority, Breach

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/"
    "schema/sarif-schema-2.1.0.json"
)

RULES = {
    "cumulative_value": (
        "Compound value extraction",
        "A sequence of individually permitted calls extracts more value than "
        "the run limit allows. Each call is within its own ceiling; the total "
        "is not.",
    ),
    "ungated_irreversible": (
        "Reachable irreversible effect with no approval",
        "An irreversible effect is reachable and no approval gate stands in "
        "front of it.",
    ),
}


# A tool declaration in any spelling this package reads: block YAML, flow
# YAML (`- { name: pay, ... }`), and JSON. Only the line number is wanted, so
# parsing the document properly to lose the line numbers and then hunt for
# them again would be worse.
#
# Flow style was missed at first and every result on such a manifest anchored
# at line 1, which is not a missing answer but a wrong one: line 1 is usually
# `version:`, so the annotation landed somewhere unrelated.
# Anchored at the start of a line or just after a `{` or `,`, so the key does
# not have to come first inside a flow mapping. `- { effect: read, name: pay }`
# is as valid as the other order and used to fall back to line 1.
NAME_LINE = re.compile(
    r"""(?:^|[{,])\s*-?\s*\{?\s*(?:"name"|'name'|name)\s*:\s*"""
    r"""(?P<name>"[^"]*"|'[^']*'|[^,}\n]+)"""
)


def _tool_lines(manifest: str | Path) -> dict[str, int]:
    """Find the line each tool is declared on, for anchoring a result."""
    lines: dict[str, int] = {}
    try:
        text = Path(manifest).read_text(encoding="utf-8")
    except OSError:
        return lines
    for number, line in enumerate(text.splitlines(), start=1):
        match = NAME_LINE.search(line)
        if match is None:
            continue
        name = match.group("name").strip().rstrip(",}").strip().strip("\"'")
        if name and name not in lines:
            lines[name] = number
    return lines


# Mermaid node labels are delimited by quotes inside brackets, so a name
# carrying either escapes the label and injects arbitrary graph syntax. Tool
# names reach here from `scan`, which exists to ingest untrusted MCP
# catalogues, so this is the same exposure `scan` already quotes against when
# it writes YAML. Mermaid reads HTML entities, which is what makes escaping
# possible without mangling the name.
MERMAID_ESCAPES = (
    ("&", "#amp;"),
    ('"', "#quot;"),
    ("<", "#lt;"),
    (">", "#gt;"),
    ("[", "#91;"),
    ("]", "#93;"),
    ("(", "#40;"),
    (")", "#41;"),
    ("{", "#123;"),
    ("}", "#125;"),
)


def _label(text: object) -> str:
    """Render any name as an inert Mermaid label."""
    cleaned = " ".join(str(text).split())
    for bad, good in MERMAID_ESCAPES:
        cleaned = cleaned.replace(bad, good)
    return cleaned


def _path_text(breach: Breach) -> str:
    return " -> ".join(step.render() for step in breach.path)


def to_sarif(
    authority: Authority,
    manifest: str | Path,
    *,
    tool_version: str = "",
) -> dict:
    """Render reachable breaches as a SARIF 2.1.0 log."""
    manifest_path = Path(manifest)
    lines = _tool_lines(manifest_path)
    # Code scanning resolves the uri against the repository root, so an
    # absolute path attaches the finding to nothing. Relative to the working
    # directory is what CI actually has.
    try:
        uri = manifest_path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        uri = manifest_path.as_posix()

    kinds = {breach.kind for breach in authority.breaches}
    rules = []
    for kind in sorted(kinds):
        name, description = RULES.get(
            kind, (kind.replace("_", " ").capitalize(), "A reachable breach.")
        )
        rules.append(
            {
                "id": kind,
                "name": name,
                "shortDescription": {"text": name},
                "fullDescription": {"text": description},
                "help": {
                    "text": description,
                    "markdown": (
                        f"**{name}**\n\n{description}\n\n"
                        "Reported by [AgentMandate]"
                        "(https://github.com/mrwersa/agentmandate). The finding "
                        "is about what the reviewed manifest *permits* under a "
                        "bounded search, not about what the model tends to do."
                    ),
                },
                "defaultConfiguration": {"level": "error"},
            }
        )

    results = []
    for breach in authority.breaches:
        anchor = breach.path[-1].tool if breach.path else ""
        line = lines.get(anchor, 1)
        results.append(
            {
                "ruleId": breach.kind,
                "level": "error",
                "message": {
                    "text": (
                        f"{breach.detail}. Reachable path: {_path_text(breach)}. "
                        f"No single call here is wrong; the finding exists only "
                        f"in the sequence, so this is anchored at the last tool "
                        f"on the path rather than at a guilty line."
                    )
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri},
                            "region": {"startLine": line},
                        }
                    }
                ],
                "partialFingerprints": {
                    # Stable across reruns and across line moves, so GitHub
                    # does not report the same breach as new after a reformat.
                    "authorityPath/v1": f"{breach.kind}:{_path_text(breach)}"
                },
            }
        )

    driver: dict = {
        "name": "AgentMandate",
        "informationUri": "https://github.com/mrwersa/agentmandate",
        "rules": rules,
    }
    if tool_version:
        driver["version"] = tool_version

    return {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [{"tool": {"driver": driver}, "results": results}],
    }


def to_mermaid(authority: Authority, mandate: Mandate) -> str:
    """Draw the breaching path as a chain, with each step's binding.

    An earlier version drew one node per tool and edges between them, which
    produced self-loops: the whole point of a compound breach is often that
    the same tool is called twice on different bindings, and a node per tool
    cannot show that. One node per step can, and the binding is the part a
    reviewer needs to see.
    """
    lines = ["flowchart LR"]

    if not authority.breaches:
        lines.append(f'  ok["no reachable breach within depth {authority.depth}"]')
        for index, tool in enumerate(sorted(authority.reachable_tools)):
            lines.append(f'  t{index}(["{_label(tool)}"])')
        lines.append("  classDef ok fill:#e9f6ef,stroke:#267148,color:#1b5235;")
        lines.append("  class ok ok;")
        return "\n".join(lines)

    breach = authority.breaches[0]

    previous: str | None = None
    for index, step in enumerate(breach.path):
        node = f"s{index}"
        detail = []
        if step.binding:
            detail.append(step.binding)
        if step.spent is not None:
            detail.append(f"{step.spent} {step.currency}")
        label = _label(step.tool)
        if detail:
            # The break is ours, added after escaping, so a name carrying
            # markup cannot contribute any.
            label += "<br/>" + _label(" · ".join(detail))
        # A rounded node reads as a read, a box as something that changes
        # state. The shape carries the effect class without a legend.
        # `Authority.effects` is (effect class, scope) pairs, not a per-tool
        # map, so the shape has to come from the manifest.
        declared = mandate.tool(step.tool)
        shape = (
            f'{node}(["{label}"])'
            if declared is not None and declared.effect == READ
            else f'{node}["{label}"]'
        )
        lines.append(f"  {shape}")
        if previous is not None:
            lines.append(f"  {previous} --> {node}")
        previous = node

    lines.append(f'  breach["{_label(breach.detail)}"]')
    if previous is not None:
        lines.append(f"  {previous} --> breach")
    lines.append("  classDef breach fill:#fdecea,stroke:#a33b33,color:#7a2b24;")
    lines.append("  class breach breach;")

    ungated = sorted(authority.ungated_irreversible)
    if ungated:
        lines.append(
            f'  note["ungated irreversible: {_label(", ".join(ungated))}"]'
        )

    extra = sorted(
        authority.reachable_tools - {step.tool for step in breach.path}
    )
    if extra:
        lines.append(f'  rest["also reachable: {_label(", ".join(extra))}"]')

    if len(authority.breaches) > 1:
        lines.append(
            f'  more["+{len(authority.breaches) - 1} further reachable breach(es)"]'
        )

    return "\n".join(lines)


def render_sarif(authority: Authority, manifest: str | Path, version: str = "") -> str:
    return json.dumps(to_sarif(authority, manifest, tool_version=version), indent=2)
