#!/usr/bin/env python3
"""Build the phase-3 registry RENEW cases for terminal targets and changed envelopes.

Owner decisions G1 and G2 added two sentences to RESERVATION-RECORDS.md (RES-WIRE-004, the
paragraph beginning "A refused RENEW does not change its reservation"):

  A RENEW whose explicit reservation is SETTLED or RELEASED is INPUT_INVALID, checked after
  current-history dependency, authentication and type admission and before the proposal and
  envelope check. A RENEW whose proposal or envelope digest differs from the target's retained
  digests is OCCURRENCE_CONFLICT.

Every expected result below is derived from that text, RES-003's admission-before-policy order,
RES-006, RES-WIRE-001's authentication codes, RES-WIRE-003's history type rule and RES-WIRE-004's
fixed phase-5 code order. Prior states come from the rule-derived reservation fixture transitions
(REGISTER, RESERVE, SETTLE, RELEASE). No consumer is imported or executed.
"""

from __future__ import annotations

import copy
import json

from authority_fixture import authority_refusal, authority_specimen, revocation_check
from corpus_common import CASES, candidate_pin, digest, exact_case, write_canonical_json
from reservation_fixture import (
    budget_result,
    clock,
    fixture,
    host_and_event,
    open_state,
    refusal,
    released_state,
    request,
    settled_state,
    transition,
)


GROUP = CASES / "phase3-renew"
EXPECTED_PIN = "sha256:fd52d69dd3c3546bff2cec9d46fb8d6b942fd57b77b0a3ab8377a592e80d00b6"
RESERVATION_ID = "reserve-a"
RENEWAL_PERMIT_UNTIL = "2026-09-10T04:35:00Z"
ORIGINAL_VALID_FROM = "2026-09-01T00:00:00Z"
REVISED_AUTHORIZATION_ID = "license-class-authorization-revised"
# Whole-second instants after the original valid_from and before the 2026-09-10T04:30:00Z clock,
# tried in ascending order; the first whose envelope digest sorts after the original is used.
REVISED_VALID_FROM_CANDIDATES = [f"2026-09-0{day}T{hour:02d}:00:00Z" for day in range(2, 10) for hour in range(24)]

TERMINAL_RULE = (
    "RES-WIRE-004 (owner decision G1): a RENEW whose explicit reservation is SETTLED or RELEASED is "
    "INPUT_INVALID, checked after current-history dependency, authentication and type admission and "
    "before the proposal and envelope check."
)
CONFLICT_RULE = (
    "RES-WIRE-004 (owner decision G2): a RENEW whose proposal or envelope digest differs from the "
    "target's retained digests is OCCURRENCE_CONFLICT; RES-006 says a changed proposal field or "
    "envelope is not a renewal."
)
PHASE5_ORDER = (
    "RES-WIRE-004 fixes the phase-5 code order DEPENDENCY_MISMATCH, EVIDENCE_UNAVAILABLE, "
    "UNSUPPORTED_RELATION, REFERENCE_INVALID, BINDING_MISMATCH, TYPE_INVALID, INPUT_INVALID, "
    "LIMIT_EXCEEDED, DEFINITION_CONFLICT, OCCURRENCE_CONFLICT, RESERVATION_NOT_FOUND, "
    "ADMINISTRATION_NOT_ESTABLISHED."
)
REFUSAL_SHAPE = (
    "RES-003 and RES-WIRE-004: an admission refusal creates no receipt, advances nothing and returns "
    "the exact supplied state and digest, so the reservation keeps its status, permit and evidence."
)
VALID_PREMISES = (
    "Every other admission fact holds: the event clock equals the authority clock and the registry's "
    "last clock (equal instants are allowed for serialized events), expected_revision is current, the "
    "single history is the target budget's current complete journal, and host_evidence carries exactly "
    "one HISTORY tuple for it."
)


