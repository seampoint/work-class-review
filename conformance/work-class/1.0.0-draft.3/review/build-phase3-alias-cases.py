#!/usr/bin/env python3
"""Build phase-3 committed-source alias vectors from RESERVATION-RECORDS, AGGREGATES and RECOVERY.

A shared budget whose aggregate committed_source declares key and contribution field names
that differ from the proposal mapping's field names ("source aliases"). RES-WIRE-002 fixes the
prescribed terminal history record: its ACTIVE fields are exactly the committed_source's key
fields carrying the contribution key values, plus the committed_source contribution field
carrying the contribution value for SUM or CARDINALITY, sorted by field name. COUNT has no
contribution field.

The alias names mirror the r8 sealed regression `reserve-valid-committed-source-aliases`
(`historical-beneficiary`, `historical-amount`). The prior REGISTERED and RESERVED states are
rebuilt here from the draft-3 reservation fixture under candidate_pin(), so every digest is
recomputed; the r8 bytes carry the old pin and are not reused.

Expected results are constructed only from the normative text and the digest rules in
corpus_common. No consumer is imported, executed or read.
"""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, canonical_bytes, candidate_pin, digest, exact_case, write_canonical_json
from fixture_factory import PIN
from recovery_fixture import (
    disposition_expected,
    dispose_request,
    evidence_for,
    facts_for as recovery_facts_for,
    registered as recovery_registered,
)
from authority_fixture import authority_specimen
from reservation_fixture import (
    effect_record,
    fixture,
    host_and_event,
    native,
    refusal,
    registered_state,
    request,
    reservation_record,
    settled_state,
    transition,
    V,
)


GROUP = CASES / "phase3-alias"
ANCHOR = "license-spend"
SOURCE_KEY = "historical-beneficiary"
SOURCE_CONTRIBUTION = {"SUM": "historical-amount", "CARDINALITY": "historical-card", "COUNT": None}
MAPPING_CONTRIBUTION = {"SUM": "amount", "CARDINALITY": "card", "COUNT": None}

assert PIN == candidate_pin()


# ---------------------------------------------------------------------------
# Facts


def proposal_value(facts: dict, name: str) -> str:
    return next(row["value"]["value"] for row in facts["authority_a"]["proposal"]["fields"] if row["name"] == name)


def native_type(facts: dict, name: str) -> str:
    authorization = facts["authorizations"][0]
    step = next(row for row in authorization["authority_definition"]["work_class"]["steps"] if row["id"] == authorization["step"])
    return next(row["type_ref"] for row in step["fields"] if row["name"] == name)


def shape_facts(facts: dict, *, reducer: str = "SUM", aliased: bool = True, two_mappings: bool = False, opening: str = "800") -> dict:
    """Rewrite the draft-3 reservation fixture's budget for one reducer and alias choice.

    The opening journal keeps one unrelated ACTIVE event for employee-7 (800 USD for SUM,
    one row for COUNT, element card-801 for CARDINALITY) under the committed_source names.
    """
    assert not (two_mappings and reducer != "SUM")
    definition = facts["budget"]["aggregate"]
    aggregate = definition["aggregate"]
    source = aggregate["committed_source"]
    key_name = SOURCE_KEY if aliased else "beneficiary"
    contribution_name = (SOURCE_CONTRIBUTION if aliased else MAPPING_CONTRIBUTION)[reducer]
    mapping_contribution = MAPPING_CONTRIBUTION[reducer]

    if reducer == "SUM":
        contribution = {"kind": "SUM", "field": mapping_contribution}
    elif reducer == "COUNT":
        contribution = {"kind": "COUNT"}
    else:
        contribution = {"kind": "CARDINALITY", "field": mapping_contribution}
    if reducer != "SUM":
        aggregate.update(reducer=reducer, result_type="count", bound={"type_ref": "count", "value": "1000"},
            element_type="beneficiary" if reducer == "CARDINALITY" else None)
    mapping = aggregate["mappings"][0]
    mapping["contribution"] = copy.deepcopy(contribution)
    source["key_fields"] = [key_name]
    source["contribution"] = {"kind": reducer, **({"field": contribution_name} if contribution_name else {})}
    if two_mappings:
        second = copy.deepcopy(mapping)
        second["id"] = "pay-card"
        second["key_fields"] = ["card"]
        aggregate["mappings"] = sorted([mapping, second], key=lambda row: row["id"].encode("utf-8"))

    projection = [{"native_field": "beneficiary", "native_type": native_type(facts, "beneficiary"),
        "budget_field": "beneficiary", "budget_type": "beneficiary"}]
    if reducer == "SUM":
        projection.append({"native_field": "amount", "native_type": native_type(facts, "amount"),
            "budget_field": "amount", "budget_type": "amount"})
    if reducer == "CARDINALITY" or two_mappings:
        projection.append({"native_field": "card_id", "native_type": native_type(facts, "card_id"),
            "budget_field": "card", "budget_type": "beneficiary"})
    projection.sort(key=lambda row: row["budget_field"].encode("utf-8"))

    opening_fields = {key_name: {"type_ref": "beneficiary", "value": "employee-7"}}
    if reducer == "SUM":
        opening_fields[contribution_name] = {"type_ref": "amount", "value": opening}
    elif reducer == "CARDINALITY":
        opening_fields[contribution_name] = {"type_ref": "beneficiary", "value": "card-801"}
    facts["history"]["journal"][0]["event"]["fields"] = [
        {"name": name, "value": opening_fields[name]} for name in sorted(opening_fields, key=lambda value: value.encode("utf-8"))
    ]

    budget_digest = digest("budget-definition", facts["budget"])
    facts["history"]["budget_digest"] = budget_digest
    for authorization in facts["authorizations"]:
        authorization["budget_digest"] = budget_digest
        authorization["projection"] = copy.deepcopy(projection)
    facts["reducer"] = reducer
    facts["aliased"] = aliased
    facts["two_mappings"] = two_mappings
    facts["opening"] = opening
    return facts


