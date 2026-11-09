# Bank SAR filing, amendment and independent customer message

This development specimen uses fictional Maple Research Bank records and synthetic endpoints. It implements the selected controlled gateway contract. Its first custody recipient, MRB-GOVERNED-FILING-GATEWAY, is a terminal synthetic sink with zero onward calls. FINCEN-BSA-EFILING remains reviewed payload metadata. Nothing in this packet was submitted to FinCEN or sent to a customer.

## Retained workflows

The 54 author-derived source cases cover current preparation permission; exact filing approval and current reviewer/submission holdings; revocation, valid regrant and incompatible roles; signing before the reviewer's first permission grant; full native XML and nine separate supporting records; protected reads, agent handoff and first filing disclosure; generated filing identifiers and complete warning inventory; a separately approved full amendment; rejection of the initial acknowledgement as evidence of that amendment; and an independently authorized customer message.

Three lifecycle streams retain source-derived complete expected results:

- `requests.jsonl` and `results-derived.json`: initial filing, seven requests.
- `amendment-requests.jsonl` and `amendment-results-derived.json`: separate amendment, seven requests.
- `customer-requests.jsonl` and `customer-results-derived.json`: independent customer message, nine requests.

The amendment and customer workflows are alternate traces starting from the same retained initial filing exposure. They do not demonstrate one combined chronological registry run. Both preserve the exact original global flow history. The amendment has a new package, full corrected/amended XML, assessment, attributable approval, token, native submission identity, receipt and BSA Identifier. Its authenticated prior-filing source retains the complete original native record and generated prior BSA Identifier.

The expected results were authored by the agent that implemented the TypeScript consumer. They are author-derived, not independent of that consumer. Separate source-only review checked all 54 frozen case hashes, full payload and supporting records, complete prior receipt, exact human bindings, original global history and immutable provider identities without reading consumer code or actual results. That independent seal remains historical at predecessor pin `sha256:120242f6e3a9cc67348932386460144ace5924d9b02852b878093b74a7af82a3`. The snapshot-eligibility successor mechanically regenerates the current inputs and commitments; it requires fresh consumer evidence and does not carry the earlier source seal forward. The current case inventory and source coverage record that distinction.

## Contract and provider boundaries

The signing-time SAR_APPROVE witness is an authenticated historical-provider assertion. It contains the retained holdings configuration and state, signing instant and eligibility result. The evidence-only human leaf does not execute a nested current holdings query. The filing gate separately checks the same reviewer's current SAR_APPROVE and the executor's current SAR_SUBMIT against the installed mutable registry. Revocation preserves historical approval; a valid regrant can restore reliance while the same approval remains current, unwithdrawn and unexpired. No live reviewer session is required for filing.

The selected assessment and human subject bind the complete XML bytes, ordered manifest, all request fields, native format and serializer identity, and exact native correspondence digest. The selected assessment context retains the complete emitted-field and conditional correspondence metadata once, plus all nine supporting record bodies. This preserves the complete reviewed evidence while avoiding redundant copies. The amendment authority is near the existing 1 MiB bound; adding records or fields requires a fresh size check.

The completion contract retains provider-generated BSA Identifier, native submission identity, disposition and complete canonical warning/error inventory with exact nominal types and valid scalars. It also matches the exact admitted request, generated receipt identity/time, accepted filing status and processing stage. It does not interpret the warning string, qualify a real acknowledgement or create a correction duty. The complete raw receipt is separately bound to the native record digest, operation, permit, dispatch and exact request, and requires current protected reporting-reader authority.

The portable native-format packet under `native-format/` retains upstream schemas, closed offline validation, complete fictional XML, field correspondence and acknowledgement normalization. One source question remains about completeness of the subject's relationships with the bank. Schema validity does not settle substantive report completeness. The real acknowledgement shapes supply neither a precise historical filing instant nor a provider event timestamp. A qualified provider must supply timestamps required by a portable completion record. No idempotency, authoritative absence lookup, cancellation, all-route participation or atomic external permission guarantee is inferred from a token or synthetic callback.

Durable submission recovery, protected conflict handling and the persistent calendar duty service are separate host-demo components. Their retained runs establish their tested local semantics. They do not qualify a real filing provider, establish five years of custody, prove every bank filing route participates, or prove restrictions cover unmediated memory, retrieval, logging or output routes. `source-coverage.json` records those boundaries and remaining scenario gaps.

## Reproduce

Run the specimen verifier from the repository root with a new SSD-backed report directory:

```sh
python3 -B conformance/work-class/1.0.0-draft.3/specimens/bank-sar-filing/verify-specimen.py --report-directory runs/<fresh-run>/bank-specimen
```

The verifier checks artifact hashes and the contract pin, then compares both consumers against the retained source-derived results for all three streams. It retains complete request, stdout and stderr bytes. It does not regenerate expected results from a consumer. Native schema and acknowledgement checks use the separate command documented in `native-format/README.md`.
