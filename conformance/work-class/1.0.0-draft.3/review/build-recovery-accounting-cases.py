"""Derive effect/no-effect substitution under every supported budget reducer."""

from __future__ import annotations

import copy

from corpus_common import CASES, digest, exact_case, write_canonical_json
from recovery_fixture import (
    disposition_expected, dispose_request, evidence_for, facts_for, registered,
)
from reservation_fixture import budget_result, effect_record, host_and_event, native, request, reservation_record, transition


GROUP = CASES / "recovery-accounting"


def facts_for_reducer(reducer: str) -> dict:
    facts = facts_for()
    definition = facts["budget"]["aggregate"]
    aggregate = definition["aggregate"]
    if reducer != "SUM":
        if not any(row["id"] == "count" for row in definition["types"]):
            definition["types"].append({"id": "count", "kind": "INTEGER", "unit": None, "nonnegative": True})
        definition["types"].sort(key=lambda row: row["id"].encode())
        aggregate.update(reducer=reducer, result_type="count", element_type="beneficiary" if reducer == "CARDINALITY" else None,
            bound={"type_ref": "count", "value": "1000"})
        contribution = {"kind": reducer, **({"field": "item"} if reducer == "CARDINALITY" else {})}
        aggregate["mappings"][0]["contribution"] = copy.deepcopy(contribution)
        aggregate["committed_source"]["contribution"] = copy.deepcopy(contribution)
        for row in facts["history"]["journal"]:
            row["event"]["fields"] = [field for field in row["event"]["fields"] if field["name"] == "beneficiary"]
            if reducer == "CARDINALITY":
                row["event"]["fields"].append({"name": "item", "value": {"type_ref": "beneficiary", "value": "card-801"}})
        for authorization in facts["authorizations"]:
            authorization["projection"] = [row for row in authorization["projection"] if row["budget_field"] == "beneficiary"]
            if reducer == "CARDINALITY":
                step = next(row for row in authorization["authority_definition"]["work_class"]["steps"] if row["id"] == authorization["step"])
                native_type = next(row["type_ref"] for row in step["fields"] if row["name"] == "card_id")
                authorization["projection"].append({"native_field": "card_id", "native_type": native_type,
                    "budget_field": "item", "budget_type": "beneficiary"})
    bd = digest("budget-definition", facts["budget"])
    facts["history"]["budget_digest"] = bd
    for authorization in facts["authorizations"]:
        authorization["budget_digest"] = bd
    facts["reducer"] = reducer
    return facts


def contribution_value(facts: dict) -> dict:
    return {"SUM": {"type_ref": "amount", "value": "150"}, "COUNT": {"type_ref": "count", "value": "1"},
        "CARDINALITY": {"type_ref": "beneficiary", "value": "card-802"}}[facts["reducer"]]


def evaluations(facts: dict, value: str) -> list:
    rows = budget_result(facts, value)
    if facts["reducer"] == "CARDINALITY":
        rows[0]["result"]["partitions"][0]["accumulator"] = {"kind": "SET", "values": [
            {"type_ref": "beneficiary", "value": "card-801"}, contribution_value(facts)]}
    return rows


def reserve(facts: dict, state: dict, *, authority_key="authority_a", event_id="reserve-a", total="950"):
    event, host = host_and_event(facts, "RESERVE", event_id, state["core"]["revision"], {
        "authority": facts[authority_key], "histories": [state["core"]["budgets"][0]["history"]]}, administration=False)
    core = copy.deepcopy(state["core"])
    row = reservation_record(facts, authority_key, event_id)
    row["contributions"][0]["value"] = contribution_value(facts)
    core["reservations"].append(row)
    core["reservations"].sort(key=lambda item: item["id"].encode())
    return request(state, event, host), transition(state, event, host, core, "RESERVED", reservation_id=event_id,
        budgets=evaluations(facts, total), authority_result=facts[authority_key + "_result"])