def alias_facts(**options) -> dict:
    return shape_facts(fixture(), **options)


# ---------------------------------------------------------------------------
# Contributions, evaluations and prescribed records


def contributions(facts: dict, authority_key: str = "authority_a") -> list:
    """RES-WIRE-002: one retained contribution per selected mapping, sorted by [anchor,mapping,occurrence,key]."""
    proposal = facts[authority_key]["proposal"]
    occurrence = digest("reservation-occurrence",
        {"work_class": proposal["work_class"], "instance": proposal["instance"], "occurrence": proposal["occurrence"]})
    projected = {
        row["budget_field"]: {"type_ref": row["budget_type"],
            "value": next(f["value"]["value"] for f in proposal["fields"] if f["name"] == row["native_field"])}
        for row in facts["authorizations"][0]["projection"]
    }
    rows = []
    for mapping in facts["budget"]["aggregate"]["aggregate"]["mappings"]:
        kind = mapping["contribution"]["kind"]
        value = {"type_ref": "count", "value": "1"} if kind == "COUNT" else copy.deepcopy(projected[mapping["contribution"]["field"]])
        rows.append({"anchor": ANCHOR, "mapping": mapping["id"], "occurrence": occurrence,
            "key": [copy.deepcopy(projected[name]) for name in mapping["key_fields"]], "value": value})
    return sorted(rows, key=lambda row: canonical_bytes([row["anchor"], row["mapping"], row["occurrence"], row["key"]]))


def reserve_evaluation(facts: dict) -> list:
    """AGG-004/AGG-008 for the opening journal plus the one new proposal (no other pending)."""
    reducer = facts["reducer"]
    partitions = []
    for row in contributions(facts):
        on_opening = row["key"] == [{"type_ref": "beneficiary", "value": "employee-7"}]
        if reducer == "SUM":
            total = str((int(facts["opening"]) if on_opening else 0) + int(row["value"]["value"]))
            accumulator = {"kind": "SCALAR", "value": total}
        elif reducer == "COUNT":
            total = str((1 if on_opening else 0) + 1)
            accumulator = {"kind": "SCALAR", "value": total}
        else:
            values = sorted(([{"type_ref": "beneficiary", "value": "card-801"}] if on_opening else []) + [row["value"]], key=canonical_bytes)
            total = str(len(values))
            accumulator = {"kind": "SET", "values": values}
        partitions.append({"occurrence": None, "key": copy.deepcopy(row["key"]), "accumulator": accumulator,
            "result": total, "status": "SATISFIED", "reasons": []})
    partitions.sort(key=lambda row: canonical_bytes({"occurrence": row["occurrence"], "key": row["key"]}))
    return [{"anchor": ANCHOR, "result": {
        "schema": V + "/aggregate-result", "specification_pin": PIN,
        "definition_digest": digest("aggregate-definition", facts["budget"]["aggregate"]),
        "status": "SATISFIED", "partitions": partitions, "reasons": []}}]


def prescribed_record(facts: dict, row: dict, effect_id: str, occurred_at: str, *, names: str = "source") -> dict:
    """RES-WIRE-002's prescribed committed record.

    names="source" is the text's record. names="mapping" substitutes the proposal mapping's
    field names, and names="both" supplies the union of both inventories; neither is the
    prescribed record.
    """
    aggregate = facts["budget"]["aggregate"]["aggregate"]
    source = aggregate["committed_source"]
    mapping = next(m for m in aggregate["mappings"] if m["id"] == row["mapping"])
    fields = {}
    if names in ("source", "both"):
        fields.update(dict(zip(source["key_fields"], row["key"])))
        if source["contribution"]["kind"] in ("SUM", "CARDINALITY"):
            fields[source["contribution"]["field"]] = row["value"]
    if names in ("mapping", "both"):
        fields.update(dict(zip(mapping["key_fields"], row["key"])))
        if mapping["contribution"]["kind"] in ("SUM", "CARDINALITY"):
            fields[mapping["contribution"]["field"]] = row["value"]
    return {
        "id": digest("reservation-committed-event", {"budget_digest": facts["history"]["budget_digest"], "effect_id": effect_id, "mapping": row["mapping"]}),
        "state": "ACTIVE",
        "occurred_at": occurred_at,
        "fields": [{"name": name, "value": copy.deepcopy(fields[name])} for name in sorted(fields, key=lambda value: value.encode("utf-8"))],
    }


