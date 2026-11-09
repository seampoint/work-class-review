#!/usr/bin/env python3
"""Build the frozen aggregate-step judgments from reservation wire rules.

Expected records are constructed from the normative transition and digest
rules. The script does not import or execute a draft-2 implementation.
"""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_specimen
from corpus_common import CASES, digest, exact_case, write_canonical_json
from reservation_fixture import (
    budget_result,
    effect_record,
    fixture,
    host_and_event,
    native,
    open_state,
    refusal,
    released_state,
    request,
    settled_state,
    transition,
    zero_state,
)


GROUP = CASES / "reservation-edges"


def emit(case_id: str, input_value: dict, expected: dict, derivation: str) -> None:
    case = exact_case(case_id, "aggregate-step", input_value, expected, [], derivation)
    write_canonical_json(GROUP / f"{case_id}.json", case)


def retained_effect_transition(
    facts: dict,
    state: dict,
    case_id: str,
    event_kind: str,
    native_record: dict,
    *,
    decision: str,
    next_status: str,
    disposition: str,
    reason: str,
    append_effect: bool = True,
    blocked: list[dict] | None = None,
    histories: list[dict] | None = None,
) -> tuple[dict, dict]:
    payload = {"native": native_record}
    if event_kind == "SETTLE":
        payload["histories"] = copy.deepcopy(histories if histories is not None else [state["core"]["budgets"][0]["history"]])
    event, host = host_and_event(
        facts,
        event_kind,
        "event-" + case_id.lower(),
        state["core"]["revision"],
        payload,
        administration=False,
    )
    core = copy.deepcopy(state["core"])
    core["reservations"][0]["status"] = next_status
    if append_effect:
        core["effects"].append(effect_record(native_record, disposition, reason, blocked))
        core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    expected = transition(
        state,
        event,
        host,
        core,
        decision,
        reservation_id="reserve-a",
        reasons=[reason] if decision == "EFFECT_DISPUTED" else [],
    )
    return request(state, event, host), expected


def duplicate_release(facts: dict, state: dict, case_id: str) -> tuple[dict, dict]:
    prior = next(row["native"] for row in state["core"]["effects"] if row["native"]["outcome"] == "NO_EFFECT")
    repeated = copy.deepcopy(prior)
    repeated["id"] = "native-no-effect-repeat"
    repeated["evidence_ref"] = "evidence-native-no-effect-repeat"
    event, host = host_and_event(
        facts,
        "RELEASE",
        "event-" + case_id.lower(),
        state["core"]["revision"],
        {"native": repeated},
        administration=False,
    )
    expected = transition(state, event, host, state["core"], "RELEASED", reservation_id="reserve-a")
    return request(state, event, host), expected


def dual_budget_refusal() -> tuple[dict, dict]:
    facts = fixture()
    authority_a, result_a = authority_specimen(
        shared_budgets=["license-spend", "license-spend-two"],
        instance_id="instance-1",
        occurrence_id="issue:1",
    )
    authority_b, result_b = authority_specimen(
        shared_budgets=["license-spend", "license-spend-two"],
        instance_id="instance-2",
        occurrence_id="issue:2",
    )
    facts["authority_a"], facts["authority_a_result"] = authority_a, result_a
    facts["authority_b"], facts["authority_b_result"] = authority_b, result_b
    facts["configuration"]["slots"] = [
        {"anchor": "license-spend", "exposure_domain": "issuer-global-usd"},
        {"anchor": "license-spend-two", "exposure_domain": "issuer-second-usd"},
    ]

    first = facts["budget"]
    first_authorization = facts["authorizations"][0]
    first_authorization["envelope_digest"] = digest("authority-envelope", authority_a["envelope"])
    first_authorization["authority_definition"]["envelope"] = copy.deepcopy(authority_a["envelope"])

    second = copy.deepcopy(first)
    second["anchor"] = "license-spend-two"
    second["exposure_domain"] = "issuer-second-usd"
    second["aggregate"]["aggregate"]["id"] = "beneficiary-exposure-two"
    second["reservation_policy"]["settlement"] = {"provider": "other-provider", "source": "other-ledger"}
    second_digest = digest("budget-definition", second)
    second_authorization = copy.deepcopy(first_authorization)
    second_authorization["id"] = "license-class-authorization-two"
    second_authorization["budget_digest"] = second_digest
    first_authorization["budget_digest"] = digest("budget-definition", first)
    facts["authorizations"] = [first_authorization]

    second_history = copy.deepcopy(facts["history"])
    second_history["budget_digest"] = second_digest
    second_history["evidence_ref"] = "complete-opening-history-two"

    state = zero_state(facts)
    for index, (event_id, definition, authorization, history) in enumerate(
        [
            ("register-license-budget", first, first_authorization, facts["history"]),
            ("register-license-budget-two", second, second_authorization, second_history),
        ]
    ):
        event, host = host_and_event(
            facts,
            "REGISTER",
            event_id,
            str(index),
            {"definition": definition, "authorizations": [authorization], "history": history},
        )
        core = copy.deepcopy(state["core"])
        core["budgets"].append(
            {
                "definition": copy.deepcopy(definition),
                "definition_digest": digest("budget-definition", definition),
                "authorizations": [copy.deepcopy(authorization)],
                "history": copy.deepcopy(history),
            }
        )
        core["budgets"].sort(key=lambda row: row["definition"]["anchor"].encode("utf-8"))
        state = transition(state, event, host, core, "REGISTERED")["state"]

    event, host = host_and_event(
        facts,
        "RESERVE",
        "reserve-two-policies",
        "2",
        {
            "authority": authority_a,
            "histories": sorted(
                [facts["history"], second_history],
                key=lambda row: row["budget_digest"].encode("utf-8"),
            ),
        },
        administration=False,
    )
    return request(state, event, host), refusal(state, "UNSUPPORTED_RELATION")


