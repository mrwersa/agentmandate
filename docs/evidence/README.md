# Authority Evidence

This directory holds real authority graphs, provider and protocol captures,
and separately labelled synthetic probes. Graph packages record what an
upstream system published, what AgentMandate inferred, what review corrected,
and what remains unresolved. They challenge the model; they are not
endorsements or deployment-ready policies.

Protocol implementation captures are labeled separately. For example,
`authorizer-delegation/` proves the shape of issued delegation chains but has no
operational tool graph and does not count toward the real-graph diversity gate.

To contribute a graph, follow the repository's
[real-graph checklist](../../CONTRIBUTING.md#contributing-a-real-authority-graph)
and copy [TEMPLATE.md](TEMPLATE.md) into `docs/evidence/<subject>/README.md`.
Keep raw captures, generated scanner output, and reviewed manifests separate so
review never turns observation into intent silently.

Continuity's evidence-specific converters live outside the installed package.
Run `python scripts/migrate_continuity_evidence.py` from the repository root to
regenerate the canonical continuity profiles from their digest-pinned
AgentCore and Anthropic sources and compare them byte for byte. The command
proves replay and source identity; it does not promote their review state.

For the current status of each capture family, read
[continuity consolidation](../continuity-evidence-consolidation.md). Dated
capture READMEs describe what was available at capture time. Statements there
about missing public consumers, finite producers, or delegation should not be
read as the current package feature list; use [Stability](../../STABILITY.md).
The upstream README copies are retained byte-for-byte, including upstream links
that may not resolve inside this repository.

Two additional offline tools preserve distinct boundaries:

- `python scripts/project_principal_observations.py` reproduces both the archival
  principal observations and the separate unreviewed runtime profile. It does
  not accept those observations or authorize shared-mandate accounting.
- `python scripts/audit_capture_clocks.py` replays the six-file clock audit;
  see its [scope and limitations](../capture-clock-audit.md).

The IAM producer evidence converter is likewise repository-only. Run
`python scripts/migrate_producer_evidence.py` to regenerate the canonical IAM
boundary from its digest-pinned catalogue, sanitized capture, and adapter and
compare it byte for byte. The migration remains `unreviewed`.

Delegation's superseded grant-v1 reader and evidence converters are also
repository-only. Run `python scripts/migrate_delegation_evidence.py` to replay
both the legacy grant chain and the real Authorizer chain against their
canonical fixtures and verify their declared source bytes.

The three principal-v1 fixtures predate delegation attachment v2. Run
`python scripts/replay_principal_v1.py` to round-trip them and reproduce their
pinned Authority IR projections. Attachment v2 replaces the delegated-user
consumption path only; it has no equivalent for the historical fixed-user
credential or intersecting-principal shapes.

The native Cedar bundle is historical repository evidence rather than a
runtime input. Run `python scripts/replay_cedar_bundle_v1.py` to verify the
canonical document-cloud bundle digest, every declared source byte, and its
pinned Authority IR projection. Managed Cedar retains the shared mapping-v1
parser in the installed package.

`probes/` is the exception: it contains shaped, synthetic questions that may
expose a design problem but cannot justify a schema or roadmap claim by itself.
