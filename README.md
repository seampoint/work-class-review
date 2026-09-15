# Work-Class Governance Specification: review candidate

Open technical-review snapshot of `seampoint.work-class/1.0.0-draft.2`, frozen at pin `sha256:5442ee3b55675d849e388981487b806c0be29f686df6df8520b488508f86ceec`. Claim ceiling `APPARATUS_ONLY`: see [CLAIM-CARD.md](CLAIM-CARD.md).

## Start here

1. [Preprint](conformance/work-class/1.0.0-draft.2/review/paper/preprint.pdf), with [Markdown](conformance/work-class/1.0.0-draft.2/review/paper/preprint.md) and [TeX](conformance/work-class/1.0.0-draft.2/review/paper/preprint.tex) sources: the argument, architecture, evidence and limits.
2. [Reviewer packet](conformance/work-class/1.0.0-draft.2/review/REVIEWER-PACKET-20260914.md): what the candidate is, what changed in draft 2, the evidence and the known gaps.
3. [Specification](library/work-class-specification/1.0.0-draft.2/README.md).
4. The four application specimens under [conformance/work-class/1.0.0-draft.2/specimens/](conformance/work-class/1.0.0-draft.2/specimens/), each with its own README and claim boundary.
5. The [freeze record](conformance/work-class/1.0.0-draft.2/review/FREEZE.json) and the [independent review round](conformance/work-class/1.0.0-draft.2/review/records/FREEZE-REVIEW-20260913.md).

## Rights and review

The normative specification uses the [Community Specification License 1.0](LICENSE-SPECIFICATION.md). The conformance apparatus and reference code use [Apache 2.0](LICENSE-CODE). The paper uses [Creative Commons Attribution 4.0](LICENSE-PAPER). [LICENSE.md](LICENSE.md) defines the path boundaries; [Scope.md](Scope.md) and [Notices.md](Notices.md) record the Necessary Claims scope and current patent disclosure.

This phase requests technical findings, not contributed text or code. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Verify

Requires Node.js 24.10.0 and CPython 3.14.6. Those are the recorded versions for a passing run. A failure on another Node or Python version is not a specification defect; match the recorded versions before reporting a verify failure.

```sh
npm ci --ignore-scripts
npm ci --ignore-scripts --prefix conformance/work-class/1.0.0-draft.2/typescript
bash scripts/verify.sh first-run
```

The pass runs the corpus check, both reference consumers over all cases with every result compared across languages, the four specimen verifiers, the TypeScript consumer's typecheck and unit tests, and the pin-currency control. Reports go to the ignored `runs/` directory by default; set `WORK_CLASS_RUNS` to another directory.

## Reporting findings

Cite the pin, the document and paragraph, the exact input, the rule, the expected result and the practical effect. Say whether the finding is a specification gap, an implementation defect, an evidence gap or a host obligation.

[REVIEWER-SNAPSHOT.md](REVIEWER-SNAPSHOT.md) records what this snapshot contains and what it deliberately leaves out.
