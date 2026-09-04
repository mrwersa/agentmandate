# Documentation map

Start with the [project overview](../README.md) for the problem, a working
counterexample, installation, and the command summary. The pages below serve
different purposes. A contract page describes a current or experimental data
boundary. A gate review records why a public surface was exposed or deferred.
An evidence page records what was observed and must not be read as a product
guarantee.

## Use AgentMandate

- [Manifest reference](manifest.md): declare one reviewed mandate.
- [Source and catalogue scanning](inventory.md): derive a manifest skeleton
  without importing agent code.
- [CI integration](ci.md): exit codes, GitHub Actions, SARIF, and rollout.
- [Runtime trace verification](traces.md): replay JSON Lines or OpenTelemetry
  evidence against a mandate.
- [Test obligations](test-obligations.md) and the
  [evaluation loop](evaluation-loop.md): connect authority analysis to external
  agent evaluation without confusing permitted paths with model behaviour.

## Understand the model

- [Design](../DESIGN.md): the authority model, search boundary, and non-goals.
- [Authority IR](authority-ir.md): canonical provenance and the reviewed
  manifest-v1 analysis profile.
- [Stability](../STABILITY.md): supported public surfaces and versioning.
- [Roadmap](../ROADMAP.md): delivered, active, evidence-blocked, and later work.

## Reviewed evidence attachments

These public CLI surfaces validate structure separately from eligibility to
change an analysis result:

- [Dynamic inventory](dynamic-inventory.md)
- [Conditional authority](conditions-delegation.md)
- [Delegation chains](delegation-v2.md)
- [Managed Cedar evidence](cedar-import.md) and
  [effective policy revision comparison](cedar-effective-diff.md)
- [Finite producer cardinality](bounded-producers.md)

[Authority continuity](authority-continuity.md) remains private and
experimental. It asks whether consumed state remains attached to one reviewed
mandate across a session, handoff, or policy revision. A session identifier is
evidence for that question, not the mandate itself.

## Decision records and evidence

Files ending in `-gate-4-review.md`, `-gate-5-review.md`, or `-audit.md` are
dated decision records. They preserve acceptance criteria and negative results;
they are not the shortest route to using the current CLI.

The [evidence index](evidence/README.md) separates captured source material,
reviewed corrections, synthetic fixtures, and analysis results. Synthetic
fixtures establish implementation behaviour, not operational deployment facts.
