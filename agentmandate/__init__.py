"""AgentMandate: analyse what an AI agent is permitted to do.

Two questions this package answers that a per-tool scanner cannot:

- Given a set of individually legal tools, is there a legal call sequence that
  breaches a limit? ``reach`` returns the sequence, not a score.
- Did this release widen what the agent can reach? ``diff`` compares effective
  authority rather than configuration text, because the two come apart.

It also covers the ordinary single-manifest checks and replays recorded runs
against the declaration, so it is usable without another tool alongside it.
"""

from __future__ import annotations

__version__ = "0.3.1"

from .diff import Change, Delta, compare
from .lint import Finding, check
from .manifest import Mandate, ManifestError, Money, Tool, load, loads
from .obligations import (
    OBLIGATIONS_SCHEMA,
    Obligation,
    ObligationSet,
    derive,
    load_obligations,
    save_obligations,
    to_decision_suite,
)
from .reach import Authority, Breach, Step, analyse
from .scan import Proposal, propose, render, scan_file
from .verify import Conformance, Observation, Violation, replay, replay_file

__all__ = [
    "Authority",
    "Breach",
    "Change",
    "Conformance",
    "Delta",
    "Finding",
    "Mandate",
    "ManifestError",
    "OBLIGATIONS_SCHEMA",
    "Money",
    "Obligation",
    "ObligationSet",
    "Observation",
    "Proposal",
    "Step",
    "Tool",
    "Violation",
    "__version__",
    "analyse",
    "check",
    "derive",
    "compare",
    "load",
    "load_obligations",
    "loads",
    "save_obligations",
    "to_decision_suite",
    "propose",
    "render",
    "replay",
    "replay_file",
    "scan_file",
]
