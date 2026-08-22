# Repository Guidelines

Single Python package (`agentmandate/`, ~5k lines) that analyses what an AI agent is permitted to do: `manifest.py` loads manifests, `reach.py` searches reachable authority, `diff.py` compares manifests across releases, `cli.py` exposes the `mandate` command. Tests mirror module names (`agentmandate/diff.py` → `tests/test_diff.py`). `examples/` holds sample manifests, traces, and agent code; user docs go in `docs/`; maintenance scripts in `scripts/`.

## Commands

```bash
python -m pip install -e ".[dev]"        # venv first
python -m pytest -q                      # full suite
python -m pytest -q --cov=agentmandate --cov-report=term-missing --cov-fail-under=100
ruff check .                             # before pushing; CI enforces this exact rule set
python -m build && python -m twine check dist/*   # release prep (needs `build`, `twine`)
mandate --help                           # smoke-test editable install
```

CI runs five required jobs: test matrix (3.10–3.14), lint, coverage, no-dependency-install, package. Run lint + coverage locally before opening a PR.

## Hard constraints

- **Zero runtime dependencies in core.** `dependencies = []` is deliberate; CI installs the bare package and analyses a JSON manifest with nothing else present. PyYAML is an optional extra, imported lazily inside `manifest.py` (~line 341) with a missing-module error that names the fix. Do not add imports to core modules or move the yaml import to module level.
- **100% statement coverage is a CI gate.** Every statement you add needs a test, including error paths and CLI exit codes. Uncovered lines fail the build even when all tests pass.
- **Docs are tested.** `tests/test_readme_asset.py` asserts the `docs/assets/authority-path.svg` matches the executable counterexample in the README and that README prose contains **no literal version numbers** (the badge and PyPI carry them). Editing README or the diagram can break tests.
- **Version lives only in `agentmandate/__init__.py`.** `pyproject.toml` reads it via hatch's dynamic version. Never put a version number anywhere else.
- **Releases are automated**, cut by merging a PR that bumps `__version__` and moves changelog entries into a dated section (see RELEASING.md); a GitHub Release then publishes to PyPI via trusted publishing. Don't tag or publish by hand.
- **Exit-code contract:** every analysis command exits non-zero on a finding and accepts `--json`, so they drop into CI unchanged. Preserve this when touching `cli.py`; tests assert specific exit codes.

## Style

Python 3.10+, four-space indent, ruff line-length 100 with the pinned rule set in `pyproject.toml`. Type-annotated throughout; keep public exports explicit in `agentmandate/__init__.py` (`__all__`). A name importable but missing from `__all__` counts as a defect worth releasing over. `ManifestError` intentionally subclasses `ValueError` so callers catch either — that's why `TRY004` is ruff-ignored; don't "fix" it.

## Testing

pytest, files named `test_*.py`. Add or update tests for every behavioral change; parameterize related edge cases instead of duplicating bodies. Fixtures must contain no credentials, customer data, account IDs, or real trace IDs.

## Workflow

`main` is protected; everything lands via PR from a branch such as `feature/short-description` (also seen: `docs/…`, `fix/…`, `release/…`). Conventional Commit subjects (`feat:`, `fix:`, `docs:`, `release:`), imperative mood, one focused change per commit. Open an issue before starting a large extractor. Merge only after CI passes and review threads resolve.

Cut a release whenever a user-visible change merges (API, CLI surface, README describing behavior differently, user-facing defect fix) — see RELEASING.md for the full triggers and non-triggers.