def main() -> None:
    facts = fixture()

    state = settled_state(facts)
    no_effect = native(facts, "NO_EFFECT", "contradictory-no-effect")
    input_value, expected = retained_effect_transition(
        facts,
        state,
        "D2-145",
        "RELEASE",
        no_effect,
        decision="EFFECT_DISPUTED",
        next_status="DISPUTED",
        disposition="DISPUTED",
        reason="UNEXPECTED_EFFECT",
        blocked=[{"anchor": "license-spend", "key": [{"type_ref": "beneficiary", "value": "employee-7"}]}],
    )
    emit(
        "D2-145",
        input_value,
        expected,
        "A conclusive no-effect fact contradicts the retained matched effect. The terminal-state table keeps committed history, restores unresolved pending exposure through DISPUTED status, blocks the reserved partition, and records EFFECT_DISPUTED.",
    )

    unknown = native(facts, "UNKNOWN", "unknown-after-settlement")
    input_value, expected = retained_effect_transition(
        facts,
        state,
        "D2-146",
        "SETTLE",
        unknown,
        decision="UNKNOWN",
        next_status="SETTLED",
        disposition="UNKNOWN",
        reason="UNKNOWN_OUTCOME",
    )
    emit(
        "D2-146",
        input_value,
        expected,
        "UNKNOWN after SETTLED is retained as evidence in a new effect record and receipt. The terminal reservation status and committed history remain unchanged and no pending exposure is restored.",
    )

    state = released_state(facts)
    input_value, expected = duplicate_release(facts, state, "D2-147")
    emit(
        "D2-147",
        input_value,
        expected,
        "The second record differs only in native evidence identity and reference. Same-fact duplicate detection returns RELEASED, advances one admitted-event revision, and adds neither another effect nor exposure.",
    )

    state = settled_state(facts)
    changed = native(
        facts,
        "EFFECT",
        "changed-fact-same-effect",
        completion_mismatch=True,
        mismatch_reason="NATIVE_REQUEST_MISMATCH",
    )
    changed["effect_id"] = "effect-1"
    changed["observed_request"]["fields"][0]["value"]["value"] = "151"
    changed["actual_fields"] = copy.deepcopy(changed["observed_request"]["fields"])
    input_value, expected = retained_effect_transition(
        facts,
        state,
        "D2-160",
        "SETTLE",
        changed,
        decision="EFFECT_DISPUTED",
        next_status="DISPUTED",
        disposition="DISPUTED",
        reason="NATIVE_REQUEST_MISMATCH",
        blocked=[{"anchor": "license-spend", "key": [{"type_ref": "beneficiary", "value": "employee-7"}]}],
    )
    emit(
        "D2-160",
        input_value,
        expected,
        "The retained effect_id already denotes the matched 150 fact. A new evidence identity changes the observed amount to 151, so it is a conclusive conflict. The record is retained as disputed, pending exposure is restored, and no second committed journal contribution is added.",
    )

    input_value, expected = dual_budget_refusal()
    emit(
        "D2-177",
        input_value,
        expected,
        "The complete current authority result requires both registered anchors, but their immutable settlement provider/source pairs differ. RES-WIRE-003 rejects that relationship before evaluation and preserves the registry exactly.",
    )

    state = zero_state(facts)
    event, host = host_and_event(
        facts,
        "REGISTER",
        "register-role-unsupported",
        "0",
        {"definition": facts["budget"], "authorizations": facts["authorizations"], "history": facts["history"]},
    )
    emit(
        "D2-272",
        request(state, event, host),
        {"status": "REFUSED", "code": "ROLE_UNSUPPORTED", "path": ""},
        "This schema-valid request is assigned by suite metadata to the capability-limited adapter variant whose claim omits RESERVATION_TRANSITIONS. Role gating precedes the reservation transition and therefore returns the closed protocol refusal without a state.",
    )

    state = open_state(facts)
    malformed_native = native(
        facts,
        "NO_EFFECT",
        "inconsistent-mismatch-false",
        completion_mismatch=False,
        mismatch_reason="NATIVE_REQUEST_MISMATCH",
    )
    event, host = host_and_event(
        facts,
        "RELEASE",
        "event-d2-294",
        state["core"]["revision"],
        {"native": malformed_native},
        administration=False,
    )
    emit(
        "D2-294",
        request(state, event, host),
        refusal(state, "INPUT_INVALID"),
        "The closed shape admits both fields, but completion_mismatch false semantically requires a null mismatch_reason. INPUT_INVALID leaves the exact prior registry state and receipts unchanged.",
    )
    malformed_native_b = native(
        facts,
        "NO_EFFECT",
        "inconsistent-mismatch-true",
        completion_mismatch=True,
        mismatch_reason=None,
    )
    event, host = host_and_event(
        facts,
        "RELEASE",
        "event-d2-294-null-reason",
        state["core"]["revision"],
        {"native": malformed_native_b},
        administration=False,
    )
    supplemental = exact_case(
        "R2-294-null-reason",
        "aggregate-step",
        request(state, event, host),
        refusal(state, "INPUT_INVALID"),
        ["RES-WIRE-003", "RES-WIRE-004"],
        "The complementary invalid pairing sets completion_mismatch true but supplies no supported cause. It is refused without retaining evidence or changing state.",
    )
    write_canonical_json(GROUP / "R2-294-null-reason.json", supplemental)

    for case_id, mismatch_reason in [("D2-296", "NATIVE_REQUEST_MISMATCH"), ("R2-296-unexpected", "UNEXPECTED_EFFECT")]:
        mismatched = native(
            facts,
            "NO_EFFECT",
            "mismatched-no-effect-" + mismatch_reason.lower(),
            completion_mismatch=True,
            mismatch_reason=mismatch_reason,
        )
        input_value, expected = retained_effect_transition(
            facts,
            state,
            case_id,
            "RELEASE",
            mismatched,
            decision="EFFECT_DISPUTED",
            next_status="DISPUTED",
            disposition="DISPUTED",
            reason=mismatch_reason,
            blocked=[{"anchor": "license-spend", "key": None}],
        )
        if case_id == "D2-296":
            emit(
                case_id,
                input_value,
                expected,
                "A changed or disqualified dispatch attribution declares NATIVE_REQUEST_MISMATCH. The unusable no-effect fact cannot release capacity; it is retained as disputed exposure, blocks the anchor, and copies the declared reason exactly.",
            )
        else:
            supplemental = exact_case(
                case_id,
                "aggregate-step",
                input_value,
                expected,
                ["RES-007", "RES-008", "RES-WIRE-003", "RES-WIRE-004"],
                "The second supported mismatch cause declares UNEXPECTED_EFFECT. The same conservative transition applies, but the receipt and retained effect copy this distinct declared reason.",
            )
            write_canonical_json(GROUP / f"{case_id}.json", supplemental)

    print(json.dumps({"exact_case_ids": ["D2-145", "D2-146", "D2-147", "D2-160", "D2-177", "D2-272", "D2-294", "D2-296"], "supplementary_cases": 2}, indent=2))


if __name__ == "__main__":
    main()