def history_with(facts: dict, base_history: dict, records: list) -> dict:
    history = copy.deepcopy(base_history)
    for record in records:
        history["journal"].append({"sequence": str(len(history["journal"]) + 1), "event": record})
    history["revision"] = str(len(history["journal"]))
    return history


# ---------------------------------------------------------------------------
# States


def reserved(facts: dict, prior: dict) -> dict:
    event, host = host_and_event(facts, "RESERVE", "reserve-a", prior["core"]["revision"],
        {"authority": facts["authority_a"], "histories": [prior["core"]["budgets"][0]["history"]]}, administration=False)
    core = copy.deepcopy(prior["core"])
    row = reservation_record(facts, "authority_a", "reserve-a")
    row["contributions"] = contributions(facts)
    core["reservations"].append(row)
    core["reservations"].sort(key=lambda item: item["id"].encode("utf-8"))
    return transition(prior, event, host, core, "RESERVED", reservation_id="reserve-a",
        budgets=reserve_evaluation(facts), authority_result=facts["authority_a_result"])["state"]


def open_alias_state(facts: dict) -> dict:
    return reserved(facts, registered_state(facts))


def settle(facts: dict, state: dict, case_id: str, history: dict, native_record: dict) -> tuple[dict, dict, dict]:
    event, host = host_and_event(facts, "SETTLE", "settle-" + case_id.lower(), state["core"]["revision"],
        {"native": native_record, "histories": [history]}, administration=False)
    return event, host, request(state, event, host)


# ---------------------------------------------------------------------------
# Cases


def label(facts: dict) -> str:
    if facts["two_mappings"]:
        return "SUM budget with two mappings (pay keyed by beneficiary, pay-card keyed by card)"
    return facts["reducer"] + (" budget with source aliases" if facts["aliased"] else " budget without aliases")


def source_description(facts: dict) -> str:
    source = facts["budget"]["aggregate"]["aggregate"]["committed_source"]
    mappings = facts["budget"]["aggregate"]["aggregate"]["mappings"]
    return ("committed_source key_fields " + json.dumps(source["key_fields"]) + " and contribution " + json.dumps(source["contribution"], sort_keys=True)
        + "; mapping(s) " + "; ".join(m["id"] + " key_fields " + json.dumps(m["key_fields"]) + " contribution " + json.dumps(m["contribution"], sort_keys=True) for m in mappings))


def settled_case(facts: dict, case_id: str) -> tuple[dict, dict, str]:
    state = open_alias_state(facts)
    record = native(facts, "EFFECT", "native-effect")
    rows = contributions(facts)
    prescribed = [prescribed_record(facts, row, record["effect_id"], record["occurred_at"]) for row in rows]
    history = history_with(facts, state["core"]["budgets"][0]["history"], prescribed)
    event, host, supplied = settle(facts, state, case_id, history, record)
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = history
    core["reservations"][0].update(status="SETTLED", matched_effect=record["effect_id"])
    core["effects"] = [effect_record(record, "MATCHED", "MATCHED_EFFECT")]
    expected = transition(state, event, host, core, "SETTLED", reservation_id="reserve-a")
    fields = "; ".join(r["id"][:15] + "... fields " + ",".join(f["name"] + "=" + f["value"]["value"] for f in r["fields"]) for r in prescribed)
    derivation = (
        label(facts) + ": " + source_description(facts) + ". Prior state: REGISTER of the budget with an opening journal in committed_source names, then RESERVE of reserve-a "
        "(RESERVED; AGG-006 resolves the history through the committed_source names and AGG-008 adds the projected contribution(s)). "
        "SETTLE carries a clean EFFECT record (completion_mismatch false, attributed, observed and reserved requests equal, effect-1 at the native declared time) and the complete history extended by "
        + str(len(prescribed)) + " prescribed record(s): " + fields + ". RES-WIRE-002: each terminal contribution's event id is digest(reservation-committed-event,{budget_digest,effect_id,mapping}) and its ACTIVE fields are exactly the committed_source's key fields with the contribution key values, plus the committed_source contribution field/value for SUM or CARDINALITY (none for COUNT), sorted by field name; occurred_at is the native declared time. "
        "RES-WIRE-003 history admission passes: the prior journal is an exact prefix, sequences are contiguous, AGG field admission (AGG-006) finds the required committed_source fields, as_of is not in the future and MAX_AGE 60 holds. "
        "A matching settlement requires completion_mismatch false, equal requests and every prescribed record in the supplied journal, so the OPEN row of the prior-state table gives SETTLED: the reservation becomes SETTLED with matched_effect effect-1, the supplied history is retained, and one MATCHED effect record with reason MATCHED_EFFECT, affected anchor license-spend and no blocked partitions is added. "
        "RES-WIRE-004: SETTLE receipts have budgets [] and authority_result null; SETTLED has no reasons; revision advances by one and last_clock is the event clock."
    )
    return supplied, expected, derivation


