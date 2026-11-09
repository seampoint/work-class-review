#!/usr/bin/env python3
"""Build phase-3 cases for findings M-1, M-2 and m-1 of the independent review and for ruling R-f.

Every expected result is derived from the text. Three groups:

- ADM-001 to 010: authority withheld with no shared budgets. RES-003 orders phase-5 admission before
  policy, RESERVATION-RECORDS fixes the phase-5 code order and says missing RENEW references are
  admission failures, RESERVATIONS.md says one occurrence can be admitted only once.
- ADM-011 to 016: shared budgets with exclusive keys, governed by owner ruling R-f in
  EXCLUSIVE-KEY-HISTORY.md section 6.
- ADM-017 to 020: DISPOSE adopting a history that does or does not retract a prescribed record
  (RESERVATION-RECORDS retraction paragraph, ruling R-a). ADM-019 and 020 reach ACCEPT_UNRESOLVED's
  aggregate evaluation, where the marking must already apply.

- ADM-021 to 023: exclusive withholding reached with several slots, or with a stale history.
- ADM-024 to 031: contingent rows on a retained LEAVE_UNRESOLVED (ruling R-h) and an explicit
  LEAVE_UNRESOLVED with an unusable history (ruling R-i).

No consumer is imported or executed here. The author had read both consumers while diagnosing the
review findings; see the expectation seal.
"""

from __future__ import annotations

import copy
import json

import reservation_fixture as rf
from authority_fixture import authority_refusal, authority_specimen, revocation_check
from corpus_common import CASES, canonical_bytes, candidate_pin, digest, exact_case, write_canonical_json
from equipment_history_fixture import PROVIDER, SOURCE
import recovery_fixture as recovery
from reservation_fixture import (
    budget_result, clock, effect_record, fixture, host_and_event, matching_history, native, refusal,
    request, reservation_record, transition, zero_state,
)


GROUP = CASES / "phase3-admission"
EXPECTED_PIN = "sha256:fd52d69dd3c3546bff2cec9d46fb8d6b942fd57b77b0a3ab8377a592e80d00b6"
KEYS = [{
    "id": "card-identity-key", "slot": "card-identity", "namespace": "access-card",
    "projection": [{"field": "card_id", "type_ref": "IDENTITY"}],
    "retention": "RETAIN_UNTIL_SETTLED_OR_AUTHORIZED_RELEASE",
}]
MEDIATED_KEYS = [{**KEYS[0], "projection": [{"field": "card_id", "type_ref": "IDENTITY", "key_field": "card_id"}]}]
ORDER = (
    "RES-WIRE-004 fixes the phase-5 code order DEPENDENCY_MISMATCH, EVIDENCE_UNAVAILABLE, UNSUPPORTED_RELATION, "
    "REFERENCE_INVALID, BINDING_MISMATCH, TYPE_INVALID, INPUT_INVALID, LIMIT_EXCEEDED, DEFINITION_CONFLICT, "
    "OCCURRENCE_CONFLICT, RESERVATION_NOT_FOUND, ADMINISTRATION_NOT_ESTABLISHED, and RES-003 orders admission phases "
    "1-5 before (6) policy evaluation. AUTHORITY_WITHHELD is a policy decision, so an admission code precedes it."
)
RF = (
    "Owner rulings R-f and R-g (EXCLUSIVE-KEY-HISTORY section 6): a WITHHELD with EXCLUSIVE_HISTORY_UNAVAILABLE or "
    "EXCLUSIVE_KEY_OCCUPIED carries that reason alone and empty budgets, an exclusive withholding takes precedence over "
    "numerical history reasons, and a current complete history supplied with it is still committed with the retraction marking."
)
SHAPE = "RES-003: an admission refusal creates no receipt and returns the exact supplied state and digest."


def revoked(authority: dict) -> dict:
    value = copy.deepcopy(authority)
    for row in value["observations"]:
        if row["query"]["at"] == value["clock"]["instant"]:
            row["revoked"] = True
    return value


def withheld_result(authority: dict) -> dict:
    return authority_refusal([
        revocation_check(authority, row["query"]["subject_digest"], row["query"]["at"])
        for row in authority["observations"] if row["revoked"]
    ])


def claims(facts: dict, key: str) -> list[dict]:
    return copy.deepcopy(facts[key + "_result"].get("required_exclusive_keys", []))


def key_states(facts: dict, key: str, event_id: str) -> list[dict]:
    registry = digest("reservation-registry", facts["configuration"])
    proposal = facts[key]["proposal"]
    return [{
        "key_digest": digest("exclusive-key", {"registry": registry, "slot": row["slot"], "namespace": row["namespace"], "key": row["key"]}),
        "slot": row["slot"], "namespace": row["namespace"], "key": copy.deepcopy(row["key"]),
        "owner_instance": proposal["instance"], "owner_occurrence": proposal["occurrence"],
        "acquisition_event": event_id, "status": "HELD", "settlement_evidence": None,
    } for row in claims(facts, key)]


def emit(produced: list[str], number: int, value: dict, expected: dict, requirements: list[str], derivation: str) -> None:
    case_id = f"C3-P3-ADM-{number:03d}"
    write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, "aggregate-step", value, expected, requirements, derivation))
    produced.append(case_id)


# ---------------------------------------------------------------------------
# Group 1: authority withheld, no shared budgets.


