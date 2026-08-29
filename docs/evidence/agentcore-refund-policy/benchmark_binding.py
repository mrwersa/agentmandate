"""Measure issuer-signature verification and session derivation for one binding."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path

from mandate_binding import verify_and_derive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--warmups", type=int, default=20)
    parser.add_argument("--repetitions", type=int, default=200)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    binding = json.loads(args.binding.read_text(encoding="utf-8"))
    public_key = args.public_key.read_bytes()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))

    def run() -> None:
        verify_and_derive(
            binding, public_key, as_of=as_of, expected_principal="caller"
        )

    for _ in range(args.warmups):
        run()
    observations = []
    for _ in range(args.repetitions):
        start = time.perf_counter_ns()
        run()
        observations.append(time.perf_counter_ns() - start)
    openssl = subprocess.run(
        ["openssl", "version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    result = {
        "binding_benchmark_version": 1,
        "operation": "Ed25519 verify plus deterministic session derivation",
        "warmups": args.warmups,
        "repetitions": args.repetitions,
        "median_ms": statistics.median(observations) / 1_000_000,
        "minimum_ms": min(observations) / 1_000_000,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "openssl": openssl,
        },
        "timing_boundary": "in-process adapter call including one OpenSSL subprocess",
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
