# Authority Evidence

Each directory here records a real authority graph: what an upstream system
published, what AgentMandate inferred, what review corrected, and what the
result changed or left unresolved. These packages challenge the model; they are
not endorsements or deployment-ready policies.

To contribute a graph, follow the repository's
[real-graph checklist](../../CONTRIBUTING.md#contributing-a-real-authority-graph)
and copy [TEMPLATE.md](TEMPLATE.md) into `docs/evidence/<subject>/README.md`.
Keep raw captures, generated scanner output, and reviewed manifests separate so
review never turns observation into intent silently.

`probes/` is the exception: it contains shaped, synthetic questions that may
expose a design problem but cannot justify a schema or roadmap claim by itself.
