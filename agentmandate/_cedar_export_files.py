"""Materialize a complete export in a new directory; never overwrite a bundle."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

_RESERVE_RENAME = os.name != "nt"


def write_bundle(result: dict, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise ValueError("export output directory already exists; choose a new path")
    with TemporaryDirectory(prefix=".agentmandate-export-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        (stage / "policies.cedar").write_text(result["policies"], encoding="utf-8")
        for name, value in (
            ("schema.json", result["cedar_schema"]),
            ("entities.json", result["entities"]),
            ("tests.json", result["tests"]),
            ("export.json", result),
        ):
            (stage / name).write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        # Reserve the destination exclusively after staging is complete. A
        # directory created during staging must not be replaced by rename.
        if _RESERVE_RENAME:
            destination.mkdir()
        try:
            stage.rename(destination)
        except OSError:
            if _RESERVE_RENAME:
                destination.rmdir()
            raise
