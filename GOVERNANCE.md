# Governance

These rules govern the specification and its conformance apparatus. They carry over, for this work, the obligations of Neo's constitution (`planning/constitution.md` at `seampoint/neo` commit `e20b8a06`: claim limits, P5, P7, review and verification, and the 2026-09-13 amendment) and the process rules of the draft 2 completion plan. Changes to these rules are recorded under Amendments with a date and the decision behind them.

## Candidate identity

The candidate pin is the SHA-256 of the contract manifest. Any change to a normative document, schema or expected result creates a new pin. Every result, review and record stays attached to the pin it was produced under.

## Changing the specification

No normative or schema change lands without the specification owner's approval of its wording. A proposed change states the affected behavior, the decision, its compatibility effect, the decisive cases and the implementation mapping.

When an implementation exposes behavior the text does not decide, record the gap and classify it: an implementation defect, a specification gap needing a proposed change, or behavior that must be refused or excluded. Code does not become the specification by landing first.

## Expected results

Every expected judgment, state and digest is derived from the specification text and sealed with a hash before either consumer runs on it. Implementation output is never the expected answer. A construction fix may change bytes; it may not change a sealed judgment.

## The two consumers

The TypeScript and Python consumers are co-equal. Behavior claimed as conforming must produce the same public result or refusal in both. When they differ, the text decides: if it decides, fix the consumer that contradicts it; if it does not, the owner decides the rule and both consumers follow. Agreement between the consumers is not evidence that either matches the text.

## Verification

Each build step gets one complete verification pass (`scripts/verify.sh`) when it is complete. Results are reported with the commands run and their output, including failures and known debt. Run reports, export reports and scratch output are never committed; freeze records carry their hashes.

## Review

Independent adversarial review is required before adopting or changing the specification or a schema, changing public validation or runtime decision behavior, changing an authority or security boundary, or raising a claim ceiling. Independent means the reviewer did not author the change and does not edit it during review. Before a candidate's freeze, that review may be batched and run once over the accumulated changes, provided every expected result was derived before either consumer ran and every intermediate build passed a complete verification pass. Corrections made after a review round are recorded as unreviewed until reviewed.

## Open review phase

Seampoint LLC is the maintainer and editor during the open review phase. Outside readers are invited to report findings under `CONTRIBUTING.md`; the project does not yet accept outside specification text or source code.

The normative specification is available under the Community Specification License 1.0, the conformance apparatus and reference code under Apache 2.0, and the white paper under Creative Commons Attribution 4.0. `LICENSE.md` records the path boundaries. `Scope.md` records the bounds of the specification and its Necessary Claims commitment. `Notices.md` records patent disclosures, exclusions, license acceptances and withdrawals.

A later decision may open a contribution process. That requires published contributor terms, named maintainers and editors, a written decision process and an appeal path before the first outside contribution is accepted.

## Claims

[CLAIM-CARD.md](CLAIM-CARD.md) sets what may be claimed. Consumer agreement, a passing suite and agent review do not raise a ceiling.

## Publication

Pushing to `seampoint/work-class-specification`, publishing or opening a reviewer snapshot, inviting reviewers and any external disclosure each need the owner's approval for that action. Open licenses do not authorize Seampoint personnel to publish an unapproved candidate.

## Records

Contract decisions live in `conformance/work-class/1.0.0-draft.2/review/CONTRACT-DECISIONS.md`. Reviews, sealed derivations and freeze records live under `conformance/work-class/1.0.0-draft.2/review/`. Record each durable decision once, where it stays current.

## Amendments

**2026-09-14:** Governance moved with the specification from `seampoint/neo`. Run reports are no longer committed.
