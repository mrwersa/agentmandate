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

__version__ = "0.9.1"

from .diff import Change, Delta, compare
from .drift import Drift, DriftFinding, compare_source
from .inventory import Binding, Declaration, Inventory, InventoryError, collect
from .lint import Finding, check
from .manifest import Limits, Mandate, ManifestError, Money, Tool, load, loads
from .obligations import (
    OBLIGATIONS_SCHEMA,
    Obligation,
    ObligationSet,
    derive,
    load_obligations,
    reconcile,
    save_obligations,
    to_decision_suite,
)
from .reach import Authority, Breach, Step, analyse
from .scan import Proposal, propose, render, scan_file, scan_source
from .scenarios import (
    SCENARIOS_SCHEMA,
    Scenario,
    ScenarioSet,
    ScenarioStep,
    derive_scenarios,
    load_scenarios,
    reconcile_scenarios,
    save_scenarios,
)
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
    "SCENARIOS_SCHEMA",
    "Scenario",
    "ScenarioSet",
    "ScenarioStep",
    "Step",
    "Tool",
    "Violation",
    "__version__",
    "analyse",
    "check",
    "derive",
    "derive_scenarios",
    "compare",
    "load",
    "load_obligations",
    "load_scenarios",
    "loads",
    "save_obligations",
    "save_scenarios",
    "to_decision_suite",
    "propose",
    "render",
    "replay",
    "replay_file",
    "reconcile",
    "reconcile_scenarios",
    "Binding",
    "Drift",
    "DriftFinding",
    "compare_source",
    "Declaration",
    "Inventory",
    "InventoryError",
    "Limits",
    "collect",
    "scan_file",
    "scan_source",
]
