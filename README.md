# Work-class standard: reviewer snapshot

Private technical-review snapshot of `seampoint.work-class/1.0.0-draft.2`, frozen at pin `sha256:dc925a1473d788e69f8912136e84796b143bc60dfe118ae004ba310a0108f1ea`. Claim ceiling `APPARATUS_ONLY`: see [CLAIM-CARD.md](CLAIM-CARD.md).

## Start here

1. [Reviewer packet](conformance/work-class/1.0.0-draft.2/review/REVIEWER-PACKET-20260914.md): what the candidate is, what changed in draft 2, the evidence and the known gaps.
2. [Specification](library/work-class-specification/1.0.0-draft.2/README.md).
3. The four application specimens under [conformance/work-class/1.0.0-draft.2/specimens/](conformance/work-class/1.0.0-draft.2/specimens/), each with its own README and claim boundary.
4. The [freeze record](conformance/work-class/1.0.0-draft.2/review/FREEZE.json) and the [independent review round](conformance/work-class/1.0.0-draft.2/review/records/FREEZE-REVIEW-20260913.md).

## Verify

Requires Node.js 24.10.0 and CPython 3.14.6.

```sh
npm ci --ignore-scripts
npm ci --ignore-scripts --prefix conformance/work-class/1.0.0-draft.2/typescript
bash scripts/verify.sh first-run
```

The pass runs the corpus check, both reference consumers over all cases with every result compared across languages, the four specimen verifiers, the TypeScript consumer's typecheck and unit tests, and the pin-currency control. Reports go to the ignored `runs/` directory by default; set `WORK_CLASS_RUNS` to another directory.

## Reporting findings

Cite the pin, the document and paragraph, the exact input, the rule, the expected result and the practical effect. Say whether the finding is a specification gap, an implementation defect, an evidence gap or a host obligation.

[REVIEWER-SNAPSHOT.md](REVIEWER-SNAPSHOT.md) records what this snapshot contains and what it deliberately leaves out.
