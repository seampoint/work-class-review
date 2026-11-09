# Work-class Specification Draft 3

Specification-only public review snapshot for `seampoint.work-class/1.0.0-draft.3`, pin `sha256:fd52d69dd3c3546bff2cec9d46fb8d6b942fd57b77b0a3ab8377a592e80d00b6`. See [LICENSE.md](LICENSE.md) for rights and path boundaries. The specification remains a draft, and the conformance evidence covers development verification.

Start with the [reviewer packet](conformance/work-class/1.0.0-draft.3/review/records/REVIEWER-PACKAGE-20261108.md) and [freeze](conformance/work-class/1.0.0-draft.3/review/records/DRAFT3-PUBLIC-REVIEW-FREEZE-20261108.md). This package contains 138 requirements, 34 manifested contract files, 2484 indexed cases and 12 specimen artifact-index families. The preparation record binds the tested implementation separately from this package's source commit, avoiding a self-referential commit claim.

## Reproduce

Use Node.js 24.10.0 and CPython 3.14.8. Install locked dependencies with `npm ci --ignore-scripts` and `npm ci --ignore-scripts --prefix conformance/work-class/1.0.0-draft.3/typescript`. Python dependencies are vendored; their native binaries have platform limits recorded in their notices. Current evidence applies to its recorded platform only.

Run `python3 -B scripts/verify-review-package.py --out runs/reviewer-all --scope all` from the package root. This validates the complete emitted inventory and explicit evidence overlay, checks schemas and corpus, runs both consumers against every frozen expected result, compares complete results, runs units/type checking and specimen checks. It does not regenerate every historical source judgment, reproduce private reviews, qualify a host or test every platform. `--scope inventory`, `support`, `corpus` or `specimens` selects a smaller scope; smaller scopes do not imply all-scope success. Use a fresh output directory each time. Optional `--case-id` selects corpus cases and is not a full-corpus pass.

Each indexed fresh process has a 600-second and 32 MiB per-channel bound. Outer corpus limits are 21,600 seconds per consumer. Limits are reproduction allowances, not performance claims. Reports preserve commands, exits and before/after emitted inventories. Set `WORK_CLASS_CHILD_CAPTURE_DIR` to a fresh directory to retain native child streams. The bank native XML check has separately declared dependencies in its native-format folder. Host integration and live-provider duties require separate evidence.

The canonical suite retains its exact original bytes. The [reviewer evidence overlay](conformance/work-class/1.0.0-draft.3/suite/reviewer-evidence-overlay-20261108.json) accounts for included and explicitly omitted internal evidence with original hashes. [OMITTED-REFERENCES.md](OMITTED-REFERENCES.md) identifies excluded provenance targets. Complete frozen cases and expectations are included; private planning, correspondence, Git history and raw historical run archives are not. A hash identifies retained evidence; it does not promise a public download or reproduce a review.

The aggregate specimen command covers eleven families and the verifier also runs the information-flow supplement. The bank source constructor has separate [instructions](conformance/work-class/1.0.0-draft.3/review/records/bank-independent-source-20261008/README.md); its reproduction does not regenerate other families.

Claim limits remain APPARATUS_ONLY, DRAFT_NOT_ADOPTED and NOT_QUALIFIED. Fictional policies have no real-process-owner acceptance. Reference-consumer results do not establish complete mediation, truthful observations, production durability or mission assurance.
