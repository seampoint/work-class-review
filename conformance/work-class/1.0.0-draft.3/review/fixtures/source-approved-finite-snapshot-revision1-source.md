# Fictional card issuance with finite proposal authority

Source identifier: `finite-card-snapshot-policy`. Source revision: `revision-1`. Obligation identifier: `issue-card`.

This is a newly authored development source. Its people, providers and approval records are fictional. The associated acceptance records are mechanically constructed test inputs. They do not record an external reviewer's acceptance or an organization's deployment permission.

The card issuer may issue the exact proposed card to the named beneficiary only after the configured authority, credential, scope, amount bound and revocation checks pass at proposal time. The configured per-action amount bound is 1000000 USD. This source selects no shared budget, holdings rule, information-flow rule or content-assessment rule.

The source owner approves a finite snapshot of those proposal checks. The resulting permit authorizes the exact request for at most 300 seconds, ending at its exclusive expiry. This source requires no second authority refresh or native atomic comparison with an external approval register at dispatch. Changes to the source facts after proposal do not withdraw the issued permit before that expiry. A later renewal would require a new proposal evaluation.

The host may execute one send under that permit. A reliable NOT_SENT result with no accepted acknowledgement leaves the permit available for one later send within its remaining validity. A send or uncertain send consumes the permit. An unknown completion stops the occurrence and retains its permit, dispatch and evidence. The host must not resend or issue a new permit for that occurrence after an uncertain send; a fresh observation may establish what happened without authorizing another execution.

Successful completion requires a provider record that identifies the card, beneficiary, amount, operation result, provider event and event time. Completion lookup uses the exact card identifier and retained dispatch. When no dispatch authorization was selected, its authorization digest is null. Missing or uncertain completion evidence stops the occurrence rather than treating a missing result as evidence that nothing happened.

An optional dispatch authorization requires a nonnull effective fence bound to the exact permit, request and connector. Once retained, its digest must accompany the dispatch. Omitting a selected gate or a retained authorization does not permit fallback to the ungated path.

Before a real deployment, a source reviewer must confirm that the actual process permits this finite snapshot, that changes after proposal may leave the permit effective for its remaining lifetime, and that the no-resend rule and completion evidence meet that process's obligations. A source requiring refresh at dispatch, withdrawal before native commitment, or a selected mandatory gate cannot be approved against this definition. Accepted record status alone does not establish that semantic correspondence.
