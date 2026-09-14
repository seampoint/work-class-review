# R10. A closure that reaches an unfired join through a child join names that join's construct

Written before changing either implementation. Found while proving D2-251's rebuilt state reachable.

Text. LIFECYCLE.md:289: "`construct_ids` is the raw UTF-8 sorted unique set of every parallel block or
fan-out whose split, expansion or join the closure traverses." The same paragraph: "The final branch
or object effect names its relationship to the join, the join's outgoing relationship when present,
and the block or fan-out."

Observed (both implementations, run 2026-09-12). A branch operation whose SEQUENCE edge reaches the
parallel join while the sibling branch is still OPEN: both name `parallel-1`, the join does not fire,
the branch obligation discharges and the instance stays ACTIVE. So both implementations already read
"traverses the join" as reaching it, whether or not it fires.

Derivation. The sentence names one set and one condition, "whose ... join the closure traverses",
with no distinction by how the closure arrived at the join. When a fan-out object's effect joins its
child pass and the fan-out join's outgoing relationship reaches the enclosing parallel join, the
closure has reached that parallel join exactly as a direct branch completion does. The enclosing
block is therefore in `construct_ids` together with the fan-out, and the join's outgoing relationship
from the fan-out join is in `relationship_digests`. Whether the parallel join then fires does not
change the set, as the direct case shows.

Required, both implementations: that closure's ROUTE detail names `["fanout-b","parallel-1"]` (raw
UTF-8 order) and the two relationship digests. TypeScript does this. Python names only the fan-out,
which is inconsistent with its own direct-arrival result under the same sentence.

Classification: implementation defect in Python, decided by one uniform sentence together with both
implementations' agreement on the direct case. Constitution gate 2.
