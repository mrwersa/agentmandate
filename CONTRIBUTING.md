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
   python -m pytest -q --cov=agentmandate --cov-fail-under=100
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

## Contributing a real authority graph

Start from the [evidence contribution template](docs/evidence/TEMPLATE.md) and
place the finished package in `docs/evidence/<subject>/`. A real graph must
include:

- a published, version-pinned subject and source revision;
- a reproducible capture or a digest-pinned raw inventory;
- the deployment, selection, and completeness boundary that review assumes;
- preserved raw inventory and scanner output beside the reviewed manifest;
- every material correction, classified as **extractor defect**, **source
  ambiguity**, **model gap**, or **deployment policy**; and
- an understandable counterexample, limitation, or authority-shape consequence
  linked to a shipped change, open roadmap prerequisite, or explicit no-action
  conclusion.

One correction may have several classifications. Do not infer deployment
policy from implementation, upgrade heuristic evidence through review, or
describe a correction-free skeleton as precise without recording what a human
checked. Silence may mean the scanner missed uncertainty.

Capture code must state whether it imports or executes the subject, touches the
network, or contacts live infrastructure. Prefer pinned dependencies,
side-effect-free discovery, placeholder credentials, and byte-verifiable
output. Remove telemetry and account-specific environment where possible. A
synthetic graph belongs in `docs/evidence/probes/` and does not count as real
evidence for a model or roadmap gate.

Before opening an evidence PR, run the digest lint against your directory:

```bash
python scripts/evidence_lint.py
```

When a capture contributes to the paper-facing evidence set, also regenerate
and check the consolidated handoff:

```bash
python scripts/evidence_summary.py
python scripts/evidence_summary.py --check
```

`--require-complete-classification` is deliberately stricter. It fails while
any legacy correction lacks a canonical class assigned before the study. Do
not make it pass by reclassifying old prose after seeing the aggregate counts.

It fails when a README cites a SHA-256 that no longer matches the committed
file, or when the cited file is missing. The machine-checked form is
`\`<file>\`, SHA-256 \`<digest>\`` and must reference an artifact committed
in the same directory. Pins on external artifacts (upstream archives, pinned
source files) must be written in prose — "upstream archive SHA-256 is …" — so
the linter treats them as provenance notes rather than verifiable claims.