def keyed_reserved() -> tuple[dict, dict]:
    facts = fixture(exclusive_keys=KEYS)
    state = zero_state(facts)
    event, host = host_and_event(facts, "RESERVE", "reserve-a", "0",
        {"authority": facts["authority_a"], "histories": [], "exclusive_keys": claims(facts, "authority_a")}, administration=False)
    core = copy.deepcopy(state["core"])
    core["reservations"] = [reservation_record(facts, "authority_a", "reserve-a")]
    core["exclusive_keys"] = key_states(facts, "authority_a", "reserve-a")
    done = transition(state, event, host, core, "RESERVED", reservation_id="reserve-a", authority_result=facts["authority_a_result"])
    return facts, done["state"]


def keyed_settled(facts: dict, state: dict) -> dict:
    record = native(facts, "EFFECT", "native-exclusive-effect")
    record["provider"], record["source"] = "card-provider", "card-system"
    event, host = host_and_event(facts, "SETTLE", "settle-a", state["core"]["revision"],
        {"native": record, "histories": []}, administration=False)
    core = copy.deepcopy(state["core"])
    core["reservations"][0].update(status="SETTLED", matched_effect="effect-1")
    for row in core["exclusive_keys"]:
        row.update(status="CONSUMED", settlement_evidence="effect-1")
    core["effects"] = [effect_record(record, "MATCHED", "MATCHED_EFFECT", affected_anchors=[])]
    return transition(state, event, host, core, "SETTLED", reservation_id="reserve-a")["state"]


def event_request(facts: dict, state: dict, kind: str, event_id: str, payload: dict) -> dict:
    event, host = host_and_event(facts, kind, event_id, state["core"]["revision"], payload, administration=False)
    return request(state, event, host)


def group_one(add) -> None:
    facts, opened = keyed_reserved()
    settled = keyed_settled(facts, opened)
    stopped = revoked(facts["authority_a"])
    premise = ("The budget-free work class has an exclusive key and empty required_budgets. reserve-a is OPEN holding its key. "
        "Every current revocation observation in the supplied authority input reports revoked:true, so its evaluation alone would be AUTHORITY_NOT_ESTABLISHED. ")
    keys = claims(facts, "authority_a")

    add(1, event_request(facts, opened, "RENEW", "renew-missing", {"reservation": "missing-r", "authority": stopped, "histories": [], "exclusive_keys": keys}),
        refusal(opened, "RESERVATION_NOT_FOUND"), ["RES-003", "RES-WIRE-004"],
        premise + "RENEW names missing-r, which no reservation has. RESERVATION-RECORDS: missing reservation references in RENEW/RELEASE are admission failures. " + ORDER + " The result is RESERVATION_NOT_FOUND, not WITHHELD. " + SHAPE)

    changed, _ = authority_specimen(shared_budget=False, exclusive_keys=KEYS, instance_id="instance-1-changed", occurrence_id="issue:1")
    changed["clock"] = clock()
    add(2, event_request(facts, opened, "RENEW", "renew-changed", {"reservation": "reserve-a", "authority": revoked(changed), "histories": [], "exclusive_keys": claims(facts, "authority_a")}),
        refusal(opened, "OCCURRENCE_CONFLICT"), ["RES-003", "RES-006", "RES-WIRE-004"],
        premise + "RENEW names reserve-a but its authority input names instance-1-changed, so the proposal digest differs from the retained one. RESERVATION-RECORDS: a RENEW whose proposal or envelope digest differs from the target's retained digests is OCCURRENCE_CONFLICT. " + ORDER + " The result is OCCURRENCE_CONFLICT, not WITHHELD. " + SHAPE)

    add(3, event_request(facts, settled, "RENEW", "renew-terminal", {"reservation": "reserve-a", "authority": stopped, "histories": [], "exclusive_keys": keys}),
        refusal(settled, "INPUT_INVALID"), ["RES-003", "RES-006", "RES-WIRE-004"],
        "As C3-P3-ADM-001, but an exact native completion has settled reserve-a. RESERVATION-RECORDS: a RENEW whose explicit reservation is SETTLED or RELEASED is INPUT_INVALID. " + ORDER + " " + SHAPE)

    add(4, event_request(facts, opened, "RENEW", "renew-stray", {"reservation": "missing-r", "authority": stopped, "histories": [facts["history"]], "exclusive_keys": keys}),
        refusal(opened, "DEPENDENCY_MISMATCH"), ["RES-003", "RES-WIRE-003", "RES-WIRE-004"],
        premise + "RENEW names missing-r and also supplies a history for a budget this operation does not require, with its HISTORY tuple. RES-WIRE-003: an extra budget identity is DEPENDENCY_MISMATCH. " + ORDER + " DEPENDENCY_MISMATCH precedes RESERVATION_NOT_FOUND. " + SHAPE)

    value = event_request(facts, opened, "RENEW", "renew-control", {"reservation": "reserve-a", "authority": stopped, "histories": [], "exclusive_keys": keys})
    add(5, value, transition(opened, value["event"], value["host_evidence"], copy.deepcopy(opened["core"]), "WITHHELD", reservation_id="reserve-a", budgets=[], authority_result=withheld_result(stopped), reasons=["AUTHORITY_WITHHELD"]),
        ["RES-003", "RES-006", "RES-WIRE-004"],
        "Control for C3-P3-ADM-001 and 002. " + premise + "RENEW names reserve-a with its unchanged proposal and envelope, so admission succeeds. RES-005 and RES-WIRE-004 record the authority refusal as WITHHELD with AUTHORITY_WITHHELD and empty budgets; RES-006 retains the reservation and its permit. The revision advances.")

    add(6, event_request(facts, opened, "RESERVE", "reserve-duplicate", {"authority": stopped, "histories": [], "exclusive_keys": keys}),
        refusal(opened, "OCCURRENCE_CONFLICT"), ["RES-002", "RES-003", "RES-WIRE-004"],
        premise + "RESERVE names the occurrence reserve-a already holds. RESERVATIONS.md: one occurrence can be admitted only once. " + ORDER + " The result is OCCURRENCE_CONFLICT, not WITHHELD. " + SHAPE)

    add(7, event_request(facts, opened, "RESERVE", "reserve-duplicate-stray", {"authority": stopped, "histories": [facts["history"]], "exclusive_keys": keys}),
        refusal(opened, "DEPENDENCY_MISMATCH"), ["RES-002", "RES-003", "RES-WIRE-003", "RES-WIRE-004"],
        "As C3-P3-ADM-006, with an extra history for a budget the operation does not require, and its HISTORY tuple. RES-WIRE-003: an extra budget identity is DEPENDENCY_MISMATCH. " + ORDER + " DEPENDENCY_MISMATCH precedes OCCURRENCE_CONFLICT. " + SHAPE)

    other = revoked(facts["authority_b"])
    value = event_request(facts, opened, "RESERVE", "reserve-other", {"authority": other, "histories": [], "exclusive_keys": claims(facts, "authority_b")})
    withheld = transition(opened, value["event"], value["host_evidence"], copy.deepcopy(opened["core"]), "WITHHELD", budgets=[], authority_result=withheld_result(other), reasons=["AUTHORITY_WITHHELD"])
    add(8, value, withheld, ["RES-002", "RES-003", "RES-WIRE-004"],
        "Control for C3-P3-ADM-006. RESERVE names a different occurrence, so admission succeeds and the revoked authority is recorded as WITHHELD with AUTHORITY_WITHHELD, empty budgets and reservation null. No reservation or key is created. The revision advances.")

    after = withheld["state"]
    value = event_request(facts, after, "RESERVE", "reserve-other-again", {"authority": other, "histories": [], "exclusive_keys": claims(facts, "authority_b")})
    add(9, value, transition(after, value["event"], value["host_evidence"], copy.deepcopy(after["core"]), "WITHHELD", budgets=[], authority_result=withheld_result(other), reasons=["AUTHORITY_WITHHELD"]),
        ["RES-002", "RES-003", "RES-WIRE-004"],
        "After C3-P3-ADM-008, a new event repeats that RESERVE. A WITHHELD receipt creates no reservation, so the occurrence has not been admitted as a reservation and this is not OCCURRENCE_CONFLICT. The result is again WITHHELD with AUTHORITY_WITHHELD.")

    add(10, event_request(facts, settled, "RESERVE", "reserve-terminal", {"authority": stopped, "histories": [], "exclusive_keys": keys}),
        refusal(settled, "OCCURRENCE_CONFLICT"), ["RES-002", "RES-003", "RES-WIRE-004"],
        "As C3-P3-ADM-006, but reserve-a is SETTLED. Its reservation retains the occurrence key, and one occurrence can be admitted only once whatever its later status. " + ORDER + " " + SHAPE)


