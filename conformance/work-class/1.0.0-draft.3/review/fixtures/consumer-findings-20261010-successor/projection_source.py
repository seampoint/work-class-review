"""Source-only projection stimuli copied from the retained manual constructors."""
from __future__ import annotations

import copy
from authority_fixture import authority_specimen
from corpus_common import digest
from equipment_completion_fixture import KEYS, completion_authority_mutator, completion_carrier, completion_key_proposal
from lifecycle_factory import base_lifecycle


def no_quantity(supplied, original):
    for step in supplied["work_class"]["steps"]:
        step["quantity_mode"] = "NONE"
    supplied["envelope"]["limits"]["per_action"] = []


def legacy_carrier():
    carrier = completion_carrier()
    carrier["terminal_policy"] = "LEGACY_NONTERMINAL"
    for name in ("provider_record_identity", "event_time_identity", "additional_fields", "lookup"):
        del carrier[name]
    return carrier


def legacy_keys(supplied, original):
    no_quantity(supplied, original)
    step = supplied["work_class"]["steps"][0]
    step["exclusive_keys"] = copy.deepcopy(KEYS)
    step["completion"] = legacy_carrier()
    supplied["work_class"]["types"].append({"id": "STRING", "kind": "STRING", "nonnegative": False, "unit": None})
    supplied["work_class"]["types"].sort(key=lambda row: row["id"].encode())
    supplied["envelope"]["enforcement"]["mechanisms"] = ["ATOMIC_RESERVATION_TRANSITION", "AUTHORITY_BEFORE_RESERVATION"]


def projection_proposal_inputs():
    rows = []
    for name, mutator in (("legacy-keyless", no_quantity), ("legacy-keyed", legacy_keys),
                          ("stop-retain-keyless", completion_authority_mutator)):
        base = base_lifecycle(authority_mutator=mutator)
        if name == "legacy-keyed":
            completion_key_proposal(base)
        event = copy.deepcopy(base.get("key_proposal_event", base["proposal_event"]))
        common = {key: base["deploy_input"][key] for key in ("profile", "role", "specification_pin", "definition", "definition_digest")}
        request = {**common, "state": copy.deepcopy(base["clock_result"]["state"]),
                   "state_digest": base["clock_result"]["state_digest"], "event": event}
        rows.append({"name": name, "input": request, "expected": {"status": "STEP", "disposition": "PERMITTED"}})

        def altered(supplied, original):
            mutator(supplied, original)
            step = supplied["work_class"]["steps"][0]
            if name == "legacy-keyless":
                step["completion"] = legacy_carrier()
                supplied["work_class"]["types"].append({"id": "STRING", "kind": "STRING", "nonnegative": False, "unit": None})
                supplied["work_class"]["types"].sort(key=lambda row: row["id"].encode())
            else:
                del step["completion"]
                references = {field["type_ref"] for row in supplied["work_class"]["steps"] for field in row["fields"]}
                references.update(ref for row in supplied["work_class"]["steps"] for ref in row.get("authority_type_refs", []))
                supplied["work_class"]["types"] = [row for row in supplied["work_class"]["types"] if row["id"] in references]

        authority_input, _ = authority_specimen(shared_budget=False, instance_id=event["instance_id"],
                                                occurrence_id=event["occurrence"]["occurrence_id"], mutator=altered)
        changed = copy.deepcopy(request)
        changed["event"]["authority_input"] = authority_input
        changed["event"]["observation_digests"] = sorted((digest("authority-observation", row) for row in authority_input["observations"]), key=str.encode)
        if name == "legacy-keyed":
            changed["event"]["budget_inputs"][0]["request"]["event"]["payload"]["authority"] = copy.deepcopy(authority_input)
        expected_refusal = {"status": "REFUSED", "profile": changed["profile"], "role": changed["role"],
                            "code": "BINDING_MISMATCH", "path": "", "state": copy.deepcopy(changed["state"]),
                            "state_digest": changed["state_digest"], "budget_states": [
                                {"registry_digest": row["registry_digest"], "affected_anchors": copy.deepcopy(row["affected_anchors"]),
                                 "state": copy.deepcopy(row["request"]["state"]), "state_digest": row["request"]["state_digest"]}
                                for row in changed["event"]["budget_inputs"]]}
        rows.append({"name": name + ("-extra-carrier" if name == "legacy-keyless" else "-missing-carrier"),
                     "input": changed, "expected": expected_refusal})
    return rows


