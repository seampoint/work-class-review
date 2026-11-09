"""Derive focused REC-016 work-only recovery controls without invoking either consumer."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / "conformance/work-class/1.0.0-draft.3"
sys.path.insert(0, str(AREA / "review"))

from corpus_common import canonical_bytes, digest
from lifecycle_factory import admitted_transition
from recovery_fixture import authorize, generation, normalize_native
from recovery_lifecycle_fixture import PBR, PROJECTION_KEYS, work_dispose_expected


def withhold(request, reasons):
    before, event = request["state"], request["event"]
    assert event["supersedes"] is None
    assert any(row["status"] == "BLOCKED_DISPUTE" for row in before["active"])
    identity = {
        "incident_digest": digest("recovery-incident", {
            "principal": before["deployment_organization_id"], "target": event["target"],
        }),
        "generation_digest": generation(event["evidence"]),
        "result": "LEAVE_UNRESOLVED",
        "policy_digest": None,
        "controller": event["controller"],
        "supersedes": None,
    }
    disposition = {
        "id": digest("recovery-disposition", identity),
        **identity,
        "acceptance_basis_digest": None,
        "target": event["target"],
        "evidence": event["evidence"],
        "event_digest": digest("runtime-event", event),
        "accepted_at": PBR["NOW"],
        "source_event": event,
    }
    projection = {key: before[key] for key in PROJECTION_KEYS}

    def retain(state):
        state["recovery_records"].append(deepcopy({
            "event": event,
            "host_evidence": request["recovery_host"],
            "disposition": disposition,
            "before_projection": projection,
            "after_projection": projection,
        }))

    return admitted_transition(
        before, event, disposition="WITHHELD", reason_codes=sorted(reasons),
        details=[], receipt_recovery_disposition_digest=disposition["id"], mutate=retain,
    )


def bind_changed_packet(request, name):
    event, host = request["event"], request["recovery_host"]
    event["event_id"] = name
    event["controller"] = None
    packet = event["evidence"]
    host["authenticated_records"] = [{
        "kind": "RECOVERY_EVIDENCE", "record_digest": digest("recovery-evidence", packet),
        "provider": packet["provider"], "source": packet["source"],
    }]
    host["recovery_bases"] = []
    if event["requested_result"] == "ESTABLISH_EFFECT":
        facts = {
            "configuration": {
                "principal": request["state"]["deployment_organization_id"],
                "recovery": request["definition"]["recovery"],
            },
            "clock": {"instant": PBR["NOW"]},
        }
        authorize(facts, event, host, operation="ESTABLISH_EFFECT",
                  scope_digest=digest("recovery-target", event["target"]))


def build():
    predecessor = AREA / "cases/recovery-lifecycle/C3-RL-007.json"
    source = json.loads(predecessor.read_bytes())
    control = source["input"]
    assert work_dispose_expected(control) == source["expected"]
    cases = [{"id": "original-positive-control", "input": control, "expected": source["expected"]}]

    def add(name, request, reasons):
        cases.append({"id": name, "input": request, "expected": withhold(request, reasons)})

    for wrong_conclusion in (False, True):
        request = deepcopy(control)
        packet = request["event"]["evidence"]
        packet["rules_out_past_and_future_effects"] = True
        name = "excluded-effect"
        reasons = ["RECOVERY_CONFLICT_UNRESOLVED"]
        if wrong_conclusion:
            name = "excluded-effect-and-wrong-conclusion"
            packet["conclusion"] = "UNRESOLVED"
            reasons.append("RECOVERY_EVIDENCE_INCOMPLETE")
        bind_changed_packet(request, name)
        add(name, request, reasons)

    packet = control["event"]["evidence"]
    exact_packet = digest("recovery-evidence", packet)
    other_packet = digest("recovery-evidence", {**packet, "provider_revision": "4"})
    for name, identity in [
        ("pending-exact-packet", exact_packet),
        ("pending-distinct-packet", other_packet),
        ("pending-covered-fact", packet["covered_evidence_digests"][0]),
    ]:
        request = deepcopy(control)
        request["recovery_host"]["pending_evidence"] = [{
            "target": deepcopy(request["event"]["target"]), "record_digest": identity,
        }]
        if name == "pending-exact-packet":
            cases.append({"id": name, "input": request, "expected": work_dispose_expected(request)})
        else:
            add(name, request, ["RECOVERY_PENDING_EVIDENCE"])

    for desired in ("ESTABLISH_EFFECT", "LEAVE_UNRESOLVED"):
        request = deepcopy(control)
        event = request["event"]
        event["requested_result"] = desired
        assert len(event["evidence"]["attempts"]) == 1
        event["evidence"]["attempts"][0]["effect_ids"] = []
        name = "unattributed-effect-" + desired.lower().replace("_", "-")
        bind_changed_packet(request, name)
        add(name, request, ["RECOVERY_EVIDENCE_INCOMPLETE"])
    for desired in ("ESTABLISH_EFFECT", "LEAVE_UNRESOLVED"):
        request = deepcopy(control)
        event = request["event"]
        event["requested_result"] = desired
        event["evidence"]["attempts"][0]["effect_ids"] = ["different-effect-id"]
        name = "attribution-names-other-effect-" + desired.lower().replace("_", "-")
        bind_changed_packet(request, name)
        add(name, request, ["RECOVERY_EVIDENCE_INCOMPLETE"])

    request = deepcopy(control)
    event = request["event"]
    event["requested_result"] = "LEAVE_UNRESOLVED"
    packet = event["evidence"]
    original = packet["native_outcomes"][0]
    contradictory = deepcopy(original)
    contradictory["evidence_id"] = "contradictory-master-change"
    field = next(row for row in contradictory["actual_fields"] if row["name"] == "destination_account")
    field["value"]["value"] = "acct-conflict"
    assert contradictory["native_operation_id"] == original["native_operation_id"]
    original_fact = digest("recovery-fact", normalize_native(original))
    contradictory_fact = digest("recovery-fact", normalize_native(contradictory))
    assert original_fact != contradictory_fact and contradictory_fact not in packet["covered_evidence_digests"]
    packet["native_outcomes"].append(contradictory)
    packet["covered_evidence_digests"] = sorted([*packet["covered_evidence_digests"], contradictory_fact])
    packet["superseded_evidence_digests"] = [value for value in packet["superseded_evidence_digests"] if value != original_fact]
    name = "contradictory-native-effect-leave-unresolved"
    bind_changed_packet(request, name)
    add(name, request, ["RECOVERY_CONFLICT_UNRESOLVED"])

    request = deepcopy(request)
    packet = request["event"]["evidence"]
    packet["superseded_evidence_digests"] = sorted([*packet["superseded_evidence_digests"], contradictory_fact])
    name = "superseded-native-conflict-leave-unresolved"
    bind_changed_packet(request, name)
    cases.append({"id": name, "input": request, "expected": work_dispose_expected(request)})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("xb") as stream:
        stream.write(canonical_bytes(build()) + b"\n")


if __name__ == "__main__":
    main()
