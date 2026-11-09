#!/usr/bin/env python3
"""Build exact replay, authority, and lifecycle-binding precedence vectors."""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_refusal, authority_specimen, envelope_digest, old_digest, revocation_check
from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_budget_fixture import budget_lifecycle, initial_budget_success, reserve_for_proposal
from lifecycle_factory import base_lifecycle, stateful_refusal, step_input, withheld_proposal
from reservation_fixture import registered_state


GROUP = CASES / "additional-precedence"


def emit(case_id: str, base: dict, state: dict, event: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "step", step_input(base, state, event), expected, [], derivation),
    )


def replace_authority(event: dict, authority_input: dict) -> None:
    event["authority_input"] = authority_input
    event["credential_ids"] = sorted(
        (row["id"] for row in authority_input["credentials"]),
        key=lambda value: value.encode("utf-8"),
    )
    event["observation_digests"] = sorted(
        (digest("authority-observation", row) for row in authority_input["observations"]),
        key=lambda value: value.encode("utf-8"),
    )


def main() -> None:
    replay_base, _facts, original, accepted = initial_budget_success(event_id="proposal-d2-069")
    altered = copy.deepcopy(original)
    altered["budget_inputs"][0]["expected_revision"] = "0"
    registry_state = altered["budget_inputs"][0]["request"]["state"]
    registry_echo = {
        "registry_digest": altered["budget_inputs"][0]["registry_digest"],
        "affected_anchors": copy.deepcopy(altered["budget_inputs"][0]["affected_anchors"]),
        "state": copy.deepcopy(registry_state),
        "state_digest": digest("reservation-state", registry_state),
    }
    emit(
        "D2-069",
        replay_base,
        accepted["state"],
        altered,
        stateful_refusal(accepted["state"], "REPLAY_CONFLICT", [registry_echo]),
        "The current state retains proposal-d2-069 with its original canonical event digest. The repeated event identifier carries different registry-scoped budget input bytes because its outer expected revision changed from one to zero. LIFE-004 resolves this nonidentical replay before current revision or reservation semantics and returns REPLAY_CONFLICT with work and supplied registry state unchanged.",
    )

    mismatch_base = base_lifecycle()
    mismatch_event = copy.deepcopy(mismatch_base["proposal_event"])
    mismatch_event["event_id"] = "proposal-d2-092"
    occurrence_id = mismatch_event["occurrence"]["occurrence_id"]

    def change_source_revision(request: dict, _original: dict) -> None:
        request["source"]["revision"] = "source-revision-2"

    mismatch_authority, _ = authority_specimen(
        shared_budget=False,
        instance_id=mismatch_event["instance_id"],
        occurrence_id=occurrence_id,
        mutator=change_source_revision,
    )
    replace_authority(mismatch_event, mismatch_authority)
    emit(
        "D2-092",
        mismatch_base,
        mismatch_base["clock_result"]["state"],
        mismatch_event,
        stateful_refusal(mismatch_base["clock_result"]["state"], "BINDING_MISMATCH"),
        "The authority input is internally rebound to source revision source-revision-2, but the lifecycle definition remains bound to the earlier source revision. LIFE-007 requires exact source identity, revision, and obligation inventory equality before authority evaluation. The mismatch is an admission refusal and changes neither state nor budgets.",
    )

    budget_base, budget_facts = budget_lifecycle()
    revoked_event = copy.deepcopy(budget_base["proposal_event"])
    revoked_event["event_id"] = "proposal-d2-085"

    def revoke_envelope(request: dict, original_request: dict) -> None:
        original_envelope_digest = old_digest("authority-envelope", original_request["envelope"])
        observation = next(
            row
            for row in request["observations"]
            if row["query"]["at"] == request["clock"]["instant"]
            and row["query"]["subject_digest"] == original_envelope_digest
        )
        observation["revoked"] = True

    revoked_authority, _ = authority_specimen(
        shared_budget=True,
        instance_id=revoked_event["instance_id"],
        occurrence_id=revoked_event["occurrence"]["occurrence_id"],
        mutator=revoke_envelope,
    )
    replace_authority(revoked_event, revoked_authority)
    registry = registered_state(budget_facts)
    budget_input, _budget_output, _reservation = reserve_for_proposal(
        budget_base,
        budget_facts,
        registry,
        revoked_event,
    )
    budget_input["expected_revision"] = "0"
    budget_input["request"]["event"]["expected_revision"] = "0"
    revoked_event["budget_inputs"] = [budget_input]
    authority_refusal_value = authority_refusal([
        revocation_check(revoked_authority, envelope_digest(revoked_authority), revoked_authority["clock"]["instant"])
    ])
    emit(
        "D2-085",
        budget_base,
        budget_base["clock_result"]["state"],
        revoked_event,
        withheld_proposal(budget_base, revoked_event, authority_refusal_value),
        "The current revocation observation establishes that the selected authority envelope is revoked. The supplied registry transition also selects revision zero while the registry is at revision one, but LIFE-006 evaluates current authority before shared-budget revision and policy. The admitted authority withholding records AUTHORITY_NOT_ESTABLISHED, AUTHORITY_REQUIRED, and REVOKED; it creates no permit and does not evaluate or change the registry.",
    )

    print(json.dumps({"case_ids": ["D2-069", "D2-085", "D2-092"]}, indent=2))


if __name__ == "__main__":
    main()
