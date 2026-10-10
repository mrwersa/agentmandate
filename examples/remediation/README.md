# Keep a refund capability while reducing its headroom

Use the [repair guide](../../docs/remediation.md) for the main refund example
and the result contract. This directory contains a **synthetic** two-tool
example: `seed` can produce fresh item bindings, and `pay` can spend up to
£5 per item without approval. The declared run total is £5 at depth four.

The graph has two independent findings: ungated irreversible calls and a
reachable £10 total. Keeping both tools requires approval **and** a lower
ceiling to clear both within four calls:

```bash
mandate remediate examples/remediation/ungated-refund.json --keep-tool seed --keep-tool pay --ceiling pay=2 --json > /tmp/refund-repairs.json
```

The command exits 1 for the original findings. Review the joint candidate,
then write its semantic manifest into a separate file:

```bash
python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path('/tmp/refund-repairs.json').read_text())
Path('/tmp/refund-candidate.json').write_text(
    json.dumps(report['candidates'][0]['manifest'], indent=2) + '\n'
)
PY
mandate lint /tmp/refund-candidate.json
mandate reach /tmp/refund-candidate.json --depth 4
mandate verify /tmp/refund-candidate.json --trace examples/remediation/normal-refund.jsonl
```

The supplied trace records two approved £1 payments against one synthetic
item. It is conformant to the candidate's cumulative £2 per-item ceiling.
Changing either payment to £2 or removing approval makes replay fail. These
are offline synthetic checks, not evidence of a live deployment or business
success. Trace conformance does not verify producer lineage or execution of
the whole application, and remediation does not consume the trace.

To preserve those calls during candidate generation, supply the separate
[required path](required-joint.json):

```bash
mandate remediate examples/remediation/ungated-refund.json --keep-tool seed --keep-tool pay --ceiling pay=0 --ceiling pay=2 --required-workflows examples/remediation/required-joint.json
```

The zero ceiling is rejected. Approval plus a £2 ceiling retains both supplied
£1 payments within the manifest model. The command still exits 1 for the
original findings. The [workflow guide](../../docs/required-workflows.md) explains
how to author source-bound requirements and read the scoped v3 result. These
requirements are caller-authored intent, separate from the trace above.

The candidate remains truncated: a third fresh item can exceed the run total
at depth six. A lower tool ceiling and an approval requirement do not enforce
the total at runtime. The source example and its total limit stay unchanged.
