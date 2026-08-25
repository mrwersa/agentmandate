# Authorizer evidence: a real delegation chain does not fit the provisional grant

This capture satisfies the roadmap's missing identity prerequisite: a real
RFC 8693 implementation issued four tokens that retain one subject and carry
an ordered, nested actor chain. It also shows why delegation analysis must not
start from the current synthetic grant fixture. OAuth proves scopes, audience,
issuer, actors, and a five-minute lifetime; it does not prove tool/effect
mappings, and the current records cannot represent sub-day expiry or prior
actors without distortion.

## Evidence boundary and provenance

- **Subject:** [Authorizer 2.4.0](https://github.com/authorizerdev/authorizer/releases/tag/2.4.0),
  published 19 August 2026 under Apache-2.0. Tag `2.4.0` resolves to commit
  [`4ad0758c`](https://github.com/authorizerdev/authorizer/tree/4ad0758cebf49e65e91ae45047a1f288d1c95a7f).
- **Implementation source:**
  [`internal/http_handlers/token_exchange.go`](https://github.com/authorizerdev/authorizer/blob/4ad0758cebf49e65e91ae45047a1f288d1c95a7f/internal/http_handlers/token_exchange.go),
  SHA-256 `f32aca8ad291d8822cbc3d7fe92af89e108998b6d5e586dacdefc84b84b99579`.
- **Upstream scenario:** the public
  [`with-agent-delegation`](https://github.com/authorizerdev/examples/tree/c48e885918da42bf04ce81ab04b061b12f2c70ce/with-agent-delegation)
  example at commit `c48e885918da42bf04ce81ab04b061b12f2c70ce`;
  its `demo.mjs` SHA-256 is
  `f3d3083a047eb7bbf27b73f7b5292966efaa6e089e2ac93bcf7f9de77018f1da`.
- **Deployment:** the upstream `make dev` profile using SQLite, fixed local
  development keys, and loopback GraphQL/OAuth endpoints. No resource server
  was contacted. This is real upstream implementation evidence, not a customer
  deployment or proof that a downstream API enforces the token.
- **Capture:** `capture.json`, SHA-256
  `bbbe73c3b138fa9e6e207e3958971bc92f2f91b771967fb5252c1c0d7b8f0409`.
  It completely records the four issued hops and three rejection cases in the
  pinned upstream scenario; it does not claim a complete tool inventory.

The normative distinction matters. [RFC 8693 section
1.1](https://www.rfc-editor.org/rfc/rfc8693.html#section-1.1) says a
subject-only exchange is impersonation; delegation retains a distinct actor.
Authorizer requires an `actor_token`, binds it to the authenticated client,
and emits the current and prior actors through nested `act` claims.

## Capture and safety

The adapter accepts only `http://localhost:8080` or
`http://127.0.0.1:8080`. It creates disposable user and service-account
records, performs only loopback administration and token requests, then
deletes them. Access tokens, client secrets, user IDs, session IDs, absolute
timestamps, and raw server logs never enter `capture.json`; the script decodes
tokens in memory, verifies reviewed invariants, and emits stable aliases and
durations. The committed artifact contains no account or trace identifiers.

Reproduce with Go 1.26.6 (the version required by the release's `go.mod`) and
Node 18+. Clone and check out the pinned source, then start Authorizer using its
documented development target:

```console
$ git clone https://github.com/authorizerdev/authorizer.git /tmp/authorizer
$ git -C /tmp/authorizer checkout 4ad0758cebf49e65e91ae45047a1f288d1c95a7f
$ cd /tmp/authorizer
$ make dev
```

The upstream example is provenance rather than a runtime dependency of the
adapter. Verify its pin separately, then run from this repository in another
shell:

```console
$ git clone https://github.com/authorizerdev/examples.git /tmp/authorizer-examples
$ git -C /tmp/authorizer-examples checkout c48e885918da42bf04ce81ab04b061b12f2c70ce
$ AUTHORIZER_ADMIN_SECRET=admin node \
    docs/evidence/authorizer-delegation/capture-delegation.mjs \
    --output /tmp/authorizer-delegation.json
$ cmp docs/evidence/authorizer-delegation/capture.json \
    /tmp/authorizer-delegation.json
```

The Go 1.26.6 Linux amd64 archive used for this review matched its published
SHA-256, `708effb774be8237570d0add163225abbdfaf4fca28b2611df167beba4feef89`.
The capture was run twice with fresh identifiers and tokens; both outputs were
byte-identical.

## Review corrections

1. **Extractor defect:** after the host wall clock stepped backward by roughly
   one second, the unmodified example masked a `Token used before issued` HTTP
   response as an undefined-token JavaScript error at hop 3. The adapter waits
   2.1 seconds before each exchange, preserves named HTTP failures, and
   validates that every issued token still has the documented 300-second TTL.
   The interval changes no authority fact; it is retained visibly in source.
2. **Model gap:** the four issued tokens carry nested actor history of depths
   one through four. The current `delegated_user` record carries one actor and
   one grant reference, so it cannot preserve the shortest chain.
3. **Model gap:** token validity is 300 seconds. Current grant and principal
   records use dates, which would widen a five-minute capability to as much as
   a day or expire it prematurely depending on interpretation.
4. **Source ambiguity / deployment policy:** the issuer establishes scopes and
   audience, but not which tools or effect classes those scopes authorize.
   Current grant v1 requires non-empty `tools` and `effects`; populating them
   from this capture would invent deployment policy.
5. **Source ambiguity:** the capture proves issuance and three authorization-
   server rejections. Because it contacts no resource server, it does not prove
   that a downstream service validates issuer, audience, expiry, actor, or
   scope.

## Result and roadmap consequence

The real chain is:

```text
subject:demo-user
  -> agent:orchestrator          six scopes
  -> agent:research-agent        three scopes
  -> agent:crm-reader            two scopes
  -> agent:export-agent          two scopes
```

Every token retains the subject, names the current actor first, nests prior
actors in order, binds one audience, and expires after 300 seconds. The server
then rejects a fifth hop (`invalid_request`), recovery of a dropped scope
(`invalid_scope`), and another client's actor token (`invalid_grant`).

This clears the “genuine chain” evidence prerequisite but holds analysis and
public exposure. [Issue #92](https://github.com/mrwersa/agentmandate/issues/92)
requires the delegation contract to support ordered hops,
timestamp-resolution validity, and source-specific partial surfaces. A later
operational tool graph must establish scope-to-tool/effect policy before
AgentMandate can claim a real `delegation.widens` counterexample.

Non-goals: this evidence does not make AgentMandate an issuer, token verifier,
resource server, credential broker, or runtime proxy. It does not promote
Authorizer's demo CRM scopes into reviewed tool policy.
