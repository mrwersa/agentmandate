# Why the search spends the available headroom

`reach` does not try every possible refund amount. It chooses the binding with
the largest remaining ceiling and spends that headroom. For manifest v1, this
preserves the greatest reachable cumulative value and the existence and shortest
call length of a cumulative-value breach within the selected depth. The argument
depends on the model below; it is not a claim about arbitrary tool input schemas
or provider behavior.

For example, one case has a £5 cumulative refund ceiling. Refunding £2 and then
£3 cannot exceed what one £5 refund already reaches, and uses an extra call.
Repeated refunds matter when a producer can create another case, not because
splitting one case's allowance creates more value.

## Assumptions in the current model

The kernel starts with no bindings or spend. Scopes are types; held bindings of
one scope are interchangeable for tool enablement. A spending tool has one
nonnegative cumulative ceiling per binding, identical across its bindings.
Spend accounts are keyed by **tool, scope and binding**: two tools do not share
one allowance merely because their scope names match.

Any amount between zero and remaining headroom is permitted by this numeric
model. Request granularity, minimum amounts, input-dependent outputs and
relationships between amounts are not encoded. Scope requirements and
production depend on held bindings, not on amounts already spent. Bindings and
spend only accumulate; there are no refunds, replenishment, expiry or consumption
of bindings in this kernel. A finite producer cap, when supplied by a separately
validated consumer, depends on binding count rather than spending.

`limits.total` and `limits.effects` are properties the search checks for a
breach, not guards that stop exploration. Approval and principal labels do not
change monetary enablement. Budgeted calls still count when they spend zero or
have no remaining monetary headroom. Cumulative analysis needs one currency;
resolve the structural and currency errors reported by `lint` before relying on
the model. The argument concerns exact arithmetic on parsed monetary values.

## A prefix argument

Fix an enabled sequence of tool calls. Keep its scope production and effect
calls unchanged, but replace its monetary choices with greedy fills.

For a tool with positive ceiling C, every binding in the greedy walk is either
unspent or filled to C. Its next positive-headroom choice therefore fills one
previously unspent binding. Let f be the number of filled bindings for this tool.
The greedy cumulative spend is C × f.

Induct over call prefixes. Initially both walks have spent zero. On a call that
fills a new binding, the other walk can add at most C, so it cannot exceed the
new greedy total. If no unspent binding is available, the greedy walk has already
filled every held binding; the other walk cannot exceed that total capacity.
Calls to other tools leave this tool's account unchanged. A zero ceiling adds
zero in either walk. This establishes the inequality separately for every tool
at every prefix, including calls that produce a binding before spending.

Summing the per-tool inequalities shows that greedy spend is at least the spend
of the original sequence at each prefix. Enablement, scope production and
budgeted effect counts are preserved because none depends on the amounts.
Thus any cumulative-value breach in k calls has a greedy breach in at most k
calls. Conversely, every greedy fill is an allowed amount choice in this model,
so it cannot create a monetary breach that the full amount-choice model lacks.
The bounded maximum and minimum breach length agree in both directions.

No-change calls may be omitted from a queued path. They cannot enable a later
call or add spend; an effect-budgeted call changes its counter and is retained.
Visiting an identical state at its shortest depth also leaves at least as much
of the remaining call budget as visiting it later. These reductions preserve
the existential result, not every concrete trace or allocation of amounts.

## Where the argument stops

Suppose paying **exactly £1** unlocks a second tool that can spend £4, while the
first tool's ceiling is £2. A greedy £2 payment does not unlock that tool; a £1
payment can reach £5. This amount-dependent example falls outside manifest v1
and demonstrates why the enablement assumption matters. Do not translate such
a workflow into unconditional scope production and then apply this argument.

Fixed request amounts, shared cross-tool budgets, binding-specific permissions,
value conversion, negative/net spending and arbitrary conditions need their
own models and arguments. The result here does not establish business-scenario
preservation, live enforcement, state continuity, or general policy equivalence.
It does not equate the two searches' state sets, exact witnesses or truncation
flags. A clean bounded result retains the [ordinary depth limit](search-performance.md).

## Exact search arithmetic

The search uses an isolated Decimal context sized from the nonzero tool
ceilings and call depth. Aligning the ceiling digits gives a width w; at most D
calls add at most D ceilings. Reserving w plus the bit length of D is a
conservative allowance for the sum's carry digits, with a minimum precision of
28 digits. Subtraction and accumulation are exact within Decimal's representable
range; inexact arithmetic is trapped. The caller's precision, rounding, exponent
limits, flags and traps are preserved.

This fixes a concrete earlier failure: a ceiling of
`"1.0000000000000000000000000001"` above a limit of `"1"` was rounded to one
under the default context, losing a reachable breach. Regression checks also
cover small addends beside large ceilings, sum carries, caller contexts and
large positive/negative exponents. Arithmetic outside the representation's
limits raises a `ValueError` for Python callers and exits 2 in the CLI, without
an analysis report. Precision sizing is not a time or memory cap: widely
separated decimal places may require large intermediates, so keep the process
resource limits described in the search guide.

Use quoted amount strings in JSON or YAML when decimal digits matter. An
unquoted fractional number can be rounded by its format reader before manifest
validation. This fix preserves parsed values; it does not reconstruct digits
already lost while decoding an input.

## Reproduce the independent check

From a development checkout:

```bash
python scripts/check_headroom_abstraction.py --output /tmp/headroom-check.json
python -m pytest tests/test_headroom_abstraction.py -q
```

The repository-only reference search uses integer units and tries zero plus
every permitted positive integer amount on every held binding. It builds its
own states and transitions; it imports no greedy search helpers. The comparison
checks maximum cumulative value, reachable tools, effect/scope pairs, principal
and approval findings, breach subjects and shortest enabling/breach lengths.
Exit 0 means agreement across the configured cases; exit 1 lists mismatches;
exit 2 reports invalid reference inputs or I/O errors.
The report is maintenance data, not an authority artifact.

The [recorded run](headroom-abstraction-results.json) checks **879 synthetic
cases**, with **15,404 reference states**, **27,403 examined transitions** and
**14,454 positive amount choices**; it finds no mismatches. The Cartesian grid
covers eight graph shapes, three ceilings, three total limits, three budget
settings and four depths. Fifteen additional cases cover finite producer caps.
Separate tests check fractional units and detect deliberately under-spending
and fresh-binding-ignoring kernel mutations. These are finite executable checks
of the argument, not a proof over all manifests, a provider capture, or an
independent security review.

The report pins generated inputs, reference source and the measured kernel
source. Future kernel changes must retain semantic agreement; the recorded
source hash describes that run rather than certifying every later implementation.
