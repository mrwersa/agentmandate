# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Authority IR v1 provides a canonical, provenance-bearing representation of
  agents, tools, scopes, principals, roles, constraints, facts, and authority
  edges. Facts retain source location, adapter version, confidence, and review
  state; derived reachability, effect, transition, and breach edges cite their
  supporting source records.
- `mandate ir export MANIFEST` writes one canonical source snapshot, including
  separate content and semantic digests. `mandate ir validate SNAPSHOT` checks
  structural and graph integrity without treating parsed evidence as reviewed
  authority. There is intentionally no `import` command.
- `mandate reach --ir SNAPSHOT` analyzes only the closed manifest-v1 profile:
  supported adapter versions, complete typed predicates, verified semantic
  digests, and evidence that is both exact and accepted. Unsupported,
  contested, unreviewed, heuristic, or malformed semantics fail with exit 2
  and no partial standard output.
- `mandate reach --ir SNAPSHOT --json` writes result-envelope v1. It binds the
  source graph, effective depth, truncation boundary, existing ordered and
  repeated counterexamples, and augmented provenance graph with a canonical
  result digest. Reading the envelope re-runs analysis rather than trusting a
  recomputable checksum.

### Changed

- `mandate reach` now accepts exactly one input: a manifest path or the `--ir`
  snapshot option. Existing manifest, text, JSON, SARIF, graph, and exit-code
  behavior is unchanged; canonical result-envelope JSON is specific to the IR
  input.


## 0.9.1 - 2026-08-23

### Fixed

- Generated `mandate scan` comments no longer retain a trailing space when
  catalogue prose is truncated at the comment-length limit. Evidence fixtures
  can now preserve the scanner's byte-exact output without normalizing it.
- An effect-budget breach is reported once per class by keying on the class
  itself rather than on a prefix of the message. Matching `detail` worked only
  while every message happened to open with the effect name, so a reworded
  message would have produced one breach per call above the budget and nothing
  would have failed to say so. The published JSON is unchanged: `kind`,
  `detail` and `path`.


## 0.9.0 - 2026-08-05

Non-monetary effect budgets shipped before bounded scope cardinality because
two real graphs asked for a call count and no committed graph yet justified a
cardinality bound. On the GitHub MCP graph the model could already say that
triggering a workflow is irreversible and ungated. It could not say how many
times. A count, not a voice.

### Added

- `limits.effects` bounds how many calls of an effect class one run may make,
  for authority that is counted rather than priced: accounts closed,
  credentials rotated, workflows triggered. Declared only, so a manifest that
  names no budget behaves exactly as before.
  The search change is the load-bearing part. A tool that neither mints a scope
  nor spends against a ceiling was skipped as reaching no new state, so an
  irreversible tool with no scope never extended a path and a budget over it
  could never have fired. A budgeted call now progresses the walk the way
  spending does.


## 0.8.1 - 2026-08-05

Everything below has been on `main` since the start of August and reaching
nobody who installs the package. `Limits` and `reconcile` are the reason to
publish rather than wait: both are importable and neither was in `__all__`, so
`load(...).limits` handed back a type a caller could not name from the entry
point they were told to use.

`RELEASING.md` now says when to cut one, which is the rule whose absence let
this sit.

### Fixed

- `Limits` and `reconcile` are exported from the package root. Both were
  reachable through `agentmandate.manifest` and `agentmandate.obligations`,
  and `load(...).limits` handed users a type they could not name from the
  primary entry point, so the two names that broke the export pattern are now
  public.

### Changed

- The README is restructured around what a reader needs first. The
  payment-dispute example was told twice, once in prose and again in console
  output, and a five-bullet command list announced commands nobody had met yet.
  Showing beats telling, so the console output does the work and the prose is
  gone.
- A reader now reaches the finding inside the first screen: install, a clean
  lint, one read-only tool added, and a reachable breach. Positioning, the
  manifest format, and the command reference follow, rather than leading.
- CI wiring moves to `docs/ci.md`: the action, SARIF, the diff gate, and exit
  codes. Three sections of the README were CI detail a first-time reader does
  not need, and a Marketplace listing renders this file as its landing page.
