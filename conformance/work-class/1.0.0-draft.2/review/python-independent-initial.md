# Independent Python draft-2 initial checkpoint

This checkpoint records the independent implementation before any draft-2 suite handoff. The historical source reference supplied for the work was commit `ac2e457f6f5c481d4d5c5688b81c7297976fe0cc`.

No draft-2 TypeScript file, draft-2 implementation output, suite expected output, implementation-generated helper or implementation report was inspected. The implementation used only the manifested draft-2 normative prose and schemas copied into the Python input directory and the expressly allowed historical draft-1 Python baseline.

## Contract input

The final remediated candidate is copied under `conformance/work-class/1.0.0-draft.2/python/input`. Its raw contract-manifest SHA-256 and specification pin are `f300bd38c6e73360e5e0df06c25ac0a1894427f9ba713e58d2cd3dd06832e46d`. All 22 manifested files match their declared hashes. The copied schema-bundle raw SHA-256 is `75d38ec873573a539b069981419764b77dc69046491fa1f24e05d8b95dd58ae5`. The copied requirements raw SHA-256 is `d8541ea69e650d36605cb74b822598a23a355c83ad9b4970ff3ea6b2203d36e7`.

## Implemented files

The wire and in-process interfaces are `python/adapter.py` and `python/consumer.py`. The implementation modules are `implementation/common.py`, `artifacts.py`, `aggregate_contract.py`, `operations.py`, `work_class.py`, `lifecycle.py`, `authority.py`, `authority_acts.py`, `authority_observations.py`, `core.py`, `evidence.py`, `reservation_v2.py`, `composition.py` and `reference_host.py`. Contract-derived tests are in `tests/test_foundations.py`. `implementation/__init__.py` defines the package boundary. Pinned Python dependencies are copied under `python/vendor` so the adapter does not depend on adjacent implementation code.

## Implemented protocol surface

The adapter exposes all eight operations: `aggregate-step`, `capabilities`, `check-evidence`, `deploy`, `evaluate`, `readback`, `step` and `validate`. Its capability result claims `AGGREGATE_EVALUATOR`, `AUTHORITY_EVALUATOR`, `CHOICE_LOOP_RUNTIME`, `DEADLINE_RUNTIME`, `LINEAR_WORK_RUNTIME`, `PARALLEL_FANOUT_RUNTIME`, `REFERENCE_SINGLE_PROCESS_CONTENTION`, `REVIEW_EVIDENCE` and `SHARED_BUDGET_TRANSITIONS`.

The implementation covers restricted canonical JSON transport, schema-bundle resolution, artifact admission and readback, aggregate evaluation, authority evaluation, reservation registration and transitions, deployment authorization, proposal authority, prior-effect and actor-separation bases, atomic registry-scoped reservation, permit creation and renewal, dispatch and acknowledgement history, stable dispatch-attempt identity, governed and foreign evidence, duplicate and conflict retention, unknown outcome handling, affirmative no-effect authorization and release, exact replay, choice and loop routing, deadline clocks and atomic due-set behavior, parallel split and join, nested obligation frontiers, frozen fan-out object binding, work-state restart validation, initial-root installation, commit failure, exact retained-event replay, and serialized single-process work and budget contention.

## Contract-derived verification

The following command was run from the repository root without corpus or TypeScript access:

```text
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s conformance/work-class/1.0.0-draft.2/python/tests -p 'test_foundations.py' -v
```

The final checkpoint run executed 35 tests and all passed. The tests include public deploy and step paths; authority-only proposal, dispatch, effect, duplicate and conflict flows; budget-backed reserve plus effect settlement; budget-backed affirmative no-effect release with separate completion and registry administration evidence; exact deadline boundary and restart; a mixed blocked and eligible due set; rollback of every proposed expiry closure when another eligible expiry stops; parallel and fan-out joins; prior-effect and actor-separation bindings; altered-state rejection; transport failures; exact host install replay including changed or cross-candidate budget-root rejection; current-state exact event replay with historical budget input; commit failure; two-thread lifecycle contention; and atomic export of work and affected budget roots. Restart mutation checks reject a rehashed false clock decision, an incompatible clock disposition and a rehashed proposal-to-permit chain whose proposal digest does not match the exact replayed event.

The contract input was rehashed after the implementation work. The manifest hash remained `f300bd38c6e73360e5e0df06c25ac0a1894427f9ba713e58d2cd3dd06832e46d`, all 22 entries still matched, and the schema-bundle and requirements hashes remained unchanged.

Two bounded read-only Sol reviews examined the implementation and contract-derived test evidence. The first found that restart admission did not recompute the complete deployment authorization-to-evidence links and exact host installation replay did not compare the supplied budget roots. The second found that restart admission accepted incompatible decision receipt facts and exact replay did not recompute the proposal digest from a retained `PROPOSE` event. All four defects were corrected. The implementation also now emits budget-backed effect details in the contract's required `BUDGET`, then `EFFECT` order. The added checks cover altered deployment evidence, changed initial budget roots, false clock decision facts, false proposal identities and exact current-state replay without comparing retained historical budget input to the current registry root.

## Remaining limits before a conformance claim

The 35 local tests are contract-derived spot checks. They do not prove the complete frozen corpus, mutation catalog, exact expected bytes, every refusal-precedence combination, every aggregate reducer boundary, every authority observation permutation, every loop topology, all 64-level nesting cases, every obligation restart variant, every foreign and late-effect conflict permutation, or every multi-deadline fixed-point closure. The budget-backed lifecycle test isolates lifecycle and reservation composition by substituting one fixed successful authority result during reserve and replay; direct authority behavior has separate tests, but the combined path has not yet used one naturally produced authority result. The single-process host proves in-memory serialization and atomic root replacement only. It does not establish durable crash recovery, distributed coordination, authenticated provider facts or native connector enforcement.

The capability inventory is the implementation surface submitted for testing. `PROTOCOL.md` defines a capability result as a claim to test rather than a certificate. No role is described as qualified by this checkpoint.

The draft-2 qualification suite, expected judgments, TypeScript implementation and implementation-generated outputs remain unopened at this checkpoint. `npm run gates` was therefore not run because it may execute or expose those prohibited inputs. Suite comparison begins only after the lead records this checkpoint and authorizes the handoff.
