# Reviewer packet: `seampoint.work-class/1.0.0-draft.2`, pre-freeze candidate

Prepared 2026-09-14 for readers who want the current draft 2 text before its semantic freeze. It supersedes `REVIEWER-PACKET-PROVISIONAL-20260913.md`. Status: pre-freeze, claim ceiling `APPARATUS_ONLY`. Nothing in this packet is adopted or qualified. One independent review round has run over the draft 2 changes. Its text-decided findings and the specification owner's decisions on the questions it raised are applied at this pin; those corrections have not themselves been independently reviewed.

Commit `84da38c4` (this packet is added in the commit after it) on branch `codex/work-class-specification`. Candidate pin (SHA-256 of `contract-manifest.json`): `sha256:dc925a1473d788e69f8912136e84796b143bc60dfe118ae004ba310a0108f1ea`.

## What to read

Start with `library/work-class-specification/1.0.0-draft.2/README.md`, then `Specification.md`, then the document for your interest: `LIFECYCLE.md` (events, decisions, deployment, effects, disputes, restart), `COMPOSITION.md` (definitions, choice, loops, deadlines, parallel work, fan-out), `AUTHORITY.md` and `AUTHORITY-CHECKS.md` (grants and acts), `AGGREGATES.md`, `RESERVATIONS.md` and `RESERVATION-RECORDS.md` (shared budgets), `PROTOCOL.md` (the adapter protocol), `EXTERNAL-DEPENDENCIES.md` and `SCOPE-AND-BOUNDARY.md` (what the host supplies). The JSON schemas are generated and closed; `requirements.json` is the requirement inventory generated from the text.

Four non-normative application specimens exercise the text end to end under both reference consumers, one per domain, under `conformance/work-class/1.0.0-draft.2/specimens/`: `access-card/` (access), `supplier-payment/` (money), `sepsis-surveillance/` (care) and `roe-engagement/` (force). Each README states its claim boundary. The rules-of-engagement specimen is built from the rules-of-engagement example in section 2.3.1 of the SEI reference architecture for assuring ethical conduct in lethal autonomous weapons systems; `roe-engagement/MAPPING.md` maps each component of that architecture to the construct that carries it or states it as outside scope, and `EXPOSED-RULES.md` in the sepsis and rules-of-engagement directories lists the general rules each exposed. All four specimens' review acts are labelled synthetic proxies because no person has performed them.

## What changed since the provisional packet

- Amendment batch (2026-09-13): deployment requires accepted correspondence, source-confirmation and policy-decision evidence (LIFE-003); fan-out cycle admission defines "through"; one serialized writer per organization-and-instance namespace and per reservation registry; every relied-on human act has an attributable return; seven decisions on effect reconciliation, dispatch, deadlines and restart.
- Rules the specimens exposed and draft 2 closes: a deadline measured from a completed ancestor occurrence (`ELAPSED_FROM_ANCESTOR`, COMPOSITION 5.1), so the sepsis hour-one bundle runs from the alert; `failed_checks` on authority refusals and in the lifecycle `AUTHORITY` detail, so a withholding names the condition that failed; and clarifying sentences in LIFE-006, LIFE-008, LIFE-010, LIFE-015 and RES-WIRE-004.
- Reservation rules settled by the specification owner: the ordered reason list for a record without a completion mismatch; a record whose attributed request differs from the reserved request is retained as a dispute for settle and release alike; `LATE_EFFECT_AFTER_RELEASE` applies only to an effect record; a reservation state bound to another pin is `STATE_INVALID`.
- Three consumer divergences settled: a construct above the declared profile is `UNSUPPORTED_FEATURE`; a return channel invalid at evaluation is `ACT_NOT_AUTHORIZED`; an observation dated after its query is `INPUT_INVALID`.
- Review round corrections: five clarifying sentences (reason precedence over the ordered list; a `BLOCKED_DISPUTE` occurrence stays blocked under an inherently disputed classification; the null-key entry for an unprojectable fact; the `UNKNOWN` consequence in the LIFE-006 row; the `BUDGET` detail on effect observations that apply a registry result) and consumer fixes that the text decides. Decisions on the questions the round raised (2026-09-14): the deployment review records' binding conditions precede their availability conditions; a fresh `REJECTED` dispatch attempt on a consumed permit is admitted, `DISPATCH_REFUSED` when its request matches and `DISPUTED` when it changed; the lifecycle `AUTHORITY` detail no longer caps `failed_checks`; the reservation transition does not compare an observed request with the actual evidence fields, because it cannot see completion bindings. `conformance/work-class/1.0.0-draft.2/review/CONTRACT-DECISIONS.md` records each decision with its reasoning; `review/records/FREEZE-REVIEW-20260913.md` records the review round.