def mapping_names_refusal(facts: dict, case_id: str) -> tuple[dict, dict, str]:
    state = open_alias_state(facts)
    record = native(facts, "EFFECT", "native-effect")
    rows = contributions(facts)
    wrong = [prescribed_record(facts, row, record["effect_id"], record["occurred_at"], names="mapping") for row in rows]
    history = history_with(facts, state["core"]["budgets"][0]["history"], wrong)
    _, _, supplied = settle(facts, state, case_id, history, record)
    expected = refusal(state, "INPUT_INVALID")
    source = facts["budget"]["aggregate"]["aggregate"]["committed_source"]
    required = source["key_fields"] + ([source["contribution"]["field"]] if "field" in source["contribution"] else [])
    derivation = (
        label(facts) + ": " + source_description(facts) + ". Same prior RESERVED state and clean EFFECT record as the matching alias settlement, but the appended committed record(s) carry the proposal mapping's field names "
        + json.dumps(sorted({f["name"] for r in wrong for f in r["fields"]})) + " instead of the committed_source names " + json.dumps(required) + ". "
        "RES-WIRE-003: all event records retain AGG's scalar, date and field admission. AGG-006: each ACTIVE event's fields must supply the required key and contribution fields of the committed_source declaration; the mapping names are not those fields. "
        "AGG-008's dynamic validation matrix makes a missing required field phase-5 INPUT_INVALID. Every supplied value is well typed (TYPE_INVALID does not apply, and RES-WIRE-003 orders TYPE_INVALID before INPUT_INVALID), authentication tuples are complete, and the journal is an exact contiguous prefix extension, so no earlier phase-5 code applies. "
        "RES-WIRE-004: an admission refusal returns the exact supplied state and digest with status REFUSED, code INPUT_INVALID and path \"\", creates no receipt and does not advance the revision. "
        "The history is refused before reconciliation, so the record is not treated as a merely uncorroborating journal (HISTORY_UNCORROBORATED) and the native evidence is not retained by this refused event."
    )
    return supplied, expected, derivation


def both_names_disputed(facts: dict, case_id: str) -> tuple[dict, dict, str]:
    state = open_alias_state(facts)
    record = native(facts, "EFFECT", "native-effect")
    rows = contributions(facts)
    extended = [prescribed_record(facts, row, record["effect_id"], record["occurred_at"], names="both") for row in rows]
    history = history_with(facts, state["core"]["budgets"][0]["history"], extended)
    event, host, supplied = settle(facts, state, case_id, history, record)
    blocked = sorted({canonical_bytes({"anchor": r["anchor"], "key": r["key"]}): {"anchor": r["anchor"], "key": copy.deepcopy(r["key"])} for r in rows}.values(), key=canonical_bytes)
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = history
    core["reservations"][0]["status"] = "DISPUTED"
    core["effects"] = [effect_record(record, "DISPUTED", "HISTORY_UNCORROBORATED", blocked)]
    expected = transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["HISTORY_UNCORROBORATED"])
    derivation = (
        label(facts) + ": " + source_description(facts) + ". Same prior RESERVED state and clean EFFECT record, but the appended record under the prescribed event id carries the union of the committed_source names and the mapping names "
        + json.dumps([f["name"] for f in extended[0]["fields"]]) + ". History admission passes: AGG-006 requires the committed_source fields and they are present and well typed; the extra fields are typed values of declared types. "
        "RES-WIRE-002 prescribes ACTIVE fields that are exactly the committed_source key and contribution fields and states that a committed record with any field beyond the prescribed set is not the prescribed record, so this record is not the prescribed record. RES-WIRE-003: a matching settlement requires every prescribed committed record in the supplied journal; missing journal corroboration retains EFFECT_DISPUTED. "
        "RES-WIRE-004 reason order: no second effect id, no changed fact under a retained id and no request difference, so UNEXPECTED_EFFECT does not apply and the reason is HISTORY_UNCORROBORATED. "
        "Prior-state table, OPEN with an attributable effect that is not matching: EFFECT_DISPUTED, reservation DISPUTED with matched_effect null and its pending exposure retained. "
        "Blocked partitions are the canonical sorted unique union of the reserved keys and the keys projectable from the complete observed fields under the retained authorization, here the single reserved key. The admitted non-duplicate history is retained in the budget."
    )
    return supplied, expected, derivation


def recovery_alias_facts(reducer: str) -> dict:
    return shape_facts(recovery_facts_for(), reducer=reducer)