# ---------------------------------------------------------------------------
# Group 2: shared budgets with exclusive keys (ruling R-f).


def both_facts(keys: list[dict]) -> dict:
    original = rf.authority_specimen
    rf.authority_specimen = lambda **kw: original(**{**kw, "shared_budget": True})
    try:
        return fixture(exclusive_keys=keys)
    finally:
        rf.authority_specimen = original


def registered(facts: dict) -> dict:
    state = zero_state(facts)
    if any("uniqueness" in row for row in facts["configuration"]["exclusive_slots"]):
        state["core"]["key_history"] = []
    event, host = host_and_event(facts, "REGISTER", "register-license-budget", "0",
        {"definition": facts["budget"], "authorizations": facts["authorizations"], "history": facts["history"]})
    core = copy.deepcopy(state["core"])
    core["budgets"] = [{"definition": copy.deepcopy(facts["budget"]), "definition_digest": digest("budget-definition", facts["budget"]),
        "authorizations": copy.deepcopy(facts["authorizations"]), "history": copy.deepcopy(facts["history"])}]
    return transition(state, event, host, core, "REGISTERED")["state"]


def reserved_settled(facts: dict, *, settle: bool = True) -> tuple[dict, dict]:
    """REGISTER, RESERVE reserve-a and, by default, an exact SETTLE. The key, if any, is then CONSUMED."""
    state = registered(facts)
    keys = claims(facts, "authority_a")
    payload = {"authority": facts["authority_a"], "histories": [facts["history"]]}
    if keys:
        payload["exclusive_keys"] = keys
    event, host = host_and_event(facts, "RESERVE", "reserve-a", state["core"]["revision"], payload, administration=False)
    core = copy.deepcopy(state["core"])
    row = reservation_record(facts, "authority_a", "reserve-a")
    if not keys:
        row.pop("exclusive_keys", None)
    # reservation_record leaves contributions empty for an exclusive-key fixture; this class also has a budget.
    row["contributions"] = [{"anchor": "license-spend", "mapping": "pay", "occurrence": row["occurrence_key"],
        "key": [{"type_ref": "beneficiary", "value": "employee-7"}], "value": {"type_ref": "amount", "value": "150"}}]
    core["reservations"] = [row]
    if keys:
        core["exclusive_keys"] = key_states(facts, "authority_a", "reserve-a")
    state = transition(state, event, host, core, "RESERVED", reservation_id="reserve-a", budgets=budget_result(facts, "950"), authority_result=facts["authority_a_result"])["state"]
    if not settle:
        return state, facts["history"]
    record = native(facts, "EFFECT", "native-effect")
    history = matching_history(facts, record)
    event, host = host_and_event(facts, "SETTLE", "settle-a", state["core"]["revision"], {"native": record, "histories": [history]}, administration=False)
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = history
    core["reservations"][0].update(status="SETTLED", matched_effect="effect-1")
    for key in core.get("exclusive_keys", []):
        key.update(status="CONSUMED", settlement_evidence="effect-1")
    core["effects"] = [effect_record(record, "MATCHED", "MATCHED_EFFECT")]
    return transition(state, event, host, core, "SETTLED", reservation_id="reserve-a")["state"], history


