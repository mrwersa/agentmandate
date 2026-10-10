"""Measure the pinned search corpus; output is maintenance data, not authority."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import tracemalloc
import types
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "tests/fixtures/search-baselines.json"
sys.path.insert(0, str(ROOT))

from agentmandate import __version__, loads  # noqa: E402
from agentmandate.reach import _analyse_with_trace  # noqa: E402


def fingerprint(authority, trace):
    paths = [
        {
            "tool": name,
            "path": [
                {
                    "tool": step.tool,
                    "binding": step.binding,
                    "spent": None if step.spent is None else str(step.spent),
                    "currency": step.currency,
                }
                for step in path
            ],
        }
        for name, path in trace.reachable_paths
    ]

    def digest(value):
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    return {
        "authority_sha256": digest(authority.as_dict()),
        "trace_sha256": digest(paths),
    }


def _baseline_kernel(baselines):
    source = subprocess.check_output(
        ["git", "show", f"{baselines['baseline_ref']}:agentmandate/reach.py"], cwd=ROOT
    )
    if hashlib.sha256(source).hexdigest() != baselines["baseline_source_sha256"]:
        raise ValueError("baseline search source does not match its pinned digest")
    module = types.ModuleType("agentmandate._benchmark_baseline")
    module.__package__ = "agentmandate"
    sys.modules[module.__name__] = module
    exec(compile(source, "<pinned-search-baseline>", "exec"), module.__dict__)
    return module._analyse_with_trace


def _measure(kernels, mandate, case, repeat):
    samples = {name: [] for name in kernels}
    peaks = {}
    kwargs = {"depth": case["depth"], "producer_caps": case["producer_caps"]}
    for index in range(repeat):
        order = list(kernels) if index % 2 == 0 else list(reversed(kernels))
        for name in order:
            gc.collect()
            started = perf_counter_ns()
            authority, trace = kernels[name](mandate, **kwargs)
            samples[name].append(perf_counter_ns() - started)
            if fingerprint(authority, trace) != {
                key: case[key] for key in ("authority_sha256", "trace_sha256")
            }:
                raise ValueError(f"{name} search changed pinned output for {case['name']}")
    # Allocation instrumentation is excluded from elapsed-time samples.
    for name, kernel in kernels.items():
        gc.collect()
        tracemalloc.start()
        try:
            authority, trace = kernel(mandate, **kwargs)
            peaks[name] = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
    return {
        name: {
            "elapsed_ns_samples": values,
            "elapsed_ns_median": statistics.median(values),
            "peak_traced_bytes": peaks[name],
        }
        for name, values in samples.items()
    }


def benchmark(*, repeat=3, compare_baseline=False, names=None):
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        raise ValueError("repeat must be a positive integer")
    baselines = json.loads(BASELINES.read_text())
    cases = [case for case in baselines["cases"] if names is None or case["name"] in names]
    if not cases or (names is not None and set(names) - {case["name"] for case in cases}):
        raise ValueError("unknown or empty benchmark case selection")
    kernels = {"current": _analyse_with_trace}
    if compare_baseline:
        kernels["baseline"] = _baseline_kernel(baselines)
    rows = []
    for case in cases:
        data = (ROOT / case["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != case["input_sha256"]:
            raise ValueError(f"input digest changed for {case['path']}")
        mandate = loads(data.decode(), source=case["path"])
        metrics = {}
        authority, trace = _analyse_with_trace(
            mandate, depth=case["depth"], producer_caps=case["producer_caps"], _metrics=metrics
        )
        if fingerprint(authority, trace) != {
            key: case[key] for key in ("authority_sha256", "trace_sha256")
        }:
            raise ValueError(f"current search changed pinned output for {case['name']}")
        tools = len(mandate.tools)
        scopes = len({tool.produces for tool in mandate.tools if tool.produces})
        effects = len(mandate.limits.effects)
        spenders = sum(tool.spends_value for tool in mandate.tools)
        depth = case["depth"]
        tree_bound = sum(tools**level for level in range(depth + 1))
        representation_bound = (depth + 1) ** (scopes + effects + spenders * depth)
        state_bound = min(tree_bound, representation_bound)
        if metrics["states_discovered"] > state_bound:
            raise ValueError("observed states exceed the documented conservative bound")
        rows.append(
            {
                **case,
                "tool_count": tools,
                "state_bound": state_bound,
                "metrics": metrics,
                "measurements": _measure(kernels, mandate, case, repeat),
            }
        )
    real = [row for row in rows if row["kind"] == "real-graph"]
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "package_version": __version__,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "timing_clock": "perf_counter_ns",
            "memory_measure": "tracemalloc peak during kernel only; excludes input loading",
            "repeat": repeat,
            "gc_enabled": gc.isenabled(),
            "gc_thresholds": list(gc.get_threshold()),
        },
        "source_sha256": hashlib.sha256((ROOT / "agentmandate/reach.py").read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "baselines_sha256": hashlib.sha256(BASELINES.read_bytes()).hexdigest(),
        "baseline_ref": baselines["baseline_ref"],
        "baseline_source_sha256": baselines["baseline_source_sha256"],
        "real_graph_runs": len(real),
        "real_graph_truncated_runs": sum(row["truncated"] for row in real),
        "cases": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--compare-baseline", action="store_true")
    parser.add_argument("--case", action="append", dest="names")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = benchmark(
            repeat=args.repeat, compare_baseline=args.compare_baseline, names=args.names
        )
        text = json.dumps(result, sort_keys=True, indent=2) + "\n"
        if args.output:
            args.output.write_text(text)
        else:
            print(text, end="")
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