## Evidence at this pin

425 conformance cases; 295 of the 296 contract judgments have exact vectors (D2-193 pending). Both reference consumers, TypeScript and Python with no shared evaluator, reproduce all 425 byte for byte with zero differing results. The four specimens pass under both consumers. Repository gates: 681 of 681. Expected judgments are derived from the text before either consumer runs. These are apparatus results. The independent review round ran at `sha256:5a75779d...`; the corrections and decisions applied since then have not been independently reviewed.

## Known gaps

Recorded limitations: no accepted independent review exists for the access-card correspondence subject (blocker AC-REV-001), and every specimen's review acts remain labelled synthetic proxies; the sepsis specimen's two timing approximations (time zero is the alert's delivery, and the attending's window runs from the page step's activation) are draft 3 design inputs; a disputed effect has no attributable human exit in draft 2 (CR-02); the rules-of-engagement specimen records a required escalation with no runtime trace, no operator-initiated stop and no age bound on the operator's decision act, all draft 3 design inputs; the Python consumer's unit tests under `python/tests/` are stale and outside the gates.

Draft 3 items: CR-02a and CR-02b (disposition of a disputed reservation and lifecycle dispute clearance), CR-06 (business-day boundaries), CR-07 (host conformance profile), pre-approved materiality thresholds, and the specimen design inputs listed in `CONTRACT-DECISIONS.md`.

## Manifest

| File | SHA-256 (prefix) |
|---|---|
| `AGGREGATES.md` | `5847e166f7e6f38d...` |
| `AUTHORITY-CHECKS.md` | `70f4e2b681629a42...` |
| `AUTHORITY.md` | `a549ead8e17b2b9c...` |
| `COMPOSITION.md` | `6ab89348b2427251...` |
| `EXTERNAL-DEPENDENCIES.md` | `afd78d0cef496504...` |
| `LIFECYCLE.md` | `089c5cbf1e183078...` |
| `PROTOCOL.md` | `de3802b22b80e20a...` |
| `README.md` | `e9b9fc1dfcdfa3a4...` |
| `RESERVATION-RECORDS.md` | `3803696cff1fd629...` |
| `RESERVATIONS.md` | `1ff66eba843b1b2b...` |
| `SCOPE-AND-BOUNDARY.md` | `08296d9fff10b881...` |
| `Specification.md` | `48470078d954ce1a...` |
| `aggregate.schema.json` | `b5ce6cfec0cc415a...` |
| `authority.schema.json` | `2f4a7ecd0113df91...` |
| `boundary.schema.json` | `c0dfdb12c8d56de8...` |
| `evidence.schema.json` | `a83111e571c86bf8...` |
| `lifecycle.schema.json` | `00793114d85eae95...` |
| `protocol.schema.json` | `57a9f8aea572bfb4...` |
| `requirements.json` | `97a3c9af062d8aab...` |
| `reservation.schema.json` | `a80e9375c76f7251...` |
| `schema-bundle.json` | `bc250d77e33fc9e3...` |
| `work-class.schema.json` | `f1590559ca1855aa...` |

Full hashes are in `contract-manifest.json`; the pin is the SHA-256 of that file's bytes.