- The README shows the GitHub Action above the fold. A Marketplace listing
  renders this file, so somebody arriving from a search wants the usage before
  the library tour.
- `RELEASING.md` records that the Marketplace listing is not automated and
  cannot be. Listing a release is a web-UI checkbox with no API behind it, so
  the release workflow will never tick it, and advancing the listing should be
  a decision rather than a consequence of a version number moving.
- The version-pin guard now covers every prose markdown file rather than the
  README alone. `STABILITY.md` carries the pin the README refuses, and that
  pin drifted in the sibling project because the guard scanned one file, so a
  test now checks all of them except the changelog and the release notes.
- The roadmap now describes the released 0.8.0 loop and the seven-check worked
  example. Its future work follows the distortions found in the real AgentKit
  graph instead of saying both that nothing is next and that a graph has
  already asked for changes.
- The README, evaluation-loop guide, and test-obligation guide place
  AgentMandate at the action boundary: the model proposes a call, while the
  platform owns identity, authorisation, and the effect. The two guides use
  reviewable Mermaid flows.
- Simple Mermaid figures now publish an SVG for repository documentation and
  retain a PNG only for Medium. PlantUML is deliberately not added for flows
  that need no extra notation.

### Fixed

- The release guide now matches the workflow: an existing GitHub Release, not
  a tag by itself, marks a version complete. An orphaned tag remains
  recoverable by design.

## 0.8.0 - 2026-08-01

### Added

- A GitHub Action. The gate was six commands and a handful of flags, which is
  a wrapper rather than a feature, and it is the difference between a tool
  people try and a tool people run.

  ```yaml
  - uses: mrwersa/agentmandate@v0.8.0
    with:
      manifest: mandate.yaml
      baseline: mandate-released.yaml
      source: src/agent
  ```

- The counterexample renders in the job summary as a Mermaid graph rather than
  a log line, beside a table of what each check asked and the output of any
  that failed. The boundary travels with it: the summary states that findings
  describe what the manifest permits under a bounded search, not what the
  model tends to do.
- Only the checks the caller supplied inputs for run. A manifest is enough for
  `lint` and `reach`; `drift`, `diff`, and `verify` stay off until given what
  they need. An action demanding a baseline, agent source, and an OTLP export
  before saying anything would be adopted by nobody.
- SARIF is written and its path returned, and uploading it stays the caller's
  step. Uploading needs `security-events: write`, and an action requesting a
  token permission it can avoid is one more reason to refuse it.
- `fail-on: never` reports without failing, so a team can turn this on over an
  existing repository without blocking everyone on the first day. A gate
  nobody can adopt incrementally is a gate that gets removed rather than
  fixed.
- A lint warning is reported without blocking. `lint` exits zero on a warning
  and non-zero on an error, and counting both into one number produced
  `verdict=clean` beside `findings=1`, a self-contradicting pair, with the
  warning appearing nowhere in the summary. Blocking and advisory findings are
  counted apart, `notes` is a separate output, and an advisory finding shows
  as a warning mark rather than a tick. Dropping the count would have made the
  arithmetic agree by losing a real finding, which is the failure this package
  is about.
- Artefacts are written to `RUNNER_TEMP` rather than the checkout. A
  repository that fails on a dirty tree, or a later step that archives the
  workspace, would otherwise pick them up, and two jobs would collide on the
  same filename. Both paths are still returned as outputs.
- The human-readable output of a check is fetched only when something will
  show it, so a clean run does not pay for text nobody reads.
- The action runs against this repository's own examples in CI, including the
  clean case, the failing case, and the report-only case, because a wrapper
  nobody exercises breaks quietly in somebody else's pull request.

### Fixed

- The README said "Alpha, version 0.4.0" while 0.7.0 was the live release,
  three minors behind, because nothing failed when the number stopped being
  true. The version is in the badge and on PyPI; prose does not repeat it, and
  a test now refuses any version string in the README that can drift.
- A test requires every CLI command to be named in the README. A command
  nobody can discover from the front page is a command nobody finds.

