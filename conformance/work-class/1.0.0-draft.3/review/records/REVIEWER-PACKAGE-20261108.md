# Draft 3 specification reviewer guide

Start with the [specification](../../../../../library/work-class-specification/1.0.0-draft.3/README.md), then the [evidence freeze](DRAFT3-PUBLIC-REVIEW-FREEZE-20261108.md). This edition selects the specification and conformance apparatus. The contract pin is `sha256:fd52d69dd3c3546bff2cec9d46fb8d6b942fd57b77b0a3ab8377a592e80d00b6`.

Draft 2 established exact authority, recorded effects and shared constraints as a portable contract. Draft 3 extends the work model with recovery from disputed and uncertain effects, current-source checks and clock duties, permission exclusions, bound assessments and a finite information-custody profile. The specification states which duties belong to the checker, coordinating host and evidence provider. In particular, a host must commit the returned work state, affected selected-registry state and canonical event preimages together before dispatch.

Review the [case index](../../cases/index.json), [suite manifest](../../suite/manifest.json) and [work-only recovery supplement](../../../../../tests/draft3_work_recovery/SEALED-CASES.json). These artifacts contain complete expected judgments against the specified contract. Both reference implementations and the exact fixture bytes are included. The top-level `README.md` gives the dependency and verification commands. Use `OMITTED-REFERENCES.md` to identify deliberately excluded historical references.

The most useful review findings give an exact counterexample, the implicated rule and a complete trace. Distinguish incorrect interpretation of a fictional source, an incorrect expected judgment, a runtime discrepancy and an unenforced host premise. The tested contract does not itself authenticate the physical world or operate real connectors.
