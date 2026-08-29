"""Measure the trusted managed-Cedar comparison over the committed capture.

Input parsing and filesystem reads happen before timing.  The reported wall
clock therefore covers ``compare_managed_cedar`` only.  The output is an
observation, not a byte-reproducible build product: reruns should preserve the
result and measurement method, while timings may vary by host.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import date
from pathlib import Path

from agentmandate._managed_cedar import ManagedOracle, compare_managed_cedar
from agentmandate.manifest import load

HERE = Path(__file__).resolve().parent


def _oracle(name: str) -> tuple[ManagedOracle, dict[str, bytes]]:
    oracle = ManagedOracle.from_json((HERE / name).read_text(encoding="utf-8"))
    contents = {item.locator: (HERE / item.locator).read_bytes() for item in oracle.sources}
    oracle.verify_sources(contents)
    return oracle, contents


def measure(*, warmups: int, repetitions: int, measured_at: str) -> dict:
    """Return one measurement record for the committed baseline and candidate."""
    if warmups < 0 or repetitions < 1:
        raise ValueError("warmups must be non-negative and repetitions must be positive")
    mandate = load(HERE / "mandate.yaml")
    baseline, baseline_contents = _oracle("managed-oracle-v1.json")
    candidate, candidate_contents = _oracle("candidate-managed-oracle-v1.json")

    def compare():
        return compare_managed_cedar(
            mandate,
            baseline,
            baseline_contents,
            candidate,
            candidate_contents,
            as_of=date(2026, 8, 29),
        )

    for _ in range(warmups):
        compare()
    samples_ns = []
    result = None
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        result = compare()
        samples_ns.append(time.perf_counter_ns() - started)
    assert result is not None
    changes = [item.classification for item in result.changes]
    if result.findings or changes.count("widens") != 1:
        raise ValueError("committed comparison does not contain exactly one trusted widening")

    samples_ms = [value / 1_000_000 for value in samples_ns]
    median_ms = statistics.median(samples_ms)
    return {
        "measurement_version": 1,
        "capture": "agentcore-refund-policy",
        "measured_at": measured_at,
        "counterexample_length": 1,
        "counterexample_definition": (
            "minimum canonical managed requests needed to witness the deny-to-allow change"
        ),
        "analysis_wall_clock_ms": round(median_ms, 6),
        "timing_definition": (
            "median in-process compare_managed_cedar wall-clock time after input loading"
        ),
        "samples": {
            "warmups": warmups,
            "repetitions": repetitions,
            "minimum_ms": round(min(samples_ms), 6),
            "median_ms": round(median_ms, 6),
            "maximum_ms": round(max(samples_ms), 6),
        },
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "result": {"classifications": changes, "finding_count": len(result.findings)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warmups", type=int, default=100)
    parser.add_argument("--repetitions", type=int, default=1000)
    parser.add_argument("--measured-at", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    content = json.dumps(
        measure(
            warmups=args.warmups,
            repetitions=args.repetitions,
            measured_at=args.measured_at,
        ),
        indent=2,
        sort_keys=True,
    ) + "\n"
    if args.output is None:
        sys.stdout.write(content)
    else:
        args.output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
