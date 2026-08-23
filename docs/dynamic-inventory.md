# Dynamic inventory declaration contract

Status: **Gate 4 candidate**. A v1 reader, dedicated Authority IR inventory
profile, and drift reconciliation implement gates 1–3 against canonical
AgentKit and Sentry fixtures. `inventory validate` and explicit `drift` inputs
now expose the proposed public boundary for review. Parsing never makes an
inventory trustworthy.

## Problem boundary

Static source reading can prove that `Agent(tools=[search, refund])` contains
two tools. It cannot enumerate `Agent(tools=provider.for_tenant(config))`, a
registry populated by plugins, or Sentry's skill-filtered catalogue behind a
dispatch tool. Importing the application to ask would execute the code under
review and could perform arbitrary side effects.

A dynamic inventory declaration is a reviewed claim about one such boundary.
It lets `drift` compare a captured member set with the agent's declared
authority while preserving why the static read stopped. It is not permission,
discovery, or proof that an upstream system told the truth.

## Candidate artifact

The declaration is a separate, versioned JSON artifact. Keeping it outside the
mandate prevents observed inventory from becoming reviewed intent merely by
parsing. A candidate v1 body contains:

```json
{
  "inventory_version": 1,
  "boundary": {
    "id": "refund-provider",
    "kind": "provider",
    "target": {
      "source": "src/agent.py",
      "binding": "resolver"
    }
  },
  "selection": {
    "environment": "production",
    "provider": "case-management"
  },
  "source": {
    "kind": "provider-capture",
    "locator": "inventory/refunds-production.json",
    "format_version": "1",
    "producer": "case-management-provider",
    "producer_version": "2026.08",
    "content_sha256": "..."
  },
  "membership": {
    "relation": "contains_tool",
    "completeness": "complete",
    "members": ["issue_refund", "search_cases"]
  },
  "evidence": {
    "confidence": "exact",
    "review": "accepted",
    "reviewer": "security-platform",
    "expires": "2026-11-23"
  }
}
```

This v1 shape is exercised by canonical fixtures and a strict private reader.
It remains experimental until reconciliation and public-CLI review establish
its trust behavior. Fields have the following intended semantics:

- `boundary.id` is a stable, reviewer-chosen identifier. It must not depend on
  a line number. `kind` is a closed vocabulary: `factory`, `provider`,
  `registry`, or `deployment`. IDs are unique within one reconciliation input;
  two boundaries targeting the same binding must still have distinct IDs, and
  a repeated ID is a conflict rather than an alias.
- `target` joins the declaration to one source binding. Repository-relative
  source and binding names establish identity; source locations are diagnostic
  metadata only.
- `selection` records every input that changes membership. Version 1 accepts
  only `environment`, `tenant`, `region`, `provider`, `skills`, `toolsets`, and
  `configuration`; adding a key requires an explicit profile change. Scalar or
  string or string-list values are canonicalized. Values are non-secret identifiers;
  credentials, tokens, passwords, and private material are forbidden.
- `source` binds the claim to captured bytes and the producer that emitted
  them. `format_version` and `producer_version` are independent. Unknown
  versions are explicit, never empty strings.
- `membership` is complete only for the named relation, boundary, selection,
  and producer revision. Completeness never applies to effects, principals,
  argument schemas, hidden delegation, or another deployment.
- `evidence` keeps epistemic confidence separate from human review. Expiry is
  an explicit review decision, not a generated timestamp.

Canonical JSON, hashing, strict-reader errors, and version rejection should
follow the Authority IR rules. Member order is not semantic. Duplicate member
names, absolute locators, unknown fields, and selection keys outside the closed
v1 vocabulary are rejected. The closed keys make reader behavior mechanical;
they do not replace fixture review for secrets hidden under an innocuous name.

## Trust and reconciliation

Parsing proves structure only. A declaration can discharge an unresolved
static boundary only when all of these hold:

1. its boundary target matches the selected agent binding;
2. its selection matches the deployment being reviewed;
3. its source digest and supported adapter version verify;
4. completeness is `complete`;
5. every consumed claim is `exact` and `accepted`; and
6. the review has not expired at the reconciliation evaluation date.

`partial` and `unknown` inventories may widen the observed member set, but
cannot prove absence or permit removal findings. `heuristic`, `unreviewed`,
`contested`, expired, or selector-mismatched evidence remains visible and
produces an `unresolved` finding.