def revised_envelope_specimen() -> tuple[dict, dict, str]:
    """Authority input A with only envelope.temporal_validity.valid_from changed.

    authority_specimen rebinds every dependent digest (acts, returns, host selection, operation
    digest), so the changed input is self-consistent and its derived authority result is READY.
    The candidate date is the first one whose envelope digest sorts after the original's, so the
    two registered authorizations sort identically by id, by envelope_digest and by canonical bytes.
    """
    original, _ = authority_specimen(shared_budget=True, instance_id="instance-1", occurrence_id="issue:1")
    original_digest = digest("authority-envelope", original["envelope"])
    assert original["envelope"]["temporal_validity"]["valid_from"] == ORIGINAL_VALID_FROM
    for candidate in REVISED_VALID_FROM_CANDIDATES:

        def mutate(request_value: dict, _original: dict, value: str = candidate) -> None:
            request_value["envelope"]["temporal_validity"]["valid_from"] = value

        revised, revised_result = authority_specimen(
            shared_budget=True, instance_id="instance-1", occurrence_id="issue:1", mutator=mutate
        )
        revised_digest = digest("authority-envelope", revised["envelope"])
        if revised_digest.encode("utf-8") > original_digest.encode("utf-8"):
            revised["clock"] = clock()
            assert revised["proposal"] == original["proposal"]
            return revised, revised_result, candidate
    raise RuntimeError("no candidate valid_from sorts after the original envelope digest")


def two_authorization_facts(revised: dict) -> dict:
    """Register a second exact class/envelope authorization for the revised envelope.

    RES-001 makes each exact work-class authorization a separate complete record binding one
    envelope digest. Registering both keeps the authorization lookup satisfied for either envelope,
    so the revised envelope differs from the reservation only in the retained envelope digest.
    """
    facts = fixture()
    first = facts["authorizations"][0]
    second = copy.deepcopy(first)
    second["id"] = REVISED_AUTHORIZATION_ID
    second["envelope_digest"] = digest("authority-envelope", revised["envelope"])
    second["authority_definition"]["envelope"] = copy.deepcopy(revised["envelope"])
    assert first["id"].encode("utf-8") < second["id"].encode("utf-8")
    assert first["envelope_digest"].encode("utf-8") < second["envelope_digest"].encode("utf-8")
    facts["authorizations"] = [first, second]
    return facts


def changed_proposal_specimen() -> dict:
    """Authority input A for a different instance, rebound so the input is self-consistent."""
    changed, _ = authority_specimen(shared_budget=True, instance_id="instance-1-changed", occurrence_id="issue:1")
    changed["clock"] = clock()
    return changed


def revoked(authority: dict) -> dict:
    """D2-174 pattern: every current revocation observation reports revoked:true."""
    value = copy.deepcopy(authority)
    for observation in value["observations"]:
        if observation["query"]["at"] == value["clock"]["instant"]:
            observation["revoked"] = True
    return value


def type_fault(history: dict) -> dict:
    """Append one ACTIVE journal entry whose DECIMAL amount is spelled '01'.

    Specification.md forbids a leading zero in a nonnegative decimal; AGG phase 4 and RES-WIRE-003
    make that TYPE_INVALID for an ACTIVE history-event field. Appending keeps the prior journal an
    exact prefix and the natural revision equal to the journal length, so no other history rule fails.
    """
    value = copy.deepcopy(history)
    value["journal"].append(
        {
            "sequence": str(len(value["journal"]) + 1),
            "event": {
                "id": "c3-p3-renew-type-fault",
                "state": "ACTIVE",
                # Equal to the history's as_of and the event clock, and not earlier than any
                # retained entry, so no time-ordering or future-occurrence rule is touched.
                "occurred_at": "2026-09-10T04:30:00Z",
                "fields": [
                    {"name": "amount", "value": {"type_ref": "amount", "value": "01"}},
                    {"name": "beneficiary", "value": {"type_ref": "beneficiary", "value": "employee-7"}},
                ],
            },
        }
    )
    value["revision"] = str(len(value["journal"]))
    return value