def recovery_case(reducer: str, case_id: str) -> tuple[dict, dict, str]:
    facts = recovery_alias_facts(reducer)
    state = reserved(facts, recovery_registered(facts))
    unknown = native(facts, "UNKNOWN", "native-disputed", completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
    event, host = host_and_event(facts, "SETTLE", "retain-disputed-outcome", state["core"]["revision"],
        {"native": unknown, "histories": [state["core"]["budgets"][0]["history"]]}, administration=False)
    core = copy.deepcopy(state["core"])
    core["reservations"][0]["status"] = "DISPUTED"
    core["effects"].append(effect_record(unknown, "DISPUTED", "UNEXPECTED_EFFECT", [{"anchor": ANCHOR, "key": None}]))
    disputed = transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])["state"]
    packet = evidence_for(facts, disputed, conclusion="EFFECT_ESTABLISHED", attempts=1)
    effect = packet["native_outcomes"][0]
    rows = contributions(facts)
    prescribed = [prescribed_record(facts, row, effect["effect_id"], effect["occurred_at"]) for row in rows]
    history = history_with(facts, disputed["core"]["budgets"][0]["history"], prescribed)
    supplied = dispose_request(facts, disputed, "ESTABLISH_EFFECT", evidence=packet, histories=[history])
    expected = disposition_expected(supplied)
    fields = ",".join(f["name"] + "=" + f["value"]["value"] for f in prescribed[0]["fields"])
    derivation = (
        label(facts) + " under selected recovery: " + source_description(facts) + ". Prior: REGISTER with recovery selected (REC-001 empty recovery state), RESERVE of reserve-a, then SETTLE of a completion-mismatched UNKNOWN (UNEXPECTED_EFFECT), which per the RES-WIRE-003 table makes reserve-a DISPUTED and blocks the anchor with a null key. "
        "DISPOSE ESTABLISH_EFFECT carries REC-003 independent human controller authority and a complete RECOVERY_ADJUDICATION packet from the settlement provider pair with one attempt and established effect-1 (REC-004). "
        "REC-006 requires the corresponding prescribed committed journal entries under every affected projection; RES-WIRE-002 fixes them in committed_source names: " + fields + ", id digest(reservation-committed-event,{budget_digest,effect_id,mapping:pay}). "
        "REC-004: DISPOSE evaluates the supplied complete history, which preserves the prior journal as prefix and passes AGG-006 field admission. "
        "The transition records DISPOSITION_RECORDED with the disposition digest, retains the disposition record (REC-002 identities), adopts the supplied history, leaves contingent and allowances empty, and preserves the historical DISPUTED reservation flag and DISPUTED effect records unchanged (REC-006). Receipt budgets are empty because ESTABLISH_EFFECT performs no new proposal evaluation."
    )
    return supplied, expected, derivation


# ---------------------------------------------------------------------------
# Phase-3 rulings: retraction after SETTLED (R-a) and DISPOSE admission order (RECOVERY.md)


def other_partition_authority(facts: dict, beneficiary: str = "employee-9") -> None:
    """Replace authority_b by an instance-2 proposal on another beneficiary.

    In the draft-1 authority specimen the beneficiary value occurs only in the proposal field and
    in the result's scope/actual_scope subjects (bound through the envelope's beneficiary-binding),
    so the result is the specimen's rebound result with those two subject lists changed.
    """
    def mutate(supplied, _original):
        next(row for row in supplied["proposal"]["fields"] if row["name"] == "beneficiary")["value"]["value"] = beneficiary

    authority, result = authority_specimen(instance_id="instance-2", occurrence_id="issue:2", mutator=mutate)
    authority["clock"] = copy.deepcopy(facts["clock"])
    result["scope"]["subjects"] = [beneficiary]
    result["actual_scope"]["subjects"] = [beneficiary]
    facts["authority_b"], facts["authority_b_result"] = authority, result


def sum_evaluation(facts: dict, key_value: str, total: str) -> list:
    status = "SATISFIED" if int(total) <= 1000 else "VIOLATED"
    reasons = [] if status == "SATISFIED" else ["BOUND_VIOLATED"]
    return [{"anchor": ANCHOR, "result": {
        "schema": V + "/aggregate-result", "specification_pin": PIN,
        "definition_digest": digest("aggregate-definition", facts["budget"]["aggregate"]),
        "status": status,
        "partitions": [{"occurrence": None, "key": [{"type_ref": "beneficiary", "value": key_value}],
            "accumulator": {"kind": "SCALAR", "value": total}, "result": total, "status": status, "reasons": reasons}],
        "reasons": reasons}}]


