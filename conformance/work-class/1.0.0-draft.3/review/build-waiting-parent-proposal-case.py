#!/usr/bin/env python3
"""Build D2-247: a child proposal admitted under a parent obligation WAITING on its child pass.

The checkpoint carries an incomplete child pass, so LIFE-019's all-DISCHARGED rule does not bite
and the waiting variant is admissible. PAR-001 keeps the parent WAITING because only the child
join resumes it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from composition_fixture import permitted_operation_proposal, proposal_for_occurrence
from corpus_common import CASES, exact_case, write_canonical_json
from lifecycle_factory import step_input


def _nested_module():
    path = Path(__file__).resolve().parent / "build-nested-parallel-closure-cases.py"
    spec = importlib.util.spec_from_file_location("nested_parallel_closure", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NESTED = _nested_module()
GROUP = CASES / "waiting-parent-proposal"


def build() -> None:
    base, outer = NESTED.setup_outer("D2-247")
    _permit, parent_dispatched, parent_effect = NESTED.execute(
        base, outer["state"], "outer-a", "d2-247-outer-a"
    )
    nested = NESTED.nested_entry_result(base, parent_dispatched, parent_effect)

    child = next(
        row["occurrence"] for row in nested["state"]["active"] if row["occurrence"]["step_id"] == "child-a"
    )
    proposal, authority_result = proposal_for_occurrence(
        base, nested["state"], child, event_id="proposal-d2-247"
    )
    expected = permitted_operation_proposal(base, nested["state"], proposal, authority_result)

    GROUP.mkdir(parents=True, exist_ok=True)
    write_canonical_json(
        GROUP / "D2-247.json",
        exact_case(
            "D2-247", "step", step_input(base, nested["state"], proposal), expected, [],
            "The checkpoint's parent obligation is WAITING on an exact existing child pass whose own obligations are still OPEN. LIFE-019 admits that waiting variant because the child-pass identity, the outer prefix, the obligation inventory and the acyclic nesting all agree, and because the pass is incomplete the rule that rejects an ACTIVE state holding an all-DISCHARGED pass does not apply. LIFE-007 then governs the proposal itself: current accepted authority and no shared budget give PERMITTED with an empty reason set and exactly one permit created, with the child occurrence moving to PERMITTED. PAR-001 keeps the parent obligation WAITING with its child-pass reference retained, because only the child join resumes it and no obligation in that pass has completed.",
        ),
    )


def main() -> None:
    build()
    print(json.dumps({"case_ids": ["D2-247"], "output": str(GROUP)}, indent=2))


if __name__ == "__main__":
    main()
