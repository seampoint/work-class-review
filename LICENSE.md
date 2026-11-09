# Licenses

This repository separates the open standard from the software and writing that accompany it.

## Specification

The normative documents, schemas, requirement inventory and contract manifest under `library/work-class-specification/1.0.0-draft.2/` and `library/work-class-specification/1.0.0-draft.3/`, together with exact copies of those files elsewhere in the repository, are licensed under the Community Specification License 1.0 in `LICENSE-SPECIFICATION.md`.

That license grants royalty-free copyright and Necessary Claims rights for conforming implementations of the specification. Its patent grant reaches only claims necessary to implement the normative specification within the scope recorded in `Scope.md`. It does not grant rights to authoring, translation, deployment, host-interception, integration or other technology that the specification does not require.

## Source code and conformance materials

Seampoint-authored source code, conformance cases, expected results, runners, reference consumers, host harnesses and application specimens under `conformance/work-class/1.0.0-draft.2/`, except exact copies of specification materials and the white paper named below, are licensed under the Apache License 2.0 in `LICENSE-CODE`.

For draft 3, the Seampoint-authored reference consumers, conformance cases and expectations, runners, host demonstrations, specimen artifacts and source tools under `conformance/work-class/1.0.0-draft.3/` are licensed under Apache 2.0 as included in the approved specification-only reviewer export. This excludes exact copies of specification materials, `review/paper/`, and `review/records/`. The exact export inventory is identified by `REVIEW-PACKAGE.json`. The selected Seampoint-authored programs and synthetic inputs and expected results in `review/records/bank-independent-source-20261008/` within that same conformance path are included in the Apache 2.0 grant. Third-party notices and upstream licenses continue to apply.

The root `package.json`, `package-lock.json`, `scripts/verify.sh` and code used to build the reviewer snapshot are also licensed under Apache 2.0. This includes the draft 3 export verification entry points `scripts/verify-draft3.sh` and `scripts/verify-review-package.py` and the sealed work-only recovery supplement under `tests/draft3_work_recovery/`.

## White paper

`conformance/work-class/1.0.0-draft.2/review/paper/WHITE-PAPER-1.0-r3b.md` is licensed under the Creative Commons Attribution 4.0 International Public License in `LICENSE-PAPER`.

## Draft 3 reviewer documents

In the approved specification-only reviewer export, the top-level `README.md`, `REVIEW-PACKAGE.json` and `OMITTED-REFERENCES.md`, the suite reviewer evidence overlay, and the four specification review records `DRAFT3-PUBLIC-REVIEW-FREEZE-20261108.md`, `DRAFT3-PUBLIC-REVIEW-FREEZE-20261108.json`, `REVIEWER-PACKAGE-20261108.md` and `REVIEW-PREPARATION-20261108.json` are licensed under the Creative Commons Attribution 4.0 International Public License in `LICENSE-PAPER`.

## Other materials

Files not covered above remain Copyright © 2026 Seampoint LLC. All rights reserved. Third-party components retain their own licenses; see `THIRD-PARTY-NOTICES.md`.

No license grants a right to use Seampoint trademarks except for reasonable factual attribution. See `TRADEMARKS.md`.
