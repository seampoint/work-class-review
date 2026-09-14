# M4 derivations, fan-out and loop ancestry — 2026-09-12

Candidate pin `sha256:674d2f97e5a6b8f6e812ab140a1f821544fbdd4faa3ec6a03917225a9324c5c0`. Sealed before
construction.

## The shared allocation rule

`COMP-002`: "Parallel-block and fan-out pass numbers are one plus the largest retained pass for the
pair `(construct_id, exact outer enclosing prefix)`, or one on first entry in that context." The
pass counter is therefore keyed on the pair, not on the construct alone, so the same construct
entered under a different outer prefix is a different counter.

`LIFE-018` states the same for fan-outs from the other side: "Re-entry to the same expand step under
the same exact outer enclosing prefix is excluded from this candidate and is refused as
`UNSUPPORTED_FEATURE` at definition admission. First entry under a different outer prefix is a
distinct context with pass `1`." `FAN-001` repeats it: "First entry to the same fan-out under a
different outer branch or object prefix is a distinct context and receives pass `1`."

The distinction that matters for both cases below: repeat expansion within one outer prefix is
excluded from the candidate, so the only admissible second entry is one under a different prefix,
and that entry is pass 1 rather than pass 2.

## D2-115 — `STEP/COMPLETED`

The same fan-out is entered for the first time under a different exact outer enclosing prefix, with
a valid set at the per-expansion object maximum.

Derivation. The inner fan-out has already expanded under the first outer object, retaining pass 1
for the pair `(fanout-inner, <outer object 1 prefix>)`. The expansion now under the second outer
object is a first entry for the pair `(fanout-inner, <outer object 2 prefix>)`, so `COMP-002`'s
"or one on first entry in that context" allocates pass `1`, not pass 2. `LIFE-018` and `FAN-001`
confirm it and make clear this is not the excluded repeat-expansion case, because the outer prefix
differs.

`FAN-001` fixes the resulting rows: the pass retains the source-ordered object key list and the
allocation rule derives occurrence ordinals in that order; each object occurrence carries the
fan-out pass identity, fan-out id, occurrence ordinal, canonical object key and complete enclosing
ancestry; a nested fan-out retains the outer object key and all inner pass identities. Because the
expand occurrence is directly owned by an outer obligation, successful nonempty expansion changes
that parent obligation to `WAITING` on the exact `FANOUT` child-pass reference in the same
transition.

The set is at the per-expansion object maximum, which is admitted rather than refused: the maximum
is the largest admissible set, and `WCD-001`'s instance-wide active-obligation limit is a separate
bound that still applies and is not crossed here.

Expected result. `STEP`, disposition `COMPLETED`, empty reason codes, `EFFECT` and `ROUTE` details.
One new fan-out pass at pass `1` under the second outer object, its object occurrences active with
ordinals in source order, their obligations `OPEN`, and the owning outer obligation `WAITING` on the
new child pass.

## D2-113 — `STEP/COMPLETED`

The same loop is entered for the first time under a second frozen fan-out object.

Derivation. `COMP-002`: "Since loop member sets cannot overlap or nest, the current loop pass is one
plus the largest retained pass for the pair `(loop_id, exact outer enclosing prefix)` only when the
back edge is selected; a new outer branch or object context begins at one." Two independent
conditions have to hold for an increment, and neither holds here: this is entry from outside rather
than back-edge selection, and the outer prefix is the second fan-out object rather than the first.
`COMP-002` also says plainly "Entry from outside allocates pass `1`."

`LIFE-016` governs the loop occurrence's own shape: "Every operation occurrence in the loop carries
one `LOOP` enclosing segment with the loop identifier and current pass; branch and fan-out segments
remain in their outer-to-inner positions." So the new occurrence carries the outer `FANOUT` segment
for the second object followed by a `LOOP` segment at pass 1, in that outer-to-inner order.

The first object's retained loop pass is irrelevant to this allocation because the pair key differs.

Expected result. `STEP`, disposition `COMPLETED`, empty reason codes. The loop is entered at pass
`1` under the second object's context, with the loop occurrence carrying the outer fan-out segment
and a `LOOP` segment at pass 1, independent of whatever pass the first object's loop reached.

## What these derivations do not establish

They fix the judgment, classification, reason codes and pass allocation from the text. They do not
fix canonical bytes, which follow from construction.