### Fixed

- `drift` no longer reports a declared tool as `removed` when the source binds
  it from a module the scan never read. An absent declaration is not an absent
  tool, so the report now gives only the `unresolved` finding instead of
  contradicting it. The removal claim is suppressed whenever the read could
  not enumerate the whole list, whether that is an unreadable binding or a
  binding outside the scanned path.
- `drift --union-bindings` names the source side correctly. The union of
  several agents is reported as the union, and a single agent selected under
  the flag is named like any other binding. Both previously read as "no agent
  binding was found", which was false whenever a binding had been chosen.

## 0.7.0 - 2026-07-31

### Added

- `mandate reach --sarif` emits SARIF 2.1.0, so a reachable breach is
  annotated on the pull request that introduced it rather than sitting in a
  log nobody opens. Findings are `error` rather than `warning`, because they
  already exit non-zero and a UI disagreeing with the exit code is how a gate
  stops being believed.
- Each result is anchored at the line declaring the last tool on the path, and
  the message says that is a convention: a compound breach has no single
  guilty line. The fingerprint is the kind and the path, so reformatting the
  manifest does not make GitHub report the same breach as new.
- `mandate reach --graph` emits Mermaid, which GitHub renders inline. One node
  per step rather than per tool, since the same tool called twice on different
  bindings is usually the whole finding and a node per tool draws that as a
  self-loop. Rounded nodes are reads, boxes change something.
- Two output formats at once is refused. Both write to standard output, so
  emitting both would produce a file that is neither.
- Mermaid labels are escaped. A tool name carrying a quote or a bracket
  escaped its label and injected arbitrary graph syntax, and tool names reach
  the diagram from `scan`, which exists to read untrusted MCP catalogues.
  `scan` already quotes them when writing YAML; this is the same exposure in a
  second output.
- Every manifest spelling anchors at the tool it declares: block YAML, flow
  YAML in either key order, and JSON. Flow style was missed first, then found
  only when `name` came first, so `- { effect: read, name: pay }` still fell
  back. Searching the whole line for the key made a comma inside a quoted
  value look like a key boundary, inventing a tool out of
  `description: "a, name: b"`, so the reader tracks the quote state. The reader recognised only
  block YAML, so results on the other two fell back to line 1, which is not a
  missing answer but a wrong one, since line 1 is usually `version:`.
- A manifest inside the working directory gets a relative URI. Code scanning
  resolves the URI against the repository root, so an absolute path attached
  the finding to nothing.

- `mandate drift manifest.yaml --source src/agent` compares the declared
  mandate against the implementation. A manifest is a claim, and two things
  quietly falsify it: somebody adds a tool to the agent's list and nobody
  edits the YAML, or a signature changes and the argument a ceiling was
  counted against stops existing. Neither looks like a permission change in
  review.
- The direction of the error decides the ordering. A tool the agent has and
  the mandate omits comes first, because it means every clean `reach` report
  so far described a smaller graph than the real system. A tool the mandate
  declares and the agent no longer has still fails, because a gate reporting
  breaches nobody can reach is a gate somebody switches off.
- A `value_arg` or `scope_key` that no longer names an argument the tool takes
  is reported. The manifest still parses and the analysis still runs, so
  nothing else reveals that the ceiling is counted against nothing. A
  `scope_key` an argument carries, such as `case` against `case_id`, is not
  reported, since a false finding on every well-formed manifest would make the
  command useless.
- A tool list the read cannot enumerate is a finding rather than a clean pass.
  Reporting no drift from evidence that could not see the whole list would be
  the false assurance this package exists to prevent.
- Selecting a binding by a label two agents share is refused. A label is a
  variable name and `agent` is the most common one there is, so
  `--binding agent` silently merged two different agents, which is the
  overstatement `--binding` exists to escape reintroduced through the escape
  hatch itself. Disambiguate by location instead, which the message shows.
