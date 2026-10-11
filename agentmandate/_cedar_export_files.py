"""Materialize a complete Cedar export without overwriting an existing bundle."""

import json
import os
from pathlib import Path

from ._policy_export_files import write_files

_RESERVE_RENAME = os.name != "nt"


def write_bundle(result: dict, destination: Path) -> None:
    files = {"policies.cedar": result["policies"]}
    for name, value in (
        ("schema.json", result["cedar_schema"]),
        ("entities.json", result["entities"]),
        ("tests.json", result["tests"]),
        ("export.json", result),
    ):
        files[name] = json.dumps(value, indent=2, sort_keys=True) + "\n"
    write_files(files, destination, reserve_rename=_RESERVE_RENAME)
