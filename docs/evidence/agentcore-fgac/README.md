# AgentCore Cedar mapping source evidence

This fixture preserves the source-side half of Cedar gate 4 from
[`aws-samples/sample-agentcore-gateway-fgac`](https://github.com/aws-samples/sample-agentcore-gateway-fgac/tree/3e0d462c679c4cddfdea1bfc9176256628c7d699)
at commit `3e0d462c679c4cddfdea1bfc9176256628c7d699`. It proves what the pinned
repository declares. It does not prove which tools a deployed Gateway lists or
that AgentCore Policy evaluated a call.

## Reproduction

The files under `upstream/` are byte-identical copies of the nine paths listed
in `source-index.json`. They contain no credentials or live deployment output.
Rebuild the source catalogue offline with:

```bash
python docs/evidence/agentcore-fgac/capture_catalogue.py \
  > /tmp/agentcore-catalogue.json
diff -u docs/evidence/agentcore-fgac/catalogue.json \
  /tmp/agentcore-catalogue.json
```

- `source-index.json`, SHA-256 `6c9e29599025d328677e1332e4528aea0514fe6c24c1b6447b6a464c599ae30a`
- `catalogue.json`, SHA-256 `2bcce6bc89861bb468be7e52ac5e943e8c1a74ca527e0f32c5aa66a7e60321e4`

## Finding: the six-tool claim is not source-complete

The three router modules declare six explicit `operation_id` values and the
README's customer Cedar policy names three of them. However, `main.py` also
declares public `GET /health` without an explicit operation ID, and
`export_openapi.py` emits `app.openapi()` without filtering that route. The
source-side domain is therefore seven routes, not six.

The capture does not guess the generated Gateway action for `/health`.
FastAPI normally generates an operation ID, but only a captured OpenAPI
document and AgentCore `tools/list` can establish the actual deployed tool
name. The customer policy's exact three-action list would default-deny that
additional action; the admin policy's wildcard could permit it. Consequently,
the current six-entry mapping is incomplete and authority-ineligible.

## Reviewer corrections

1. **Extractor defect:** the original audit counted only explicit
   `operation_id` decorators and omitted the undecorated health route. The
   capture now enumerates every route decorator in the four included modules.
2. **Source ambiguity:** source code does not establish the generated Gateway
   tool name for `/health`; it stays null and unresolved rather than receiving
   a guessed FastAPI identifier.
3. **Deployment policy:** the backend health route is public while AgentCore
   Cedar is default-deny for customers and wildcard-permit for admins. Those
   layers are recorded separately, not collapsed into one verdict.
4. **Model gap:** native `tools/list`, policy validation, attachment mode, and
   ENFORCE decisions remain absent. No `maps_to_tool` edge is earned.

## Gate consequence

Issue [#112](https://github.com/mrwersa/agentmandate/issues/112) remains open.
Its set-equality check must cover all generated OpenAPI operations, including
health if it is exported, before mapping review can begin. No AWS or Okta
resources were created for this capture.
