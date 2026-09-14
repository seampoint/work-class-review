#!/usr/bin/env python3
"""Check that every requirement a case cites resolves to a defined requirement.

`check-corpus.mjs` binds citations to the frozen judgment only for `D2-` case identifiers, so
cases outside that prefix have their citations checked for presence but never for resolution.
Nothing checks, for any case, that a cited identifier exists in `requirements.json`.

This control closes that gap. It reports rather than repairs: a dangling citation is a defect
in the case or in the requirements catalog, and which one is wrong is a judgment call for the
project owner, not for this script.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE.parent
REVIEW = CANDIDATE / "review"
ROOT = CANDIDATE.parents[2]
CONTRACT = ROOT / "library" / "work-class-specification" / "1.0.0-draft.2"
sys.path.insert(0, str(REVIEW))
from corpus_common import candidate_pin  # noqa: E402


def defined_requirements() -> dict:
    rows = json.loads((CONTRACT / "requirements.json").read_text())["requirements"]
    return {row["id"]: row for row in rows}


def judgments() -> dict:
    contract = json.loads((REVIEW / "EXPECTED-JUDGMENTS-CONTRACT.json").read_text())
    return {row["id"]: row for row in contract["judgments"]}


def main() -> int:
    defined = defined_requirements()
    contract = judgments()
    failures: list = []
    cited: set = set()
    contract_bound = unbound = 0

    cases = json.loads((CANDIDATE / "cases" / "index.json").read_text())["cases"]
    for row in cases:
        case_id = row["id"]
        requirements = row.get("requirements") or []
        for requirement in requirements:
            cited.add(requirement)
            if requirement not in defined:
                failures.append({
                    "case_id": case_id,
                    "requirement": requirement,
                    "detail": "cited requirement is not defined in requirements.json",
                })
        # Citation equality against the frozen judgment is enforced by check-corpus.mjs only
        # for D2- identifiers. Record which cases have no such binding at all.
        judgment = contract.get(case_id)
        if judgment is None:
            unbound += 1
        else:
            contract_bound += 1
            if judgment["normative_references"] != requirements:
                failures.append({
                    "case_id": case_id,
                    "requirement": None,
                    "detail": "citations differ from the frozen judgment",
                })

    uncited = sorted(set(defined) - cited)
    result = {
        "status": "PASS" if not failures else "FAIL",
        "identity": "seampoint.work-class.citation-namespace-control/1.0.0-draft.2",
        "candidate_pin": candidate_pin(),
        "cases_checked": str(len(cases)),
        "requirements_defined": str(len(defined)),
        "requirements_cited": str(len(cited)),
        "requirements_uncited": str(len(uncited)),
        "uncited_requirement_ids": uncited,
        "cases_bound_to_a_frozen_judgment": str(contract_bound),
        "cases_with_no_frozen_judgment": str(unbound),
        "failures": failures,
    }
    print(json.dumps(result, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
