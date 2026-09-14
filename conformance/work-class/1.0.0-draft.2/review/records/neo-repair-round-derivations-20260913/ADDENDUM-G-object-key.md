# Addendum to the gate-2 repair round derivations, 2026-09-13

Written from the specification text before changing either consumer for this rule. Extends rule G of
DERIVATIONS.md (sha256 e45c86e62fef79913ed61c46474113fe67f3f3f490a9cbb59bb83df10337a912).

## G-object-key. A continuation outside every fan-out segment has a null object key

Text. LIFECYCLE.md:36: "If the path contains a fan-out segment, the occurrence's top-level `object_key`
equals the innermost fan-out segment's key; otherwise it is null." LIFECYCLE.md:291: when the pass joins,
"the successor removes the discharged branch or fan-out segment and every region-local segment after it,
retains the common outer prefix, and then appends only segments introduced by the continuing structural
closure."

Derivation. When a fan-out pass joins and its continuation activates an operation, a split's branch heads or
a fan-out's objects, each new occurrence's `object_key` follows its own enclosing path: the key of its
innermost fan-out segment, or null when the path has none. The object key of the occurrence that completed
the pass does not carry across the join. Required, both consumers.

Demonstration that motivated it (does not decide it). `gate2-review-20260912/g4_object_key.py`: a top-level
fan-out with one object, object-step to fanout-join to after. After the object's matching effect, Python
creates `after#1` with enclosing `[]` and `object_key` `object-1`; TypeScript creates it with `object_key`
null.
