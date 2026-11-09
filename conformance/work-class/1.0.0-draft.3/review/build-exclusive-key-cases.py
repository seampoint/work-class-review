"""Build apparatus-only cases for exclusive reservation keys."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, exact_case, write_canonical_json
from reservation_fixture import (
    effect_record,
    fixture,
    host_and_event,
    native,
    request,
    reservation_record,
    transition,
    zero_state,
)


GROUP = CASES / "exclusive-keys"
KEY_DEFINITION = [
    {
        "id": "card-identity-key",
        "slot": "card-identity",
        "namespace": "access-card",
        "projection": [{"field": "card_id", "type_ref": "IDENTITY"}],
        "retention": "RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE",
    }
]


def emit(case_id: str, input_value: dict, expected: dict, derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(
            case_id,
            "aggregate-step",
            input_value,
            expected,
            ["RES-001A", "RES-WIRE-004"],
            derivation,
        ),
    )


def claims(facts: dict, authority_key: str = "authority_a") -> list[dict]:
    return copy.deepcopy(facts[authority_key + "_result"]["required_exclusive_keys"])


def key_states(facts: dict, authority_key: str, reservation_id: str, event_id: str) -> list[dict]:
    authority = facts[authority_key]
    return [
        {
            "key_digest": row["key_digest"],
            "slot": row["slot"],
            "namespace": row["namespace"],
            "key": copy.deepcopy(row["key"]),
            "owner_instance": authority["proposal"]["instance"],
            "owner_occurrence": authority["proposal"]["occurrence"],
            "acquisition_event": event_id,
            "status": "HELD",
            "settlement_evidence": None,
        }
        for row in claim_rows(facts, authority_key)
    ]


def claim_rows(facts: dict, authority_key: str) -> list[dict]:
    registry = "sha256:placeholder"
    from corpus_common import digest

    registry = digest("reservation-registry", facts["configuration"])
    return [
        {
            "key_digest": digest(
                "exclusive-key",
                {
                    "registry": registry,
                    "slot": row["slot"],
                    "namespace": row["namespace"],
                    "key": row["key"],
                },
            ),
            "slot": row["slot"],
            "namespace": row["namespace"],
            "key": copy.deepcopy(row["key"]),
        }
        for row in claims(facts, authority_key)
    ]


def reserved_case() -> tuple[dict, dict, dict, dict]:
    facts = fixture(exclusive_keys=KEY_DEFINITION)
    state = zero_state(facts)
    supplied = claims(facts)
    event, host = host_and_event(
        facts,
        "RESERVE",
        "reserve-exclusive-1",
        "0",
        {"authority": facts["authority_a"], "histories": [], "exclusive_keys": supplied},
        administration=False,
    )
    core = copy.deepcopy(state["core"])
    core["reservations"] = [reservation_record(facts, "authority_a", event["id"])]
    core["exclusive_keys"] = key_states(facts, "authority_a", event["id"], event["id"])
    expected = transition(
        state,
        event,
        host,
        core,
        "RESERVED",
        reservation_id=event["id"],
        authority_result=facts["authority_a_result"],
    )
    return facts, state, request(state, event, host), expected


def main() -> None:
    facts, state, reserved_input, reserved = reserved_case()
    emit(
        "C3-exclusive-key-reserve",
        reserved_input,
        reserved,
        "A READY_FOR_RESERVATION result with one resolved card identity claims the configured exclusive slot atomically. The state retains the typed key digest and owner binding as HELD; no numerical budget or native effect is asserted.",
    )

    collision = copy.deepcopy(facts)
    collision_state = reserved["state"]
    event, host = host_and_event(
        collision,
        "RESERVE",
        "reserve-exclusive-2",
        collision_state["core"]["revision"],
        {"authority": collision["authority_b"], "histories": [], "exclusive_keys": claims(collision, "authority_b")},
        administration=False,
    )
    expected = transition(
        collision_state,
        event,
        host,
        copy.deepcopy(collision_state["core"]),
        "WITHHELD",
        authority_result=collision["authority_b_result"],
        reasons=["EXCLUSIVE_KEY_OCCUPIED"],
    )
    emit(
        "C3-exclusive-key-collision",
        request(collision_state, event, host),
        expected,
        "A second occurrence resolves the same business key. The registry advances its receipt but creates no second reservation and exposes no owner or key value in the external decision.",
    )

    native_effect = native(facts, "EFFECT", "native-exclusive-effect", reservation_id="reserve-exclusive-1")
    native_effect["provider"] = "card-provider"
    native_effect["source"] = "card-system"
    settle_event, settle_host = host_and_event(
        facts,
        "SETTLE",
        "settle-exclusive-1",
        collision_state["core"]["revision"],
        {"native": native_effect, "histories": []},
        administration=False,
    )
    settled_core = copy.deepcopy(collision_state["core"])
    settled_core["reservations"][0].update(status="SETTLED", matched_effect="effect-1")
    for row in settled_core["exclusive_keys"]:
        row.update(status="CONSUMED", settlement_evidence="effect-1")
    settled_core["effects"] = [effect_record(native_effect, "MATCHED", "MATCHED_EFFECT", affected_anchors=[])]
    settled = transition(collision_state, settle_event, settle_host, settled_core, "SETTLED", reservation_id="reserve-exclusive-1")
    emit(
        "C3-exclusive-key-settle",
        request(collision_state, settle_event, settle_host),
        settled,
        "An exact native completion matches the reserved request and consumes the complete exclusive key set in the same durable transition.",
    )

    mismatched = native(facts, "EFFECT", "native-exclusive-mismatch", reservation_id="reserve-exclusive-1", completion_mismatch=True, mismatch_reason="NATIVE_REQUEST_MISMATCH")
    mismatched["provider"] = "card-provider"
    mismatched["source"] = "card-system"
    mismatched["observed_request"]["fields"][0]["value"]["value"] = "card-999"
    mismatched["actual_fields"] = copy.deepcopy(mismatched["observed_request"]["fields"])
    mismatch_event, mismatch_host = host_and_event(
        facts,
        "SETTLE",
        "settle-exclusive-mismatch",
        collision_state["core"]["revision"],
        {"native": mismatched, "histories": []},
        administration=False,
    )
    mismatch_core = copy.deepcopy(collision_state["core"])
    mismatch_core["reservations"][0]["status"] = "DISPUTED"
    mismatch_core["effects"] = [effect_record(mismatched, "DISPUTED", "NATIVE_REQUEST_MISMATCH", affected_anchors=[])]
    mismatch = transition(collision_state, mismatch_event, mismatch_host, mismatch_core, "EFFECT_DISPUTED", reservation_id="reserve-exclusive-1", reasons=["NATIVE_REQUEST_MISMATCH"])
    emit(
        "C3-exclusive-key-mismatch",
        request(collision_state, mismatch_event, mismatch_host),
        mismatch,
        "A completion with changed request fields does not consume the key. The reservation and key remain retained as disputed evidence.",
    )

    unknown = native(facts, "UNKNOWN", "native-exclusive-unknown", reservation_id="reserve-exclusive-1")
    unknown["provider"] = "card-provider"
    unknown["source"] = "card-system"
    unknown_event, unknown_host = host_and_event(
        facts,
        "SETTLE",
        "settle-exclusive-unknown",
        collision_state["core"]["revision"],
        {"native": unknown, "histories": []},
        administration=False,
    )
    unknown_core = copy.deepcopy(collision_state["core"])
    unknown_core["reservations"][0]["status"] = "UNKNOWN"
    unknown_core["effects"] = [effect_record(unknown, "UNKNOWN", "UNKNOWN_OUTCOME", affected_anchors=[])]
    unknown_expected = transition(collision_state, unknown_event, unknown_host, unknown_core, "UNKNOWN", reservation_id="reserve-exclusive-1")
    emit(
        "C3-exclusive-key-unknown",
        request(collision_state, unknown_event, unknown_host),
        unknown_expected,
        "An unknown completion retains the reservation and its HELD key. It records evidence without granting a new reservation or consuming the key.",
    )

    print(json.dumps({"case_ids": [path.stem for path in sorted(GROUP.glob("C3-*.json"))]}, indent=2))


if __name__ == "__main__":
    main()
