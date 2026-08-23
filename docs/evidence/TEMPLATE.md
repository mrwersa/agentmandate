# {Subject} evidence: {one-sentence authority finding}

State the authority question this graph tests and why the result matters. Say
whether it exposes an extractor defect, source ambiguity, model gap, or
deployment policy boundary; do not lead with a product description.

## Evidence boundary and provenance

- **Subject:** `<published package/project and exact version>` with a link,
  publication date, license, and registry integrity or artifact SHA-256.
- **Source:** `<tag or full commit>` with a link. Explain any difference from
  the published artifact.
- **Deployment profile:** `<enabled features, identity, selected providers,
  tenant/resource bounds>`. Mark reviewed assumptions that the source does not
  establish.
- **Inventory boundary:** `<complete or partial, and for which relation,
  selection, binding, and producer revision>`. A verified digest proves bytes,
  not completeness.

## Capture and safety

List prerequisites with exact versions and give commands that reproduce the
raw inventory. Record its filename and digest. State explicitly:

- whether capture imports or executes upstream code;
- every network or live-infrastructure interaction;
- how telemetry, credentials, customer data, account IDs, and real trace IDs
  were excluded; and
- which dependencies or lock files pin the capture environment.

Use placeholders only. If safe recapture is impossible, commit digest-pinned
raw output and document the missing step rather than claiming reproducibility.

```console
$ {capture command}
$ mandate scan docs/evidence/{subject}/catalogue.json --agent {agent-name}
```

Preserve generated output as `scan-skeleton.yaml`; keep human review in
`mandate.yaml`. If another collector format applies, name both files clearly.

## Review corrections

Enumerate every material difference between the raw/generated artifact and the
reviewed manifest. For each one, state the evidence and use one or more of:

1. **Extractor defect:** a deterministic source fact was available but parsed
   incorrectly. Link a regression test or issue when mechanically solvable.
2. **Source ambiguity:** the captured interface did not contain the semantic
   fact, so human review remains mandatory.
3. **Model gap:** the reviewed fact cannot yet be represented without
   distortion. Link the roadmap prerequisite or issue.
4. **Deployment policy:** the value is external intent and must not be inferred
   from implementation.

If review found no corrections, list what was checked and remaining unknowns.
Do not call the extraction clean merely because the scanner was silent.

## Result and consequence

Show the smallest understandable `mandate reach`, `lint`, or `drift` result.
Explain what authority shape or limitation it demonstrates, then link each
material outcome to one of:

- a shipped behavior and its test or review;
- an open roadmap prerequisite or issue; or
- an explicit decision that no product change is justified.

State non-goals: capabilities this evidence does not establish and actions the
analyzer must not take. Synthetic examples may supplement this package but do
not turn it into real evidence.

## Submission checklist

- [ ] Subject, source, deployment, and completeness boundaries are explicit.
- [ ] Raw inventory, scanner output, reviewed manifest, and capture pins are
  present or any omission is explained.
- [ ] Digests reproduce and capture commands are safe and documented.
- [ ] Every correction is enumerated, classified, and linked to evidence.
- [ ] The result is reproducible and its consequence is named.
- [ ] No secret, customer datum, account identifier, or real trace identifier
  is present.
- [ ] Tests pin claims that could silently regress.
