# Why the search spends the available headroom

`reach` does not try every possible consumption amount. It chooses the binding
with the largest remaining ceiling and spends that headroom. For manifest v3, this
preserves each named quantity's greatest reachable consumption and the existence
and shortest call length of its `quantity_budget` breach within the selected
depth. The argument depends on the model below; it is not a claim about arbitrary
tool input schemas or provider behavior.

For example, one case has a £5 cumulative refund ceiling. Refunding £2 and then
£3 cannot exceed what one £5 refund already reaches, and uses an extra call.
Repeated refunds matter when a producer can create another case, not because
splitting one case's allowance creates more variable value. A fixed charge
can make the extra call consume more requests or compute; those calls remain
explicit in the search.

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

`limits.quantities` and `limits.effects` are properties the search checks for a
breach, not guards that stop exploration. Approval and principal labels do not
alter which spending calls the kernel explores. Effect-budgeted and fixed-charge calls still count when
they spend zero or have no remaining variable quantity headroom. Each named quantity
requires one consistent unit; resolve structural and per-quantity unit errors
before relying on the model.
The argument concerns exact arithmetic on parsed non-negative quantities.

## A prefix argument

Fix an enabled sequence of tool calls. Keep its scope production and effect
calls unchanged, but replace its quantity amounts with greedy fills.

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

On the same call sequence, each tool adds exactly the same constant vector of
fixed charges in both walks, regardless of amount or selected binding. Adding
these equal fixed totals preserves every prefix inequality. Charged calls
remain transitions even when the chosen variable amount is zero.

Within each named pool, summing the inequalities for tools assigned to that
pool shows that greedy consumption is at least the original sequence's
consumption at each prefix. Amounts in different pools are never summed.
Enablement, scope production and budgeted effect counts are preserved because
none depends on the amounts.
Thus a `quantity_budget` breach of any pool in k calls has a greedy breach
of that pool in at most k calls. Conversely, every greedy fill is an allowed
amount choice in this model, so it cannot create a quantity-budget breach that
the full amount-choice model lacks. The bounded maximum and minimum breach
length agree in both directions.

No-change calls may be omitted from a queued path. They cannot enable a later
call or add consumption; effect-budgeted and fixed-charge calls change tracked
state and are retained.
Visiting an identical state at its shortest depth also leaves at least as much
of the remaining call budget as visiting it later. These reductions preserve
the existential result, not every concrete trace or allocation of amounts.

## Where the argument stops

Suppose paying **exactly £1** unlocks a second tool that can spend £4, while the
first tool's ceiling is £2. A greedy £2 payment does not unlock that tool; a £1
payment can reach £5. This amount-dependent example falls outside manifest v3
and demonstrates why the enablement assumption matters. Do not translate such
a workflow into unconditional scope production and then apply this argument.

Minimum or exact variable request amounts, input-dependent charges, shared
cross-tool per-binding ceilings, binding-specific
permissions, value conversion, negative/net spending and arbitrary conditions
need their own models and arguments. The result here does not establish
business-scenario preservation, live enforcement, state continuity, or general
policy equivalence.
It does not equate the two searches' state sets, exact witnesses or truncation
flags. A clean bounded result retains the [ordinary depth limit](search-performance.md).

## Exact search arithmetic

The search uses an isolated Decimal context sized from the nonzero tool
ceilings, fixed charges and call depth. Aligning these amounts gives a width w.
Within any one pool, at most D calls contribute at most 2D terms: one fixed
charge and one variable amount per call. Reserving w plus the bit length of 2D is a
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

Use quoted amount strings in JSON or YAML when decimal digits matter. JSON
fractional numbers are parsed as exact decimals. An unquoted YAML fractional
number can be rounded by its format reader before manifest validation. This fix
preserves parsed values; it does not reconstruct digits already lost while
decoding an input.

## Reproduce the independent check

From a development checkout:

```bash
python scripts/check_headroom_abstraction.py --output /tmp/headroom-check.json
python -m pytest tests/test_headroom_abstraction.py -q
```

The repository-only reference search uses integer units and tries zero plus
every permitted positive integer amount on every held binding. It builds its
own states and transitions; it imports no greedy search helpers. The comparison
checks maximum consumption per quantity, reachable tools, effect/scope pairs,
principal and approval findings, breach subjects and shortest enabling/breach lengths.
Exit 0 means agreement across the configured cases; exit 1 lists mismatches;
exit 2 reports invalid reference inputs or I/O errors.
The report is maintenance data, not an authority artifact.

The [recorded run](headroom-abstraction-results.json) checks **879 synthetic
cases without fixed charges**, with **15,404 reference states**, **27,403 examined transitions** and
**14,454 positive amount choices**; it finds no mismatches. The Cartesian grid
covers eight graph shapes, three ceilings, three quantity budgets, three budget
settings and four depths. Fifteen additional cases cover finite producer caps.
Separate tests check fractional units and detect deliberately under-spending
and fresh-binding-ignoring kernel mutations. These are finite executable checks
of the argument, not a proof over all manifests, a provider capture, or an
independent security review.

The report pins generated inputs, reference source and the measured kernel
source. Future kernel changes must retain semantic agreement; the recorded
source hash describes that run rather than certifying every later implementation.

## Several named quantities

Apply the prefix argument separately to each quantity. A tool has one amount
argument and quantity assignment; filling its ceiling affects only that pool.
Enablement, binding production and effect counts remain amount-independent, so
greedy filling preserves the componentwise maxima and shortest budget breaches.
Different quantities are never summed. Their maxima can occur on different
paths; the report makes no claim that all maxima are jointly attainable.
`tests/test_quantities.py` checks this extension against an independent Fraction
sequence oracle over separate/shared pools, matching/different units, bounded
and unbounded production, zero/fractional amounts and three depths.

## Constant charges alongside variable amounts

The same argument permits a fixed positive vector on every completed call.
The vector can share a pool with the variable amount or charge separate pools;
its entries do not consume variable per-binding headroom. A call with no variable
headroom can still increase fixed totals, so removing it as a no-change read
would be unsound. Producer-cap rejection occurs before the modeled completed
call and adds no charge.

`tests/test_fixed_charges.py` adds 96 independent Fraction-oracle comparisons.
They enumerate every integer amount, including zero, on every held binding,
across four depths, bounded/unbounded producers, zero/positive ceilings, shared/
separate pools and producer/consumer/both charge placement. The oracle imports
no greedy helpers and compares componentwise maxima and shortest pool-breach
lengths. These checks are separate from the recorded 879-case no-fixed-charge
study. Neither check establishes input-dependent rates or runtime accounting.
