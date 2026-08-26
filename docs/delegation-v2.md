# Delegation record revision

Status: **proposed and experimental**. This is the post-evidence contract for
issue [#92](https://github.com/mrwersa/agentmandate/issues/92). It replaces the
private, synthetic grant-v1 delegation shape only after fixtures and profile
validation land. No current command accepts this format as analyzable
authority. The private strict reader and both canonical migration fixtures are
implemented. A private, closed Authority IR projection preserves the records
behind registered relations, and the private analysis consumer re-validates
those profiles before making decisions. Public exposure remains gated.

## Evidence-driven changes

The [Authorizer capture](evidence/authorizer-delegation/README.md) invalidated
three assumptions in grant v1:

- one `actor` loses the ordered, nested actor history carried by RFC 8693;
- date-only validity cannot preserve a 300-second token;
- an issuer's scopes and audience do not establish deployment-specific tools
  or effects.

The revision therefore records a chain, not an isolated synthetic grant. It
also separates facts observed at the issuer from reviewed deployment mappings.
Unknown mappings remain explicit and cannot become empty authority.

## Candidate chain record

```json
{
  "delegation_version": 1,
  "id": "authorizer-demo-chain",
  "subject": "subject:demo-user",
  "hops": [
    {
      "id": "hop-1",
      "grantor": "http://localhost:8080",
      "actors": ["agent:orchestrator"],
      "actor_history": "complete",
      "audience": "https://api.internal/orchestrator",
      "validity": {"kind": "duration", "ttl_seconds": 300},
      "surface": {
        "scopes": {
          "domain": "http://localhost:8080",
          "basis": "issuer",
          "completeness": "complete",
          "members": ["crm:read", "crm:write", "email", "mail:send", "openid", "profile"],
          "evidence": {
            "confidence": "exact",
            "review": "accepted",
            "reviewer": "evidence-review",
            "expires": "2027-08-25"
          },
          "source": {
            "kind": "oauth-claims",
            "locator": "docs/evidence/authorizer-delegation/capture.json",
            "location": "/hops/0/scopes",
            "content_sha256": "bbbe73c3b138fa9e6e207e3958971bc92f2f91b771967fb5252c1c0d7b8f0409"
          }
        },
        "tools": {
          "domain": null,
          "basis": "unavailable",
          "completeness": "unknown",
          "members": []
        },
        "effects": {
          "domain": null,
          "basis": "unavailable",
          "completeness": "unknown",
          "members": []
        }
      },
      "evidence": {
        "confidence": "exact",
        "review": "accepted",
        "reviewer": "evidence-review",
        "expires": "2027-08-25"
      },
      "source": {
        "kind": "oauth-claims",
        "locator": "docs/evidence/authorizer-delegation/capture.json",
        "location": "/hops/0",
        "content_sha256": "bbbe73c3b138fa9e6e207e3958971bc92f2f91b771967fb5252c1c0d7b8f0409"
      }
    }
  ]
}
```

The gate-2 migration fixture will contain all four hops; one is shown here to
keep the example readable. Each subsequent complete `actors` list must equal
the new current actor followed by the prior hop's complete list. Actors are
stored current-first because that is the nested `act` claim order. Hop IDs are
unique, and every hop has the chain's one subject. `actor_history` is `complete`
or `partial`, and actor entries are non-empty and unique.

Actor-history trust is chain-wide. Any partial hop makes every decision derived
from that chain unresolved, including decisions at earlier or later hops; a
consumer cannot prove chain integrity by traversing around the gap. Continuity
is still checked across a partial boundary: the next list must begin with its
new current actor followed by the prior hop's current actor. When both histories
are complete, the stronger full-list equality above applies. A later complete
claim does not erase an earlier partial hop.

`source.location` is an RFC 6901 JSON Pointer into the digest-pinned artifact.
This gives each hop and surface dimension replayable provenance without
duplicating raw tokens.

## Validity and deterministic evaluation

Validity is a closed union:

- `window`: canonical UTC `issued_at` and `expires_at` timestamps;
- `duration`: a positive integer `ttl_seconds`, when sanitization or the source
  preserves duration but not an absolute issuance time;
- `date_window`: canonical `issued` and `expires` dates, solely for lossless
  migration of the synthetic v1 fixture.

Only `window` is eligible for live attenuation analysis. The caller must supply
an RFC 3339 UTC `as_of` timestamp; the analyzer never reads the wall clock.
The interval is half-open: `issued_at <= as_of < expires_at`. Equality at
issuance is eligible; equality at expiry is expired, matching the JWT `exp`
requirement that current time be before expiration in
[RFC 7519 section 4.1.4](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1.4).
`duration` and `date_window` remain valid archival evidence but produce a named
`delegation.validity-unresolved` finding. Converting either to a timestamp
would invent precision.

## Partial authority surfaces

Each `scopes`, `tools`, and `effects` dimension has independent provenance:

- `basis` is `issuer`, `deployment_policy`, or `unavailable`;
- `completeness` is `complete`, `partial`, or `unknown`;
- `members` contains sorted, unique reviewed strings;
- `domain` identifies the authority namespace in which membership is
  comparable;
- claimed members carry their own evidence and source.

`unknown` requires `basis: unavailable`, `domain: null`, an empty member list,
and no evidence or source. `partial` requires at least one member but proves no
absence. `complete` may be empty and proves absence inside its named domain.
Issuer evidence can establish scopes; tools and effects require a reviewed
deployment-policy source. Reusing scope spelling across different domains is
not attenuation evidence.

For a tool invocation, analysis treats the dimensions independently:

- an excess against a complete, comparable dimension is
  `delegation.widens`;
- membership in every applicable dimension supports attenuation;
- an unknown, expired, unverifiable, cross-domain, or insufficiently complete
  dimension produces a specific unresolved finding and no widening verdict;
- no unresolved record may remove the tool or weaken its declared effect.

## Tool attachment

The delegated principal stops copying claims that can disagree with the chain:

```json
{
  "principal_version": 2,
  "id": "export-agent-principal",
  "target": {
    "source": "deploy/agent.py",
    "binding": "agent",
    "tool": "export_records"
  },
  "principal": {
    "kind": "delegated_user",
    "delegation": "authorizer-demo-chain",
    "hop": "hop-4",
    "domains": {
      "scopes": "http://localhost:8080",
      "tools": "deployment:export-agent",
      "effects": "deployment:export-agent"
    }
  },
  "evidence": {
    "confidence": "exact",
    "review": "accepted",
    "reviewer": "security-platform",
    "expires": "2027-08-25"
  }
}
```

The referenced hop is the sole source of subject, actor history, audience, and
validity. The attachment's reviewed per-dimension domains establish whether
manifest scope, tool, and effect names are comparable with the hop; spelling
alone never crosses a domain. A dangling chain or hop is a trust failure. `fixed_user_credential`
and `intersecting` retain their existing meanings when principal v2 migrates;
neither is promoted into a delegation.

## Trust and migration gates

Structural parsing and IR projection remain distinct from analysis eligibility.
The implemented standalone profile requires one pinned delegation-chain source,
recomputes its semantic digest, and rejects mixed evidence states. Generic IR
validation accepts its additive relations, while `reach --ir` refuses the
profile at the manifest-v1 trust boundary.
Before consumption, the analyzer re-reads each artifact, validates its closed
profile, verifies every supplied digest, requires exact and accepted evidence,
and evaluates review expiry against a caller-supplied date and token validity
against the caller-supplied timestamp.

The implementation and analysis gates are:

1. migrate the synthetic grant-v1 fixture to one `date_window` hop without
   improving its evidence or eligibility;
2. project all four Authorizer hops byte-stably, retaining subject, ordered
   actors, audience, complete scopes, 300-second duration, and unknown
   tools/effects;
3. reject reordered or truncated actors, invalid hop continuity, conflicting
   dimensions, non-canonical timestamps or pointers, unknown dimensions
   carrying claims, and any clean decision from a chain containing partial
   history;
4. prove that the migrated Authorizer chain yields unresolved tool/effect and
   validity findings, never `delegation.widens` or a clean decision;
5. keep all four manifest evidence graphs and existing conditional outputs
   byte-identical under conservative defaults.

Items 1–5 are implemented as private records, migrations, projection,
adversarial profile tests, and a fail-closed analysis consumer. The consumer
requires a canonical caller-supplied UTC timestamp, treats expiry as exclusive,
and checks that every complete comparable downstream surface is a subset of
its predecessor before comparing the attached tool with its referenced hop.
Unknown, partial, cross-domain, expired, or unverifiable inputs produce named
unresolved findings and cannot produce widening claims. Delegation analysis
remains private after this gate. Its first non-synthetic widening
counterexample still requires an operational, digest-pinned deployment mapping
from scopes to tools and effects. The CLI exposure is implemented behind the
same consumer and awaits its separate closing review.

A standalone chain profile requires one confidence/review state so conflicting
claims cannot be silently merged. Reviewer names remain per-fact accountability
values and may differ across hops; changing reviewer identity does not itself
upgrade or downgrade evidence confidence or review state.

## Non-goals

No token parsing, signature verification, issuer discovery, token issuance,
credential brokering, runtime interception, arbitrary claim mapping, or
cross-domain scope inference. This format records reviewed evidence; it does
not make AgentMandate an identity provider or policy enforcement point.
