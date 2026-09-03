# AWS IAM access-key cardinality evidence

Captured on 29 August 2026 in `us-east-1` against the published
`awslabs.iam-mcp-server` 1.0.11 wheel. This fixture supplies the missing
cardinality half of the [bounded-producer evidence gate](../../bounded-producer-evidence-audit.md):
the MCP producer returned two distinct authority-bearing credentials for one
IAM user, and AWS rejected the third production solely because the finite set
was exhausted.

This is deliberately a version-scoped historical result. The reviewed current
release, 1.0.23, replaces `SecretAccessKey` with a redacted marker, so its MCP
response does **not** give the agent a usable credential. Nothing here claims
that current IAM MCP deployments expose secret material.

## Reproduced result

The capture created a permissionless IAM user under
`/agentmandate-evidence/`, called the real MCP `create_access_key` tool twice,
and used each returned key once with STS `GetCallerIdentity`. Both credentials
authenticated as the same temporary user. A third call raised the service's
typed `LimitExceeded` error. Cleanup then deleted both keys and the user before
writing the sanitized outcome.

AWS documents both parts of the control: an IAM user can have at most two
access keys and the quota is not adjustable in the
[IAM service quotas](https://docs.aws.amazon.com/general/latest/gr/iam-service.html);
the [AWS CLI IAM guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-services-iam.html)
states that creating a third key returns `LimitExceeded`. STS
[`GetCallerIdentity`](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)
identifies the credentials' principal without requiring a permission grant.

The reviewed manifest selects only `create_access_key` from the full 29-tool
catalogue. That is an explicit evidence-adapter deployment policy, not a claim
that the upstream server has a one-tool allowlist. With manifest v1's only
multi-production spelling, `unbounded: true`, current reachability reports:

```text
BREACH  write calls reach 3, above the declared budget of 2 in one run
  1. create_access_key(access_key#1)
  2. create_access_key(access_key#2)
  3. create_access_key(access_key#3)
```

At depth two the control is clean. The real deployment accepts those first two
productions but rejects the modeled third path because the binding set is
exhausted. This is the finite cardinality distortion the gate required.

## Provenance and recapture

`catalogue.json`, SHA-256
`6ad70d0ecf3d05e8e9e2b08a52e7d2b8099954b586f52c6bd68bc3d99e5cff3c`.
It is the byte-stable result of the pinned server's actual `tools/list` call.
`capture.json`, SHA-256
`199f47e9bc87d39ab129bcd01ab69200326d759e1621cfdc5c5abfa9511fb3c8`.
It contains aliases and outcome classes only. The 1.0.11 wheel's upstream
SHA-256 is `e48d688f8e338098f410fcabfbedec304f65e63c179bb19001e5b80a2523de16`;
the wheel remains available from the
[versioned PyPI release](https://pypi.org/project/awslabs.iam-mcp-server/1.0.11/).

Recapture is intentionally live and side-effecting:

```bash
python -m venv .capture-venv
.capture-venv/bin/pip install -r requirements-capture.txt
.capture-venv/bin/python capture.py \
  --catalogue catalogue.json --outcome capture.json --live
```

The caller needs IAM permission to create/delete the temporary user and its
access keys, list/get that user and its keys, plus STS access. The script keeps
raw credentials in process memory, never writes them, verifies cleanup in a
`finally` block, and writes output only after the user is absent. The committed
capture records zero remaining keys and an absent user. Recapture may incur
ordinary AWS API usage; this run created no persistent resource and attached no
policy.

## Review corrections and boundary

- **Extractor defect:** `mandate scan` sees neither the returned credential nor
  its cardinality. The raw skeleton is preserved; the reviewed adapter adds the
  `access_key` producer and service principal.
- **Source/version ambiguity:** 1.0.11 returns the secret, while reviewed
  1.0.23 source redacts it. The package version and wheel digest are therefore
  load-bearing facts, not incidental provenance.
- **Model gap:** manifest v1 forces one produced binding or an unbounded series.
  It cannot express the enforced maximum of two for one user boundary.
- **Deployment policy:** the temporary user had no policies, the adapter
  selected one tool, and cleanup made key creation reversible for this run.
  The manifest therefore uses `write`, not a claim about every IAM deployment.

No access-key ID, secret key, account ID, ARN, request ID, or trace ID is
committed. The raw credential-bearing response cannot be retained safely, so
the executable capture and independently authenticated aliases are the review
artifact. This evidence selects the private finite-cardinality record shape and
canonical migration now implemented in `agentmandate._producer`. It does not
itself change the manifest schema or analyzer.

## Gate consequence

The bounded-producer initiative now has both required real distortions:
AgentKit supplies quantity relationships, and this pinned IAM MCP deployment
supplies finite authority-bearing cardinality with an accepted two-step control
and an exhaustion-only rejection. Gates 1, 2a, and 2b now preserve that
evidence in a strict private record, byte-stable migration, and closed
standalone Authority IR profile. Private analysis and public bounded-producer
behavior remain pending.
