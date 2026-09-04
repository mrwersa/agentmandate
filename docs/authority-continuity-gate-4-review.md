# Authority Continuity Gate 4 Review

Status: **review complete; public exposure deferred**. This review was
performed against merged commit `fff91d0` on 3 September 2026. Gates 1 through
3 establish strict private artifacts, separate closed Authority IR profiles,
and fail-closed reconciliation. They do not yet establish a stable public
result or command contract.

A provider session is not a mandate. A session identifier, policy revision,
or provider budget can identify observed enforcement state, but only an
eligible binding can join that state to the reviewed mandate whose consumed
authority is being assessed. Structural validity and digest identity do not
establish that join.

## Decision summary

| Review | Verdict | Evidence or remaining condition |
|---|---|---|
| Structural validation | Passed privately | Separate binding, AgentCore, and Anthropic v1 readers enforce exact fields, closed vocabularies, canonical values, safe locators, and typed failures |
| Closed IR profiles | Passed privately | Every profile is regenerated and semantic-digest checked; general `reach --ir` rejects it as manifest authority |
| Provider-neutral reconciliation | Passed privately | The consumer re-reads artifacts, verifies caller bytes and review time, keeps manifest reachability unchanged, and reports state, authority change, admission, and four alignment checks separately |
| Conservative failure | Passed privately | Unreviewed, expired, mismatched, unbound, source-invalid, or mediation-incomplete evidence remains unresolved beside full manifest authority |
| Mandate binding | Partial | The AgentCore path has a digest-bound signed-binding evaluation, but migration remains unreviewed and the zero-dependency core intentionally does not perform Ed25519 verification; Anthropic has no provider-native mandate join |
| Safe-continuation semantics | Passed privately | Each outcome now keeps comparability, issuer-amendment state, and a three-valued verdict separate; tightening can satisfy the property, while missing joins, comparison, amendment treatment, or required alignments remain unresolved |
| Accepted clean fixture | Passed synthetically | A complete fixture explicitly labels its mandate, binding, boundary, provider control, reviewer, and sources as synthetic; both real migrations remain `unreviewed` |
| Presentation stability | Passed privately | `agentmandate.continuity/v1` has a strict canonical reader, checksum, closed finding-code registry, complete input identities and manifest Authority, and eight canonical state fixtures |
| Composition boundary | Open | IR is rejected by the private profile boundary, but no public pre-I/O refusal matrix exists for SARIF, Mermaid, OTel, conditions, delegations, producers, or Cedar analyses |
| CLI failure behavior | Open | No public parser, renderer, explicit input pairing, exit-code tests, or complete-output/no-partial-output tests exist |

## Closing verdict

**Keep authority continuity private.** The private consumer is suitable for
challenging the model and replaying the two evidence families, but exposing it
now would make internal dataclass fields and dynamically constructed finding
codes an accidental compatibility contract. More importantly, it would ask a
caller to infer safe continuation from three axes that are intentionally
independent.

The next work is composition and CLI boundary review, not another provider
experiment. Public exposure can be reconsidered after the CLI proves both
exit-0 and exit-1 paths and refuses compositions that cannot preserve
uncertainty. Manifest version 1, ordinary reachability, and the public Python
API remain unchanged.

## Semantics reproduced by the review

The private consumer canonicalizes and strictly rereads each provider record
and optional binding, projects and validates the matching closed IR profile,
verifies exact caller-supplied source bytes, and evaluates eligibility at a
caller-supplied whole-second UTC timestamp. Trust failure makes all affected
axes unresolved and retains the baseline `Authority`.

The AgentCore matrix distinguishes same-boundary preservation from fresh or
revised boundaries. Early fresh-session and alpha-equivalent-revision captures
remain unresolved because they do not establish one mandate across the
transition. The later signed binding supports the narrower joined experiment
and reports reset, widening, and overshoot independently. An exclusive adapter
is still conditional evidence, not proof of complete mediation.

