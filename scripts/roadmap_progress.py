#!/usr/bin/env python3
"""Compute planning progress from the repository's explicit initiative ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POINTS = {"delivered": 1, "partial": 0.5, "blocked": 0, "not_started": 0}


def calculate(ledger: dict) -> dict:
    phases = []
    seen = set()
    for phase in ledger["phases"]:
        rows = phase["initiatives"]
        if not rows or phase["id"] in seen:
            raise ValueError("phases need unique IDs and at least one initiative")
        seen.add(phase["id"])
        titles = set()
        points = 0
        for row in rows:
            if row["title"] in titles or not row["reason"].strip():
                raise ValueError("initiatives need unique titles and a reason")
            titles.add(row["title"])
            if row["status"] not in POINTS:
                raise ValueError(f"unsupported progress status: {row['status']}")
            evidence = Path(row["evidence"])
            if evidence.is_absolute() or ".." in evidence.parts or not (ROOT / evidence).is_file():
                raise ValueError("progress evidence must name an existing repository file")
            points += POINTS[row["status"]]
        phases.append(
            {
                "id": phase["id"],
                "points": points,
                "initiatives": len(rows),
                "percent": round(100 * points / len(rows), 2),
            }
        )
    if not phases:
        raise ValueError("the ledger must contain phases")
    total = sum(p["initiatives"] for p in phases)
    points = sum(p["points"] for p in phases)
    first_three = phases[:3]
    return {
        "as_of": ledger["as_of"],
        "method": ledger["method"],
        "phases": phases,
        "overall": {
            "points": points,
            "initiatives": total,
            "percent": round(100 * points / total, 2),
        },
        "first_three_phases": {
            "points": sum(p["points"] for p in first_three),
            "initiatives": sum(p["initiatives"] for p in first_three),
            "percent": round(
                100
                * sum(p["points"] for p in first_three)
                / sum(p["initiatives"] for p in first_three),
                2,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / "docs/roadmap-progress.json")
    args = parser.parse_args()
    try:
        result = calculate(json.loads(args.ledger.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
