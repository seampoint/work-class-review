#!/usr/bin/env python3
"""Build exact replay, restart, and early-precedence lifecycle vectors."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, exact_case, write_canonical_json
from lifecycle_factory import (
    base_lifecycle,
    dispatch_event,
    dispatch_result,
    permitted_proposal,
    replay_result,
    stateful_refusal,
    step_input,
)


def build() -> list[dict]:
    base = base_lifecycle()
    proposal = base["proposal_event"]
    permitted = permitted_proposal(base)
    dispatch = dispatch_event(base, permitted, event_id="dispatch-for-replay")
    dispatched = dispatch_result(permitted, dispatch, disposition="DISPATCH_RECORDED", reasons=[], occurrence_status="DISPATCHED")
    cases = []

    cases.append(
        exact_case(
            "D2-037",
            "step",
            step_input(base, permitted["state"], proposal),
            replay_result(permitted["state"], proposal["event_id"]),
            ["LIFE-004", "LIFE-019"],
            "The exact proposal event is already retained. Replay returns its historical decision, permit, transition-state digest, and transaction digest with the current state unchanged and replay true.",
        )
    )

    altered = copy.deepcopy(proposal)
    altered["native_request"]["fields"][0]["value"]["value"] = "151"
    cases.append(
        exact_case(
            "D2-038",
            "step",
            step_input(base, permitted["state"], altered),
            stateful_refusal(permitted["state"], "REPLAY_CONFLICT"),
            ["LIFE-004", "LIFE-019"],
            "The retained proposal event identifier is reused with different complete event bytes. Replay conflict precedes current revision and policy checks.",
        )
    )

    for case_id in ["D2-070", "D2-071"]:
        cases.append(
            exact_case(
                case_id,
                "step",
                step_input(base, dispatched["state"], proposal),
                replay_result(dispatched["state"], proposal["event_id"]),
                ["LIFE-019", "WCS2-002"],
                "The exact old proposal is replayed after the later dispatch transition. Historical decision bytes and transition commitments remain fixed while the returned complete state is current.",
            )
        )

    malformed = copy.deepcopy(proposal)
    del malformed["executor"]
    malformed_input = step_input(base, permitted["state"], malformed)
    malformed_input["definition_digest"] = "sha256:" + "f" * 64
    cases.append(
        exact_case(
            "D2-080",
            "step",
            malformed_input,
            {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
            ["LIFE-002", "LIFE-018"],
            "The proposal omits its required executor while the definition digest is also wrong. Closed schema admission selects SCHEMA_INVALID before digest identity.",
        )
    )

    digest_first = copy.deepcopy(altered)
    digest_first["event_id"] = proposal["event_id"]
    digest_input = step_input(base, permitted["state"], digest_first)
    digest_input["definition_digest"] = "sha256:" + "f" * 64
    cases.append(
        exact_case(
            "D2-081",
            "step",
            digest_input,
            stateful_refusal(permitted["state"], "DIGEST_MISMATCH"),
            ["LIFE-002", "LIFE-019"],
            "The complete definition does not match its supplied digest, and the retained event identifier also carries altered bytes. Definition identity precedes replay conflict.",
        )
    )

    binding_later = copy.deepcopy(proposal)
    binding_later["instance_id"] = "case-2"
    cases.append(
        exact_case(
            "D2-082",
            "step",
            step_input(base, permitted["state"], binding_later),
            stateful_refusal(permitted["state"], "REPLAY_CONFLICT"),
            ["LIFE-004", "LIFE-019"],
            "The retained proposal identifier is reused with altered instance bytes. Replay conflict is selected before the later event-to-instance binding failure.",
        )
    )
    return cases


def main() -> None:
    cases = build()
    for case in cases:
        write_canonical_json(CASES / "replay-precedence" / f"{case['id']}.json", case)
    print(json.dumps({"case_ids": [case["id"] for case in cases]}, indent=2))


if __name__ == "__main__":
    main()