def extended(history: dict, *records: dict) -> dict:
    value = copy.deepcopy(history)
    for record in records:
        value["journal"].append({"sequence": str(len(value["journal"]) + 1), "event": record})
    value["revision"] = str(len(value["journal"]))
    return value


def retraction(history: dict) -> dict:
    return extended(history, {"id": history["journal"][-1]["event"]["id"], "state": "RETRACTED"})


def unrelated(history: dict) -> dict:
    return extended(history, {"id": "c3-p3-adm-unrelated", "state": "ACTIVE", "occurred_at": "2026-09-10T04:30:00Z", "fields": [
        {"name": "amount", "value": {"type_ref": "amount", "value": "10"}},
        {"name": "beneficiary", "value": {"type_ref": "beneficiary", "value": "employee-9"}},
    ]})


def unavailable(history: dict) -> dict:
    return {"budget_digest": history["budget_digest"], "provider": history["provider"], "source": history["source"], "status": "UNAVAILABLE",
        "as_of": None, "complete": False, "revision": None, "journal": None, "evidence_ref": "history-unavailable"}


def withheld_transition(facts: dict, value: dict, reason: str, *, history: dict | None, disputed: bool) -> dict:
    core = copy.deepcopy(value["state"]["core"])
    if history is not None:
        core["budgets"][0]["history"] = copy.deepcopy(history)
    if disputed:
        next(row for row in core["reservations"] if row["id"] == "reserve-a")["status"] = "DISPUTED"
    return transition(value["state"], value["event"], value["host_evidence"], core, "WITHHELD", budgets=[], authority_result=facts["authority_b_result"], reasons=[reason])


def mediated_facts(keys: list[dict] | None = None, plain_keys: list[dict] | None = None) -> dict:
    """reserve-a uses a class revision with plain_keys (default none); reserve-b's revision requests keys, whose mediated slot has no installed snapshot."""
    facts = both_facts(keys or MEDIATED_KEYS)
    fields = [{"name": name, "type_ref": "amount" if name == "amount" else "IDENTITY"} for name in ("amount", "beneficiary", "card_id")]
    for slot in facts["configuration"]["exclusive_slots"]:
        if slot["slot"] == "card-identity" and plain_keys:
            continue
        slot.update({
            "key_shape": [{"name": "card_id", "type_ref": "IDENTITY"}],
            "types": copy.deepcopy(facts["authority_a"]["work_class"]["types"]),
            "history_record_fields": {"held": copy.deepcopy(fields), "consumed": copy.deepcopy(fields)},
            "history_projection": [{"key_field": "card_id", "kind": "NATIVE_FIELD", "field": "card_id", "type_ref": "IDENTITY"}],
            "uniqueness": {"kind": "EXCLUSIVE_MEDIATOR_SEEDED", "provider": PROVIDER, "source": SOURCE, "record_type": "synthetic-card-history",
                "history_scope": slot["slot"] + "-complete-uses", "cutover_id": "cutover-1", "evidence_ref": "synthetic-all-writer-premise"},
        })
    extra = {"exclusive_keys": plain_keys} if plain_keys else {}
    plain, plain_result = authority_specimen(shared_budget=True, instance_id="instance-1", occurrence_id="issue:1", **extra)
    plain["clock"] = clock()
    facts["authority_a"], facts["authority_a_result"] = plain, plain_result
    rows = []
    for name, authority in (("license-class-authorization-a", plain), ("license-class-authorization-b", facts["authority_b"])):
        row = copy.deepcopy(facts["authorizations"][0])
        row.update(id=name, work_class_digest=digest("authority-work-class", authority["work_class"]), envelope_digest=digest("authority-envelope", authority["envelope"]))
        row["authority_definition"] = {"schema": row["authority_definition"]["schema"], **{key: copy.deepcopy(authority[key]) for key in ("source", "work_class", "envelope")}}
        rows.append(row)
    if canonical_bytes(rows[0]) > canonical_bytes(rows[1]):
        rows[0]["id"], rows[1]["id"] = rows[1]["id"], rows[0]["id"]
        rows.reverse()
    facts["authorizations"] = rows
    return facts