def build():
    rows = []

    def add(supplied, result, derivation):
        cid = "C3-RA-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(cid, "aggregate-step", supplied, result, ["REC-004", "REC-006", "REC-007", "REC-008", "REC-011", "REC-015"], derivation))

    for reducer in ("SUM", "COUNT", "CARDINALITY"):
        facts = facts_for_reducer(reducer)
        initial = registered(facts)
        total = {"SUM": "950", "COUNT": "2", "CARDINALITY": "2"}[reducer]
        _, reserved = reserve(facts, initial, total=total)
        state = reserved["state"]
        unknown = native(facts, "UNKNOWN", "recovery-accounting-uncertain", completion_mismatch=True, mismatch_reason="UNEXPECTED_EFFECT")
        event, host = host_and_event(facts, "SETTLE", "recovery-accounting-dispute", state["core"]["revision"], {"native": unknown, "histories": [facts["history"]]}, administration=False)
        core = copy.deepcopy(state["core"])
        core["reservations"][0]["status"] = "DISPUTED"
        core["effects"].append(effect_record(unknown, "DISPUTED", "UNEXPECTED_EFFECT", [{"anchor": facts["budget"]["anchor"], "key": None}]))
        disputed = transition(state, event, host, core, "EFFECT_DISPUTED", reservation_id="reserve-a", reasons=["UNEXPECTED_EFFECT"])
        packet = evidence_for(facts, disputed["state"], conclusion="EFFECT_ESTABLISHED", attempts=1)
        history = copy.deepcopy(facts["history"])
        history["revision"] = "2"
        effect = packet["native_outcomes"][0]
        actual = {row["name"]: row["value"]["value"] for row in effect["actual_fields"]}
        projected_fields = sorted([{"name": row["budget_field"], "value": {"type_ref": row["budget_type"], "value": actual[row["native_field"]]}}
            for row in facts["authorizations"][0]["projection"]], key=lambda row: row["name"].encode())
        source = facts["budget"]["aggregate"]["aggregate"]["committed_source"]
        required = set(source["key_fields"]) | ({source["contribution"]["field"]} if "field" in source["contribution"] else set())
        projected_fields = [row for row in projected_fields if row["name"] in required]
        history["journal"].append({"sequence": "2", "event": {
            "id": digest("reservation-committed-event", {"budget_digest": history["budget_digest"], "effect_id": effect["effect_id"], "mapping": "pay"}),
            "state": "ACTIVE", "occurred_at": effect["occurred_at"], "fields": projected_fields}})
        established = dispose_request(facts, disputed["state"], "ESTABLISH_EFFECT", evidence=packet, histories=[history])
        established_result = disposition_expected(established)
        add(established, established_result, reducer + ": exact corroborated actual execution replaces its original possible execution. Preserve historical DISPUTED flags; do not count both actual and pending.")
        if reducer != "SUM":
            following, following_result = reserve(facts, established_result["state"], authority_key="authority_b", event_id="reserve-b-after-established",
                total={"COUNT": "3", "CARDINALITY": "2"}[reducer])
            add(following, following_result, reducer + ": a subsequent independent reservation observes the established journal once and no uncertain original contribution. CARDINALITY preserves set overlap rather than adding one per execution.")
        no_effect = dispose_request(facts, disputed["state"], "ESTABLISH_NO_EFFECT")
        no_effect_result = disposition_expected(no_effect)
        add(no_effect, no_effect_result, reducer + ": affirmative complete no-effect proof releases only the original possible contribution and preserves committed history.")
        following, following_result = reserve(facts, no_effect_result["state"], authority_key="authority_b", event_id="reserve-b-after-no-effect",
            total={"SUM": "950", "COUNT": "2", "CARDINALITY": "2"}[reducer])
        add(following, following_result, reducer + ": subsequent reservation sees no released original pending contribution, while the unrelated opening history still counts normally.")
    return rows


def main():
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print({"recovery_accounting_cases": len(rows), "implementation_or_output_consulted": False})


if __name__ == "__main__":
    main()
