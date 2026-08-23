# Evidence Metric Review

Status: **evidence-diversity gate passed; scanner precision remains open**.
This review resolves the stale Foundation criterion that required four real
graphs “with reviewer notes and at least one clean result.” It does not
reclassify any existing extraction as clean.

## Decision

Split the criterion into two independent measures:

1. **Evidence diversity** asks whether enough materially different, reproducible
   graphs have challenged the authority model. This is complete.
2. **Scanner precision** asks how much safe reviewer correction generated
   skeletons require. This remains an ongoing quality measure, not evidence
   that the model has—or has not—seen enough domains.

A correction-free extraction was a poor proxy for either outcome. Catalogue
and source scanners cannot recover deployment policy, credential ownership,
conditional argument meaning, or hidden runtime inventory from names and
signatures alone. Requiring one “clean” graph rewards selecting a simple input.
Worse, a skeleton may need no correction because uncertainty was missed. The
repository must not equate silence with precision.

## Reassessed evidence set

| Graph | Material review correction | Classification | Result |
|---|---|---|---|
| Coinbase AgentKit | Initial evidence included providers the selected example never wired; name collision and invented producer anchors remained visible | completeness, model gap, deployment policy | Dynamic-inventory declarations delivered; bounded producers and relationships retained as evidence-gated work |
| GitHub MCP | Bearer IDs were guessed as minted scopes; reversible writes were overclassified; workflow production depended on an argument value | source ambiguity, heuristic precision, model gap | Non-monetary effect budgets shipped; conditional producers remain explicit roadmap evidence |
| AWS PostgreSQL MCP | SQL effect, service principal, bearer job ID, and multi-output behavior required correction | source ambiguity, identity/model gap | Conditional authority shipped; intersecting principals, resource binding, and multi-output remain visible |
| Sentry MCP | Bearer references, result limits, fixed user credentials, and a hidden dispatch meta-tool required correction | hidden inventory, source ambiguity, identity/model gap | Partial dynamic inventory and conditional-dispatch limits remain fail-closed; no clean result was manufactured |

These are not four instances of one scanner defect. They distinguish four
classes that future evidence must continue to name:

- **extractor defect:** a deterministic source fact was available but parsed
  incorrectly;
- **source ambiguity:** the captured interface did not contain the semantic
  fact, so review must remain mandatory;
- **model gap:** the reviewed fact could not be represented without distortion;
- **deployment policy:** the control was external intent and must never be
  inferred from implementation.

One correction may belong to more than one class. Classification records why
it exists; it does not turn a heuristic into an exact fact.

## Replacement gates

The evidence-diversity initiative passes only when every graph has:

- a published, version-pinned subject and reproducible or digest-pinned capture;
- an explicit deployment and completeness boundary;
- preserved raw inventory or scanner skeleton beside the reviewed manifest;
- every material correction enumerated and classified;
- at least one understandable counterexample, limitation, or authority-shape
  consequence linked to a shipped change or a named roadmap prerequisite.

All four committed graphs meet this gate across a financial framework, a code
and CI platform, a data system, and a SaaS operations system. The initiative is
therefore delivered. The synthetic conditional fixture does not count toward
this total.

Scanner precision is tracked separately through:

- exact-output fixtures, so heuristic changes cannot silently rewrite evidence;
- correction ledgers, so review burden cannot disappear from the record;
- regression tests or issues for corrections claimed to be mechanically
  solvable;
- cross-fixture improvement: a correction class is improved only when it is
  removed without suppressing uncertainty or worsening another committed
  graph.

There is deliberately no target of “one clean graph.” No current graph is
clean, and scanner precision is not marked complete. Future work may introduce
a labeled correction-rate benchmark once the repository has enough comparable
captures; it must separate policy review from extractor error.

## Consequence for Foundation

The real-graph initiative is delivered under the replacement evidence gate.
This does not close Foundation as a whole: import experiments remain deferred
pending real user pull, and the roadmap continues to state that explicitly.
It also does not relax the rule that new model features require a real graph
and understandable counterexample before becoming defaults.