def group_two(add) -> None:
    facts = both_facts(KEYS)
    settled, history = reserved_settled(facts)
    keys = claims(facts, "authority_b")
    setup = ("The class has a shared budget and an exclusive key. Setup: REGISTER, RESERVE reserve-a and an exact SETTLE leave reserve-a SETTLED, its effect MATCHED and its key CONSUMED. "
        "The event: RESERVE reserve-b for another occurrence naming the same business key, with READY authority. Any existing HELD or CONSUMED owner occupies the key (EXCLUSIVE-KEY-HISTORY section 6). ")

    def reserve_b(state: dict, event_id: str, supplied: dict) -> dict:
        return event_request(facts, state, "RESERVE", event_id, {"authority": facts["authority_b"], "histories": [supplied], "exclusive_keys": keys})

    supplied = retraction(history)
    value = reserve_b(settled, "reserve-b", supplied)
    occupied = withheld_transition(facts, value, "EXCLUSIVE_KEY_OCCUPIED", history=supplied, disputed=True)
    add(11, value, occupied, ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        setup + "The supplied current complete history retracts reserve-a's prescribed record. " + RF + " So the history is committed, reserve-a becomes DISPUTED under the retraction rule, the only reason is EXCLUSIVE_KEY_OCCUPIED, budgets are empty and no reservation or key is created.")

    supplied = unrelated(history)
    value = reserve_b(settled, "reserve-b", supplied)
    add(12, value, withheld_transition(facts, value, "EXCLUSIVE_KEY_OCCUPIED", history=supplied, disputed=False), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        setup + "The supplied current complete history adds an unrelated event and retracts nothing. " + RF + " The history is committed and reserve-a stays SETTLED.")

    value = reserve_b(settled, "reserve-b", unavailable(history))
    add(13, value, withheld_transition(facts, value, "EXCLUSIVE_KEY_OCCUPIED", history=None, disputed=False), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        setup + "The supplied history is UNAVAILABLE, with null revision, journal and as_of. It is not current and complete, and RESERVATION-RECORDS says unavailable history does not update the journal. " + RF + " The only reason is EXCLUSIVE_KEY_OCCUPIED, not HISTORY_UNAVAILABLE as well, and the retained journal is unchanged.")

    after = occupied["state"]
    current = after["core"]["budgets"][0]["history"]
    value = reserve_b(after, "reserve-b-again", current)
    add(14, value, withheld_transition(facts, value, "EXCLUSIVE_KEY_OCCUPIED", history=current, disputed=False), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        "After C3-P3-ADM-011, reserve-a is DISPUTED and blocks its reserved partition, and reserve-b's contribution is in that partition. A new RESERVE repeats the request with the current history. " + RF + " The only reason is EXCLUSIVE_KEY_OCCUPIED, not EXPOSURE_DISPUTED as well, and budgets are empty, so no blocked aggregate judgment is reported.")

    facts = mediated_facts()
    settled, history = reserved_settled(facts)
    keys = claims(facts, "authority_b")
    setup = ("A budget registers two exact class authorizations. reserve-a used the class revision without a key and is SETTLED with a MATCHED effect. reserve-b's revision requests a mediated exclusive slot, and no complete snapshot is installed for it. "
        "EXCLUSIVE-KEY-HISTORY section 6: missing usable coverage produces admitted WITHHELD with EXCLUSIVE_HISTORY_UNAVAILABLE before occupancy lookup, creating no reservation or key. ")
    supplied = retraction(history)
    value = event_request(facts, settled, "RESERVE", "reserve-b", {"authority": facts["authority_b"], "histories": [supplied], "exclusive_keys": keys})
    add(15, value, withheld_transition(facts, value, "EXCLUSIVE_HISTORY_UNAVAILABLE", history=supplied, disputed=True), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        setup + "The supplied current complete history retracts reserve-a's prescribed record. " + RF + " The prohibition on partial writes covers reservations and keys, so the history is committed and reserve-a becomes DISPUTED, with that reason alone and empty budgets.")

    value = event_request(facts, settled, "RESERVE", "reserve-b", {"authority": facts["authority_b"], "histories": [unavailable(history)], "exclusive_keys": keys})
    add(16, value, withheld_transition(facts, value, "EXCLUSIVE_HISTORY_UNAVAILABLE", history=None, disputed=False), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        setup + "The supplied history is UNAVAILABLE, so it is not current and complete and does not update the journal. " + RF + " The only reason is EXCLUSIVE_HISTORY_UNAVAILABLE.")

    # Several slots: a provider slot the first reservation occupies, and a mediated slot with no snapshot.
    two = [{**MEDIATED_KEYS[0], "id": "badge-key", "slot": "badge-identity", "namespace": "badge"}, KEYS[0]]
    facts = mediated_facts(two, [KEYS[0]])
    settled, history = reserved_settled(facts)
    supplied = retraction(history)
    value = event_request(facts, settled, "RESERVE", "reserve-b", {"authority": facts["authority_b"], "histories": [supplied], "exclusive_keys": claims(facts, "authority_b")})
    add(21, value, withheld_transition(facts, value, "EXCLUSIVE_HISTORY_UNAVAILABLE", history=supplied, disputed=True), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        "reserve-a holds a CONSUMED provider-slot key and is SETTLED. reserve-b requests that occupied key and a key in a mediated slot with no installed snapshot, with a current complete history that retracts reserve-a's prescribed record. "
        "EXCLUSIVE-KEY-HISTORY section 6: missing usable coverage produces WITHHELD before occupancy lookup. " + RF + " The only reason is EXCLUSIVE_HISTORY_UNAVAILABLE, not EXCLUSIVE_KEY_OCCUPIED as well; the history is committed and reserve-a becomes DISPUTED.")

    # Stale: the journal is unchanged, but as_of is older than the 60-second MAX_AGE allows at the event clock.
    def stale(value: dict) -> dict:
        changed = copy.deepcopy(value)
        changed["as_of"] = "2026-09-10T04:20:00Z"
        return changed

    facts = both_facts(KEYS)
    opened, history = reserved_settled(facts, settle=False)
    value = event_request(facts, opened, "RESERVE", "reserve-b", {"authority": facts["authority_b"], "histories": [stale(history)], "exclusive_keys": claims(facts, "authority_b")})
    add(22, value, withheld_transition(facts, value, "EXCLUSIVE_KEY_OCCUPIED", history=None, disputed=False), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        "reserve-a is OPEN holding the key reserve-b requests. The supplied history has as_of 2026-09-10T04:20:00Z, ten minutes before the event clock, and the committed source declares MAX_AGE 60 seconds, so it is stale. RESERVATION-RECORDS: stale history does not update the journal. " + RF + " The only reason is EXCLUSIVE_KEY_OCCUPIED, not HISTORY_STALE as well, and the retained journal is unchanged.")

    facts = mediated_facts()
    opened, history = reserved_settled(facts, settle=False)
    value = event_request(facts, opened, "RESERVE", "reserve-b", {"authority": facts["authority_b"], "histories": [stale(history)], "exclusive_keys": claims(facts, "authority_b")})
    add(23, value, withheld_transition(facts, value, "EXCLUSIVE_HISTORY_UNAVAILABLE", history=None, disputed=False), ["RES-007A", "RES-WIRE-003", "RES-WIRE-004"],
        "reserve-b requests a mediated slot with no installed snapshot, and its history is stale as in C3-P3-ADM-022. " + RF + " The only reason is EXCLUSIVE_HISTORY_UNAVAILABLE and the retained journal is unchanged.")


