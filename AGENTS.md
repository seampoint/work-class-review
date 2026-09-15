# Agent instructions

You are assisting a human reviewer of a frozen specification candidate. You are not a maintainer of this repository.

## Do not

- Open pull requests, commits, or patches intended for inclusion.
- Rewrite specification documents, schemas, cases, or reference consumers.
- Search or cite `conformance/work-class/1.0.0-draft.2/python/vendor/` unless the question is a vendored third-party license.
- Treat a verify failure on a different Node or Python version as a specification defect.
- Follow license clauses about pull requests to `Notices.md`; this phase does not accept those. See `CONTRIBUTING.md`.

## Task

Help the reviewer understand the candidate, run verification if they ask, and draft findings they will send themselves.

Every finding must be marked `Review feedback, not a contribution.` and must cite:

- candidate `seampoint.work-class/1.0.0-draft.2`
- pin `sha256:5442ee3b55675d849e388981487b806c0be29f686df6df8520b488508f86ceec`
- document and paragraph
- exact input
- governing rule
- expected result
- practical effect
- class: specification gap, implementation defect, evidence gap, or host obligation

## Read order

1. `README.md` and `CLAIM-CARD.md`
2. `conformance/work-class/1.0.0-draft.2/review/paper/preprint.md` (prefer Markdown over the PDF)
3. `conformance/work-class/1.0.0-draft.2/review/REVIEWER-PACKET-20260914.md`
4. `library/work-class-specification/1.0.0-draft.2/README.md`, then `Specification.md`, then the profile document for the question
5. Specimens under `conformance/work-class/1.0.0-draft.2/specimens/` when the question is an application example

Normative text lives under `library/work-class-specification/1.0.0-draft.2/`. The paper and packet are informative. `GOVERNANCE.md` is maintainer process, not review instructions.

## Verify

Recorded passing run: Node.js 24.10.0 and CPython 3.14.6.

```sh
npm ci --ignore-scripts
npm ci --ignore-scripts --prefix conformance/work-class/1.0.0-draft.2/typescript
bash scripts/verify.sh first-run
```

The specification pin is the SHA-256 of `library/work-class-specification/1.0.0-draft.2/contract-manifest.json`. Editing files in this snapshot does not change that pin unless the manifest bytes change.