def retraction_case(facts: dict, case_id: str, *, unrelated: bool) -> tuple[dict, dict, str]:
    _, settled, _ = settled_case(facts, case_id)
    state = settled["state"]
    if unrelated:
        other_partition_authority(facts)
    retained = state["core"]["budgets"][0]["history"]
    prescribed_id = retained["journal"][-1]["event"]["id"]
    history = history_with(facts, retained, [{"id": prescribed_id, "state": "RETRACTED"}])
    event, host = host_and_event(facts, "RESERVE", "reserve-b", state["core"]["revision"],
        {"authority": facts["authority_b"], "histories": [history]}, administration=False)
    supplied = request(state, event, host)
    core = copy.deepcopy(state["core"])
    core["budgets"][0]["history"] = history
    core["reservations"][0]["status"] = "DISPUTED"
    opening = int(facts["opening"])
    if unrelated:
        row = reservation_record(facts, "authority_b", "reserve-b")
        row["contributions"] = contributions(facts, "authority_b")
        core["reservations"].append(row)
        core["reservations"].sort(key=lambda item: item["id"].encode("utf-8"))
        evaluation = sum_evaluation(facts, "employee-9", "150")
        expected = transition(state, event, host, core, "RESERVED", reservation_id="reserve-b",
            budgets=evaluation, authority_result=facts["authority_b_result"])
        outcome = ("The new contribution's partition is employee-9. It matches no blocked entry: the disputed reserve-a blocks only its reserved partition employee-7 and no effect record carries a null-key anchor block. "
            "AGG-004/AGG-008 evaluate only the proposal's partition: committed history for employee-9 is empty (the opening event and the retracted record are employee-7), and reserve-a's restored pending charge is employee-7 only, a pending-only tuple that creates no partition. 0 + 150 = 150 <= 1000, SATISFIED, so RESERVED with a new OPEN reserve-b retaining its contribution; RES-005 permit expiry is clock plus 300 seconds.")
    else:
        expected = transition(state, event, host, core, "WITHHELD", reservation_id=None,
            budgets=[], authority_result=facts["authority_b_result"],
            reasons=["EXPOSURE_DISPUTED", "HISTORY_UNCORROBORATED", "RECOVERY_EVIDENCE_INCOMPLETE"])
        outcome = ("The affected employee-7 partition is blocked. Under R-p the fresh journal no longer corroborates the retained actual, so the whole receipt carries empty budgets and preserves the dispute reason. No reservation is created.")
    derivation = (
        label(facts) + ": " + source_description(facts) + ". Prior state: opening journal (" + facts["opening"] + " for employee-7), RESERVE of reserve-a (150, employee-7), and a matching SETTLE whose history carries the prescribed committed record in committed_source names, so reserve-a is SETTLED with matched_effect effect-1 and one MATCHED effect record. "
        "Event: RESERVE reserve-b for another occurrence (instance-2, issue:2) whose complete, fresh history appends sequence " + history["revision"] + " {id: the prescribed record id, state: RETRACTED} (AGG-006: a RETRACTED terminal record contains only id and state; the prior journal remains an exact prefix). "
        "RES-WIRE-003 as amended: a non-duplicate event's newly admitted history that retracts a prescribed event of a SETTLED reservation marks it DISPUTED, restores its unresolved pending charge and retains matched_effect and the original native records; the MATCHED effect record is left unchanged; while DISPUTED each reserved partition blocks new contributions as a retained blocked_partitions entry would; the marking applies when the history is admitted, before the event's own policy evaluation. "
        "The admitted history replaces the budget journal (only stale or unavailable reserve history is not stored). " + outcome
        + " RES-004 agrees: removing or retracting the record does not silently release the reservation."
    )
    return supplied, expected, derivation


def dispose_variant(variant: str, case_id: str) -> tuple[dict, dict, str]:
    facts = recovery_alias_facts("SUM")
    state = reserved(facts, recovery_registered(facts))
    unknown = native(facts, "UNKNOWN", "native-disputed", completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
    event, host = host_and_event(facts, "SETTLE", "retain-disputed-outcome", state["core"]["revision"],
        {"native": unknown, "histories": [state["core"]["budgets"][0]["history"]]}, administration=False)
    core = copy.deepcopy(state["core"])
    core["reservations"][0]["status"] = "DISPUTED"
    core["effects"].append(effect_record(unknown, "DISPUTED", "UNEXPECTED_EFFECT", [{"anchor": ANCHOR, "key": None}]))
    disputed = transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])["state"]
    packet = evidence_for(facts, disputed, conclusion="EFFECT_ESTABLISHED", attempts=1)
    if variant == "wrong-provider":
        packet["provider"] = "unselected-adjudicator"
    effect = packet["native_outcomes"][0]
    names = "both" if variant == "extra-fields" else "mapping"
    records = [prescribed_record(facts, row, effect["effect_id"], effect["occurred_at"], names=names) for row in contributions(facts)]
    history = history_with(facts, disputed["core"]["budgets"][0]["history"], records)
    supplied = dispose_request(facts, disputed, "ESTABLISH_EFFECT", evidence=packet, histories=[history])
    field_names = json.dumps([f["name"] for f in records[0]["fields"]])
    prior = (label(facts) + " under selected recovery: " + source_description(facts) + ". Prior: REGISTER with recovery selected, RESERVE of reserve-a, SETTLE of a completion-mismatched UNKNOWN that makes reserve-a DISPUTED with a null-key anchor block. "
        "DISPOSE ESTABLISH_EFFECT carries REC-003 independent controller authority and a complete RECOVERY_ADJUDICATION packet establishing effect-1; its history appends a record under the prescribed id with fields " + field_names + ". ")
    order = ("RECOVERY.md REC-016 admission order: schema/candidate/state/replay/revision, then exact target/request/provider binding, retained known fact/attempt coverage, supplied authority/return binding, then history structural admission. ")
    if variant == "mapping-names":
        expected = refusal(disputed, "INPUT_INVALID")
        tail = ("Target, request, provider, coverage and authority all bind and are authenticated. History structural admission then fails: RES-WIRE-003 keeps AGG field admission for every event record and AGG-006 requires the committed_source fields historical-amount and historical-beneficiary, which are missing; AGG-008 makes a missing required field INPUT_INVALID (values are well typed, so not TYPE_INVALID). "
            "The refusal changes no governed state and returns the exact supplied state and digest (RES-WIRE-004 refusal shape).")
    elif variant == "wrong-provider":
        expected = refusal(disputed, "DEPENDENCY_MISMATCH")
        tail = ("The packet's provider is unselected-adjudicator while its source stays card-ledger, and its RECOVERY_EVIDENCE tuple and the controller act are rebuilt for that packet, so it is authenticated. REC-004 requires the packet provider/source to match the original selected settlement pair (native-provider/card-ledger); RECOVERY.md: a wrong provider is DEPENDENCY_MISMATCH. "
            "Provider binding precedes history structural admission, so the mapping-named history's INPUT_INVALID is not reached. No governed state changes.")
    elif variant == "missing-authentication":
        supplied["host_evidence"]["recovery"]["authenticated_records"] = [row for row in supplied["host_evidence"]["recovery"]["authenticated_records"] if row["kind"] != "RECOVERY_EVIDENCE"]
        expected = refusal(disputed, "EVIDENCE_UNAVAILABLE")
        tail = ("The host's RECOVERY_EVIDENCE authentication tuple for the packet is omitted. REC-004 binds the packet through that tuple; RECOVERY.md: missing authenticated material is EVIDENCE_UNAVAILABLE. "
            "This is checked before history structural admission (and RES-WIRE-003 also places missing authentication before INPUT_INVALID), so the mapping-named history's INPUT_INVALID is not reached. No governed state changes.")
    else:
        expected = disposition_expected(supplied, reasons=["HISTORY_UNCORROBORATED", "RECOVERY_EVIDENCE_INCOMPLETE"], effective_result="LEAVE_UNRESOLVED")
        tail = ("Admission passes: the required committed_source fields are present and well typed, and the extra mapping-named fields are typed values of declared types. "
            "RES-WIRE-002: a committed record with any field beyond the prescribed set is not the prescribed record, so REC-006's corresponding prescribed committed journal entry is absent. "
            "RECOVERY.md: missing effect-history corroboration adds RECOVERY_EVIDENCE_INCOMPLETE and the applicable existing history reason, HISTORY_UNCORROBORATED (RES-WIRE-004); distinct reasons are sorted. A failed substantive condition retains a LEAVE_UNRESOLVED disposition with WITHHELD, null acceptance basis, no allowance and bounded known charges (REC-008 and REC-016): reserve-a stays DISPUTED, the historical DISPUTED effect record and its anchor block are unchanged, contingent and allowances stay empty. "
            "The disposition record keeps the requested evidence, controller and event; its id hashes result LEAVE_UNRESOLVED. REC-004: DISPOSE evaluates the supplied complete history, which is admitted and retained in the budget. The receipt is WITHHELD for reservation reserve-a with the disposition digest and budgets [] (no ACCEPT_UNRESOLVED evaluation).")
    return supplied, expected, prior + order + tail