def renew_request(facts: dict, state: dict, case_id: str, authority: dict, *, history: dict | None = None, missing_auth: bool = False) -> dict:
    current_history = copy.deepcopy(state["core"]["budgets"][0]["history"]) if history is None else history
    event, host = host_and_event(
        facts,
        "RENEW",
        "renew-" + case_id.lower(),
        state["core"]["revision"],
        {"reservation": RESERVATION_ID, "authority": copy.deepcopy(authority), "histories": [current_history]},
        event_clock=clock(),
        administration=False,
    )
    assert event["clock"] == authority["clock"]
    if missing_auth:
        host["authenticated_records"] = []
    return request(state, event, host)


def renewed(state: dict, value: dict, facts: dict, authority_result: dict) -> dict:
    """RES-006 success: replace authority, result and permit expiry; keep id, occurrence, contributions."""
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = copy.deepcopy(value["event"]["payload"]["histories"][0])
    target = next(row for row in core["reservations"] if row["id"] == RESERVATION_ID)
    target["authority"] = copy.deepcopy(value["event"]["payload"]["authority"])
    target["authority_result"] = copy.deepcopy(authority_result)
    target["permit_until"] = RENEWAL_PERMIT_UNTIL
    return transition(
        state, value["event"], value["host_evidence"], core, "RENEWED",
        reservation_id=RESERVATION_ID, budgets=budget_result(facts, "950"), authority_result=authority_result,
    )


def authority_withheld(state: dict, value: dict, withheld: dict) -> dict:
    """RES-WIRE-004: AUTHORITY_WITHHELD retains the complete authority refusal and leaves budgets empty."""
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = copy.deepcopy(value["event"]["payload"]["histories"][0])
    return transition(
        state, value["event"], value["host_evidence"], core, "WITHHELD",
        reservation_id=RESERVATION_ID, budgets=[], authority_result=withheld, reasons=["AUTHORITY_WITHHELD"],
    )