# ---------------------------------------------------------------------------
# Group 3: DISPOSE retraction marking (ruling R-a).


def dispose_state(facts: dict) -> tuple[dict, dict]:
    """reserve-a DISPUTED, reserve-b SETTLED with a prescribed record, in one budget."""
    _, reserved = recovery.reserve(facts, recovery.registered(facts))
    state = reserved["state"]
    event, host = host_and_event(facts, "RESERVE", "reserve-b", state["core"]["revision"],
        {"authority": facts["authority_b"], "histories": [facts["history"]]}, administration=False)
    core = copy.deepcopy(state["core"])
    core["reservations"].append(reservation_record(facts, "authority_b", "reserve-b"))
    state = transition(state, event, host, core, "RESERVED", reservation_id="reserve-b", budgets=budget_result(facts, str(100 + int(facts["amount"]) + 150)), authority_result=facts["authority_b_result"])["state"]

    proposal = facts["authority_b"]["proposal"]
    attributed = {key: copy.deepcopy(proposal[key]) for key in ("work_class", "instance", "occurrence", "step", "operation", "interface", "fields")}
    record = native(facts, "EFFECT", "native-b", reservation_id="reserve-b", request_record=attributed, effect_id="effect-b")
    history = matching_history(facts, record)
    event, host = host_and_event(facts, "SETTLE", "settle-b", state["core"]["revision"], {"native": record, "histories": [history]}, administration=False)
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = history
    next(row for row in core["reservations"] if row["id"] == "reserve-b").update(status="SETTLED", matched_effect="effect-b")
    core["effects"].append(effect_record(record, "MATCHED", "MATCHED_EFFECT"))
    state = transition(state, event, host, core, "SETTLED", reservation_id="reserve-b")["state"]

    record = native(facts, "UNKNOWN", "native-disputed", completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
    event, host = host_and_event(facts, "SETTLE", "retain-disputed-outcome", state["core"]["revision"], {"native": record, "histories": [history]}, administration=False)
    core = copy.deepcopy(state["core"])
    next(row for row in core["reservations"] if row["id"] == "reserve-a")["status"] = "DISPUTED"
    core["effects"].append(effect_record(record, "DISPUTED", "UNEXPECTED_EFFECT", [{"anchor": "license-spend", "key": None}]))
    core["effects"].sort(key=lambda row: row["id"].encode("utf-8"))
    return transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])["state"], history


def disposition_with_marking(supplied: dict, marked: bool, total: str | None = None, unassessed: bool = False) -> dict:
    original = recovery.transition

    def wrapped(before, event, host, core, *args, **kwargs):
        if marked:
            next(row for row in core["reservations"] if row["id"] == "reserve-b")["status"] = "DISPUTED"
        if unassessed:
            kwargs["budgets"] = []
        if total is not None:
            kwargs["budgets"] = budget_result({"budget": core["budgets"][0]["definition"]}, total)
        return original(before, event, host, core, *args, **kwargs)

    recovery.transition = wrapped
    try:
        return recovery.disposition_expected(supplied, reasons=["HISTORY_UNCORROBORATED", "RECOVERY_EVIDENCE_INCOMPLETE"] if unassessed else None, effective_result="LEAVE_UNRESOLVED" if unassessed else None)
    finally:
        recovery.transition = original


