"""Derive recovery of the original supplier dependency before consumer execution."""

from __future__ import annotations

import copy
import json

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from lifecycle_factory import replay_result, stateful_refusal
from recovery_fixture import authorize
from recovery_lifecycle_fixture import (
    PBR, dispatch_event_from_record, dispute_prerequisite, supplier_chain, work_dispose_expected, work_dispose_request,
)


GROUP = CASES / "recovery-lifecycle"


def build() -> list[dict]:
    rows = []

    def add(operation, supplied, expected, derivation):
        cid = "C3-RL-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(cid, operation, supplied, expected,
            ["REC-001", "REC-002", "REC-003", "REC-004", "REC-012", "REC-013", "REC-014", "REC-015", "REC-016"], derivation))

    chain = supplier_chain()
    for (operation, supplied), expected in zip(chain["requests"], chain["results"], strict=True):
        add(operation, supplied, expected, "The source-selected recovery definition retains ordinary deployment, current clock, exact supplier-change authority, dispatch and completion behavior. No recovery decision or fabricated monetary reservation occurs during this setup.")
    dispute, disputed = dispute_prerequisite(chain)
    add("step", dispute, disputed, "Conflicting later conclusive evidence disputes the completed supplier-master result, retains its historical route and blocks the still-unproposed payment through its exact ancestor relationship.")

    restore = work_dispose_request(chain, disputed["state"])
    restored = work_dispose_expected(restore)
    add("step", restore, restored, "Independent controller adjudication with complete provider evidence establishes the original supplier/account fact. The unproposed payment returns to ACTIVE proposal eligibility. Its later proposal still needs fresh current authority, separation and budget. Every old disputed outcome and completed route remains unchanged.")

    replay = copy.deepcopy(restore)
    replay["state"] = copy.deepcopy(restored["state"])
    replay["state_digest"] = restored["state_digest"]
    add("step", replay, replay_result(restored["state"], restore["event"]["event_id"]), "Exact work-disposition replay after a fresh process reconstructs its complete application and before/after projection, returning historical decision evidence with current state and no rerouting or actuation.")

    absent = copy.deepcopy(restore)
    absent["event"]["controller"] = None
    add("step", absent, stateful_refusal(disputed["state"], "ADMINISTRATION_NOT_ESTABLISHED"), "A work-only prerequisite requires explicit independent controller authority; possessing its provider evidence does not grant adjudication authority.")

    self_controller = copy.deepcopy(restore)
    h = self_controller["recovery_host"]
    h["authenticated_records"] = [x for x in h["authenticated_records"] if x["kind"] != "RECOVERY_RETURN"]
    f = {"configuration": {"principal": disputed["state"]["deployment_organization_id"], "recovery": chain["definition"]["recovery"]}, "clock": {"instant": PBR["NOW"]}}
    authorize(f, self_controller["event"], h, operation="ESTABLISH_EFFECT",
        scope_digest=digest("recovery-target", self_controller["event"]["target"]), actor="destination-confirmer-person")
    add("step", self_controller, stateful_refusal(disputed["state"], "ADMINISTRATION_NOT_ESTABLISHED"), "The destination confirmer cannot adjudicate the disputed supplier-master effect even with an otherwise complete bound controller act.")

    negative = work_dispose_request(chain, disputed["state"], result="ESTABLISH_NO_EFFECT", event_id="disprove-original-master-change")
    stopped = work_dispose_expected(negative)
    add("step", negative, stopped, "Affirmative no-effect adjudication disproves the already completed prerequisite. The source selects STOP for the ACTIVE instance, retains the historical completion/route and every disputed record, and creates no replacement work.")

    terminal = work_dispose_request(chain, stopped["state"], result="LEAVE_UNRESOLVED", event_id="terminal-recovery-evidence")
    terminal["event"]["supersedes"] = stopped["state"]["recovery_records"][-1]["disposition"]["id"]
    add("step", terminal, work_dispose_expected(terminal), "A STOPPED instance accepts later attributable recovery evidence without reactivation, new routing, joins or a change to its terminal status.")

    leave = work_dispose_request(chain, disputed["state"], result="LEAVE_UNRESOLVED", event_id="leave-master-conflict")
    add("step", leave, work_dispose_expected(leave), "Work-only leave-unresolved records the complete provider packet while preserving every dependent block; no zero-value reservation is created.")

    tampered = copy.deepcopy(replay)
    tampered["state"]["recovery_records"][0]["after_projection"]["active"][0]["status"] = "BLOCKED_DISPUTE"
    tampered["state_digest"] = PBR["work_state_digest"](tampered["state"])
    add("step", tampered, stateful_refusal(tampered["state"], "STATE_INVALID"), "A freshly rehashed checkpoint cannot contradict the recovery record's derived after-projection or the current active occurrence status.")

    permitted_chain = supplier_chain(permitted_payment=True)
    p_dispute, p_disputed = dispute_prerequisite(permitted_chain)
    add("step", p_dispute, p_disputed, "A later supplier-master dispute blocks an already PERMITTED payment while retaining the exact original permit, factual bases and actuation count.")
    p_restore = work_dispose_request(permitted_chain, p_disputed["state"], event_id="restore-permitted-payment-basis")
    p_restored = work_dispose_expected(p_restore, restored_status="PERMITTED")
    add("step", p_restore, p_restored, "Original exact supplier/account evidence restores the unchanged unsent occurrence to PERMITTED status. Its old permit still cannot dispatch; renewal requires current authority under the original renewal rules, without another actuation or reservation.")
    old_dispatch = dispatch_event_from_record(p_restored["state"], permitted_chain["payment_permit"], {
        "event_id": "old-restored-payment-dispatch", "native_request": copy.deepcopy(permitted_chain["payment_permit"]["native_request"]),
        "connector": copy.deepcopy(permitted_chain["change_dispatch"]["connector"]),
        "attempt": copy.deepcopy(permitted_chain["change_dispatch"]["attempt"]),
        "acknowledgement": copy.deepcopy(permitted_chain["change_dispatch"]["acknowledgement"]), "clock_revision": "1"})
    old_dispatch["attempt"]["attempt_id"] = "old-permit-payment-attempt"
    old_dispatch["attempt"]["request_digest"] = digest("dispatch-native-request", {
        "instance_id": p_restored["state"]["instance_id"], "occurrence_id": permitted_chain["payment_permit"]["occurrence"]["occurrence_id"],
        **copy.deepcopy(permitted_chain["payment_permit"]["native_request"])})
    old_supplied = PBR["lifecycle_input"](permitted_chain["definition"], permitted_chain["definition_digest"], p_restored["state"], old_dispatch)
    add("step", old_supplied, stateful_refusal(p_restored["state"], "PREREQUISITE_MISSING"), "Restoration never revives dispatch of an old permit. An otherwise exact SENT observation against it refuses before actuation; eligible fresh renewal is required.")
    return rows


def main() -> None:
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print(json.dumps({"recovery_lifecycle_cases": str(len(rows)), "implementation_or_output_consulted": False}))


if __name__ == "__main__":
    main()
