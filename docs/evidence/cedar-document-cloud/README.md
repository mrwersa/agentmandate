# Cedar document-cloud policy fixture

This fixture exercises the first two levels of the Cedar import trust ladder:
the bundle parses, the policies validate against the schema, and two concrete
decisions reproduce. It deliberately does not contain an AgentMandate
deployment mapping and is not authority-eligible.

## Provenance

The source files are byte-preserving copies of the official Cedar
`document_cloud` example at commit
[`c251f7d`](https://github.com/cedar-policy/cedar-examples/tree/c251f7d1ad171bd12dee5d1d7a1cceaec994518f/cedar-example-use-cases/document_cloud).
The capture uses the official `@cedar-policy/cedar-wasm` package at version
4.12.0. Its npm SHA-512 integrity is
`sha512-tCSj92hh4fnmas4ojO4tjx8wAAW3mKVgQ7M388NsSpXp64FVeYY6xwhKtJRaaYGK0qLiN2jnq8/SNIU2r5fdPw==`.

- `policies.cedar`, SHA-256 `fe0a1f463dbac5756b256df94807c34d6eb81eb501b76e627f54802b5811f990`
- `policies.cedarschema`, SHA-256 `245214bd26ed3e859f44c91f9ac546094153028eb99e0493675b8c2e9d7ea8bf`
- `entities.json`, SHA-256 `cfad0e9dfee7493c1e631ab3d3a13ff0deedb935a63a520bf61af54dc866a1b4`
- `allow-request.json`, SHA-256 `d967ed52d5903d49fa4d507824442e289647ede845d226639a987aab86947fcf`
- `deny-request.json`, SHA-256 `0cc5bf04d737d1ccf98a3d45cc651046afebc6e8ac6e94fad8ac84248f75790d`
- `native-output.json`, SHA-256 `baffdf624af51211d22d12c66a2675d9ad775d454b42d6a0d432659be15ecb7d`
- `package-lock.json`, SHA-256 `c513bec68ba13c86196a0b8e1e7a1b31b88a52b7533f8ddcbada09e781033539`
- `bundle.json`, SHA-256 `592699ddc1c20cadf8a1914d18f815bbd49363bbacbe97a1b9a78f458e5860e7`

The bundle's local source digests exclude the bundle itself, avoiding a
self-referential checksum. The capture script and package manifest are
reproduction machinery rather than policy evidence.

## Reproduction

From this directory:

```bash
npm ci --ignore-scripts
npm run capture > /tmp/cedar-native-output.json
diff -u native-output.json /tmp/cedar-native-output.json
```

The committed raw output is the required offline test oracle. A focused test
also performs the byte comparison when the pinned package is already installed;
normal Python CI does not download Node packages. This keeps core dependency
and offline-test guarantees while leaving a one-command native recapture.

## Reproduced results

| Request | Decision | Determining policies | Schema-based request parsing |
|---|---|---|---|
| Alice views her public document | `allow` | `policy1`, `policy9` | not used |
| Bob views Alice's public document | `deny` | `policy4` | not used |

Policy validation succeeds without warnings. The deny is a satisfied forbid,
not default deny, and that distinction remains in the bundle.

## Boundary discovered

When the same allow request is authorized with schema-based request/entity
validation enabled, the official fixture fails: `Document::"alice_public"`
declares `manageACL` and `modifyACL` values as `Document` entities while the
schema requires `DocumentShare`. The capture preserves the first native error
in `schema_checked_probe` and marks both reproduced decisions
`schema_checked: false`.

This is not repaired locally. Doing so would stop the files being the pinned
official fixture and would silently strengthen the reproduced claim. It means:

- **source ambiguity:** the example's runner demonstrates authorization without
  proving schema-conformant entity/request parsing;
- **model boundary:** policy validation and concrete authorization are separate
  native claims and must remain separate records; and
- **deployment policy:** no action-to-tool, entity-to-binding, request-builder,
  or enforcement-point mapping is present.

The fixture therefore proves transport, digest verification, policy
validation, allow/deny preservation, and an explicit ineligibility reason. It
does not prove that any agent submits these requests or obeys these decisions.
