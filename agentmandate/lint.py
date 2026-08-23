"""Single-manifest checks.

These are the defects visible in one manifest without walking the graph. Other
agent scanners cover much of this ground, and that overlap is deliberate: a
tool that only reported compound findings would be unusable without also
running one of them. The checks here are the floor, not the contribution.

Every finding names the control it comes from, because in a regulated setting
"the linter says no" carries less weight than "this breaks separation of
duties, and here is the pair of tools that proves it".
"""

from __future__ import annotations

from dataclasses import dataclass

from .manifest import IRREVERSIBLE, SERVICE, Mandate

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    subject: str
    message: str

    def render(self) -> str:
        return f"{self.severity.upper():7} {self.rule:24} {self.subject}\n        {self.message}"


def _separation_of_duties(mandate: Mandate) -> list[Finding]:
    """One principal must not hold both sides of a maker-checker control.

    NIST separates static conflict, where the role assignment itself is wrong,
    from dynamic conflict enforced at access time. A manifest can only settle
    the static half, so that is what this reports.
    """
    findings: list[Finding] = []
    proposers = set(mandate.roles.get("proposer", ()))
    approvers = set(mandate.roles.get("approver", ()))
    if not proposers or not approvers:
        return findings
    if proposers & approvers:
        overlap = ", ".join(sorted(proposers & approvers))
        findings.append(
            Finding(
                rule="sod.same-tool",
                severity=ERROR,
                subject=overlap,
                message=(
                    "the same tool is listed as both proposer and approver, "
                    "so the control approves itself"
                ),
            )
        )
    # The agent holds both sides even when the tools differ, because a single
    # identity can call either one. An approve tool the proposing agent can
    # invoke is not an independent second pair of eyes.
    findings.append(
        Finding(
            rule="sod.single-identity",
            severity=ERROR,
            subject=f"{min(proposers)} + {min(approvers)}",
            message=(
                "one agent identity reaches both the proposer and the approver "
                "role, so maker-checker is not enforced. The approver must be a "
                "human or an independently authorised service the agent cannot "
                "invoke"
            ),
        )
    )
    return findings


def check(mandate: Mandate) -> list[Finding]:
    """Run every single-manifest rule and return findings, worst first."""
    findings: list[Finding] = []
    findings.extend(_separation_of_duties(mandate))

    for tool in mandate.tools:
        if tool.effect == IRREVERSIBLE and not tool.requires_approval:
            findings.append(
                Finding(
                    rule="effect.ungated-irreversible",
                    severity=ERROR,
                    subject=tool.name,
                    message=(
                        "an irreversible effect with no approval requirement. "
                        "Reversibility, not confidence, decides where a gate belongs"
                    ),
                )
            )
        if tool.principal == SERVICE:
            findings.append(
                Finding(
                    rule="identity.service-principal",
                    severity=ERROR if tool.effect != "read" else WARNING,
                    subject=tool.name,
                    message=(
                        "uses a fixed credential represented as "
                        f"`{SERVICE}` rather than the caller's identity, which "
                        "is the confused-deputy shape. Where the platform "
                        "supports it, exchange the caller's token for each call "
                        "instead of fixed credentials. Exchange is not always "
                        "available or sufficient: a credential may be a "
                        "delegated user token or intersect other principals, and "
                        "manifest v1 cannot show which. Record the delegated or "
                        "intersecting identity shape in named review instead of "
                        "treating the exchange as complete"
                    ),
                )
            )
        if tool.spends_value and tool.scope_key not in tool.requires:
            findings.append(
                Finding(
                    rule="ceiling.unbound-scope",
                    severity=ERROR,
                    subject=tool.name,
                    message=(
                        f"the ceiling is measured against {tool.scope_key!r}, but the "
                        "tool does not require that scope, so the bound is not "
                        "attached to anything the caller was authorised for"
                    ),
                )
            )
        if tool.unbounded and tool.produces is None:
            findings.append(
                Finding(
                    rule="scope.unbounded-nothing",
                    severity=WARNING,
                    subject=tool.name,
                    message="marked unbounded but produces no scope, so the flag has no effect",
                )
            )

    currencies = {t.ceiling.currency for t in mandate.tools if t.ceiling}
    if mandate.limits.total is not None:
        currencies.add(mandate.limits.total.currency)
    if len(currencies) > 1:
        findings.append(
            Finding(
                rule="ceiling.mixed-currency",
                severity=ERROR,
                subject=", ".join(sorted(currencies)),
                message=(
                    "ceilings in more than one currency cannot be summed, so "
                    "cumulative analysis would be meaningless"
                ),
            )
        )

    order = {ERROR: 0, WARNING: 1}
    return sorted(findings, key=lambda f: (order[f.severity], f.rule, f.subject))
