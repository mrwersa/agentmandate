"""Compare the declared mandate against the implementation.

A manifest is a claim about what an agent may do. The implementation is what
it can actually do, and the two separate quietly: somebody adds a tool to the
agent's list and nobody edits the YAML, or a signature changes and the
argument a ceiling was counted against stops existing.

Neither of those looks like a permission change in review, which is the same
reason ``diff`` exists. The difference is what is being compared. ``diff``
compares two manifests and asks whether the *declaration* widened. This
compares a manifest against source and asks whether the declaration is still
describing the thing it claims to describe.

The direction of the error matters. A tool the agent has and the manifest
omits means ``reach`` has been searching a smaller graph than the real one,
so every clean report it produced was about a system that does not exist. A
tool the manifest declares and the agent no longer has is less dangerous and
still worth failing on, because a gate that reports breaches nobody can reach
is a gate somebody switches off.

An inventory the reader could not fully enumerate is a finding in its own
right. Reporting no drift from evidence that could not see the whole tool
list would be the exact false assurance this package exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .inventory import Inventory, collect
from .manifest import Mandate

if TYPE_CHECKING:
    from ._inventory import InventoryReconciliation

# Ordered by how much a reader should care. Authority the mandate does not
# describe comes first, because it silently invalidates every other answer.
DRIFT_KINDS = ("undeclared", "argument", "removed", "unresolved")

# The subject of the note explaining that removals were not checked. Not a
# tool name, and deliberately not one a manifest could declare.
WITHHELD = "<removals>"


@dataclass(frozen=True)
class DriftFinding:
    kind: str
    tool: str
    message: str

    def render(self) -> str:
        head = f"{self.kind.upper():11} {self.tool}"
        body = "\n".join(f"      {line}" for line in self.message.split("\n"))
        return f"  {head}\n{body}"


@dataclass(frozen=True)
class Drift:
    agent: str
    declared: tuple[str, ...]
    discovered: tuple[str, ...]
    findings: tuple[DriftFinding, ...]
    # Which tool list the source side came from. `diff` refuses to compare two
    # different agents outright, and this cannot: nothing in source states the
    # agent's declared name, so identity cannot be established. Naming the
    # binding is what a reader needs to see that the comparison was against
    # the agent they meant.
    source: str = ""

    @property
    def clean(self) -> bool:
        return not self.findings

    def render(self) -> str:
        lines = [
            f"drift  {self.agent}",
            f"  {len(self.declared)} tool(s) declared, "
            f"{len(self.discovered)} given to the agent in source",
        ]
        if self.source:
            lines.append(f"  source inventory taken from {self.source}")
        else:
            lines.append(
                "  no agent binding was found in source, so this compares "
                "against every declared tool"
            )
        lines.append("")
        if self.clean:
            lines.append("  the mandate still describes the implementation")
            return "\n".join(lines)
        lines.extend(finding.render() for finding in self.findings)
        lines.append("")
        lines.append(f"{len(self.findings)} drift finding(s)")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "declared": list(self.declared),
            "discovered": list(self.discovered),
            "clean": self.clean,
            "source": self.source,
            "findings": [
                {
                    # The withheld-removals note is about the report rather
                    # than about a tool, so a machine consumer reading `tool`
                    # gets null rather than a name no manifest declares.
                    "kind": f.kind,
                    "tool": None if f.tool == WITHHELD else f.tool,
                    "subject": f.tool,
                    "message": f.message,
                }
                for f in self.findings
            ],
        }


def compare(
    mandate: Mandate,
    inventory: Inventory,
    *,
    dynamic: InventoryReconciliation | None = None,
) -> Drift:
    """Report every way the manifest has stopped describing the source."""
    findings: list[DriftFinding] = []

    declared = {tool.name: tool for tool in mandate.tools}
    discovered = {d.name: d for d in inventory.declarations}
    discovered_names = set(discovered)
    if dynamic is not None:
        discovered_names.update(dynamic.members)

    for name in sorted(discovered_names - set(declared)):
        findings.append(
            DriftFinding(
                "undeclared",
                name,
                "the agent is given this tool and the mandate does not declare "
                "it, so every reach and diff run so far analysed a smaller "
                "graph than the real one",
            )
        )

    # A declared tool whose ceiling or scope no longer names a real argument.
    # The manifest still parses, the analysis still runs, and the ceiling
    # counts against nothing.
    for name in sorted(set(declared) & set(discovered)):
        tool = declared[name]
        arguments = discovered[name].arguments
        if not arguments:
            continue
        for field, value in (("value_arg", tool.value_arg), ("scope_key", tool.scope_key)):
            if value is None or value in arguments:
                continue
            # scope_key names the scope a ceiling is counted against, which is
            # a manifest concept rather than necessarily a parameter name. It
            # is only drift when no argument plausibly carries it.
            if field == "scope_key" and any(value in arg for arg in arguments):
                continue
            findings.append(
                DriftFinding(
                    "argument",
                    name,
                    f"{field} names {value!r}, which is not an argument this "
                    f"tool takes any more (it takes: {', '.join(arguments)}). "
                    f"A ceiling counted against an argument that does not "
                    f"exist is not a ceiling.",
                )
            )

    # A removal is a claim that a tool is absent from the agent's list. That
    # claim cannot be made from a list the read could not enumerate: the tool
    # may well be in the part it could not see. Reporting both `unresolved`
    # and `removed` was asserting something positive from evidence already
    # flagged as unreadable, which is the same fail-closed rule this module
    # applies everywhere else, pointed the other way.
    #
    # A tool bound from outside the scanned path is just as unreadable as an
    # unenumerable list: it is absent from the declarations only because the
    # scan never saw it, so declaring it in the manifest must not read as a
    # removal.
    unresolved = (
        []
        if dynamic is not None and dynamic.covers_binding
        else inventory.unresolved
    )
    dynamic_findings = dynamic.findings if dynamic is not None else ()
    unreadable = (
        bool(unresolved)
        or bool(inventory.undeclared)
        or bool(dynamic_findings)
        or (dynamic is not None and not dynamic.complete)
    )
    withheld = sorted(set(declared) - discovered_names) if unreadable else []
    for name in sorted(set(declared) - discovered_names) if not unreadable else ():
        findings.append(
            DriftFinding(
                "removed",
                name,
                "the mandate declares this tool and the agent is not given it "
                "in source, so the analysis is defending authority nobody has. "
                "A gate that reports breaches nobody can reach gets switched "
                "off.",
            )
        )

    # Fail closed when the read could not see the whole list.
    for item in unresolved:
        findings.append(
            DriftFinding(
                "unresolved",
                item.split(":")[0],
                f"a binding passes tools this read cannot enumerate ({item}), "
                f"so this comparison cannot establish that nothing is missing. "
                f"Name them in the manifest, or make the list literal.",
            )
        )
    for item in inventory.undeclared:
        findings.append(
            DriftFinding(
                "unresolved",
                item,
                "this is bound to the agent but declared outside the scanned "
                "path, so whether the mandate covers it was never established. "
                "Widen --source.",
            )
        )

    for item in dynamic_findings:
        findings.append(
            DriftFinding(
                "unresolved",
                item.boundary,
                f"dynamic inventory could not establish completeness: {item.message}",
            )
        )

    # Suppressing the removal check is right, and doing it silently is not: a
    # reader who resolves the unreadable part would otherwise meet findings
    # that look new and were only withheld.
    if withheld:
        listed = ", ".join(withheld)
        findings.append(
            DriftFinding(
                "unresolved",
                WITHHELD,
                f"{len(withheld)} declared tool(s) were not checked for "
                f"removal, because a tool absent from a list this could not "
                f"read may simply be in the part it could not see: {listed}. "
                f"Resolve the findings above and run again.",
            )
        )

    order = {kind: index for index, kind in enumerate(DRIFT_KINDS)}
    # The withheld-removals note refers to the findings that caused it, so it
    # sorts last rather than alphabetically among them.
    findings.sort(key=lambda f: (order[f.kind], f.tool == WITHHELD, f.tool))

    selected = inventory.selected
    if selected is not None:
        source = f"{selected.where} ({selected.label})"
    elif inventory.united:
        source = "the union of every agent's tool list"
    else:
        source = ""
    return Drift(
        agent=mandate.agent,
        declared=tuple(sorted(declared)),
        discovered=tuple(sorted(discovered_names)),
        findings=tuple(findings),
        source=source,
    )


def compare_source(
    mandate: Mandate,
    root: str | Path,
    *,
    binding: str | None = None,
    union: bool = False,
) -> Drift:
    """Read the implementation and compare it with the mandate."""
    return compare(mandate, collect(root, binding=binding, union=union))
