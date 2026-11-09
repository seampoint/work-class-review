"""Derive explicit recovery vectors without consulting either consumer."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from corpus_common import CASES, candidate_pin, digest, exact_case, write_canonical_json
from recovery_fixture import (
    authorize, disposition_expected, dispose_request, disputed, established_history,
    evidence_for, facts_for, policy_for, policy_issue, refresh_authentication,
    registered, target_for, normalize_native,
)
from reservation_fixture import refusal


GROUP = CASES / "recovery"
RULES = ["REC-001", "REC-002", "REC-003", "REC-004", "REC-005", "REC-006", "REC-007", "REC-008", "REC-009", "REC-010", "REC-011", "REC-015", "REC-016"]


def build() -> list[dict]:
    rows = []

    def add(supplied, expected, derivation):
        case_id = "C3-RC-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(case_id, "aggregate-step", supplied, expected, RULES, derivation))

    facts = facts_for()
    initial = registered(facts)
    issue, issued = policy_issue(facts, initial)
    add(issue, issued, "A current separately selected human policy owner issues the exact family, scope, version, USD limits and validity. The policy and its complete attributable act are retained; no exposure or allowance is created.")
    for change, description in [
        (lambda r: r["host_evidence"]["recovery"].update(recovery_bases=[]), "Missing policy-owner designation"),
        (lambda r: r["host_evidence"]["recovery"]["recovery_bases"][0].update(revoked=True), "Revoked policy-owner designation"),
        (lambda r: r["host_evidence"]["recovery"]["recovery_bases"][0].update(role="payment-executor"), "Executor authority cannot issue an exception policy"),
        (lambda r: r["host_evidence"]["recovery"]["recovery_bases"][0]["validity"].update(valid_until="2026-09-10T04:30:00Z"), "Policy-owner authority expires exclusively at the evaluation instant"),
    ]:
        altered = copy.deepcopy(issue)
        change(altered)
        add(altered, refusal(initial, "ADMINISTRATION_NOT_ESTABLISHED"), description + "; the registry remains unchanged.")

    wrong = copy.deepcopy(issue)
    wrong["event"]["payload"]["policy_digest"] = "sha256:" + "1" * 64
    refresh_authentication(facts, wrong)
    add(wrong, refusal(initial, "DEPENDENCY_MISMATCH"), "A complete authenticated policy cannot be paired with another digest.")

    revoked_request, revoked_result = policy_issue(facts, issued["state"], action="REVOKE", policy=issue["event"]["payload"]["policy"])
    add(revoked_request, revoked_result, "Withdrawal requires a current human revoke remit over the same complete policy scope. Retain the old issue and the revocation, with no allowance refund or financial release.")

    state = disputed(facts)
    leave = dispose_request(facts, state, "LEAVE_UNRESOLVED")
    add(leave, disposition_expected(leave), "Explicit leave-unresolved retains the complete authenticated evidence and current conservative charges and blocks. No human release authority or exception allowance is inferred.")
    no_effect = dispose_request(facts, state, "ESTABLISH_NO_EFFECT")
    no_effect_result = disposition_expected(no_effect)
    add(no_effect, no_effect_result, "Affirmative provider adjudication closes every original attempt's past and future execution possibility. The independent controller act carries adjudication and disputed-exposure release authority together. Historical DISPUTED flags remain; effective pending exposure becomes zero.")
    for change, description in [
        (lambda r: r["event"]["payload"].update(controller=None), "Missing controller act"),
        (lambda r: r["host_evidence"]["recovery"]["recovery_bases"][0].update(operations=["ESTABLISH_NO_EFFECT"]), "Adjudication-only authority cannot release disputed exposure"),
        (lambda r: r["host_evidence"]["recovery"]["recovery_bases"][0].update(operations=["RELEASE_DISPUTED_EXPOSURE"]), "Release-only authority cannot adjudicate no effect"),
        (lambda r: r["host_evidence"]["recovery"]["recovery_bases"][0].update(revoked=True), "A revoked controller cannot release exposure"),
    ]:
        altered = copy.deepcopy(no_effect)
        change(altered)
        add(altered, refusal(state, "ADMINISTRATION_NOT_ESTABLISHED"), description + "; exact prior state is returned.")
    wrong_scope = copy.deepcopy(no_effect)
    wrong_scope["host_evidence"]["recovery"]["recovery_bases"][0]["scope_digest"] = "sha256:" + "2" * 64
    add(wrong_scope, refusal(state, "DEPENDENCY_MISMATCH"), "A controller designation for another exact target fails binding before adjudication, preserving prior exposure.")

    self_controller = copy.deepcopy(no_effect)
    self_controller["host_evidence"]["recovery"]["authenticated_records"] = [x for x in self_controller["host_evidence"]["recovery"]["authenticated_records"] if x["kind"] != "RECOVERY_RETURN"]
    authorize(facts, self_controller["event"], self_controller["host_evidence"], operation="ESTABLISH_NO_EFFECT",
        scope_digest=digest("recovery-target", target_for(state)), actor=facts["authority_a"]["proposal"]["executor"]["actor"])
    add(self_controller, refusal(state, "ADMINISTRATION_NOT_ESTABLISHED"), "Even a fully bound controller act and human designation cannot adjudicate an action performed by that same executor identity.")

    unauthenticated = copy.deepcopy(no_effect)
    unauthenticated["host_evidence"]["recovery"]["authenticated_records"] = [x for x in unauthenticated["host_evidence"]["recovery"]["authenticated_records"] if x["kind"] != "RECOVERY_EVIDENCE"]
    add(unauthenticated, refusal(state, "EVIDENCE_UNAVAILABLE"), "A caller-supplied packet and hashes do not authenticate provider adjudication.")

    altered = copy.deepcopy(no_effect)
    altered["event"]["payload"]["evidence"]["covered_evidence_digests"] = []
    refresh_authentication(facts, altered)
    add(altered, refusal(state, "DEPENDENCY_MISMATCH"), "Omitting retained relevant native facts cannot establish complete coverage; rehashed authenticated wrappers do not repair the omission.")

    conclusive_state = disputed(facts, result_kind="EFFECT")
    unsuperseded = dispose_request(facts, conclusive_state, "ESTABLISH_NO_EFFECT")
    unsuperseded["event"]["payload"]["evidence"]["superseded_evidence_digests"] = []
    refresh_authentication(facts, unsuperseded)
    add(unsuperseded, disposition_expected(unsuperseded, reasons=["HISTORY_UNCORROBORATED", "RECOVERY_CONFLICT_UNRESOLVED", "RECOVERY_EVIDENCE_INCOMPLETE"], effective_result="LEAVE_UNRESOLVED"), "No-effect adjudication without an authoritative supersession of a retained conclusive effect remains unresolved. Retain exposure and blocking.")

    packet = evidence_for(facts, state, conclusion="EFFECT_ESTABLISHED", attempts=1)
    history = established_history(facts, packet["native_outcomes"][0])
    established = dispose_request(facts, state, "ESTABLISH_EFFECT", evidence=packet, histories=[history])
    add(established, disposition_expected(established), "Fresh complete journal corroboration is evaluated by DISPOSE even though earlier native evidence was retained. The exact authorized 150 USD effect replaces its uncertain reservation in effective accounting; 800 + 150 remains 950 and historical disputes are retained.")

    small = facts_for("2")
    small_state = disputed(small)
    issue_small, issued_small = policy_issue(small, small_state)
    add(issue_small, issued_small, "The same preapproval can be installed after uncertainty was retained; issuing it alone clears no block.")
    pd = issue_small["event"]["payload"]["policy_digest"]
    accept = dispose_request(small, issued_small["state"], "ACCEPT_UNRESOLVED", policy_digest=pd)
    accepted = disposition_expected(accept)
    add(accept, accepted, "Two authenticated unchanged-argument attempts, each bounded to one 2 USD execution, retain 4 USD total exposure. The 5 USD incident limit and 10 USD cumulative limit pass. Charge budget, distinct executor and distinct connector allowances once; no case-specific human controller act is required.")

    replay = copy.deepcopy(accept)
    replay["state"] = copy.deepcopy(accepted["state"])
    replay["state_digest"] = accepted["state_digest"]
    replay_expected = copy.deepcopy(accepted)
    replay_expected["replay"] = True
    add(replay, replay_expected, "Exact replay returns the established receipt with unchanged current registry state and adds no accounting, allowance or authority.")

    wrapper = dispose_request(small, accepted["state"], "ACCEPT_UNRESOLVED", event_id="fresh-wrapper-same-incident", policy_digest=pd)
    old = accepted["state"]["core"]["recovery"]["dispositions"][0]
    add(wrapper, disposition_expected(wrapper, reused=old), "A fresh event identity over the same incident, complete evidence generation and exact policy act references the established disposition. It cannot charge another contingent execution or allowance.")

    changed = copy.deepcopy(replay)
    changed["event"]["payload"]["evidence"]["id"] = "changed-same-event"
    refresh_authentication(small, changed)
    add(changed, refusal(accepted["state"], "REPLAY_CONFLICT"), "Changing any event bytes under an already retained event identity refuses before a new evaluation.")
    stale = copy.deepcopy(wrapper)
    stale["event"]["expected_revision"] = "0"
    add(stale, refusal(accepted["state"], "REVISION_CONFLICT"), "A new stale request cannot apply a historical allowance or adjudication against current roots.")

    report_wrapper = copy.deepcopy(wrapper)
    report_wrapper["event"]["id"] = "provider-wrapper-same-facts"
    packet = report_wrapper["event"]["payload"]["evidence"]
    packet.update(id="another-provider-report", evidence_ref="another-report-reference", provider_revision="3", record_digest="sha256:" + "3" * 64)
    refresh_authentication(small, report_wrapper)
    add(report_wrapper, disposition_expected(report_wrapper, reused=old), "Authenticated report wrappers and provider report revisions do not change the underlying complete fact/attempt generation or reset allowance consumption.")

    large = facts_for("5")
    large_state = disputed(large)
    large_policy, large_issued = policy_issue(large, large_state)
    over = dispose_request(large, large_issued["state"], "ACCEPT_UNRESOLVED", policy_digest=large_policy["event"]["payload"]["policy_digest"])
    add(over, disposition_expected(over, reasons=["RECOVERY_INCIDENT_LIMIT_EXCEEDED"], effective_result="LEAVE_UNRESOLVED"), "Two possible 5 USD executions measure 10 USD for the incident, exceeding 5. Retain the original 5 plus the bounded extra 5, leave blocking in force and consume no allowance.")

    for state_variant, policy_digest, description in [
        (small_state, "sha256:" + "4" * 64, "An unknown policy digest grants no exception"),
    ]:
        missing = dispose_request(small, state_variant, "ACCEPT_UNRESOLVED", policy_digest=policy_digest)
        add(missing, disposition_expected(missing, reasons=["RECOVERY_POLICY_INVALID"], effective_result="LEAVE_UNRESOLVED"), description + "; known bounded extra exposure is retained without clearing the block.")

    revoke, revoked = policy_issue(small, accepted["state"], action="REVOKE", policy=issue_small["event"]["payload"]["policy"])
    add(revoke, revoked, "Revoking preapproval retains contingent exposure and every accepted allowance. Future permission must not rely on this historical acceptance.")
    after_revoke = dispose_request(small, revoked["state"], "ACCEPT_UNRESOLVED", event_id="accept-revoked-policy", policy_digest=pd, supersedes=old["id"])
    add(after_revoke, disposition_expected(after_revoke, reasons=["RECOVERY_POLICY_INVALID"], effective_result="LEAVE_UNRESOLVED"), "A revoked exact policy cannot authorize a fresh acceptance, including a renamed event for the formerly accepted incident.")

    version2_request, version2 = policy_issue(small, accepted["state"], version="2", supersedes=pd)
    add(version2_request, version2, "A human-issued successor policy names its exact predecessor and preserves the family, complete scope and old allowance history.")
    pd2 = version2_request["event"]["payload"]["policy_digest"]
    second = dispose_request(small, version2["state"], "ACCEPT_UNRESOLVED", event_id="accept-policy-version-2", policy_digest=pd2, supersedes=old["id"])
    second_result = disposition_expected(second)
    add(second, second_result, "Fresh acceptance under a newly selected policy version consumes the full current 4 USD again. Both 4 USD admissions remain in the family window, totaling 8; policy versioning does not reset allowance.")
    version3_request, version3 = policy_issue(small, second_result["state"], version="3", supersedes=pd2)
    add(version3_request, version3, "A third version still uses the same allowance family and retains both prior admissions.")
    latest = next(x for x in second_result["state"]["core"]["recovery"]["dispositions"] if x["policy_digest"] == pd2)
    third = dispose_request(small, version3["state"], "ACCEPT_UNRESOLVED", event_id="accept-policy-version-3", policy_digest=version3_request["event"]["payload"]["policy_digest"], supersedes=latest["id"])
    add(third, disposition_expected(third, reasons=["RECOVERY_ALLOWANCE_EXCEEDED"], effective_result="LEAVE_UNRESOLVED"), "A third 4 USD acceptance would total 12 USD in the rolling 10 USD allowance. Refuse clearance atomically for all three attributions, retain the existing two charges and the 4 USD ordinary unresolved exposure.")

    scope_change_policy = policy_for(small, accepted["state"], version="2")
    scope_change_policy["scope"]["connectors"] = ["another-connector"]
    scope_change, _ = policy_issue(small, accepted["state"], version="2", supersedes=pd, policy=scope_change_policy)
    add(scope_change, refusal(accepted["state"], "UNSUPPORTED_RELATION"), "A reissued family cannot move its connector scope to escape retained allowance history. That change requires a separately designed migration.")

    exhausted = copy.deepcopy(accept)
    exhausted["event"]["payload"]["evidence"]["attempts"][1]["maximum_executions"] = "4097"
    refresh_authentication(small, exhausted)
    add(exhausted, refusal(issued_small["state"], "LIMIT_EXCEEDED"), "The finite projected contingent inventory would exceed 4096 rows. Refuse before expanding the attacker-controlled execution count, with no partial state change.")

    tampered = copy.deepcopy(replay)
    tampered["state"]["core"]["recovery"]["contingent"] = []
    tampered["state_digest"] = digest("reservation-state", tampered["state"])
    add(tampered, refusal(tampered["state"], "STATE_INVALID"), "Rehashing a supplied checkpoint after removing contingent exposure cannot survive independent reconstruction from canonical retained events.")

    tampered_allowance = copy.deepcopy(replay)
    tampered_allowance["state"]["core"]["recovery"]["allowances"] = []
    tampered_allowance["state_digest"] = digest("reservation-state", tampered_allowance["state"])
    add(tampered_allowance, refusal(tampered_allowance["state"], "STATE_INVALID"), "A rehashed checkpoint cannot erase the allowance consumed by an established acceptance.")

    incomplete = copy.deepcopy(no_effect)
    incomplete["event"]["payload"]["evidence"]["complete_attempt_inventory"] = False
    refresh_authentication(facts, incomplete)
    add(incomplete, disposition_expected(incomplete, reasons=["RECOVERY_EVIDENCE_INCOMPLETE"], effective_result="LEAVE_UNRESOLVED"), "Authenticated partial attempt history cannot prove no past or future execution. Retain all covered exposure and blocking.")

    nonfinal = copy.deepcopy(no_effect)
    packet = nonfinal["event"]["payload"]["evidence"]
    old_fact = digest("recovery-fact", {k: v for k, v in packet["native_outcomes"][0].items() if k not in ("id", "evidence_id", "evidence_ref", "record_digest", "observed_at")})
    packet["rules_out_past_and_future_effects"] = False
    packet["native_outcomes"][0]["rules_out_past_and_future_effects"] = False
    new_fact = digest("recovery-fact", {k: v for k, v in packet["native_outcomes"][0].items() if k not in ("id", "evidence_id", "evidence_ref", "record_digest", "observed_at")})
    packet["covered_evidence_digests"] = sorted({new_fact if x == old_fact else x for x in packet["covered_evidence_digests"]})
    refresh_authentication(facts, nonfinal)
    add(nonfinal, disposition_expected(nonfinal, reasons=["RECOVERY_EVIDENCE_INCOMPLETE"], effective_result="LEAVE_UNRESOLVED"), "A no-effect assertion that leaves future execution possible cannot release disputed exposure.")

    wrong_provider = copy.deepcopy(no_effect)
    wrong_provider["event"]["payload"]["evidence"]["provider"] = "unselected-adjudicator"
    refresh_authentication(facts, wrong_provider)
    add(wrong_provider, refusal(state, "DEPENDENCY_MISMATCH"), "Even an authenticated provider cannot adjudicate an invocation whose source selected another authoritative provider.")

    omitted_attempt = copy.deepcopy(wrapper)
    omitted_attempt["event"]["id"] = "omit-known-second-attempt"
    omitted_attempt["event"]["payload"]["supersedes"] = old["id"]
    omitted_attempt["event"]["payload"]["evidence"]["attempts"] = omitted_attempt["event"]["payload"]["evidence"]["attempts"][:1]
    refresh_authentication(small, omitted_attempt)
    add(omitted_attempt, refusal(accepted["state"], "DEPENDENCY_MISMATCH"), "A newly asserted complete inventory cannot omit the already retained second attempt or split the same incident to reduce its measured exposure.")

    pending = copy.deepcopy(accept)
    pending["host_evidence"]["recovery"]["pending_evidence"] = [{"target": copy.deepcopy(pending["event"]["payload"]["target"]), "record_digest": "sha256:" + "9" * 64}]
    add(pending, disposition_expected(pending, reasons=["RECOVERY_PENDING_EVIDENCE"], effective_result="LEAVE_UNRESOLVED"), "Other attributable relevant evidence waiting outside governed state prevents clearance. Bounded known possible executions remain charged; no allowance is consumed.")

    own_pending = copy.deepcopy(accept)
    own_pending["host_evidence"]["recovery"]["pending_evidence"] = [{"target": copy.deepcopy(own_pending["event"]["payload"]["target"]), "record_digest": digest("recovery-evidence", own_pending["event"]["payload"]["evidence"])}]
    add(own_pending, disposition_expected(own_pending), "The complete exact packet being admitted can consume its own custody entry atomically. It is not blocked by its own pending marker.")

    near_cap = facts_for("1.5")
    near_cap["history"]["journal"][0]["event"]["fields"][0]["value"]["value"] = "998"
    cap_state = disputed(near_cap)
    cap_issue, cap_issued = policy_issue(near_cap, cap_state)
    cap_accept = dispose_request(near_cap, cap_issued["state"], "ACCEPT_UNRESOLVED", policy_digest=cap_issue["event"]["payload"]["policy_digest"])
    add(cap_accept, disposition_expected(cap_accept, reasons=["BOUND_VIOLATED"], effective_result="LEAVE_UNRESOLVED"), "A 3 USD unresolved incident fits both exception limits, but 998 committed + 1.5 original + 1.5 contingent is 1001 against the ordinary 1000 ceiling. Retain both possibilities, withhold clearance and consume no allowance.")

    same_id_policy = policy_for(small, accepted["state"], version="2")
    same_id_policy["id"] = issue_small["event"]["payload"]["policy"]["id"]
    same_id_issue, _ = policy_issue(small, accepted["state"], version="2", supersedes=pd, policy=same_id_policy)
    add(same_id_issue, refusal(accepted["state"], "DEPENDENCY_MISMATCH"), "The stable family spans versions; a full policy identifier cannot be reused for different complete content.")

    no_predecessor = copy.deepcopy(second)
    no_predecessor["event"]["payload"]["supersedes"] = None
    add(no_predecessor, refusal(version2["state"], "REVISION_CONFLICT"), "A fresh policy-version acceptance must explicitly supersede the current incident disposition; current state revision alone cannot erase that history.")

    unbound_request = copy.deepcopy(accept)
    unbound_request["event"]["payload"]["evidence"]["request"]["operation"] = "other-operation"
    refresh_authentication(small, unbound_request)
    add(unbound_request, refusal(issued_small["state"], "DEPENDENCY_MISMATCH"), "Authenticated adjudication of changed native request arguments cannot clear this reservation's original uncertainty.")

    numeric_state = copy.deepcopy(small_state)
    predecessor = None
    for version in ("9", "10", "11"):
        numeric_issue, numeric_result = policy_issue(small, numeric_state, version=version, supersedes=predecessor)
        add(numeric_issue, numeric_result, "Natural policy versions advance numerically from 9 through 10 to 11. Canonical storage order cannot select the current version or replace the exact predecessor binding.")
        numeric_state = numeric_result["state"]
        predecessor = numeric_issue["event"]["payload"]["policy_digest"]
    numeric_accept = dispose_request(small, numeric_state, "ACCEPT_UNRESOLVED", event_id="accept-numeric-policy-11", policy_digest=predecessor)
    add(numeric_accept, disposition_expected(numeric_accept), "Version 11 is the current policy after the numeric 9, 10, 11 chain. Its unchanged family can authorize one bounded 4 USD acceptance, regardless of canonical row order.")

    conflicting = copy.deepcopy(established)
    conflicting["event"]["id"] = "contradictory-one-actual-effect"
    packet = conflicting["event"]["payload"]["evidence"]
    contrary = copy.deepcopy(packet["native_outcomes"][0])
    contrary.update(id="native-same-effect-contrary", occurred_at="2026-09-10T04:29:58Z")
    packet["native_outcomes"].append(contrary)
    packet["covered_evidence_digests"] = sorted(set(packet["covered_evidence_digests"]) | {digest("recovery-fact", normalize_native(contrary))})
    refresh_authentication(facts, conflicting)
    add(conflicting, disposition_expected(conflicting, reasons=["RECOVERY_CONFLICT_UNRESOLVED", "RECOVERY_EVIDENCE_INCOMPLETE"], effective_result="LEAVE_UNRESOLVED"), "Two current accepted conclusions disagree on the occurrence instant of the same actual effect identity. Complete binding and usable journal history do not resolve that contradiction. Retain the charged journal and uncertainty, select neither conclusion and withhold clearance.")
    reversed_conflict = copy.deepcopy(conflicting)
    reversed_conflict["event"]["id"] = "contradictory-one-actual-effect-reversed"
    reversed_conflict["event"]["payload"]["evidence"]["native_outcomes"].reverse()
    refresh_authentication(facts, reversed_conflict)
    add(reversed_conflict, disposition_expected(reversed_conflict, reasons=["RECOVERY_CONFLICT_UNRESOLVED", "RECOVERY_EVIDENCE_INCOMPLETE"], effective_result="LEAVE_UNRESOLVED"), "Reversing contradictory native conclusions changes no effective judgment. Array order cannot establish one of two different facts for the same actual execution; usable committed journal entries remain retained.")
    return rows


def main() -> None:
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    judgments = {"candidate_pin": candidate_pin(), "status": "DERIVED_EXPECTATIONS_PENDING_INDEPENDENT_REVIEW",
        "implementation_or_output_consulted": False, "judgments": [{"id": row["id"], "operation": row["operation"],
            "expected_judgment": row["expected"].get("code") or row["expected"]["receipt"]["decision"],
            "derivation": row["derivation"], "requirements": row["requirements"]} for row in rows]}
    write_canonical_json(Path(__file__).with_name("RECOVERY-EXPECTED-JUDGMENTS.json"), judgments)
    print(json.dumps({"recovery_cases": str(len(rows)), "implementation_or_output_consulted": False}))


if __name__ == "__main__":
    main()
