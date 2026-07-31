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

from .inventory import Inventory, collect
from .manifest import Mandate

# Ordered by how much a reader should care. Authority the mandate does not
# describe comes first, because it silently invalidates every other answer.
DRIFT_KINDS = ("undeclared", "argument", "removed", "unresolved")


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

    @property
    def clean(self) -> bool:
        return not self.findings

    def render(self) -> str:
        lines = [
            f"drift  {self.agent}",
            f"  {len(self.declared)} tool(s) declared, "
            f"{len(self.discovered)} given to the agent in source",
            "",
        ]
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
            "findings": [
                {"kind": f.kind, "tool": f.tool, "message": f.message}
                for f in self.findings
            ],
        }


def compare(mandate: Mandate, inventory: Inventory) -> Drift:
    """Report every way the manifest has stopped describing the source."""
    findings: list[DriftFinding] = []

    declared = {tool.name: tool for tool in mandate.tools}
    discovered = {d.name: d for d in inventory.declarations}

    for name in sorted(set(discovered) - set(declared)):
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

    for name in sorted(set(declared) - set(discovered)):
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
    for item in inventory.unresolved:
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

    order = {kind: index for index, kind in enumerate(DRIFT_KINDS)}
    findings.sort(key=lambda f: (order[f.kind], f.tool))

    return Drift(
        agent=mandate.agent,
        declared=tuple(sorted(declared)),
        discovered=tuple(sorted(discovered)),
        findings=tuple(findings),
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