Expiry deliberately makes eligibility time-dependent: a previously clean run
can become an `unresolved` finding solely because its review expired. The
reconciler therefore receives an injectable `as_of` date. A future CLI may
default that value once from the current UTC date, but machine output must
record the effective date so the result is reproducible. Tests use a frozen
date, and expiry fixtures must sit clearly before or after it rather than
depending on the day the suite runs. The declaration's hashed body contains
the review expiry, never a generated current timestamp.

Version 1 cannot observe the live deployment. “Matches the deployment” means
that the caller selected a reviewed declaration whose target and selection are
the configuration under review; the result proves agreement at that declared
context, not that production loaded it. Runtime reconciliation is later fleet
governance work.

Positive membership combines by union with provenance. Eligible complete
claims for the same boundary and selection must name the same set;
disagreement is a conflict even when their producer revisions differ. The
caller must select one reviewed revision rather than relying on “latest” or a
union. Claims for different selectors are separate observations and must not
be silently merged. An accepted manifest tool absent from an eligible complete
set may be reported as removed only when it is absent from the union of literal
members and every eligible dynamic boundary, and no contributing boundary
remains unresolved. A captured member absent from the mandate is undeclared
authority. Neither conclusion is available from incomplete evidence.

The private implementation projects membership into provenance-bearing IR
facts and `contains_tool` edges through a dedicated inventory profile. The
existing manifest-v1 profile remains the only path to authority analysis;
successful inventory validation cannot grant tool effects or make a result
analyzable. The graph keeps the reviewed declaration and captured bytes as
separate sources: declaration facts cite their JSON locations, while member
facts also cite the captured source root. Reconciliation receives captured
bytes, the expected selection, and an explicit `as_of` date from its caller.
It never resolves a locator or reads the wall clock.

## Failure contract

Malformed artifacts and unsupported versions are usage errors: exit `2`, a
value-safe diagnostic on stderr, and no stdout. Valid but ineligible evidence
is a drift finding: exit `1`, with the failed trust condition named. A clean
exit `0` means only that the reviewed mandate and eligible inventory agree at
the declared boundary; it is not a claim about undiscovered boundaries.

No command may import application modules, invoke providers, query registries,
or make network requests. Capture is an explicit upstream step whose bytes are
reviewed and passed to AgentMandate.

The public candidate uses paired, repeatable `--inventory-declaration` and
`--inventory-capture` options. `--inventory-selection` is a JSON object and
`--inventory-as-of` is an ISO date. Pairing is positional, but the capture is
stored under the declaration's locator only after the caller supplies it; the
locator is never opened. For example:

```bash
mandate drift mandate.yaml --source . --binding agent \
  --inventory-declaration reviewed-inventory.json \
  --inventory-capture captured-provider.json \
  --inventory-selection '{"provider":["cdp_api","wallet"]}' \
  --inventory-as-of 2027-01-01
```

`inventory validate DECLARATION` checks transport and structure only. It does
not verify captured bytes or make the membership eligible for drift.

## Evidence gates and sequence

1. **Contract:** challenge this record shape against AgentKit and Sentry,
   especially boundary identity, selector secrets, and hidden dispatch.
2. **Reader:** add canonical fixtures, a strict typed-error boundary, digest
   verification, and no trust-bearing CLI behavior. **Implemented privately:**
   AgentKit is complete at its reviewed provider boundary; Sentry is partial
   because its captured eight-tool surface omits hidden dispatch targets.
3. **Reconciliation:** resolve literal and declared dynamic members through the
   same `Inventory`/`drift` path; prove incomplete evidence cannot authorize a
   removal. **Implemented privately:** complete AgentKit evidence discharges
   the dynamic binding; partial Sentry and expired evidence remain unresolved.
4. **Public CLI:** expose declaration input only after failure behavior and
   output stability are reviewed across both fixtures. **Candidate
   implemented:** both declarations cross structural validation; complete
   AgentKit evidence crosses reconciliation. Sentry remains a deliberate
   boundary test because its JavaScript binding is outside the current Python
   source collector; the CLI must not manufacture a selected binding from the
   declaration itself.

The initiative is complete only when `drift` can prove one declared dynamic
boundary complete and explain why every ineligible variant cannot be proved.
