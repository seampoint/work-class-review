# Supplier bank change and invoice payment with explicit recovery

Status: constructed from fictional source revision 2 and the draft-3 contract. Both consumers passed 28 independently frozen source-derived requests. The [verification record](../../review/records/recovery-source2-20261007/verification-record.json) binds the candidate, inputs, results and runtime source hashes. External source and policy review remain pending. No organization has adopted the illustrative 5 USD incident and 10 USD rolling allowance.

The [revision 2 source](../../review/fixtures/supplier-payment-recovery-revision2-source.md) retains the seven original supplier-change and payment obligations. The [original revision 1 specimen](../supplier-payment/README.md) remains separate. This specimen selects recovery in its work definition and shared registry before either identity is hashed, and uses a coherent revision 2 authority source and work class.

The ordinary trace covers two separately deployed instances, independent confirmation and payment release, exact supplier/account evidence, the 1,000 USD shared ceiling, dispatch, unknown payment and later settlement. The [recovery expectations](recovery/expectations.json) add seven financial scenarios:

- Correct an unexpected 151 USD report to the authorized 150 USD execution, preserving the original journal prefix and applying the disposition to complete the original work.
- Establish no past or future payment effect, reverse the prior provider assertion, release only covered uncertainty and stop the original occurrence under its declared failure rule.
- Leave an unexpected payment unresolved with its evidence and conservative exposure retained.
- Withhold an exception for two possible 150 USD executions. The full 300 USD case exceeds the 5 USD incident limit, and 800 + 300 exceeds the ordinary 1,000 USD ceiling. Retain the additional possible execution and consume no exception allowance.
- Apply the same registry disposition to a separate instance without completing its different payment occurrence or changing accounting again.
- Propose separately authorized fresh work after affirmative no effect. This uses a different instance and occurrence and performs no retry in the stopped instance.
- Settle payment evidence while its supplier-master prerequisite is disputed, then apply the retained result once when work-only recovery establishes the original master fact. Retain the current registry selection for restart; a rehashed checkpoint omitting it is refused.

The [source coverage record](source-coverage.json) distinguishes the original typed work-source correspondence from recovery obligations implemented by the normative profile, registry policy and lifecycle application. Review, source confirmation, organizational authority, native provider evidence and complete writer coverage are synthetic fixture assertions. They do not establish human review, authentic provider custody, durable persistence or production deployment capabilities.

`build-specimen.py` constructs requests and expected results without importing either consumer or consulting consumer output. `artifact-index.json` hashes the generated evidence. The financial recovery requests begin at explicit complete checkpoints retained in the request bodies; they are branches from the ordinary trace, not additional operations after a completed payment. `verify-specimen.py` freezes these bytes before consumer execution and checks both independent consumers against the same source-derived results.