- `drift --json` gives every finding a `subject` field beside `tool`. They
  hold the same value for a finding about a tool. They differ for the
  withheld-removals note, which is about the report rather than about a tool:
  `subject` carries the `<removals>` sentinel and `tool` is `null`, so a
  consumer reading `tool` never gets a name no manifest could declare. This
  is a new field on a command introduced in the same release, so nothing
  downstream can already depend on the older shape, but a reader diffing JSON
  between builds will see it.
- A withheld removal check is named rather than dropped silently. Suppressing
  it is right; doing it quietly would leave a reader who resolves the
  unreadable part meeting findings that look new and were only withheld.
- An unenumerable list also suppresses removals. A removal claims a tool is
  absent from the agent list, and that claim cannot be made about a list the
  read could not see into: the tool may be in the part it missed.
  `tools=[a] if flag else [a, b]` reported two removals beside the unresolved
  finding, which asserted something positive from evidence already flagged as
  unreadable. Undeclared tools still report, because a tool seen bound and not
  declared is real whatever else was missed.
- The report names which tool list the source side came from. `diff` refuses
  outright to compare two different agents; this cannot, because nothing in
  source states the agent's declared name, so identity cannot be established.
  Naming the binding is what lets a reader see the comparison was against the
  agent they meant.
- `Declaration` carries the agent-facing argument names, which is what the
  argument check reads.

### Changed

- The roadmap describes 0.7.0 rather than 0.3.2, names what each command
  establishes, and says plainly what is not planned.
