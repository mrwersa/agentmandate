"""Reproduce discovery probe counts and local timings; no service access."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentmandate import __version__, load  # noqa: E402
from agentmandate._remediation import plan  # noqa: E402
from agentmandate._required_workflows import _Requirements  # noqa: E402


def run():
    cases = [
        ("refund-cents", "examples/dispute-resolver-v2.yaml",
         "examples/remediation/required-refund.json", ("issue_refund=0.01",), 128),
        ("refund-micro-units", "examples/dispute-resolver-v2.yaml",
         "examples/remediation/required-refund.json", ("issue_refund=0.000001",), 128),
        ("refund-off-grid", "examples/dispute-resolver-v2.yaml",
         "examples/remediation/required-refund.json", ("issue_refund=0.03",), 128),
        ("two-tools", "examples/ceiling-discovery/two-tools.json",
         "examples/ceiling-discovery/required-two-tools.json", ("pay=1", "other=1"), 128),
        ("two-tools-cutoff", "examples/ceiling-discovery/two-tools.json",
         "examples/ceiling-discovery/required-two-tools.json", ("pay=1", "other=1"), 4),
    ]
    rows = []
    for name, manifest, requirements, choices, budget in cases:
        content = (ROOT / manifest).read_bytes()
        source = load(ROOT / manifest)
        needed = _Requirements.load((ROOT / requirements).read_bytes(), source,
                                    hashlib.sha256(content).hexdigest())
        start = perf_counter_ns()
        report = plan(source, discover_ceilings=choices, required_workflows=needed,
                      max_evaluations=budget)
        elapsed = perf_counter_ns() - start
        rows.append({
            "name": name, "manifest": manifest, "requirements": requirements,
            "input_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                             for path in (manifest, requirements)},
            "choices": choices, "max_evaluations": budget,
            "domain_points": report["discovery"]["domain_points"],
            "probes": report["search"]["combinations_examined"],
            "additional_reach_calls": report["search"]["candidates_analyzed"],
            "frontier_complete_within_domain": report["discovery"][
                "frontier_complete_within_domain"],
            "non_dominated": report["frontier"]["non_dominated"],
            "candidate_truncated": [c["authority"]["truncated"] for c in report["candidates"]],
            "elapsed_ns": elapsed,
        })
    return {
        "scope": "five fixed synthetic cases; one local timing each, not a performance guarantee",
        "package_version": __version__, "python": platform.python_version(),
        "platform": platform.platform(),
        "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                          for p in ("scripts/benchmark_ceiling_discovery.py",
                                    "agentmandate/_ceiling_discovery.py",
                                    "agentmandate/_remediation.py", "agentmandate/reach.py",
                                    "agentmandate/manifest.py",
                                    "agentmandate/_required_workflows.py")},
        "cases": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(run(), indent=2, sort_keys=True) + "\n")