def ordinary_block_case(facts: dict, case_id: str) -> tuple[dict, dict, str]:
    """A RESERVE on a partition blocked by an ordinary DISPUTED effect record (not a retraction)."""
    state = open_alias_state(facts)
    record = native(facts, "EFFECT", "native-effect")
    retained = state["core"]["budgets"][0]["history"]
    event, host = host_and_event(facts, "SETTLE", "settle-" + case_id.lower(), state["core"]["revision"],
        {"native": record, "histories": [retained]}, administration=False)
    blocked = [{"anchor": ANCHOR, "key": [{"type_ref": "beneficiary", "value": "employee-7"}]}]
    core = copy.deepcopy(state["core"])
    core["reservations"][0]["status"] = "DISPUTED"
    core["effects"] = [effect_record(record, "DISPUTED", "HISTORY_UNCORROBORATED", blocked)]
    disputed = transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["HISTORY_UNCORROBORATED"])["state"]
    event, host = host_and_event(facts, "RESERVE", "reserve-b", disputed["core"]["revision"],
        {"authority": facts["authority_b"], "histories": [retained]}, administration=False)
    supplied = request(disputed, event, host)
    core = copy.deepcopy(disputed["core"])
    expected = transition(disputed, event, host, core, "WITHHELD", reservation_id=None,
        budgets=[], authority_result=facts["authority_b_result"],
        reasons=["EXPOSURE_DISPUTED", "HISTORY_UNCORROBORATED", "RECOVERY_EVIDENCE_INCOMPLETE"])
    derivation = (
        label(facts) + ": an actual EFFECT for reserve-a projects to the same employee-7 partition but its exact prescribed record is absent. "
        "R-p keeps EXPOSURE_DISPUTED and adds HISTORY_UNCORROBORATED and RECOVERY_EVIDENCE_INCOMPLETE. "
        "The original pending amount cannot stand in for that actual, so no ordinary judgment is published, regardless of the opening balance. "
        "No reservation is created; history and retained effect remain unchanged."
    )
    return supplied, expected, derivation