- The README links
  [agent-release-gate](https://github.com/mrwersa/agent-release-gate), a
  worked example that runs every command here against one agent, offline.

## 0.6.0 - 2026-07-31

### Added

- `mandate scan --source` derives a manifest skeleton from agent code. `scan`
  previously needed an MCP `tools/list` catalogue, which a team only has if
  they run an MCP server, so most agents had no way to get a starting
  manifest at all.
- Recognises `@tool`, `@function_tool`, and `@ai_function` across LangChain,
  LangGraph, Strands Agents, the OpenAI Agents SDK, the Microsoft Agent
  Framework, CrewAI, and FastMCP. Matching is on the trailing name of the
  decorator rather than the import path, because every framework is imported
  differently and half of them are aliased at the import site. A renamed
  import such as `from strands import tool as strands_tool` is resolved back
  to the name it was imported under.
- The read is static. Nothing is imported, nothing is executed, and the
  framework does not need to be installed. A review runs on a branch whose
  dependencies are absent and whose side effects must not happen, and
  importing a module to learn what it is permitted to do has already done it.
- One manifest describes one agent. The inventory is the tools that agent was
  given, read from `tools=[...]` and `.bind_tools([...])`, and a declared but
  unbound tool is excluded and named. `reach` searches whatever graph it is
  given, so a manifest holding two agents' tools produces compound paths no
  single run could take, and a gate reporting breaches nobody can reach is a
  gate that gets switched off.
- A source building more than one agent is refused, naming each one and where
  it is built, until `--binding NAME` says which is meant.
  `--union-bindings` merges them for the case where they genuinely share
  authority, and labels the output so a later reader knows.
- `Agent(tools=[])` is refused. An empty list means the agent has no tools,
  and listing every declared tool there would grant authority the source
  explicitly withholds. No `tools=` list at all is different: nothing was
  said, so every declaration is offered and the file says the list has not
  been narrowed.
- Only a constructor known by name is read as a binding. A `tools=` keyword
  on any function used to decide the inventory, so an unrelated
  `render_panel(tools=[...])` could rewrite what the agent was said to hold.
  A word test replaced that and was still too loose, since `workflow_graph`
  and `team_dashboard` both matched it, so the constructors are named one by
  one. An unlisted callee is not dropped, it becomes a candidate `--binding`
  selects, so an incomplete list costs one flag rather than a wrong manifest.
- The module a reference came through decides which declaration it means.
  Two modules declaring `refund` is ordinary, and picking whichever file
  sorted first attributed one agent's signature, scope, and ceiling to
  another agent's tool. A name that genuinely could be either is reported and
  neither is used.
- A tool decorator imported from somewhere unrecognised is included and then
  questioned by name, since re-exporting a framework decorator through a
  local module is common but `@tool` from anywhere means nothing on its own.
- What the read could not enumerate is reported at the top of the file:
  `tools=load_tools()`, a starred element, a bound tool declared outside the
  scanned path, a second binding whose union would overstate what one agent
  reaches, and a file that would not parse. Each note says why it matters,
  which for a missing tool is that the next `diff` reports it as authority
  that was never added.
- Annotations narrow the guesses. `Decimal`, `int`, `float`, `Optional[float]`
  and `Annotated[float, ...]` read as numeric, so a `str` argument called
  `amount` is not proposed as a value argument. An untyped argument stays a
  candidate, because no annotation is no evidence either way.
- Framework plumbing is excluded from the signature. `self`, `ctx`,
  `tool_context`, and anything annotated `...Context` or `...ContextWrapper`
  are not agent input, and reading them would invent a scope out of a
  callback handle.
- `docs/inventory.md` and a runnable `examples/refund_agent.py`.

## 0.5.1 - 2026-07-31

### Fixed

- `agentmandate.__version__` reported `0.4.0` in the `0.5.0` release. The
  number lived in `pyproject.toml` and in `agentmandate/__init__.py`, the
  release checklist said to edit both, and only one was edited. The package
  now declares a dynamic version read from `agentmandate/__init__.py`, so
  there is one literal and the two cannot disagree.
- The `0.5.0` changelog described errored spans as excluded because "an
  errored call produced no effect". That was the reasoning the release itself
  corrected. An errored effect-bearing call is carried as incomplete evidence.

### Changed

- Releases are now cut by merging the version bump. The release notes come
  from that version's changelog section, so the prose is written once rather
  than once there and again by hand in the GitHub Release.
- The release runs when CI finishes on `main` and only when it succeeded, not
  when the push happens. A push-triggered release runs beside the CI it is
  supposed to depend on, so it could publish a commit whose tests were still
  running or had already failed, and it reads the version from the exact
  commit that passed.
- Artefacts are built and checked before the tag and the GitHub Release are
  created. Tagging first leaves a public release behind whenever a build or an
  upload fails, which is a version users can see and cannot install.
- The workflow takes a repository-wide lock, so two merges landing together
  cannot both decide the same tag is free and race to create it. Ordering is
  handled separately: CI runs finish in whatever order they finish, so only a
  commit that is still the tip of `main` releases, and anything landing on top
  releases itself. Releasing a commit that is no longer the tip would publish
  an older version after a newer one.
- The decision is keyed on whether a GitHub Release exists, not on whether the
  tag exists. A run that pushed the tag and then failed before creating the
  release used to read as finished on the next attempt, stranding a version
  with a tag and nothing published. Tagging is now resumable, and a tag
  pointing somewhere other than the commit being released is a hard error.
- The release build checks the built wheel and sdist filenames against the
  tag, because the artefact users install is the thing worth checking.

## 0.5.0 - 2026-07-31

### Added

- `mandate verify --otel trace.json` reads OpenTelemetry traces directly.
  `verify` is the command that keeps a manifest honest and it previously
  needed a bespoke JSON Lines file nobody had, while every team already has
  traces.
- `gen_ai.operation.name`, `gen_ai.tool.name`, and span start time are read
  automatically. The fields a mandate needs that no GenAI convention carries,
  which are scope, value, currency, principal, and approval, each require an
  explicit `--map`. Nothing is guessed.
- An unmapped trace fails closed and names the fields, because a trace that
  does not record the approval has not established that the approval held.
- The conversion summary prints before the verdict. Three observations
  recovered from four hundred spans is usually a mapping mistake, and a clean
  report over almost no evidence should not read as success.
- `--emit` writes the converted observations in the plain replay format for
  inspection, and re-running them through `--traces` gives identical results.
- Spans are ordered by start time, because cumulative ceilings accumulate in
  call order rather than collector write order.
- Each `traceId` is verified as its own run. An OTLP export can hold many
  traces, and a cumulative limit bounds one run, so replaying a whole export as
  one sequence reported a breach that neither run committed. Duplicate
  detection is scoped per trace for the same reason.
- An errored effect-bearing call is carried as incomplete evidence and produces
  an `errored_effect` finding. OpenTelemetry's error status means the operation
  ended with an error, not that an irreversible effect failed to commit, and a
  timeout is exactly the case where the write may already have landed. Its
  value is not accumulated, because whether it was spent is what the evidence
  fails to establish. An errored read produces no finding.
- `Observation` gains `errored`, so the replay format can express the
  distinction and an emitted file re-runs identically.
- Strict by default. A span carrying `gen_ai.tool.name` with no operation
  attribute is no longer treated as an execution, because the convention
  requires both. `--lenient-tool-spans` restores the old behaviour for older
  instrumentation.
- Newline-delimited OTLP requests are accepted, which is what OpenTelemetry's
  file exporter writes.
- `--json` returns a versioned object carrying the conversion counts alongside
  the conformance result, so CI sees the warnings rather than only the verdict.
- `--map`, `--emit`, and `--lenient-tool-spans` are refused with `--traces`
  rather than silently ignored.
- Spans that would produce a false ceiling breach are excluded and counted: a
  span whose operation is not `execute_tool` even when it carries a tool name,
  and a repeat of a `gen_ai.tool.call.id` already seen. Instrumentations
  commonly attach the tool name to the chat span that requested the call, and
  one call instrumented at both client and server is still one call.
- `docs/traces.md` and a runnable `examples/otel-trace.json`.

### Changed

- `verify` now requires exactly one of `--traces` or `--otel`, so a run cannot
  silently verify a different file from the one intended.

## 0.4.0 - 2026-07-30

### Added

- `mandate scenarios` exports each reachable breach as a versioned, structured
  scenario-test skeleton. It preserves the counterexample while leaving the
  environment, agent input, and expected control boundary for human review.
- Reviewed scenario fields reconcile against the current reachable witnesses.
  Disappearing paths are removed and newly reachable paths return unreviewed.
- An evaluation-loop guide separates permitted reachability, observed agent
  behaviour, per-call enforcement, and runtime conformance.

### Changed

- The README and test-obligation guide connect decision-point obligations to
  AgentVerity and compound paths to external scenario evaluators without
  turning AgentMandate into a runner.

## 0.3.2 - 2026-07-28

### Changed

- The README scopes every finding to permitted reachability under the reviewed
  manifest and bounded abstraction, rather than observed model behaviour or
  undeclared downstream enforcement.
- The roadmap makes external tool-graph validation a prerequisite for model
  growth, then ranks bounded cardinality, reviewed resource relationships, and
  non-monetary effect budgets as evidence-dependent candidates.

## 0.3.1 - 2026-07-28

### Changed

- The README opens with the compound-authority problem in plain language and
  separates per-call policy, reviewed decision evidence, and runtime-control
  evidence without weakening their boundaries.

## 0.3.0 - 2026-07-28

### Added

- `mandate obligations` derives reviewable test obligations from the authority
  a manifest actually makes reachable: irreversible effects, approval gates,
  service-account principals, and value-bearing calls. A tool nobody can reach
  produces no obligation, because listing it would pad a review with work that
  protects nothing.
- `--reviewed` accepts an obligations file whose decisions have been mapped by
  a human, and `--suite` renders those into an `agentverity.decision-suite/v1`
  skeleton that AgentVerity loads directly.
- `docs/test-obligations.md` walks the whole path, including what deliberately
  does not cross it.

- `README` and `DESIGN` name Policy in Amazon Bedrock AgentCore alongside the
  other enforcement tools, and say precisely where it stops: the engine
  evaluates all applicable Cedar policies for one invocation, while its
  documented analysis is policy-level. Neither models a sequence of permitted
  calls or a release-to-release comparison of reachable authority.

### Fixed

- `--reviewed` reconciles against the live manifest by stable identifier
  instead of replacing it. A stale or unrelated review previously generated a
  suite for authority the agent no longer had, which is the drift this package
  exists to catch.
- A generated suite carries probes the reviewer wrote. It previously shipped
  `REVIEW:` placeholder inputs that AgentVerity accepted and ran, producing
  numbers about nothing. An obligation now needs both a decision and at least
  one probe before it counts as reviewed.
- A malformed reviewed file produces a usage error rather than a traceback.

### Notes

- Decisions are never invented. An effect class such as `irreversible on case`
  is an authority fact; a decision such as `refund_approved` is an application
  label somebody chose. No parsing turns one into the other, so the command
  exits non-zero until every row carries a reviewed decision.
- Compound breaches do not cross the bridge. A cumulative-value path is a
  multi-call sequence, which is scenario testing rather than decision coverage.

## 0.2.0 - 2026-07-28

### Added

- Tests for every control the fail-closed work introduced. The diff rules for
  effect-class changes, `unbounded` flips, produced-scope changes, ceiling
  add and remove, extractable-value appearance and disappearance, and a
  declared workload identity all shipped without one, and an untested
  widening rule is a gate that might not be there.

### Changed

- The coverage floor is 100%, up from 90%. The package was at 100% and drifted
  to 97% in a single change without CI noticing, and the lines that slipped
  were the new controls rather than incidental code.

### Fixed

- `verify` now rejects malformed trace fields and reports missing principal,
  scope, value, or currency evidence instead of silently treating an
  incomplete record as conformant. Empty traces no longer pass vacuously.
- `diff` now compares run limits and reachable tool contracts, including
  preconditions, approvals, effects, ceilings, produced scopes, and unbounded
  minting. Cross-currency amounts are sent for review rather than compared as
  bare numerals.
- `diff` now searches both releases at one depth, blocks reductions to the
  manifest's default search depth, rejects comparisons between different
  agents, and reports workload-identity or value-argument changes.
- `scan` now quotes catalogue-derived YAML scalars, flattens untrusted
  descriptions to comments, and rejects duplicate or control-character tool
  names.
- Manifest parsing now rejects non-finite amounts, string-valued booleans,
  empty scope names, and Boolean search depths, and wraps JSON or YAML parser
  failures as `ManifestError`.

### Documentation

- The README now opens on the worked payment-dispute path and includes a
  diagram showing how a read-only case search makes two valid refunds
  reachable.
- `ROADMAP.md` separates adoption work from planned extensions to the
  authority model.

## 0.1.0 - 2026-07-28

First release.

### Added

- `mandate reach`, a bounded breadth-first search over the authority graph that
  reports a legal call sequence breaching a declared limit, as a counterexample
  rather than a score.
- `mandate diff`, a comparison of the effective authority of two manifests,
  classified widening, narrowing, or neutral, exiting non-zero on widening.
- `mandate lint`, single-manifest control checks covering separation of duties,
  ungated irreversible effects, service-account principals, ceilings scoped to
  something the tool does not require, and mixed currencies.
- `mandate verify`, replay of recorded tool calls against the manifest,
  reporting undeclared tools, exceeded ceilings, missing approvals, wrong
  principals, and run totals.
- A manifest schema carrying the three facts an ordinary tool schema omits:
  effect class, the value-bearing argument, and the scope a ceiling is measured
  against.
- Worked examples for a payment-dispute agent, including the release pair where
  adding one read-only tool takes extractable value from 500 to 2000 GBP.
- `--json` on every analysis command, and exit codes suitable for a CI gate.
- `mandate scan`, which derives a manifest skeleton from an MCP `tools/list`
  catalogue. Effects are guessed from the tool name and default to
  `irreversible`, and every guess carries a `REVIEW` marker, because a tool
  schema cannot supply reversibility, the value argument, or the scope a
  ceiling is measured against.
- A second breach class in `reach`: an irreversible effect reachable with no
  approval is now reported with the call sequence that reaches it, rather than
  only as a name in the authority summary.
- `mandate diff --record`, a markdown change record for a change advisory
  board, with the authority section derived rather than asserted.
- A `currency_mismatch` violation in `verify`, so a call spending one currency
  against a ceiling declared in another is reported rather than silently summed.
- Status badges, an exit-code table, and the pull-request workflow snippet for
  gating on an authority diff against the default branch.
