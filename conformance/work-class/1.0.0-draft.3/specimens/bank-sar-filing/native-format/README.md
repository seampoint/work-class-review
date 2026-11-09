# Native SAR format and acknowledgement fixtures

This packet retains unmodified upstream schemas, a closed URI inventory and exact fictional payload constructors. The selected format is FinCEN SAR XML 2.0 with the April 2026 version 1.7 guide. It contains one report, one subject and no attachment. The initial and full corrected/amended packages preserve separate identities. No file in this packet was transmitted to FinCEN.

The schema inventory binds 22 downloaded files by SHA-256 and records their source URIs. It explicitly maps the ACK schema's unavailable base-schema URL to the retained official base schema for the same namespace. The validator permits only this closed inventory and has no network fallback. Upstream notices remain in their original files; the project supplies no new license grant for those files.

The serializer retains emitted-field correspondence and 38 reviewed conditional field or indicator decisions. The conditional inventory covers selected semantic families, rather than every optional XSD leaf. It identifies one remaining source question about completeness of the subject's relationships with the bank. Successful schema admission does not settle that question or establish that the report's substantive contents are complete.

The ACK adapter distinguishes processing messages from the formal acknowledgement. Its complete correlation envelope binds the exact submitted-payload, processing-message and acknowledgement SHA-256 values together with tracking identity, filename, activity sequence and prior filing identity. Processing-only envelopes bind an absent acknowledgement explicitly. The trusted authentication callback must return the independently authenticated complete envelope; a boolean or partial association does not suffice. The adapter compares the declared hashes with the supplied bytes and requires the authenticated envelope to match exactly. It retains every warning/error row. The selected C21 primary warning requires correction; all nonempty warning inventories require review. A processing acceptance alone does not establish filing, and a rejected attempt does not establish absence across other attempts or routes.

Native messages supply a submission date. These native ACK shapes supply neither an exact historical filing instant nor a provider event timestamp. The adapter retains those values as unknown and records host observation time separately. A qualified provider record must supply any timestamp required by a portable completion carrier. XML validity and a synthetic authentication callback do not qualify that provider.

## Reproduce the offline checks

Install the exact dependencies in `requirements-native.txt` into an SSD-backed environment, then run from the repository root with a fresh output directory:

```sh
python -B conformance/work-class/1.0.0-draft.3/review/verify-bank-native.py --report-directory runs/<fresh-run>/bank-native
```

The command writes expected judgments before execution, complete XML calls, correspondence, runtime versions and before/after source hashes. Its 26 checks cover both payloads, clean and warning acknowledgements, full amendment identity, processing-only results and forged or mismatched correlation. A second schema-valid acknowledgement with the same activity sequence and a different BSA Identifier is refused under the original envelope. Changing its declared hash without changing the independently trusted envelope is also refused, as are substituted processing bytes and incomplete authentication proofs. Previous output directories are refused. This is offline format and correlation evidence; real provider authentication, delivery, filing-interface qualification, substantive content review and regulatory compliance require separate evidence.