The Anthropic matrix preserves one accumulated total in sequential and
parent/child observations, reports independent capacity across fresh sessions,
and reports completed concurrent usage above the configured cap. Its study
identity supports comparison of the captured transitions, but it does not make
the managed session a reviewed mandate or establish complete mediation.

These are scoped observations, not universal provider claims. Overshoot is an
admission outcome rather than a vulnerability verdict, and completed-event
telemetry does not prove reservation of in-flight work.

## Safe-continuation contract implemented privately

The private result no longer uses three-axis equality as shorthand for all
continuity claims. Each outcome carries `comparability`, `issuer_amendment`,
and a per-transition `safe_continuation` value closed to `satisfied`,
`violated`, or `unresolved`. The aggregate `clean` property consumes only that
explicit verdict and the complete finding set.

For the current scalar profile, a satisfied verdict requires an eligible
same-mandate join, comparable reviewed before/after limits, state that is
preserved or conservatively translated, no overshoot, and every alignment
required by the claim established at an accepted strength. A reviewed
tightening can be safe because the successor may be more conservative; a
widening is not safe merely because consumed state was preserved. Reset,
missing comparability, incomplete mediation, an expired binding, or an issuer
amendment whose treatment of predecessor state is unknown leaves the verdict
violated or unresolved according to the reviewed contract.

The private derivation now tests stable, tightening, widening, reset,
overshoot, approved-amendment, conditional-alignment, and unresolved cases.
An unchanged reviewed boundary can establish comparability without an
amendment. Changed boundaries remain unresolved because the current artifacts
carry neither reviewed comparability nor issuer-amendment treatment. “Same
boundary” no longer establishes derivation integrity without an eligible
same-mandate binding. `platform_verified` mediation can establish isolation and
complete mediation; an exclusive adapter remains conditional.

This completes the semantic prerequisite, not a public exit code. The explicit
synthetic fixture now reaches `satisfied`, but no serialization contract
exposes the new fields yet.

## Accepted-fixture requirement satisfied synthetically

Byte-exact migrations prove which committed captures were interpreted. They do
not supply an accountable reviewer, review lifetime, or provider-native mandate
binding. The older tests replace evidence metadata in memory to exercise Gate
3; that remains a unit-test control rather than a public clean-path claim.

The accepted synthetic fixture now includes:

- mandate bytes and identity;
- a binding, provider record, and every declared source byte;
- a transition with comparable limits and a stable or tightening successor;
- evidence sufficient for every alignment required by its claim;
- an explicit evaluation time within all half-open validity windows; and
- an expected `satisfied` safe-continuation result.

`tests/fixtures/continuity-accepted-synthetic/` pins those bytes and identities.
Private analysis strictly rereads both records, regenerates both IR profiles,
verifies all source bytes and the mandate digest, checks the evaluation time,
and produces one `preserved`/`stable`/`within_bound` transition with established
comparability, no required amendment, all four alignments established, no
findings, and `safe_continuation: satisfied`.

The fixture also proves that provider-control and binding mediation must match;
changing one side from `platform_verified` to `exclusive_adapter` makes the
join unresolved. The real AgentCore and Anthropic migrations remain unreviewed
canonical finding paths and are not promoted retrospectively.

## Presentation contract implemented privately

The versioned canonical `agentmandate.continuity/v1` result includes:

- evaluation time and complete manifest `Authority`, including depth and
  truncation;
- manifest, binding, provider-profile, and transition identities with content
  and semantic digests sufficient for offline replay;
- each alignment check with status, evidence strength, and support;
- state-continuity, authority-change, and admission axes without collapsing
  them into one label;
- reviewed comparability, safe-continuation verdict, and explicit assumptions;
  and
- findings with stable machine-readable codes and complete provenance.

