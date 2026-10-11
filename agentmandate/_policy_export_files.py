"""Stage an export bundle and publish it to a new directory without overwrite."""

from pathlib import Path
from tempfile import TemporaryDirectory


def write_files(files: dict[str, str], destination: Path, *, reserve_rename: bool) -> None:
    if destination.exists() or destination.is_symlink():
        raise ValueError("export output directory already exists; choose a new path")
    with TemporaryDirectory(prefix=".agentmandate-export-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for name, content in files.items():
            (stage / name).write_text(content, encoding="utf-8")
        # POSIX can replace an empty directory: reserve it exclusively first.
        # Windows rename already refuses an existing destination.
        if reserve_rename:
            destination.mkdir()
        try:
            stage.rename(destination)
        except OSError:
            if reserve_rename:
                destination.rmdir()
            raise
