# Work-class specification 1.0

Identity: `seampoint.work-class/1.0.0-draft.2`. This private candidate defines deterministic governance for bounded work. Read `Specification.md` first, then the profile document that matches the work class.

This README is the informative index. The manifest binds the complete candidate distribution, including this index. Every other manifest-listed file is normative.

The manifest covers linear work, typed constraints, business authority, cumulative aggregates, shared reservations, choice and bounded loops, activity deadlines, structured parallel work and frozen fan-out. `LIFECYCLE.md` defines the common governed transition, and `COMPOSITION.md` defines the cumulative profile family. Repeated expansion passes, dynamic fan-out, compensation, general cancellation, child-work invocation and distributed execution are excluded and recorded as explicit exclusions.

The contract has no dependency on Language of Work, Constraint Calculus, Workbench or Neo source code. Source mappings in the conformance package explain retained semantics; they do not add requirements to this contract.

The adapter protocol uses canonical JSON lines and the operations `capabilities`, `validate`, `evaluate`, `aggregate-step`, `deploy`, `step`, `readback` and `check-evidence`. A response includes a typed decision, refusal when applicable, receipts and complete next state. Admission failures leave state and reservations unchanged.

`EXTERNAL-DEPENDENCIES.md` describes facts and capabilities supplied by an organization or host. Those records close the description of the boundary. They do not qualify a production deployment. The reference host qualifies serialized single-process transitions and contention only.

The candidate is not a public release, license grant or production-readiness claim. Any normative change creates a new candidate identity and preserves this candidate’s results.