def group_three(add) -> None:
    facts = recovery.facts_for()
    facts["history"]["journal"][0]["event"]["fields"][0]["value"]["value"] = "100"
    state, history = dispose_state(facts)
    setup = ("Setup: in one budget with opening 100, reserve-a is DISPUTED by a mismatched native record and reserve-b is SETTLED with a prescribed journal record. The event: DISPOSE reserve-a with LEAVE_UNRESOLVED under the recovery contract. ")
    supplied = retraction(history)
    value = recovery.dispose_request(facts, state, "LEAVE_UNRESOLVED", histories=[supplied])
    add(17, value, disposition_with_marking(value, True), ["REC-004", "RES-WIRE-003", "RES-WIRE-004"],
        setup + "Its current complete history retracts reserve-b's prescribed record. RESERVATION-RECORDS: a history newly admitted with a non-duplicate event that retracts a prescribed event for a SETTLED reservation marks it DISPUTED, leaving its MATCHED effect record unchanged, and the marking applies when the history is admitted, before the event's own policy evaluation. So reserve-b becomes DISPUTED and the history is adopted with the recorded disposition.")
    supplied = unrelated(history)
    value = recovery.dispose_request(facts, state, "LEAVE_UNRESOLVED", histories=[supplied])
    add(18, value, disposition_with_marking(value, False), ["REC-004", "RES-WIRE-003", "RES-WIRE-004"],
        "Control for C3-P3-ADM-017. " + setup + "Its current complete history adds an unrelated event and retracts nothing, so reserve-b stays SETTLED and the history is adopted with the recorded disposition.")

    # ACCEPT_UNRESOLVED evaluates the aggregate, so the order of marking and evaluation is observable.
    facts = recovery.facts_for("2")
    facts["history"]["journal"][0]["event"]["fields"][0]["value"]["value"] = "100"
    state, history = dispose_state(facts)
    issued = recovery.policy_issue(facts, state)
    policy_digest = issued[0]["event"]["payload"]["policy_digest"]
    state = issued[1]["state"]
    setup = ("Setup: in one budget with opening 100, reserve-a (2 USD) is DISPUTED by an unknown native record, reserve-b (150 USD) is SETTLED with a prescribed journal record, and a small-duplicate-payments policy is current. "
        "The event: DISPOSE reserve-a with ACCEPT_UNRESOLVED over a complete inventory of two attempts of one execution each, so one contingent execution of 2 USD remains. REC and AGG-004 evaluate reserve-a's partition, employee-7. ")
    value = recovery.dispose_request(facts, state, "ACCEPT_UNRESOLVED", policy_digest=policy_digest, histories=[retraction(history)])
    add(19, value, disposition_with_marking(value, True, unassessed=True), ["REC-004", "REC-010", "RES-WIRE-003", "RES-WIRE-004"],
        setup + "The current complete history retracts reserve-b's prescribed record, marking it DISPUTED. The target's cap remains assessable at 4 USD, but the same employee-7 ordinary aggregate depends on reserve-b's uncorroborated actual. R-p withholds with empty budgets and no allowance; the finite contingent inventory is retained.")
    value = recovery.dispose_request(facts, state, "ACCEPT_UNRESOLVED", policy_digest=policy_digest, histories=[unrelated(history)])
    add(20, value, disposition_with_marking(value, False, "254"), ["REC-004", "REC-010", "RES-WIRE-003", "RES-WIRE-004"],
        "Control for C3-P3-ADM-019. " + setup + "The current complete history adds an unrelated employee-9 event and retracts nothing, so reserve-b stays SETTLED and its 150 stays committed: committed 250, reserve-a 2 and contingent 2, total 254, SATISFIED within 1000.")


# ---------------------------------------------------------------------------
# Group 4: retained LEAVE_UNRESOLVED (rulings R-h and R-i).


def contingent_rows(state: dict, supplied: dict, *, result: str | None = None) -> list[dict]:
    """REC-008: every possible execution after the first has one row per contribution, bound by R-h to this disposition."""
    payload = supplied["event"]["payload"]
    reservation = next(row for row in state["core"]["reservations"] if row["id"] == payload["target"]["reservation"])
    bound = recovery.disposition_record(supplied, result=result)["id"]
    slots = [(attempt, index) for attempt in payload["evidence"]["attempts"] if not attempt["no_effect"]
        for index in range(len(attempt["effect_ids"]) + 1, int(attempt["maximum_executions"]) + 1)]
    rows = []
    for attempt, index in slots[1:]:
        for contribution in reservation["contributions"]:
            identity = {"registry_digest": payload["target"]["registry_digest"], "reservation": reservation["id"], "attempt_id": attempt["id"],
                "execution_index": str(index), **{key: copy.deepcopy(contribution[key]) for key in ("anchor", "mapping", "key")}}
            rows.append({"id": digest("recovery-contingent", identity), "disposition_digest": bound, "reservation": reservation["id"],
                "attempt_id": attempt["id"], "execution_index": str(index), **copy.deepcopy(contribution)})
    return sorted(rows, key=canonical_bytes)


def leave_expected(supplied: dict, *, rows: bool = False, adopt: bool = True, reasons: list[str] | None = None) -> dict:
    effective = "LEAVE_UNRESOLVED" if reasons else None
    original = recovery.transition

    def wrapped(before, event, host, core, *args, **kwargs):
        if rows:
            core["recovery"]["contingent"] = contingent_rows(before, supplied, result=effective)
        if not adopt:
            core["budgets"] = copy.deepcopy(before["core"]["budgets"])
        return original(before, event, host, core, *args, **kwargs)

    recovery.transition = wrapped
    try:
        return recovery.disposition_expected(supplied, reasons=reasons, effective_result=effective)
    finally:
        recovery.transition = original


