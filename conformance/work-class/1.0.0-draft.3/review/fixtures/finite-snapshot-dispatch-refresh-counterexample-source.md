# Fictional card policy requiring dispatch refresh

Source identifier: `finite-card-snapshot-policy`. Source revision: `revision-2-counterexample`. Obligation identifier: `issue-card`. This is a documentary counterexample. No external policy owner, organization or reviewer approved it.

The card issuer may issue the exact proposed card only while its grant, credentials, scope, amount bound and revocation status remain current at native commitment. Approval at proposal time alone does not authorize a later send. A revocation before native commitment withdraws permission immediately. The host must refresh those facts and establish their ordering relative to the native commitment. A 300 second proposal permit cannot preserve permission after such a revocation. An uncertain send requires investigation and grants no permission to resend.

For this documentary comparison, consider an otherwise exact ungated definition using LIFE-008's 300 second proposal snapshot, with its source identity/revision and all four LIFE-003 accepted record subjects hypothetically bound to this source. Accepted status and matching digests are supplied facts. They do not establish that this definition expresses the source's dispatch-time refresh and withdrawal requirements.

The comparison has no mechanical consumer refusal expectation: the consumer does not infer English policy meaning from accepted status. The documentary source-correspondence judgment must reject the ungated mapping. A deployment that falsely accepts it cannot claim to have enforced this source.
