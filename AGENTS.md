# AGENTS.md — agentmandate

Single Python package `agentmandate/` (~16k lines, 21 modules). Core: `manifest.py` (loads/validates), `reach.py` (bounded breach search), `diff.py` (effective-authority compare), `cli.py` (`mandate` entrypoint). Also `scan`/`drift`/`verify`/`ir`/`inventory`/`_conditions`/`_delegation`/`_managed_cedar`/`obligations`/`scenarios`. `examples/` holds manifests/traces/sample agent; `docs/` user docs; `scripts/` maintenance; `probes/` synthetic graphs.

## Commands (exact, verified from `pyproject.toml` / `.github/workflows/ci.yml`)

```bash
python -m pip install -e ".[dev]"        # venv first; installs pyyaml+ruff for dev
python -m pytest -q                      # full suite
python -m pytest tests/test_reach.py -q  # single file
python -m pytest tests/test_reach.py -k test_name -q  # single case
python -m pytest -q --cov=agentmandate --cov-report=term-missing --cov-fail-under=100
ruff check .                             # pinned rule set below; CI enforces exactly this
python -m build && python -m twine check dist/*   # needs build+twine
mandate --help                           # smoke-test editable install
python scripts/evidence_lint.py          # only when touching docs/evidence/
```

CI required jobs (5 + gate): `test` matrix 3.10–3.14, `lint` (ruff), `coverage` (100%), `no-dependency-install`, `package` (build+twine+wheel smoke). Gate fails if any upstream fails. Run lint+coverage locally before PR.

No `opencode.json`, no pre-commit, no typecheck step — `ruff` is the only lint.

## Architecture & entrypoints

- Package `agentmandate/`; CLI `mandate = agentmandate.cli:main` (argparse, subparsers `lint|reach|diff|scan|drift|verify|ir|inventory|conditions|delegations|cedar|obligations|scenarios`).
- `scan` reads `tools=[...]` / decorators statically — nothing imported/executed, framework need not be installed. One manifest per agent; use `--binding` or reject unions.
- `reach --ir` / `ir export|validate` are the canonical Authority IR boundary; `conditions`/`delegations`/`cedar` validate-then-consume reviewed artifacts with explicit `--as-of` + captured bytes. Never compose `--ir` with conditional/delegation flags.
- Tests mirror modules (`agentmandate/diff.py` → `tests/test_diff.py`); parametrized edge cases, no credentials/account IDs/trace IDs in fixtures.

## Hard constraints (CI will fail otherwise)

- **Zero runtime deps:** `dependencies = []` in `pyproject.toml` deliberate. `no-dependency-install` job installs bare package and runs `mandate reach` on a JSON manifest. `PyYAML` is `optional-dependencies.yaml`, imported lazily inside `manifest.py:loads` (~341) with error naming `pip install "agentmandate[yaml]"`. Do not add imports to core or move yaml to top level.
- **100% statement coverage gate:** every added statement needs a test, including error paths and CLI exit codes.
- **Version lives only in `agentmandate/__init__.py:__version__`** (`0.14.0`); `pyproject.toml` reads via `hatch.version.path`. Never duplicate elsewhere. Package job asserts `metadata.version == __version__ == scripts/release_notes.py --print-version`.
- **Docs are tested (`tests/test_readme_asset.py`):** README prose must contain **no literal `version X.Y.Z` / `agentmandate~=X.Y`** (badge+PyPI carry it); `docs/assets/authority-path.svg` must match the executable counterexample; `STABILITY.md` (and any prose `*.md` except `CHANGELOG.md`/`RELEASING.md`) must pin `agentmandate~=MAJOR.MINOR.0` exactly; every `mandate <cmd>` must appear in README.
- **Exit-code contract (`cli.py:EXIT_*`):** `0` clean, `1` finding (lint error / reachable breach / widening diff / non-conformant replay), `2` usage/I/O/malformed. Every analysis command accepts `--json` and is a CI gate; `scan`/`ir export` write to stdout and are not gates. Preserve for `docs/ci.md`.
- **Public API:** keep `agentmandate/__init__.py:__all__` exhaustive; importable but unlisted counts as defect. `ManifestError` intentionally subclasses `ValueError` (so callers catch either) — `TRY004` is ignored in `pyproject.toml:tool.ruff.lint.ignore`, don't "fix".
- **Release automation only:** bump `__version__` + dated `CHANGELOG.md` section on a branch, merge to `main`; `release.yml` triggers on CI success on `main`, builds, then tags + GitHub Release + PyPI trusted publishing (`environment: pypi`). Never tag/publish by hand; `main` is protected.

## Style & workflow

- Python 3.10+, 4-space indent, `ruff` line-length 100, pinned `select = ["E","F","I","B","UP","SIM","C4","RET","PLR1730","FURB"]` in `pyproject.toml`.
- Branches `feature/short-description` (also `docs/…`, `fix/…`, `release/…`); Conventional Commits (`feat:`, `fix:`, `docs:`, `release:`), imperative, one focused change per commit. Open an issue before large extractors. PR required, merge only after CI green + threads resolved.
- Cut a release on any user-visible change (API/CLI surface, README behavior description, user-facing fix) per `RELEASING.md`; not for internal docs/evidence tidy-ups.
