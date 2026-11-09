# Supplemental consumer finding controls

This bundle contains 28 sealed requests for replay through the Python and TypeScript native adapters in 56 fresh processes. It supplements the 2,082 indexed conformance cases. It does not change their index, manifests or golden expectations.

The controls check four combinations of choice-label inventory order and route inventory order, six invalid label maps, legacy work-class and authority admission/readback, and six actual lifecycle proposal projection cases. The additional invalid map replaces one route label with a unique correctly typed undeclared value. Both inventories retain their cardinality, uniqueness and source order, isolating the requirement that their typed domains match exactly. An exact label map admits independently ordered inventories while preserving both arrays. The lifecycle projection retains the completion carrier for nonempty exclusive keys or `STOP_RETAIN` and omits a keyless `LEGACY_NONTERMINAL` carrier. Standalone authority admission of an optional carrier does not make that carrier the lifecycle's exact projection.

Twenty-five cases have independent complete expected result bodies, derived from the specification's digest and readback rules, its static admission refusals or its full immutable-state refusal envelope. Three positive proposal cases assert only `STEP` with `PERMITTED`; they also require full canonical result agreement between consumers. Those three cases do not assert independent complete golden outputs.

`CASES.json` binds every exact request wire, expected value and expectation kind to its presealed case-row digest. The original 27 rows retain their aggregate and sealed-input identities. The additional row was constructed separately from the original choice source before its native replay; the current aggregate binds all 28 rows. `PROVENANCE.json` identifies the retained synthetic source specimens, specification clauses, repository fixture builders and consumer source hashes. `verify-derivation.py` recomputes the source-derived requests and expected values and compares them with all 28 presealed rows before adapter replay. It does not use adapter responses to create expected results.

Run from the repository root after installing the repository's usual Python and TypeScript dependencies:

```sh
python3 -B conformance/work-class/1.0.0-draft.3/review/verify-consumer-findings-20261010.py --output-directory runs/consumer-findings-20261010-replay
```

The output directory must be new. The verifier retains raw stdin, stdout and stderr, exact commands, execution times, source guards and complete comparison results. It fails if the current contract pin, sealed stimuli, source provenance or tested consumer bytes differ. Dependencies are supplied by the local checkout; the replay does not fetch anything or use the authoring repository.

The specimens contain synthetic records. This evidence does not establish organizational acceptance, a native system integration, regulatory compliance or complete independent lifecycle proof.

Not checked: industry review and native host integration.
