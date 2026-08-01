# Releasing AgentMandate

Releases are cut by merging a pull request. Nothing is typed by hand at
release time, because the last manually cut release shipped a wheel whose
`__version__` was one version behind.

AgentMandate publishes from a GitHub Release through PyPI Trusted Publishing.
No long-lived PyPI token is stored in GitHub.

## Cut a release

1. Create a release branch from current `main`.
2. Raise `__version__` in `agentmandate/__init__.py`. That is the only place
   the number lives. `pyproject.toml` declares a dynamic version and reads it
   from there.
3. Move the relevant entries from `Unreleased` into a dated section:

   ```markdown
   ## 0.5.1 - 2026-07-31
   ```

   That section becomes the GitHub Release notes verbatim, so write it for
   someone deciding whether to upgrade. A missing, undated, or empty section
   fails the release rather than publishing a version nobody described.

4. Run the local checks:

   ```bash
   python -m pytest -q
   python -m pytest -q --cov=agentmandate --cov-fail-under=100
   ruff check .
   python -m build && python -m twine check dist/*
   ```

5. Open a pull request and merge it once every required check passes.

Merging does the rest, once CI has passed on the merged commit.

The release workflow runs when CI finishes on `main`, not when the push
happens, and only when CI concluded successfully. It reads the version from
the exact commit CI passed on, stops if that version is already tagged,
extracts the changelog section, builds and checks the artefacts, and only then
creates the tag and the GitHub Release before publishing to PyPI.

The order matters. Tagging first would leave a public release behind whenever
a build or an upload failed, which is a version users can see and cannot
install.

Confirm afterwards that the version appears on PyPI and that
`pip install agentmandate` resolves it.

## The Marketplace listing is not automated, and cannot be

The action is listed on the GitHub Marketplace so people find it by searching
rather than by already knowing this repository exists. Listing a release is a
checkbox on the release form in the web UI, and there is no API for it. The
release workflow creates releases through the API, so it will never tick that
box.

That is a genuine gap rather than an oversight worth fixing. Advancing the
listing to a new version should be a decision somebody makes, not something
that happens because a version number moved.

After a release that changes the action, if you want the listing to point at
it:

1. Open the release, choose **Edit**.
2. Tick **Publish this Action to the GitHub Marketplace**.
3. Accept the Developer Agreement on the first listing only.
4. Category: **Security**. Compound authority analysis is what somebody
   browsing that category is looking for.

Requirements the repository already meets, checked rather than assumed: it is
public, `action.yml` sits at the root, `branding` declares an icon and a
colour, and the name matches neither an existing listing nor a GitHub account.
Publishing needs two-factor authentication on the account.

Once the first listing exists, this badge belongs beside the others in the
README, and not before, because the link 404s until then:

```markdown
[![Marketplace](https://img.shields.io/badge/marketplace-agentmandate-2088ff?logo=github)](https://github.com/marketplace/actions/agentmandate)
```

## What the automation refuses to do

- Publish a commit whose CI run did not succeed.
- Publish a commit that is no longer the tip of `main`. CI runs finish in
  whatever order they finish, not commit order, so releasing a commit that
  something has landed on top of would publish an older version after a newer
  one. Whatever is on top releases itself.
- Publish a version with no dated changelog section.
- Publish a wheel or sdist whose filename does not match the tag.
- Re-release a version that already has a GitHub Release.
- Run two releases at once. The workflow takes a repository-wide lock.

Two bumps merged in quick succession release the second one only. The first
version is never the tip long enough to release, and its changes ship inside
the second. Merge one release at a time if each needs its own version on PyPI.

## When something fails partway

The decision is keyed on whether the **release** exists, not the tag, so a run
that pushed the tag and then died recreates only what is missing rather than
reading as finished.

If the PyPI upload is what failed, re-run the failed job from the Actions
page. The artefacts are already built and attached, and the publish step
uploads those exact files.

## Publishing from the GitHub UI

Creating a release by hand still publishes, which is the path to use for a
re-run after an infrastructure failure. Tag it `v<version>`, matching
`agentmandate/__init__.py` exactly.

Note that a release created by the workflow's own token does not trigger
another workflow run. That is why tagging and publishing live in the same
workflow file rather than in two files that chain.

## One-time PyPI setup

The trusted publisher was registered for the first release. Publishing that
version created the project and promoted the pending publisher, so this setup
does not need repeating.

- PyPI project: `agentmandate`
- GitHub owner: `mrwersa`
- Repository: `agentmandate`
- Workflow: `release.yml`
- Environment: `pypi`

Protect the `pypi` GitHub environment against unreviewed deployment where the
account plan permits it.
