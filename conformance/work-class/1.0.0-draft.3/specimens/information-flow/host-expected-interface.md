# Protected-host scenario expectation interface

Status: independently selected expectations before host execution. These cases supplement exact pure-consumer cases. Every scenario requires a protected response reader; counts describe this one controlled operation, exclude fixture construction and do not assert production behavior.

The host observation is `{public_body,protected_diagnostics,read_deliveries,connector_invocations,onward_invocations,automatic_retries,model_calls,claim_consumed,release_consumed,context_restrictions_retained}`. Counts are decimal strings. `read_deliveries` counts making an admitted source result, partial result, existence-sensitive error or tool state reachable. `connector_invocations` counts immediate custody invocation; business acceptance is separate. `claim_consumed` reports the selected operation or historical intent after the controlled operation, including its stable logical intent; it is not a count of newly consumed claims. Existing claims remain true during evidence-only replay, including replay denied to an unauthorized reader. `release_consumed` reports the selected exact compensation release after the operation, including historical consumption. `protected_diagnostics:true` means diagnostics are retained only for a separately entitled protected route, never disclosed to an unauthorized reader. A replay response counts no new delivery or invocation. Protected diagnostics must never enter the independent public response context.

## Required fault boundaries

1. Fail before atomic READ union/claim commit: zero read deliveries, zero connector invocations, no new claim, old restrictions retained, no automatic retry. A later explicit fresh authorized attempt may commit and deliver once.
2. Commit READ union/claim, then stop before delivery: zero read deliveries, claim consumed, complete restrictions retained. Exact replay returns evidence only. A new claim for the same intent refuses. No automatic retry.
3. Deliver a partial protected result, existence-sensitive error or tool state after READ commit: one read delivery, claim consumed, complete restrictions retained even if the business result fails.
4. Fail before EXPOSE claim/release commit: zero connector invocations, no new claim or release consumption. A later explicit fresh authorized attempt may invoke once if every current condition still holds.
5. Commit EXPOSE claim/release, then stop before observed invocation: zero connector invocations, claim and release consumed, no automatic retry. Exact replay remains evidence-only. New-claim same-intent retry refuses. Later no-exposure proof does not reset the first profile.
6. Invoke immediate custody, then reject, return NOT_SENT, timeout or crash before result persistence: one connector invocation, claim and release consumed, no automatic retry. Business failure cannot prove that the connector saw no bytes.
7. Change policy, sender context, source revision, recipient entitlement or withdraw release before coordinated first exposure: zero connector invocations under the old authorization. Current authority or subject binding must fail. Change ordered after established exposure preserves historical claim and one invocation; it cannot recall bytes.
8. Exhaust event capacity: zero fresh read deliveries and connector invocations. Exact historical replay returns the old receipt and complete current state without advancing revision or consuming new capacity.

## Route admission expectations

- Independent clean client request plus immutable host constant: public body exactly `Unable to process this request.` with no newline; protected diagnostics absent; model calls zero; no protected source delivery or business connector invocation. The independently admitted constant response is a transport result, not an approved customer business message.
- Any restricted agent text, report case id, context id, diagnostic, protected selection or protected destination supplied to that constant service: refuse before public output; no constant-service invocation using those bytes. Host may separately use the original independently admitted request route.
- Missing flow profile, undeclared route, alternate credentials, redirect or multiple recipients: refuse before connector invocation. Endpoint spelling and credentials do not substitute for the protected exhaustive route mapping.
- Entitled immediate connector with ungoverned final recipient, or entitled final recipient through an unentitled connector: refuse the unadmitted chain. The first profile admits one immediate custody recipient; delayed onward transfer needs a separate mediated operation. Merely declaring final-recipient intent does not establish it.
- Entitled internal evaluator, log, reviewer or audit custodian: ordinary exact access and whole restrictions precede one delivery; purpose and case remain exact. An unentitled external evaluator/log or customer-service referral receives zero protected deliveries. Model calls remain zero in this apparatus unless an explicitly selected synthetic evaluator invocation is separately counted.
- An explicitly inventoried unmediated manual route remains a deployment gap. The host cannot claim complete mediation or publish an allow result for that route.

## Current authority and recovery expectations

- Revoked Director remit, selected release withdrawal, expired release or withdrawn consultant designation before exposure: zero connector invocations; no fresh claim or release consumption. Prior immutable evidence remains retained.
- Regrant restores an unused current, effective, unwithdrawn and unexpired exact release only when all other exact conditions hold: one possible invocation under a fresh serialized claim. Regrant after withdrawal or consumption produces zero new invocations and does not reset history.
- A false withdrawal asserted by an actor outside the source's authorized withdrawal remit does not alter authenticated current release state. The host rejects that writer act. An unchanged valid release may still be used once; the rejected assertion alone supplies no authority.
- Restart with complete unused state and current exact policy may allow one new serialized disclosure. Restart after withdrawal refuses. Restart after possible exposure returns evidence only and invokes nothing. Altered or trimmed history refuses even when outer hashes are recomputed.
- Refresh may update allowed clocks, observations and current complete registry basis. Changed immutable artifact, source configuration, native content, selected context/intent/claim or human evidence refuses before invocation.

Not checked: actual host implementation, durable failure cuts, distributed writer participation, authentic source classifications, human understanding, actual downstream behavior or industry acceptance.
