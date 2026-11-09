# Fictional source revision v4

Written October 7, 2026, before the successor builder ran or either consumer received these artifacts. The eight obligation identifiers and their complete English texts are preserved from source revision `v3`. This note supplies the additional fictional provider and timing choices required to encode them. These choices do not describe an existing live provider or clinical practice.

## Source obligations and representation

| Obligation | Successor representation | Limit retained |
|---|---|---|
| `alert-window-cap` | Preserve the separate two-alerts-per-six-hour aggregate, evaluated before deployment. | Excluded from the work-class lifecycle correspondence; host invocation remains required. |
| `antibiotic-requires-physician-order` | Preserve the attending's exact per-instance order, pharmacy attestation, patient, drug, dose and route. | Measurement and recognition evidence grant no authority. |
| `bundle-completion-is-reconciled` | Require native laboratory results and medication-administration evidence. Labs expiry stops; it cannot satisfy the join. Unknown outcomes preserve obligations. | Late records preserve facts and the recorded miss. They cannot reopen stopped work. |
| `cultures-before-antibiotics-unless-overridden` | Preserve the existing cultures-first or attending-recorded-reason gate. | The prospective delay greater than forty-five minutes is unproved. The whole obligation remains uncovered, with the partial gate named in residue. |
| `escalate-unacknowledged-page` | Preserve native attending acknowledgement and rapid-response successor. Select the first admitted SENT/UNKNOWN attempt, or ACCEPTED acknowledgement, as a conservative possible-send timer trigger. | Connector acceptance does not mean attending acknowledgement or delivery. NOT_SENT without ACCEPTED does not arm. Contradictory accepted reports retain dispute and arm conservatively. |
| `hour-one-bundle` | Two immutable recognition-anchored duties, one for labs and one for antibiotic administration, each due after 3600 seconds with `AT_OR_AFTER` expiry. | Both targets lie on every normal completion path. Explicit stop paths may retain unresolved duties. |
| `screening-under-standing-protocol` | Preserve registered-nurse authority, exact screening set, protocol version and withdrawal. | No new test or executor permission is introduced. |
| `vitals-freshness` | Provider-measured time on both readiness and antibiotic authority decisions; `0 <= CLOCK - measured_at <= 900`. | A refresh request has no age prerequisite. The inherited caller-supplied `vitals_age_seconds` field remains reported interface data, not freshness proof. |

## Provider declarations and subjects

Recognition uses fictional provider `sepsis-recognition-system`, source `recognition-log`, record type `sepsis-recognition`, native record `recognition-4471`, revision `recognition-r1`. Its complete fields are nominal patient and alert identifiers. Both `event_time` and selected recognition time are 07:58. `observed_at` is 07:58:30. The instance wrapper and deployment authorization cover the complete immutable record. Patient and alert fields bind the root request and both target requests exactly. The extra alert identifier in each target request is an explicit successor interface choice.

The authorization clock is 07:59. Initial ward time is 07:59. Alert proposal and dispatch occur at 08:00; native delivery occurs at 08:01. Both event duties are therefore due 08:58, rather than 09:00, 09:01 or one hour after later target activation. Provider authenticity, complete record selection and truthful time remain host assertions.

Vitals use fictional current-applicable record selection from `monitoring-feed` / `vitals-stream` / `current-vitals-measurement`. The observation's patient subject resolves from the proposal. Its native complete declared fields are patient identity and nominal INSTANT `measured_at`. The provider returns the current applicable measurement for that patient; the caller cannot nominate a historical record ID. The observation response uses zero freshness against the authority clock and separately proves patient equality. An `ELAPSED_LTE` relation independently proves measurement age. Both operand instants use `t.instant`.

The authority roots for readiness and antibiotic decisions explicitly select `monitoring-feed` alongside `hospital-identity-provider`. This binds reliance on the declared measurement provider under the inherited root provider inventory; it does not authenticate a live provider or establish clinical reliability.

The retained readiness and antibiotic thresholds remain 900 seconds. Readiness measured at 08:15 for a decision at 08:30 passes at equality. A measurement at 08:14:59 with a newly retrieved response at 08:30 fails at age901. Antibiotic decisions use the same check at their own clock, independently of any prior readiness assessment. Refreshing vitals remains permitted when the previous measurement is stale.

## Graph and source correction

The root, parallel branches, native-results join, bounded readiness loop and physician-order step remain. Remove the labs EXPIRY-to-join edge and set its event-duty expiry target to null. This corrects the old representation, which could advance without a native laboratory result and bypass the mandatory antibiotic target. It does not remove or weaken an obligation. Antibiotic expiry also stops. Page expiry still routes to rapid response and then rejoins; that path still traverses both mandatory hour-one targets before normal completion.

The page timer uses first possible send because the source supplies no independently attributable page-delivery event. It is an explicit conservative successor interpretation. The complete native attending acknowledgement still discharges the page obligation. Its connector ACCEPTED response does not do so.

## Acceptance status

The source is authored fiction. Source confirmation, correspondence review, policy decision and deployment authorizer use `synthetic:specimen-proxy-*` identities. ACCEPTED proxy records permit apparatus construction only. No human acceptance, clinical validation, implementation qualification or production deployment is claimed.
