#!/usr/bin/env python3
"""Materialize twelve draft-2 exact-vector candidates from admitted fixtures.

The source fixture's complete input and expected result are retained. This
builder does not invent policy or reconstruct a result from an implementation.
D2-036 is a separate multi-step specimen, materialized after its late-effect
request is derived from the admitted no-effect transition.
"""

from __future__ import annotations

import json
from pathlib import Path

from corpus_common import exact_case, write_canonical_json


TARGETS = {
    "D2-020": {
        "group": "morning-vector-batch",
        "source": "cases/lifecycle-foundation/D2-012.json",
        "requirements": ["LIFE-005", "LIFE-007"],
        "scenario": "A proposal supplies a registry request whose expected revision is older than the admitted registry state.",
        "derivation": "LIFE-005 and LIFE-007 require the registry revision supplied with a proposal to equal both the request event revision and the admitted registry revision. The stale registry is refused before any work or budget root changes.",
    },
    "D2-031": {
        "group": "morning-vector-batch",
        "source": "cases/foreign-effects/D2-118.json",
        "requirements": ["LIFE-010"],
        "scenario": "A well-formed attributable effect has no permit or dispatch, but supplies the shared-budget settlement binding.",
        "derivation": "LIFE-010 classifies an attributable effect without a governed permit as FOREIGN. The supplied shared-budget binding permits retention and blocks the affected partition without discharging a work occurrence.",
    },
    "D2-034": {
        "group": "morning-vector-batch",
        "source": "cases/failure-no-effect/D2-099.json",
        "requirements": ["LIFE-011"],
        "scenario": "Affirmative no-effect evidence is authorized for an operation whose failure behavior follows its failure edge.",
        "derivation": "LIFE-011 treats a complete affirmative no-effect assertion as a failed operation. The retained evidence follows the declared failure behavior and does not create a success route.",
    },
    "D2-036": {
        "group": "morning-vector-batch",
        "source": "cases/failure-no-effect/D2-099.json",
        "requirements": ["LIFE-012"],
        "scenario": "A conclusive effect arrives after an authorized no-effect conclusion for the same native operation.",
        "derivation": "LIFE-012 requires a later conclusive fact with the same native operation identity to remain disputed when it contradicts an earlier no-effect conclusion. The prior release evidence remains in the record.",
    },
    "D2-067": {
        "group": "morning-vector-batch",
        "source": "cases/foreign-effects/D2-228.json",
        "requirements": ["LIFE-010"],
        "scenario": "A foreign attributable effect has no governed permit or dispatch and identifies a shared-budget partition.",
        "derivation": "LIFE-010 retains a well-formed foreign effect as disputed evidence. Its explicit shared-budget binding blocks the affected partition and leaves work progression unchanged.",
    },
    "D2-068": {
        "group": "morning-vector-batch",
        "source": "cases/foreign-effects/D2-118.json",
        "requirements": ["LIFE-010"],
        "scenario": "A foreign effect is retained with an explicit shared-budget anchor when its exact contribution cannot be projected.",
        "derivation": "LIFE-010 requires an unprojectable foreign effect to remain visible and to block the declared anchor. No normal route is inferred from incomplete projection data.",
    },
    "D2-084": {
        "group": "morning-vector-batch",
        "source": "cases/prior-binding-runtime/D2-277.json",
        "requirements": ["LIFE-006", "WCS2-013"],
        "scenario": "A missing prerequisite is presented together with an authority input that would fail evaluation.",
        "derivation": "LIFE-006 and WCS2-013 put event prerequisites ahead of policy evaluation. The missing predecessor is therefore refused as PREREQUISITE_MISSING without changing state.",
    },
    "D2-086": {
        "group": "morning-vector-batch",
        "source": "cases/lifecycle-foundation/D2-012.json",
        "requirements": ["LIFE-006", "WCS2-013"],
        "scenario": "A stale lifecycle revision is supplied for an otherwise limit-sensitive proposal.",
        "derivation": "LIFE-006 and WCS2-013 require the admitted work-state revision before composition limits or policy decisions are evaluated. The stale revision is refused without state change.",
    },
    "D2-101": {
        "group": "morning-vector-batch",
        "source": "cases/effect-foundation/D2-030.json",
        "requirements": ["LIFE-010", "RES-007"],
        "scenario": "A shared-budget governed occurrence produces an established effect whose actual amount cannot be projected to the permit contribution.",
        "derivation": "LIFE-010 and RES-007 retain the effect as UNEXPECTED, restore or retain disputed exposure, and block the affected partition instead of routing normally.",
    },
    "D2-128": {
        "group": "morning-vector-batch",
        "source": "cases/failure-no-effect/D2-100.json",
        "requirements": ["LIFE-010", "LIFE-011", "RES-008"],
        "scenario": "A budget-backed no-effect assertion has lifecycle completion evidence but no reservation-release administration.",
        "derivation": "LIFE-010, LIFE-011 and RES-008 keep lifecycle completion authorization separate from reservation administration. Missing release administration refuses the transition and preserves both supplied states.",
    },
    "D2-155": {
        "group": "morning-vector-batch",
        "source": "cases/foreign-effects/D2-240.json",
        "requirements": ["LIFE-010"],
        "scenario": "A governed effect supplies a registry binding whose affected anchors differ from the permit budget row.",
        "derivation": "LIFE-010 requires the event anchors to match the permit's exact budget rows. A mismatch is refused before evidence or state is admitted.",
    },
    "D2-156": {
        "group": "morning-vector-batch",
        "source": "cases/effect-foundation/D2-026.json",
        "requirements": ["LIFE-010"],
        "scenario": "A first matching established effect settles a permit using the current registry revision, which is later than the permit's reservation revision.",
        "derivation": "LIFE-010 binds settlement to the current registry request and exact permit contribution. A later valid registry revision is admissible when all bindings and histories agree, and the work occurrence completes.",
    },
}

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "cases" / "morning-vector-batch"
def load_source(spec: str) -> dict:
    return json.loads((ROOT / spec).read_text())


def transform(case_id: str, source: dict) -> dict:
    return source


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for case_id, meta in TARGETS.items():
        source = transform(case_id, load_source(meta["source"]))
        case = exact_case(case_id, source["operation"], source["input"], source["expected"], meta["requirements"], meta["derivation"])
        write_canonical_json(OUT / f"{case_id}.json", case)
    print(json.dumps({"case_ids": list(TARGETS), "count": len(TARGETS), "output": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
