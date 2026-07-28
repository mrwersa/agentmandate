# Releasing AgentMandate

AgentMandate publishes from a GitHub Release through PyPI Trusted Publishing.
No long-lived PyPI token is stored in GitHub.

## One-time PyPI setup

Register a *pending* trusted publisher on PyPI before the first release, since
the project does not exist there yet. Publishing the first version creates the
project and promotes it to a normal publisher, so this does not need repeating.

- PyPI project: `agentmandate`
- GitHub owner: `mrwersa`
- Repository: `agentmandate`
- Workflow: `release.yml`
- Environment: `pypi`

Protect the `pypi` GitHub environment against unreviewed deployment where the
account plan permits it.

## Prepare a release

1. Create a release branch from current `main`.
2. Set the version in `pyproject.toml` and `agentmandate/__init__.py`.
3. Move the relevant entries from `Unreleased` into a dated changelog section.
4. Run the local checks:

   ```bash
   python -m pytest -q
   python -m pytest -q --cov=agentmandate --cov-fail-under=90
   ruff check .
   python -m pip install build twine
   python -m build
   python -m twine check dist/*
   ```

5. Open a pull request and merge it only after every required CI check passes.

## Publish

1. Create a GitHub Release tagged `v<version>`, matching `pyproject.toml`
   exactly. The release workflow verifies this and fails the build otherwise.
2. Publishing the release triggers `release.yml`, which rebuilds from the tag,
   checks the metadata, and uploads to PyPI.
3. Confirm the version appears on PyPI and that `pip install agentmandate`
   resolves it.
