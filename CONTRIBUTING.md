# Contributing

AgentMandate uses a pull-request-only workflow for `main`.

1. Create a branch from the latest `main`:

   ```bash
   git switch main
   git pull --ff-only
   git switch -c feature/short-description
   ```

2. Keep the change focused and add tests for behavioural changes.

3. Run the local quality gate:

   ```bash
   python -m pytest -q
   python -m pytest -q --cov=agentmandate --cov-fail-under=90
   ruff check .
   ```

4. Push the branch and open a pull request:

   ```bash
   git push -u origin feature/short-description
   ```

Direct pushes, force pushes, and deletion of `main` are blocked. Merge only
after CI passes and all review conversations are resolved.

Maintainers should follow [RELEASING.md](RELEASING.md) when publishing a
version.

## Useful first contributions

The authority model is the part that most needs contact with real systems.
Good first contributions include:

- a manifest for a tool graph this models badly, with a note on what it gets
  wrong. A graph the model cannot express is more useful than a new rule
- an extractor that derives a manifest from an MCP server or a framework's
  tool registry, so manifests stop being hand-authored
- a lint rule that maps to a named control, with the control cited
- a counterexample the search should find and does not

Open an issue before a large extractor. Describe the source of truth it reads,
what it can and cannot infer, and what a human still has to annotate.

Do not include customer prompts, model outputs, credentials, real account
identifiers, or trace identifiers in an issue or a fixture.
