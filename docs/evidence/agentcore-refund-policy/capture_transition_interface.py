"""Capture the AgentCore control-plane operation inventory from a pinned SDK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import botocore
import botocore.session

CONTINUATION_TERMS = ("migrate", "reauthor", "settle", "transfer", "continuation")


def capture(output: Path) -> None:
    """Write the canonical SDK operation inventory without making a network call."""
    model = botocore.session.get_session().get_service_model("bedrock-agentcore-control")
    operations = sorted(model.operation_names)
    related = [
        operation
        for operation in operations
        if any(term in operation.lower() for term in ("policy", "session", "history"))
    ]
    continuation = [
        operation
        for operation in operations
        if any(term in operation.lower() for term in CONTINUATION_TERMS)
    ]
    value = {
        "interface_inventory_version": 1,
        "service": "bedrock-agentcore-control",
        "botocore_version": botocore.__version__,
        "operations": operations,
        "policy_session_history_operations": related,
        "state_continuation_operations": continuation,
        "interpretation": (
            "the captured SDK interface exposes policy lifecycle operations but no operation "
            "named for state migration, settlement, reauthorisation, transfer, or continuation"
        ),
    }
    output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    capture(args.output)


if __name__ == "__main__":
    main()
