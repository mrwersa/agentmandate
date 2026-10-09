"""Recompute a bounded timing audit of six frozen AgentCore event files.

This audits retained arithmetic and endpoint availability, not clock authenticity,
provider execution, independent clock domains, or continuity of a mandate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = "docs/evidence/agentcore-refund-policy/"
SOURCES = {
    "principal-continuity-events.json": (
        "07a203e38d15bae630fa6029591c899633a06a3ec9c654856903fc5f527ca09d",
        44,
    ),
    "retry-continuity-events.json": (
        "f64f681b0ae35550fcb101483f07b9bb1d1f9cd091cef164b8790dea514ebdc3",
        62,
    ),
    "continuation-events.json": (
        "b8f366492f156fa9e1854feea01d458e0e21caf528f85d7d03a38d56bc775ba6",
        228,
    ),
    "continuation-diagnostic-events.json": (
        "e9140cb8a0b7e677cb42a7562cc1bcec334fad1257306671a4b47f0abaa4ff3f",
        72,
    ),
    "temporal-transition-events.json": (
        "9a053341e71574e6f7a1e655266835ff555e88d8e55f299a1225f4fb9675444a",
        100,
    ),
    "temporal-transition-metadata-events.json": (
        "d867df688815be43daa3f66fafc2a55af08896f3ac76fb2ecdb1ab65cad80cce",
        4,
    ),
}


def _calls(value: Any, pointer: str = ""):
    if isinstance(value, dict):
        if "request" in value and "response" in value:
            yield pointer, value
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _calls(child, pointer + "/" + escaped)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _calls(child, pointer + "/" + str(index))


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise ValueError("clock audit requires UTC endpoints")
    return parsed


def audit(contents: dict[str, bytes]) -> dict[str, Any]:
    if set(contents) != {BASE + name for name in SOURCES}:
        raise ValueError("clock audit source set differs")
    files = []
    for name, (expected_digest, expected_calls) in sorted(SOURCES.items()):
        locator = BASE + name
        digest = hashlib.sha256(contents[locator]).hexdigest()
        if digest != expected_digest:
            raise ValueError(f"clock audit source digest differs: {locator}")
        calls = list(_calls(json.loads(contents[locator])))
        if len(calls) != expected_calls:
            raise ValueError(f"clock audit call count differs: {locator}")
        monotonic_pairs = 0
        negative_monotonic = 0
        regressions = []
        for pointer, call in calls:
            start = call.get("started_at", call.get("started_utc"))
            finish = call.get("finished_at", call.get("finished_utc"))
            delta = _utc(finish) - _utc(start)
            wall_us = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
            started_ns = call.get("started_monotonic_ns")
            finished_ns = call.get("finished_monotonic_ns")
            if (started_ns is None) != (finished_ns is None):
                raise ValueError("clock audit has a partial monotonic interval")
            elapsed_ns = None
            if started_ns is not None:
                if type(started_ns) is not int or type(finished_ns) is not int:
                    raise ValueError("clock audit monotonic endpoints must be integers")
                monotonic_pairs += 1
                elapsed_ns = finished_ns - started_ns
                negative_monotonic += elapsed_ns < 0
            if wall_us < 0:
                regressions.append(
                    {
                        "pointer": pointer,
                        "started_utc": start,
                        "finished_utc": finish,
                        "wall_delta_us": wall_us,
                        "monotonic_elapsed_ns": elapsed_ns,
                        "recorded_duration_ms": call.get("duration_ms"),
                        "outcome": call.get("outcome", call.get("derived_outcome")),
                    }
                )
        files.append(
            {
                "locator": locator,
                "content_sha256": digest,
                "calls_with_utc": len(calls),
                "calls_with_monotonic_endpoints": monotonic_pairs,
                "calls_without_monotonic_endpoints": len(calls) - monotonic_pairs,
                "negative_monotonic_intervals": negative_monotonic,
                "utc_regressions": regressions,
            }
        )
    return {
        "audit_version": 1,
        "scope": "six pinned AgentCore event files; not a whole-corpus timing certification",
        "files": files,
        "totals": {
            "calls": sum(f["calls_with_utc"] for f in files),
            "retained_monotonic_pairs": sum(f["calls_with_monotonic_endpoints"] for f in files),
            "utc_regressions": sum(len(f["utc_regressions"]) for f in files),
            "negative_monotonic_intervals": sum(f["negative_monotonic_intervals"] for f in files),
        },
    }


def main() -> None:
    contents = {BASE + name: (ROOT / BASE / name).read_bytes() for name in SOURCES}
    print(json.dumps(audit(contents), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
