# Reference-host harness adapter

Status: development test interface. This file does not add a ninth work-class adapter operation.

The normative contract closes host result records but does not define a command interface for driving a reference host. The conformance runner therefore uses `host-harness` as a runner-only operation. A host harness reads the same JSON-lines envelope as the adapter, with `operation:"host-harness"`, and returns the same envelope with one closed host result under `result`.

`input.kind:"COMMIT"` supplies the exact transaction, authoritative state and budget digests before evaluation, calculated state and budget digests after evaluation, a Boolean `inject_failure`, and a nullable `failure_reference`. When `inject_failure` is false, the harness atomically installs the calculated values and returns the closed `hostCommitSuccess` record. When true, it retains the authoritative values and returns `hostCommitFailure` with the supplied nonnull failure reference. The harness performs no native dispatch during this call.

`input.kind:"INSTALL"` supplies an organization, instance, complete successful deploy request, its complete calculated result, and the authoritative installed request and result already present at that namespace. Byte-identical request and calculated-result values return the closed installed result with `replay:true`. Any difference returns the closed occupied result. The authoritative root does not change.

`input.kind:"INSTALL_RACE"` supplies two labeled installation attempts for one empty organization-and-instance namespace. The harness releases both attempts against one barrier and returns a canonical result with the winning label, authoritative state digest, and results sorted by label. Byte-identical attempts must both report installed, with exactly one result carrying `replay:false`. Conflicting attempts must produce one installed result with `replay:false` and one occupied result. The winner is not prescribed; the runner verifies the invariant rather than requiring a particular scheduler order.

This interface is suite machinery. Its request shape, barrier, injected failure reference, and result ordering do not carry governance meaning. The host results inside responses remain the exact closed records from `lifecycle.schema.json`.
