# Authority Evidence

Each directory here records a real authority graph: what an upstream system
published, what AgentMandate inferred, what review corrected, and what the
result changed or left unresolved. These packages challenge the model; they are
not endorsements or deployment-ready policies.

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
regenerate all three canonical continuity profiles from their digest-pinned
AgentCore and Anthropic sources and compare them byte for byte. The command
proves replay and source identity; it does not promote their review state.

The IAM producer evidence converter is likewise repository-only. Run
`python scripts/migrate_producer_evidence.py` to regenerate the canonical IAM
boundary from its digest-pinned catalogue, sanitized capture, and adapter and
compare it byte for byte. The migration remains `unreviewed`.

Delegation's superseded grant-v1 reader and evidence converters are also
repository-only. Run `python scripts/migrate_delegation_evidence.py` to replay
both the legacy grant chain and the real Authorizer chain against their
canonical fixtures and verify their declared source bytes.

`probes/` is the exception: it contains shaped, synthetic questions that may
expose a design problem but cannot justify a schema or roadmap claim by itself.
