"""Derive seed/history expectations independently of either consumer."""

from __future__ import annotations

import copy

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from equipment_history_fixture import (
    SHAPES, historical_claim, history_fixture, history_state, rebind_seed,
    reserve_request, reserve_result, seed_request, seed_result, seeded_all, selected_slot, value,
)
from reservation_fixture import refusal


GROUP = CASES / "equipment-history"


def derived_cases() -> list[dict]:
    cases = []
    def add(number: int, supplied: dict, expected: dict, derivation: str) -> None:
        cases.append(exact_case(f"C3-EH-{number:03d}", "aggregate-step", supplied, expected,
            ["RES-001A", "RES-007A", "RES-WIRE-004", "RES-003"], derivation))
    def seed(*, status: str = "CONSUMED", work_occurrence: dict | None = None) -> tuple[dict, dict]:
        facts = history_fixture()
        event_id = "seed-request"
        claim = historical_claim(facts, "request-use", event_id, status=status, work_occurrence=work_occurrence)
        return facts, seed_request(facts, history_state(facts), "request-use", [claim], event_id)
    facts = history_fixture()
    supplied = seed_request(facts, history_state(facts), "request-use", [], "seed-empty")
    add(1, supplied, seed_result(facts, supplied), "An authenticated complete empty cutover snapshot installs the one mediated slot's coverage and no keys. The HUMAN administration subject binds the full event payload and exact registry; no native effect is fabricated.")
    facts, supplied = seed()
    add(2, supplied, seed_result(facts, supplied), "A complete authenticated historical native record and separately authenticated original-request linkage deterministically project issuer/request_id. A pre-Work-Class record retains a NATIVE_HISTORY owner and consumes its historical key without inventing an occurrence.")
    facts, supplied = seed(status="HELD")
    add(3, supplied, seed_result(facts, supplied), "A complete unresolved historical record seeds HELD with null settlement evidence. It is occupied without a fabricated completion or release conclusion.")
    facts, supplied = seed(work_occurrence={"work_class": "historical-class", "instance_id": "historical-instance", "occurrence_id": "historical-operation:1"})
    add(4, supplied, seed_result(facts, supplied), "A genuine retained native work_occurrence permits the equal WORK_OCCURRENCE owner union. These historical identities grant no current authority and need no fabricated reservation.")
    facts, supplied = seed()
    claim = supplied["event"]["payload"]["claims"][0]
    claim["key"][1] = value("caller-invented-request")
    claim["key_digest"] = digest("exclusive-key", {"registry": digest("reservation-registry", facts["configuration"]),
        "slot": claim["slot"], "namespace": claim["namespace"], "key": claim["key"]})
    supplied = rebind_seed(facts, supplied)
    add(5, supplied, refusal(supplied["state"], "BINDING_MISMATCH"), "The claimed key and its digest agree with each other, and administration authenticates the full altered snapshot. They differ from the independently projected original request, so caller keys cannot establish history.")
    facts, supplied = seed()
    supplied["event"]["payload"]["claims"][0]["record_digest"] = "sha256:" + "0" * 64
    supplied = rebind_seed(facts, supplied)
    add(6, supplied, refusal(supplied["state"], "DEPENDENCY_MISMATCH"), "The supplied historical record digest does not hash its complete body. Exact host tuples authenticate the actual body; a forged digest is an input dependency fault before occupancy.")
    facts, supplied = seed()
    supplied["event"]["payload"]["claims"][0]["request_provenance"]["source_request_digest"] = "sha256:" + "0" * 64
    supplied = rebind_seed(facts, supplied)
    add(7, supplied, refusal(supplied["state"], "DEPENDENCY_MISMATCH"), "The complete authenticated linkage record names a different source-request digest. Hashing a provenance record does not connect it to the supplied four-member request metadata.")
    for number, member in ((8, "complete"), (9, "exclusive_writers")):
        facts, supplied = seed()
        supplied["event"]["payload"]["coverage"][member] = False
        supplied = rebind_seed(facts, supplied)
        add(number, supplied, seed_result(facts, supplied, usable=False), f"Authenticated coverage expressly has {member}:false. The admitted negative decision retains the attempted full snapshot but installs no keys or usable coverage and reports EXCLUSIVE_HISTORY_UNAVAILABLE.")
    facts, supplied = seed()
    supplied["host_evidence"]["authenticated_records"] = [row for row in supplied["host_evidence"]["authenticated_records"] if row["kind"] != "EXCLUSIVE_NATIVE_HISTORY"]
    add(10, supplied, refusal(supplied["state"], "EVIDENCE_UNAVAILABLE"), "The complete native body is present but lacks its independently selected authenticated tuple. An administrative snapshot approval does not substitute for native attribution.")
    facts, supplied = seed()
    tuple_row = next(row for row in supplied["host_evidence"]["authenticated_records"] if row["kind"] == "EXCLUSIVE_REQUEST_PROVENANCE")
    tuple_row["source"] = "substituted-source"
    supplied["host_evidence"]["authenticated_records"].sort(key=canonical_bytes)
    add(11, supplied, refusal(supplied["state"], "DEPENDENCY_MISMATCH"), "A selected provenance tuple has the wrong source coordinate and leaves the exact tuple missing. Extra/mismatched dependency evidence precedes its missing counterpart.")
    facts, supplied = seed()
    supplied["event"]["payload"]["coverage"]["cutover_id"] = "different-cutover"
    supplied = rebind_seed(facts, supplied)
    add(12, supplied, refusal(supplied["state"], "BINDING_MISMATCH"), "Full authenticated coverage names a synchronization boundary different from the immutable per-slot declaration. Its valid digest and HUMAN approval cannot amend that declaration.")
    facts, supplied = seed()
    claim = supplied["event"]["payload"]["claims"][0]
    claim["owner"]["record_id"] = "invented-owner-record"
    supplied = rebind_seed(facts, supplied)
    add(13, supplied, refusal(supplied["state"], "BINDING_MISMATCH"), "The caller names a NATIVE_HISTORY owner record different from the complete authenticated native record. The key itself remains correct; owner binding independently refuses.")
    facts, supplied = seed()
    supplied["event"]["payload"]["claims"].append(copy.deepcopy(supplied["event"]["payload"]["claims"][0]))
    supplied = rebind_seed(facts, supplied)
    add(14, supplied, refusal(supplied["state"], "INPUT_INVALID"), "An exact duplicate complete seed claim is an input inventory error. Host evidence tuples deduplicate canonically; that does not permit repeated claims.")
    facts = history_fixture()
    claims = [historical_claim(facts, "approval-use", "seed-conflict", request_id=request_id) for request_id in ("old-request-1", "old-request-2")]
    claims.sort(key=canonical_bytes)
    supplied = seed_request(facts, history_state(facts), "approval-use", claims, "seed-conflict")
    add(15, supplied, refusal(supplied["state"], "OCCURRENCE_CONFLICT"), "Two distinct complete native records project the same approval key but have different genuine native owners. Neither can replace the other; the seed installs nothing and retains no fabricated winner.")
    facts, supplied = seed()
    seeded = seed_result(facts, supplied)
    replay = copy.deepcopy(supplied)
    replay["state"] = seeded["state"]
    replay["state_digest"] = seeded["state_digest"]
    add(16, replay, {**copy.deepcopy(seeded), "replay": True}, "The exact admitted seed event is replayed against its committed state. It returns the historical receipt with current state, no new revision and no new seed despite the stale original expected_revision.")
    changed = copy.deepcopy(replay)
    changed["event"]["payload"]["coverage"]["revision"] = "altered-same-event"
    add(17, changed, refusal(changed["state"], "REPLAY_CONFLICT"), "Changing coverage bytes under the already admitted seed event id conflicts at replay admission before the now-stale revision or newly invalid administrative subject.")
    second = seed_request(facts, seeded["state"], "request-use", [], "second-seed")
    add(18, second, refusal(second["state"], "DEFINITION_CONFLICT"), "A fresh fully authorized event attempts to seed an already covered slot. Initial cutover history is immutable; another event cannot replace it with an empty snapshot.")
    facts = history_fixture()
    supplied = reserve_request(facts, history_state(facts), "reserve-unseeded")
    add(19, supplied, reserve_result(facts, supplied, reason="EXCLUSIVE_HISTORY_UNAVAILABLE"), "Current authority is ready but none of the five mediated slots has retained complete cutover coverage. WITHHELD creates no reservation or key and reaches no collision lookup.")
    facts = history_fixture()
    supplied = reserve_request(facts, seeded_all(facts), "reserve-five-fresh-keys")
    add(20, supplied, reserve_result(facts, supplied), "All five independently seeded empty slots permit atomic acquisition of request, tuple, approval, work-order and inspection keys for the real current proposal owner. Numerical slots and affected anchors are empty, so no numerical history or invented budget is required.")
    def collision_state(facts: dict, status: str) -> dict:
        state = history_state(facts)
        for slot in SHAPES:
            event_id = "seed-" + slot
            claims = [historical_claim(facts, slot, event_id, status=status, approval="AP-091")] if slot == "approval-use" else []
            state = seed_result(facts, seed_request(facts, state, slot, claims, event_id))["state"]
        return state
    for number, status in ((21, "CONSUMED"), (22, "HELD")):
        facts = history_fixture()
        supplied = reserve_request(facts, collision_state(facts, status), "reserve-collided-approval")
        add(number, supplied, reserve_result(facts, supplied, reason="EXCLUSIVE_KEY_OCCUPIED"), f"A genuine {status} historical AP-091 use occupies only the approval key while all five coverages are usable. The whole new five-key reservation is withheld without partial acquisition or public owner/key detail.")
    facts = history_fixture()
    supplied = reserve_request(facts, collision_state(facts, "CONSUMED"), "stale-reserve")
    supplied["event"]["expected_revision"] = "0"
    add(23, supplied, refusal(supplied["state"], "REVISION_CONFLICT"), "A new reservation event uses a stale registry revision. Revision admission precedes protected occupied-key lookup and returns the exact unchanged state.")
    facts = history_fixture()
    facts["configuration"]["principal"] = "different-registry-principal"
    supplied = reserve_request(facts, collision_state(facts, "CONSUMED"), "wrong-principal-probe")
    add(24, supplied, refusal(supplied["state"], "DEPENDENCY_MISMATCH"), "The selected registry principal differs from the exact current authority-envelope principal. That binding refuses before the AP-091 collision and discloses no new protected lookup result.")
    facts = history_fixture()
    slot = selected_slot(facts, "request-use")
    slot["history_projection"][0] = {"key_field": "issuer", "kind": "LITERAL", "value": value("NPO-7")}
    claim = historical_claim(facts, "request-use", "seed-source-constant")
    supplied = seed_request(facts, history_state(facts), "request-use", [claim], "seed-source-constant")
    add(25, supplied, seed_result(facts, supplied), "A source-bound typed LITERAL projects the canonical issuer component, while the request identifier still comes from independently linked original-request metadata. Constants do not add a native transaction field.")
    return sorted(cases, key=lambda row: row["id"].encode("utf-8"))


def main() -> None:
    cases = derived_cases()
    for case in cases:
        write_canonical_json(GROUP / (case["id"] + ".json"), case)
    print(f"Derived {len(cases)} exact key-history cases in {GROUP}")


if __name__ == "__main__":
    main()
