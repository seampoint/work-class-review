#!/usr/bin/env python3
"""Build lifecycle role and binding precedence cases."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, exact_case, write_canonical_json
from lifecycle_factory import (
    base_lifecycle,
    dispatch_event,
    permitted_proposal,
    stateful_refusal,
    step_input,
)


GROUP = CASES / "lifecycle-precedence"


def emit(case_id: str, value: dict) -> None:
    write_canonical_json(GROUP / f"{case_id}.json", value)


def main() -> None:
    base = base_lifecycle()
    permitted = permitted_proposal(base)

    unsupported = step_input(base, base["clock_result"]["state"], base["proposal_event"])
    unsupported["role"] = "DEADLINE_RUNTIME"
    del unsupported["event"]["authority_input"]
    emit(
        "D2-079",
        exact_case(
            "D2-079",
            "step",
            unsupported,
            {
                "status": "REFUSED",
                "code": "ROLE_UNSUPPORTED",
                "path": "",
            },
            [],
            "LINEAR with DEADLINE_RUNTIME is an admitted-enum but unsupported profile-role pair. Role selection precedes the deliberately missing proposal authority_input field, so the consumer returns ROLE_UNSUPPORTED without applying closed event shape or governance semantics.",
        ),
    )

    occurrence_fault = dispatch_event(base, permitted, event_id="dispatch-d2-083")
    occurrence_fault["permit"]["occurrence"]["occurrence_id"] = "sha256:" + "f" * 64
    emit(
        "D2-083",
        exact_case(
            "D2-083",
            "step",
            step_input(base, permitted["state"], occurrence_fault),
            stateful_refusal(permitted["state"], "BINDING_MISMATCH"),
            [],
            "The event's complete permit carries an occurrence identifier that does not equal the digest of its own occurrence fields and cannot identify the admitted active occurrence. Event-to-occurrence binding fails before the absent committed-permit prerequisite is considered.",
        ),
    )

    undeclared_executor = copy.deepcopy(base["proposal_event"])
    undeclared_executor["event_id"] = "proposal-d2-093"
    undeclared_executor["executor"]["participant_id"] = "undeclared-operator"
    emit(
        "D2-093",
        exact_case(
            "D2-093",
            "step",
            step_input(base, base["clock_result"]["state"], undeclared_executor),
            stateful_refusal(base["clock_result"]["state"], "BINDING_MISMATCH"),
            [],
            "The executor binding digest still resolves to the exact current authority executor, but participant_id names no declared work-class participant and differs from that authority actor. The lifecycle refuses the participant binding before creating a proposal record or permit.",
        ),
    )

    print(json.dumps({"case_ids": ["D2-079", "D2-083", "D2-093"]}, indent=2))


if __name__ == "__main__":
    main()
