#!/usr/bin/env python3
"""Bind the draft-3 development suite to its current cases and contract.

The manifest records author-derived expectations, without adoption or qualification.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

AREA = Path(__file__).resolve().parents[1]
ROOT = AREA.parents[2]
CONTRACT = ROOT / "library/work-class-specification/1.0.0-draft.3"
ROLES = [
    "AGGREGATE_EVALUATOR", "AUTHORITY_EVALUATOR", "CHOICE_LOOP_RUNTIME", "DEADLINE_RUNTIME", "FLOW_TRANSITIONS", "HOLDINGS_TRANSITIONS", "LINEAR_WORK_RUNTIME",
    "PARALLEL_FANOUT_RUNTIME", "REFERENCE_SINGLE_PROCESS_CONTENTION", "REVIEW_EVIDENCE", "RESERVATION_TRANSITIONS",
]
SPECIMENS = ["access-card", "bank-sar-filing", "equipment-return-to-service", "factual-customer-message-review", "information-flow", "permission-holdings", "pharmaceutical-batch-disposition", "roe-engagement", "sepsis-surveillance", "sepsis-surveillance-timing", "supplier-payment", "supplier-payment-recovery"]
EVIDENCE = [
    "review/EXPECTED-JUDGMENTS-CONTRACT.json",
    "review/JUDGMENT-CASE-REGISTER.json",
    "review/CONTRACT-DECISIONS.md",
    "review/fixtures/source-approved-finite-snapshot-revision1-source.md",
    "review/SNAPSHOT-ELIGIBILITY-SOURCE-REVIEW-20261009.md",
    "review/fixtures/finite-snapshot-dispatch-refresh-counterexample-source.md",
    "review/SNAPSHOT-ELIGIBILITY-DOCUMENTARY-BOUNDARY-20261009.md",
    "review/EQUIPMENT-SOURCE-MAPPING.md",
    "review/records/EQUIPMENT-FOUNDATION-20261006.md",
    "review/records/EQUIPMENT-COMPLETE-20261006.md",
    "review/RECOVERY-EXPECTED-JUDGMENTS.json",
    "review/RECOVERY-SOURCE-COVERAGE.md",
    "review/RECOVERY-WIRE.md",
    "review/records/recovery-source2-20261007/verification-record.json",
    "review/records/RECOVERY-DEVELOPMENT-20261007.md",
    "review/records/recovery-development-20261007.json",
    "review/TIMING-SOURCE-COVERAGE.md",
    "review/TIMING-WIRE.md",
    "review/records/TIMING-DEVELOPMENT-20261007.md",
    "review/records/timing-development-20261007.json",
    "review/records/timing-source-20261007/verification-record.json",
    "review/HOLDINGS-SOURCE-COVERAGE.md",
    "review/HOLDINGS-HOST-EXPECTED-JUDGMENTS.json",
    "review/fixtures/permission-holdings-revision1-source.md",
    "review/records/HOLDINGS-DEVELOPMENT-20261008.md",
    "review/records/holdings-development-20261008.json",
    "review/fixtures/INFORMATION-FLOW-SOURCE-COVERAGE.md",
    "review/ASSESSMENT-SOURCE-COVERAGE.md",
    "review/ASSESSMENT-HOST-EXPECTED-JUDGMENTS.json",
    "review/fixtures/factual-customer-message-review-revision1-source.md",
    "review/fixtures/factual-customer-message-review-revision1-selector-clarification.md",
    "review/records/ASSESSMENT-DEVELOPMENT-20261008.md",
    "review/records/assessment-development-20261008.json",
    "review/CDMO-SOURCE-COVERAGE.md",
    "review/CDMO-HOST-EXPECTED-JUDGMENTS.json",
    "review/records/CDMO-DEVELOPMENT-20261007.md",
    "review/records/cdmo-development-20261007.json",
    "review/records/cdmo-source3-20261007/verification-record.json",
    "review/records/cdmo-source3-20261007/python-full-result-hashes.json",
    "review/records/cdmo-source3-20261007/typescript-full-result-hashes.json",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    pin = "sha256:" + sha(CONTRACT / "contract-manifest.json")
    index = json.loads((AREA / "cases/index.json").read_text())
    if index["candidate_pin"] != pin:
        raise ValueError("case index is not at the current pin")
    cases = []
    for row in index["cases"]:
        path = AREA / row["path"]
        if sha(path) != row["sha256"]:
            raise ValueError(f"case bytes differ from the index: {row['id']}")
        cases.append({key: row[key] for key in ("id", "path", "sha256", "operation", "execution_target", "requirements")})
    requirements = sorted(row["id"] for row in json.loads((CONTRACT / "requirements.json").read_text())["requirements"])
    specimens = [{"id": name, "artifact_index": f"specimens/{name}/artifact-index.json", "artifact_index_sha256": sha(AREA / f"specimens/{name}/artifact-index.json")} for name in SPECIMENS]
    manifest = {
        "identity": "seampoint.work-class.suite/1.0.0-draft.3",
        "candidate_identity": "seampoint.work-class/1.0.0-draft.3",
        "specification_pin": pin,
        "suite_revision": "1",
        "status": "DEVELOPMENT_AUTHOR_DERIVED_EXPECTATIONS",
        "binding_rule": "Expected judgments derive from draft 3 normative text and exact input. Initial author derivation preceded consumer comparisons. Retained eleven-case normative repairs and later timing fixture corrections followed diagnostic comparisons and were frozen before repeated final verification. Timing and CDMO records distinguish source-derived expectations, corrections to test inputs and protocol refusals, runtime defects and unchanged repair-regression expectations. CDMO source revision 3 retains its independent human decisions and explicit host premises; its separate source correspondence remains PENDING. October 8 holdings records retain independently frozen registry, authority, lifecycle and host expectations, diagnostic fixture corrections, ordinary recovery actor repairs and exact repeated verification. The fictional bank source requires current preparation permission and current reviewer permission at filing reliance; valid regrant preserves a still-effective historical approval. Independently frozen flow and generated-completion source cases retain failed diagnostic runs, source construction repairs and runtime repairs separately. Bank initial filing, amendment and customer communication are explicit alternate traces with complete retained evidence; native XML validation and provider authentication remain separate from generic completion checks. Assessment records retain the independently frozen first source oracle, complete failed comparisons, adjudicated stimulus corrections, the evidence-refusal schema repair and separately frozen successor expectations. October 9 finite snapshot vectors use a newly authored fictional source permitting bounded proposal authority; their constructed accepted deployment records grant no real authority. Initial behavioral expectations, failed constructor and consumer comparisons, grounded identity and refusal-precedence corrections, and separately sealed repaired inventories are retained. Ungated restart-validation repairs reconstruct recorded dispatch decisions with the same forward rules. Source semantic approval remains documentary; the independently attributable technical negative boundary rejects a refresh-required source despite hypothetical mechanically accepted records. The runner compares complete canonical actual results.",
        "expectation_review": "Inherited draft 2 and October 6 equipment reviews remain historical evidence at their recorded pins. They do not establish review or qualification of this candidate. October 7 recovery, timing and CDMO records distinguish source-derived expectations, fixture corrections, independent consumer results, original adversarial verdicts, architect adjudication and repairs. The CDMO plan verdict was REVISE BEFORE IMPLEMENTATION and implementation verdict was REVISE BEFORE ACCEPTANCE. Those verdicts remain unchanged; final guarded verification and architect disposition do not imply another Sol review of the repaired bytes. October 8 holdings and assessment review verdicts and subsequent repairs are recorded separately at their exact input inventories. Source correspondence and real-provider reliability remain separate from consumer execution results.",
        "mandatory_requirements": requirements,
        "mandatory_roles": ROLES,
        "cases": cases,
        "specimens": specimens,
        "evidence": [{"path": path, "sha256": sha(AREA / path)} for path in EVIDENCE],
        "qualification": {"status": "NOT_QUALIFIED", "host_obligations": "documented in EXTERNAL-DEPENDENCIES.md; not qualified by this suite"},
    }
    target = AREA / "suite/manifest.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"pin": pin, "cases": len(cases), "requirements": len(requirements), "specimens": len(specimens), "suite_manifest_sha256": sha(target)}, indent=2))


if __name__ == "__main__":
    main()