def group_four(add) -> None:
    facts = recovery.facts_for("2")
    state = recovery.disputed(facts)
    setup = "Setup: reserve-a (2 USD, opening 800) is DISPUTED by an unknown native record. "
    rule = ("REC-008, ruling R-h: every possible execution remains represented, and a retained disposition with a complete finite attempt inventory, including an explicit LEAVE_UNRESOLVED, "
        "replaces the reservation's current contingent rows with that inventory, each row's disposition_digest naming that disposition. The original reservation supplies the first execution. ")
    for number, attempts in ((24, 2), (25, 3)):
        evidence = recovery.evidence_for(facts, state, conclusion="UNRESOLVED", attempts=attempts)
        value = recovery.dispose_request(facts, state, "LEAVE_UNRESOLVED", evidence=evidence)
        result = leave_expected(value, rows=True)
        add(number, value, result, ["REC-008", "RES-WIRE-004"],
            setup + f"The event: explicit LEAVE_UNRESOLVED over a complete inventory of {attempts} attempts of one execution each. " + rule + f"So {attempts - 1} contingent row(s) are committed. RECOVERY: explicit LEAVE_UNRESOLVED grants nothing and retains DISPOSITION_RECORDED.")
        if number == 24:
            left = result["state"]

    issued = recovery.policy_issue(facts, state)
    policy_digest = issued[0]["event"]["payload"]["policy_digest"]
    accept = recovery.dispose_request(facts, issued[1]["state"], "ACCEPT_UNRESOLVED", policy_digest=policy_digest)
    accepted = recovery.disposition_expected(accept)
    previous = recovery.disposition_record(accept)["id"]
    value = recovery.dispose_request(facts, accepted["state"], "LEAVE_UNRESOLVED", event_id="leave-after-accept", supersedes=previous, evidence=accept["event"]["payload"]["evidence"])
    add(26, value, leave_expected(value, rows=True), ["REC-008", "RES-WIRE-004"],
        setup + "A current policy accepted the incident with ACCEPT_UNRESOLVED over two attempts, committing one contingent row and its allowance. The event: explicit LEAVE_UNRESOLVED supersedes that disposition over the same inventory. " + rule + "So the row's identity and value are unchanged and its disposition_digest names the LEAVE_UNRESOLVED disposition. Allowance history is append-only and is retained.")

    event, host = host_and_event(facts, "RESERVE", "reserve-b", left["core"]["revision"], {"authority": facts["authority_b"], "histories": [facts["history"]]}, administration=False)
    add(27, request(left, event, host), transition(left, event, host, copy.deepcopy(left["core"]), "WITHHELD", budgets=budget_result(facts, "954"), authority_result=facts["authority_b_result"], reasons=["EXPOSURE_DISPUTED"]),
        ["REC-008", "REC-010", "RES-WIRE-004"],
        "After C3-P3-ADM-024, RESERVE reserve-b (150 USD, employee-7) with READY authority. reserve-a's retained null-key effect blocks the anchor, so the contribution is blocked. RESERVATION-RECORDS: a blocked new contribution is still evaluated and its WITHHELD receipt carries that judgment with EXPOSURE_DISPUTED. REC-008: contingent rows are retained pending exposure. "
        "Committed 800, reserve-a 2, its contingent row 2 and the new 150: total 954, SATISFIED within 1000. No reservation is created.")

    rule = "RECOVERY, ruling R-i: an unusable supplied history is not adopted and adds no reason to an explicit LEAVE_UNRESOLVED, which retains DISPOSITION_RECORDED. "
    history = facts["history"]
    incomplete = unavailable(history)
    incomplete["status"] = "INCOMPLETE"
    aged = copy.deepcopy(history)
    aged["as_of"] = "2026-09-10T04:20:00Z"
    for number, name, supplied in ((28, "UNAVAILABLE", unavailable(history)), (29, "INCOMPLETE", incomplete), (30, "stale under the 60-second MAX_AGE", aged)):
        value = recovery.dispose_request(facts, state, "LEAVE_UNRESOLVED", histories=[supplied])
        add(number, value, leave_expected(value, adopt=False), ["REC-016", "RES-WIRE-004"],
            setup + f"The event: explicit LEAVE_UNRESOLVED over one attempt, whose supplied history is {name}. " + rule + "The result has no reasons and the retained journal is unchanged.")

    evidence = recovery.evidence_for(facts, state, conclusion="UNRESOLVED", attempts=2)
    value = recovery.dispose_request(facts, state, "ESTABLISH_EFFECT", evidence=evidence)
    add(31, value, leave_expected(value, rows=True, reasons=["RECOVERY_EVIDENCE_INCOMPLETE"]), ["REC-006", "REC-008", "RES-WIRE-004"],
        setup + "The event: an authorized ESTABLISH_EFFECT whose packet concludes UNRESOLVED over a complete inventory of two attempts and establishes no effect. REC-006 requires a complete packet establishing the exact attributable effects, so the evidence is incomplete: RECOVERY_EVIDENCE_INCOMPLETE. RECOVERY reserves RECOVERY_CONFLICT_UNRESOLVED for a covered conclusive contradiction, and an unresolved packet with no retained conclusive fact has none. A failed substantive condition retains LEAVE_UNRESOLVED with WITHHELD, and under ruling R-h that retained disposition commits one contingent row bound to itself.")


def main() -> None:
    assert candidate_pin() == EXPECTED_PIN, candidate_pin()
    GROUP.mkdir(parents=True, exist_ok=True)
    for stale in GROUP.glob("*.json"):
        stale.unlink()
    produced: list[str] = []

    def add(number, value, expected, requirements, derivation):
        emit(produced, number, value, expected, requirements, derivation)

    group_one(add)
    group_two(add)
    group_three(add)
    group_four(add)
    print(json.dumps({"output": str(GROUP), "case_ids": produced}, indent=2))


if __name__ == "__main__":
    main()