The strict reader enforces exact fields, types, ordering, closed vocabularies,
canonical UTC time, complete Authority shape, semantic identities, and an
envelope checksum. Canonical fixtures cover satisfied, reset, widened,
tightened, overshot, unresolved, untrusted, and truncated results. The result
is presentation only and is never accepted as authority input. Its Python
records and schema remain private and unsupported.

Human output must show manifest authority separately from transition outcomes
and assumptions. A finding exits 1 only after complete human or JSON output.
Malformed structure, invalid time, incomplete option groups, conflicting
source mappings, or unsupported composition exits 2 with empty stdout.

## CLI boundary to review

The eventual surface should follow the existing validate-then-consume pattern,
but this sketch is **not approved syntax**:

```text
mandate continuity validate ARTIFACT
mandate continuity reconcile MANIFEST \
  --continuity-provider PROVIDER_RECORD \
  --continuity-source LOCATOR=CAPTURE \
  --continuity-binding BINDING \
  --continuity-binding-source LOCATOR=CAPTURE \
  --continuity-as-of YYYY-MM-DDTHH:MM:SSZ
```

Validation would prove structure only. Reconciliation must reread and validate
the provider-specific profile, require exactly the source locators it declares,
pair an optional binding by explicit identity rather than argument position,
and require mandate bytes when a binding claims their digest. The command must
not accept a raw session identifier as evidence that two observations belong
to one mandate.

Provider-specific validation may ultimately need explicit artifact kinds or
subcommands because binding, AgentCore, and Anthropic records have independent
versions. That choice must be settled before command names become public.

## Composition decision

Until a combined consumer and schema exist, continuity reconciliation must be
refused before reading inputs or writing output with:

- `reach --ir`, because continuity profiles are evidence attachments rather
  than manifest Authority;
- SARIF and Mermaid, whose current models describe breach paths rather than
  lifecycle transitions and three independent axes;
- OTel replay, which cannot infer a mandate join or complete mediation from a
  trace or session identifier;
- conditional, delegation, and producer analysis, whose consumers transform
  or constrain reachability and cannot safely be chained with a separately
  rendered continuity result; and
- Cedar alignment or effective diff, which can establish reviewed request
  decisions but does not by itself establish preservation of consumed state.

Support later requires one consumer to validate all participating artifacts,
retain every unresolved finding, define a combined schema, and preserve the
distinction between request authorization, reachability, and continuity. One
rendered result must never be fed into another analyzer as authority.

## Exit conditions for reconsidering exposure

1. **Complete privately:** define and implement the per-transition
   comparability and safe-continuation contract, including stable, tightening,
   widening, reset, issuer-amendment, conditional-alignment, and unresolved
   tests.
2. **Complete synthetically:** commit an accountable or explicitly synthetic
   accepted fixture that reaches a genuine clean/satisfied path while leaving
   the real unreviewed migrations honest.
3. **Complete privately:** implement a strict versioned result envelope, closed
   finding codes, checksum, and canonical satisfied, reset, widened, tightened,
   overshot, unresolved, untrusted, and truncated fixtures.
4. Review a validate-then-consume CLI shape with explicit artifact identity,
   source pairing, binding requirements, UTC evaluation time, human and JSON
   rendering, exit 0/1/2, complete-output, and no-partial-output tests.
5. Refuse IR, SARIF, Mermaid, OTel, condition, delegation, producer, and Cedar
   composition before I/O unless a reviewed joint consumer preserves every
   uncertainty.
6. Reproduce byte-identical existing command output when no continuity inputs
   are supplied, keep the Python records private, and release any public CLI or
   schema as a user-visible minor version under `RELEASING.md`.

## Non-goals

This review does not add a manifest field, public Python record, runtime proxy,
session allocator, distributed counter, reservation protocol, cryptographic
library, provider query, policy-equivalence engine, or generic quantity
language. It does not claim that a session is a mandate, that a valid signature
proves complete mediation, or that a correct per-request decision proves
authority continuity.