def main() -> None:
    GROUP.mkdir(parents=True, exist_ok=True)
    produced: list[tuple[str, str]] = []

    def emit(supplied: dict, expected: dict, derivation: str, requirements: list) -> None:
        case_id = "C3-P3-ALIAS-" + str(len(produced) + 1).zfill(3)
        write_canonical_json(GROUP / f"{case_id}.json", exact_case(case_id, "aggregate-step", supplied, expected, requirements, derivation))
        summary = expected.get("receipt", {}).get("decision") or expected["status"] + ":" + expected.get("code", "")
        produced.append((case_id, summary))

    settle_requirements = ["AGG-006", "RES-004", "RES-007", "RES-WIRE-002", "RES-WIRE-003", "RES-WIRE-004"]
    refusal_requirements = ["AGG-006", "AGG-008", "RES-003", "RES-WIRE-002", "RES-WIRE-003", "RES-WIRE-004"]
    recovery_requirements = ["AGG-006", "REC-004", "REC-006", "RES-WIRE-002", "RES-WIRE-003"]

    # Self-check: the generic constructors reproduce the draft-3 fixture's non-aliased SETTLED state.
    control = alias_facts(reducer="SUM", aliased=False)
    supplied, expected, _ = settled_case(control, "self-check")
    reference = settled_state(fixture())
    assert expected["state"]["core"] == {**reference["core"]}, "non-aliased control diverges from reservation_fixture.settled_state core"

    # 1. SUM alias, matching settlement in source names.
    emit(*settled_case(alias_facts(reducer="SUM"), "alias-sum"), settle_requirements)
    # 2. SUM alias, record in mapping names -> refused.
    emit(*mapping_names_refusal(alias_facts(reducer="SUM"), "alias-sum-mapping-names"), refusal_requirements)
    # 3. SUM alias, record carrying both inventories -> not the prescribed record.
    emit(*both_names_disputed(alias_facts(reducer="SUM"), "alias-sum-both-names"), settle_requirements)
    # 4-7. COUNT and CARDINALITY aliases.
    for reducer in ("COUNT", "CARDINALITY"):
        emit(*settled_case(alias_facts(reducer=reducer), "alias-" + reducer.lower()), settle_requirements + ["AGG-002"])
        emit(*mapping_names_refusal(alias_facts(reducer=reducer), "alias-" + reducer.lower() + "-mapping-names"), refusal_requirements + ["AGG-002"])
    # 8-9. Two mappings with source aliases.
    emit(*settled_case(alias_facts(reducer="SUM", two_mappings=True), "alias-two-mappings"), settle_requirements + ["AGG-003"])
    emit(*mapping_names_refusal(alias_facts(reducer="SUM", two_mappings=True), "alias-two-mappings-mapping-names"), refusal_requirements + ["AGG-003"])
    # 10-12. Recovery ESTABLISH_EFFECT on aliased budgets.
    for reducer in ("SUM", "COUNT", "CARDINALITY"):
        emit(*recovery_case(reducer, "recovery-" + reducer.lower()), recovery_requirements + (["AGG-002"] if reducer != "SUM" else []))
    # 13. Control: non-aliased SUM settlement.
    supplied, expected, derivation = settled_case(alias_facts(reducer="SUM", aliased=False), "control-sum")
    emit(supplied, expected,
        "Control. " + derivation + " Because committed_source and mapping names coincide, the prescribed record equals the record the earlier fixture builds; this vector's expected core equals reservation_fixture.settled_state's core (asserted by the builder).", settle_requirements)

    # 14-17. Retraction after SETTLED on the same partition (R-a): with and without BOUND_VIOLATED, aliased and not.
    retraction_requirements = ["AGG-006", "AGG-007", "RES-004", "RES-005", "RES-WIRE-002", "RES-WIRE-003", "RES-WIRE-004"]
    for aliased in (True, False):
        for opening in ("800", "500"):
            emit(*retraction_case(alias_facts(reducer="SUM", aliased=aliased, opening=opening),
                "retract-" + ("alias" if aliased else "plain") + "-" + opening, unrelated=False), retraction_requirements + ["AGG-008"])
    # 18-19. Retraction carried by a RESERVE on an unrelated known partition.
    for aliased in (True, False):
        emit(*retraction_case(alias_facts(reducer="SUM", aliased=aliased),
            "retract-unrelated-" + ("alias" if aliased else "plain"), unrelated=True), retraction_requirements + ["AGG-004"])
    # 20-23. DISPOSE ESTABLISH_EFFECT admission order and corroboration on an aliased budget.
    for variant in ("mapping-names", "wrong-provider", "missing-authentication", "extra-fields"):
        emit(*dispose_variant(variant, "dispose-" + variant), ["AGG-006", "AGG-008", "REC-003", "REC-004", "REC-006", "REC-008", "REC-016", "RES-WIRE-002", "RES-WIRE-003"])

    # 24-25. Control: RESERVE blocked by an ordinary DISPUTED effect record's blocked_partitions entry.
    for opening in ("500", "800"):
        emit(*ordinary_block_case(alias_facts(reducer="SUM", opening=opening), "ordinary-block-" + opening),
            ["AGG-008", "RES-005", "RES-007", "RES-WIRE-003", "RES-WIRE-004"])

    print(json.dumps({"cases": [{"id": cid, "expected": summary} for cid, summary in produced], "count": len(produced),
        "output": str(GROUP), "implementation_or_output_consulted": False}, indent=2))


if __name__ == "__main__":
    main()
