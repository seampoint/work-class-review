#!/usr/bin/env python3
"""Build exact lifecycle authority-withholding vectors from AUTH-005 and LIFE-007."""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_refusal, authority_specimen, credential_check, envelope_digest, envelope_validity_check, old_digest, revocation_check
from corpus_common import CASES, digest, exact_case, write_canonical_json
from lifecycle_factory import base_lifecycle, step_input, withheld_proposal


GROUP = CASES / "authority-withholding"


def authority_event(base: dict, mutator) -> dict:
    root = base["clock_result"]["state"]["active"][0]["occurrence"]
    authority_input, _ = authority_specimen(
        shared_budget=False,
        instance_id=base["clock_result"]["state"]["instance_id"],
        occurrence_id=root["occurrence_id"],
        mutator=mutator,
    )
    event = copy.deepcopy(base["proposal_event"])
    event["event_id"] = "proposal-authority-withheld"
    event["authority_input"] = authority_input
    event["credential_ids"] = sorted(
        (row["id"] for row in authority_input["credentials"]),
        key=lambda value: value.encode("utf-8"),
    )
    event["observation_digests"] = sorted(
        (digest("authority-observation", row) for row in authority_input["observations"]),
        key=lambda value: value.encode("utf-8"),
    )
    return event


def main() -> None:
    base = base_lifecycle()
    state = base["clock_result"]["state"]

    def expire_envelope(request: dict, _original: dict) -> None:
        request["envelope"]["temporal_validity"]["valid_until"] = "2026-09-10T04:30:00Z"

    event = authority_event(base, expire_envelope)
    refusal = authority_refusal([envelope_validity_check(event["authority_input"])])
    case = exact_case(
        "D2-014",
        "step",
        step_input(base, state, event),
        withheld_proposal(base, event, refusal),
        [],
        "The altered envelope and every dependent digest remain exact. Its exclusive upper validity bound equals the selected current authority instant, while all other current checks remain valid. AUTH-005 therefore returns AUTHORITY_NOT_ESTABLISHED with sole reason ENVELOPE_EXPIRED; LIFE-007 records that policy withholding and no permit.",
    )
    write_canonical_json(GROUP / "D2-014.json", case)

    def expire_credential(request: dict, _original: dict) -> None:
        request["credentials"][0]["validity"]["valid_until"] = "2026-09-10T04:30:00Z"

    event = authority_event(base, expire_credential)
    event["event_id"] = "proposal-expired-credential"
    refusal = authority_refusal([credential_check(event["authority_input"], "credential-1")])
    case = exact_case(
        "D2-015",
        "step",
        step_input(base, state, event),
        withheld_proposal(base, event, refusal),
        [],
        "The selected credential, its authenticated-record digest and the proposal credential inventory remain exact after rebinding. Its exclusive upper validity bound equals the selected current authority instant. AUTH-005 returns AUTHORITY_NOT_ESTABLISHED with sole reason CREDENTIAL_EXPIRED; LIFE-007 records a withholding without a permit.",
    )
    write_canonical_json(GROUP / "D2-015.json", case)

    def revoke_envelope(request: dict, original: dict) -> None:
        old_envelope_digest = old_digest("authority-envelope", original["envelope"])
        observation = next(
            row
            for row in request["observations"]
            if row["query"]["at"] == request["clock"]["instant"]
            and row["query"]["subject_digest"] == old_envelope_digest
        )
        observation["revoked"] = True

    event = authority_event(base, revoke_envelope)
    event["event_id"] = "proposal-revoked-envelope"
    request = event["authority_input"]
    refusal = authority_refusal([revocation_check(request, envelope_digest(request), request["clock"]["instant"])])
    case = exact_case(
        "D2-016",
        "step",
        step_input(base, state, event),
        withheld_proposal(base, event, refusal),
        [],
        "The exact current revocation query for the selected envelope reports revoked true and every other current or historical query remains available, current and false. AUTH-005 returns AUTHORITY_NOT_ESTABLISHED with sole reason REVOKED; LIFE-007 retains the complete authority-refusal digest and creates no permit.",
    )
    write_canonical_json(GROUP / "D2-016.json", case)
    print(json.dumps({"case_ids": ["D2-014", "D2-015", "D2-016"]}, indent=2))


if __name__ == "__main__":
    main()