def emit(case_id: str, value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    write_canonical_json(
        GROUP / f"{case_id}.json",
        exact_case(case_id, "aggregate-step", value, expected, requirements, derivation),
    )


def main() -> None:
    assert candidate_pin() == EXPECTED_PIN, candidate_pin()
    GROUP.mkdir(parents=True, exist_ok=True)
    for stale in GROUP.glob("*.json"):
        stale.unlink()

    facts = fixture()
    authority = copy.deepcopy(facts["authority_a"])
    opened = open_state(facts)
    settled = settled_state(facts)
    released = released_state(facts)
    assert next(r for r in settled["core"]["reservations"] if r["id"] == RESERVATION_ID)["status"] == "SETTLED"
    assert next(r for r in released["core"]["reservations"] if r["id"] == RESERVATION_ID)["status"] == "RELEASED"

    revised, _revised_result, revised_valid_from = revised_envelope_specimen()
    facts2 = two_authorization_facts(revised)
    opened2 = open_state(facts2)
    settled2 = settled_state(facts2)
    retained = next(r for r in opened2["core"]["reservations"] if r["id"] == RESERVATION_ID)
    assert retained["envelope_digest"] != digest("authority-envelope", revised["envelope"])
    assert retained["proposal_digest"] == digest("authority-proposal", revised["proposal"])
    changed_proposal = changed_proposal_specimen()

    produced: list[str] = []

    def add(case_id: str, value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
        emit(case_id, value, expected, requirements, derivation)
        produced.append(case_id)

    # G1. Terminal target.
    value = renew_request(facts, settled, "C3-P3-RENEW-001", authority)
    add(
        "C3-P3-RENEW-001", value, refusal(settled, "INPUT_INVALID"), ["RES-006", "RES-WIRE-004"],
        "Setup: REGISTER, RESERVE and a matching SETTLE leave reserve-a SETTLED at revision 3. The case: RENEW names reserve-a with "
        "its unchanged exact proposal and envelope and the same READY authority input that reserved it. " + VALID_PREMISES + " "
        "RES-006 admits RENEW only for an OPEN or UNKNOWN reservation. " + TERMINAL_RULE + " No earlier phase-5 code applies, "
        "so the result is INPUT_INVALID. " + REFUSAL_SHAPE,
    )

    value = renew_request(facts, released, "C3-P3-RENEW-002", authority)
    add(
        "C3-P3-RENEW-002", value, refusal(released, "INPUT_INVALID"), ["RES-006", "RES-WIRE-004"],
        "Setup: REGISTER, RESERVE and an authorized affirmative RELEASE leave reserve-a RELEASED at revision 3 with the opening "
        "history unchanged. The case: RENEW names reserve-a with its unchanged exact proposal and envelope and a READY authority "
        "input. " + VALID_PREMISES + " " + TERMINAL_RULE + " The result is INPUT_INVALID. " + REFUSAL_SHAPE,
    )

    value = renew_request(facts, settled, "C3-P3-RENEW-003", changed_proposal)
    add(
        "C3-P3-RENEW-003", value, refusal(settled, "INPUT_INVALID"), ["RES-006", "RES-WIRE-004"],
        "Setup as C3-P3-RENEW-001: reserve-a is SETTLED. The case: the RENEW authority input names instance instance-1-changed, so "
        "its proposal digest differs from reserve-a's retained proposal digest; every authority digest is rebound so the input is "
        "self-consistent. Both INPUT_INVALID (terminal target) and OCCURRENCE_CONFLICT (changed proposal) apply. " + TERMINAL_RULE + " "
        + PHASE5_ORDER + " INPUT_INVALID precedes OCCURRENCE_CONFLICT on both grounds, so the result is INPUT_INVALID. " + REFUSAL_SHAPE,
    )

    value = renew_request(facts, settled, "C3-P3-RENEW-004", authority, missing_auth=True)
    add(
        "C3-P3-RENEW-004", value, refusal(settled, "EVIDENCE_UNAVAILABLE"), ["RES-006", "RES-WIRE-001", "RES-WIRE-004"],
        "Setup as C3-P3-RENEW-001: reserve-a is SETTLED. The case: the otherwise valid RENEW supplies one current history but "
        "host_evidence.authenticated_records is empty. RES-WIRE-001 requires exactly one HISTORY tuple per supplied history and "
        "makes a missing tuple EVIDENCE_UNAVAILABLE. " + TERMINAL_RULE + " The terminal check therefore runs only after "
        "authentication admission, and EVIDENCE_UNAVAILABLE also precedes INPUT_INVALID in the phase-5 order. The result is "
        "EVIDENCE_UNAVAILABLE. " + REFUSAL_SHAPE,
    )

    settled_history = settled["core"]["budgets"][0]["history"]
    value = renew_request(facts, settled, "C3-P3-RENEW-005", authority, history=type_fault(settled_history))
    add(
        "C3-P3-RENEW-005", value, refusal(settled, "TYPE_INVALID"), ["RES-006", "RES-WIRE-003", "RES-WIRE-004"],
        "Setup as C3-P3-RENEW-001: reserve-a is SETTLED. The case: the supplied current history extends the retained journal by "
        "one ACTIVE entry whose DECIMAL amount is spelled 01, and its HISTORY tuple is rebound to that body. Specification.md "
        "forbids a leading zero in a nonnegative decimal, and RES-WIRE-003 validates every supplied ACTIVE history-event field's "
        "scalar and nominal type after dependency and authentication admission. " + TERMINAL_RULE + " The terminal check runs "
        "after type admission, and TYPE_INVALID also precedes INPUT_INVALID in the phase-5 order. The result is TYPE_INVALID. "
        + REFUSAL_SHAPE,
    )

    value = renew_request(facts, settled, "C3-P3-RENEW-006", revoked(authority))
    add(
        "C3-P3-RENEW-006", value, refusal(settled, "INPUT_INVALID"), ["RES-003", "RES-006", "RES-WIRE-004"],
        "Setup as C3-P3-RENEW-001: reserve-a is SETTLED. The case: the otherwise valid RENEW carries a well-formed authority input "
        "whose current revocation observations report revoked:true; against an OPEN target the same input is an admitted "
        "AUTHORITY_WITHHELD decision (control C3-P3-RENEW-013). RES-003 orders admission phases 1-5 before (6) policy evaluation "
        "and transition, and RES-005/RES-WIRE-004 make an authority refusal a recorded WITHHELD policy decision, not an admission "
        "code. " + TERMINAL_RULE + " The terminal check is phase-5 admission, so it refuses the event before authority is "
        "evaluated. The result is INPUT_INVALID, not WITHHELD, and no receipt is created. " + REFUSAL_SHAPE,
    )

    # G2. Changed envelope.
    envelope_setup = (
        "Setup: the budget registers two exact class/envelope authorizations, license-class-authorization for the original "
        "envelope and " + REVISED_AUTHORIZATION_ID + " for a revised envelope whose only change is temporal_validity.valid_from "
        + revised_valid_from + " (still before the 2026-09-10T04:30:00Z clock). reserve-a was reserved under the original envelope. "
        "The revised authority input rebinds every dependent digest (acts, returns, host selection, operation digest), keeps the "
        "proposal byte-identical, and has an exact registered authorization, so the authority input alone is ready."
    )
    value = renew_request(facts2, opened2, "C3-P3-RENEW-007", revised)
    add(
        "C3-P3-RENEW-007", value, refusal(opened2, "OCCURRENCE_CONFLICT"), ["RES-006", "RES-WIRE-004"],
        envelope_setup + " The case: reserve-a is OPEN and RENEW supplies the revised authority input. " + VALID_PREMISES + " "
        "The proposal digest equals the retained one but the envelope digest differs. " + CONFLICT_RULE + " No earlier phase-5 "
        "code applies, so the result is OCCURRENCE_CONFLICT. " + REFUSAL_SHAPE,
    )

    value = renew_request(facts2, opened2, "C3-P3-RENEW-008", revised, missing_auth=True)
    add(
        "C3-P3-RENEW-008", value, refusal(opened2, "EVIDENCE_UNAVAILABLE"), ["RES-006", "RES-WIRE-001", "RES-WIRE-004"],
        envelope_setup + " The case: as C3-P3-RENEW-007 but host_evidence.authenticated_records is empty. RES-WIRE-001 makes the "
        "missing HISTORY tuple EVIDENCE_UNAVAILABLE. " + PHASE5_ORDER + " EVIDENCE_UNAVAILABLE precedes OCCURRENCE_CONFLICT, so the "
        "result is EVIDENCE_UNAVAILABLE. " + REFUSAL_SHAPE,
    )

    open_history = opened2["core"]["budgets"][0]["history"]
    value = renew_request(facts2, opened2, "C3-P3-RENEW-009", revised, history=type_fault(open_history))
    add(
        "C3-P3-RENEW-009", value, refusal(opened2, "TYPE_INVALID"), ["RES-006", "RES-WIRE-003", "RES-WIRE-004"],
        envelope_setup + " The case: as C3-P3-RENEW-007 but the supplied current history extends the retained journal by one ACTIVE "
        "entry whose DECIMAL amount is spelled 01, with its HISTORY tuple rebound. RES-WIRE-003 and AGG phase 4 make that "
        "TYPE_INVALID. " + PHASE5_ORDER + " TYPE_INVALID precedes OCCURRENCE_CONFLICT, so the result is TYPE_INVALID. "
        + REFUSAL_SHAPE,
    )

    value = renew_request(facts2, settled2, "C3-P3-RENEW-010", revised)
    add(
        "C3-P3-RENEW-010", value, refusal(settled2, "INPUT_INVALID"), ["RES-006", "RES-WIRE-004"],
        envelope_setup + " A matching SETTLE then leaves reserve-a SETTLED at revision 3. The case: RENEW supplies the revised "
        "authority input with the current settled history. Both INPUT_INVALID (terminal target) and OCCURRENCE_CONFLICT (changed "
        "envelope) apply. " + TERMINAL_RULE + " " + PHASE5_ORDER + " The terminal check precedes the envelope check on both "
        "grounds, so the result is INPUT_INVALID. " + REFUSAL_SHAPE,
    )

    # Controls: the same baselines without the decisive fault.
    value = renew_request(facts, opened, "C3-P3-RENEW-011", authority)
    add(
        "C3-P3-RENEW-011", value, renewed(opened, value, facts, facts["authority_a_result"]), ["RES-006", "RES-WIRE-004"],
        "Control for the G1 baseline. Setup: REGISTER and RESERVE leave reserve-a OPEN at revision 2. The case: the same RENEW as "
        "C3-P3-RENEW-001 against the OPEN target. " + VALID_PREMISES + " RES-006 reevaluates current authority, which is READY with "
        "the fixture's derived result, removes reserve-a's own 150 pending contribution and evaluates it once: committed 800 plus "
        "150 is 950, within the LTE 1000 bound. RES-WIRE-004 sets the permit to the earlier of the envelope's 2026-10-01 validity "
        "end and now plus 300 seconds, 2026-09-10T04:35:00Z. The receipt is RENEWED with the evaluated SATISFIED judgment and the "
        "authority result; id, occurrence, contributions, creation time and status are unchanged and the revision advances to 3.",
    )

    original_authority2 = copy.deepcopy(facts2["authority_a"])
    value = renew_request(facts2, opened2, "C3-P3-RENEW-012", original_authority2)
    add(
        "C3-P3-RENEW-012", value, renewed(opened2, value, facts2, facts2["authority_a_result"]), ["RES-001", "RES-006", "RES-WIRE-004"],
        "Control for the G2 baseline. " + envelope_setup + " The case: RENEW of the OPEN reserve-a with the original, unchanged "
        "envelope. RES-001 makes each exact class/envelope authorization a separate record, and this envelope has its exact "
        "authorization. The derivation of C3-P3-RENEW-011 applies unchanged: RENEWED, total 950 SATISFIED, permit_until "
        "2026-09-10T04:35:00Z, revision 3.",
    )

    revoked_authority = revoked(authority)
    value = renew_request(facts, opened, "C3-P3-RENEW-013", revoked_authority)
    withheld = authority_refusal([
        revocation_check(revoked_authority, row["query"]["subject_digest"], row["query"]["at"])
        for row in revoked_authority["observations"] if row["revoked"]
    ])
    add(
        "C3-P3-RENEW-013", value, authority_withheld(opened, value, withheld), ["RES-003", "RES-006", "RES-WIRE-004"],
        "Control for C3-P3-RENEW-006. Setup as C3-P3-RENEW-011: reserve-a is OPEN. The case: the revoked authority input of "
        "C3-P3-RENEW-006. Admission succeeds, and RES-006 reevaluates every current authority and revocation check. AUTH-005 and "
        "AUTHORITY-CHECKS give AUTHORITY_NOT_ESTABLISHED with one REVOCATION failed check per revoked current query and sole reason "
        "REVOKED. RES-005 and RES-WIRE-004 record that as WITHHELD with reason AUTHORITY_WITHHELD, retaining the complete authority "
        "refusal, with empty budgets. RES-006 retains the reservation and does not extend its permit. The supplied history is "
        "current and complete, so it is committed with the decision (RES-WIRE-003 withholds the journal update only for stale or "
        "unavailable history; here the bytes are unchanged). The revision advances to 3.",
    )

    print(json.dumps({"output": str(GROUP), "case_ids": produced, "revised_valid_from": revised_valid_from}, indent=2))


if __name__ == "__main__":
    main()
