"""Derive timing refusal and current-clock consistency cases from the contract."""
from __future__ import annotations

import base64
import copy
import json
import runpy
from pathlib import Path

from corpus_common import CASES, canonical_bytes, exact_case, write_canonical_json
from lifecycle_factory import stateful_refusal, step_input
from timing_fixture import clock_event, clock_result, deferred_control, qualifying_withholding

GROUP = CASES / "timing-admission"
LIFECYCLE = runpy.run_path(str(Path(__file__).with_name("build-timing-lifecycle-cases.py")))


def build():
    rows = []

    def add(operation, supplied, expected, derivation):
        cid = "C3-TA-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(cid, operation, supplied, expected,
            ["TIME-003", "TIME-005", "TIME-006", "TIME-007"], derivation))

    base = deferred_control()
    current = base["clock_result"]["state"]
    proposal = LIFECYCLE["proposal"]
    event, refusal = proposal(base, current, "false-unavailable", failure="CLOCK_UNAVAILABLE")
    add("step", step_input(base, current, event), stateful_refusal(current, "CLOCK_INVALID"),
        "TIME-006 rejects a submitted UNAVAILABLE authority clock that contradicts the latest retained AVAILABLE row. No evaluation, receipt or timer is installed.")

    forged = qualifying_withholding(base, current, event, refusal, arm=False)
    after = clock_event(forged["state"], "2", "2026-09-10T04:31:00Z", event_id="after-false-outage")
    for replay in (event, after):
        add("step", step_input(base, forged["state"], replay), stateful_refusal(forged["state"], "STATE_INVALID"),
            "An outer-digest-correct checkpoint retains an unavailable proposal evaluation that contradicted its preceding available clock. Historical validation refuses before exact replay or a fresh clock can admit it.")

    for status in ("UNAVAILABLE", "CONFLICTING"):
        recorded_event = clock_event(current, "2", status=status, event_id="retained-" + status.lower())
        recorded = clock_result(current, recorded_event)
        add("step", step_input(base, current, recorded_event), recorded,
            "The explicit lifecycle clock records " + status + "; an old available sample cannot supply current permission.")
        event, refusal = proposal(base, recorded["state"], "project-" + status.lower(), failure="CLOCK_UNAVAILABLE")
        add("step", step_input(base, recorded["state"], event),
            qualifying_withholding(base, recorded["state"], event, refusal, arm=False),
            "Authority's two-status clock projects retained " + status + " to UNAVAILABLE with null revision. The complete withholding is retained but starts no first-proved-failure timer.")
        event = copy.deepcopy(event)
        event.update(event_id="nonnull-unavailable-" + status.lower(), clock_revision="2")
        add("step", step_input(base, recorded["state"], event), stateful_refusal(recorded["state"], "CLOCK_INVALID"),
            "Submitted unavailable authority time requires a null lifecycle revision, including the CONFLICTING projection.")

    event, _ = proposal(base, current, "malformed-false-outage", failure="CLOCK_UNAVAILABLE")
    event["authority_input"]["unexpected"] = True
    add("step", step_input(base, current, event), {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
        "The closed outer request schema rejects an unsupported embedded authority field before state or clock-status checks; an unavailable status does not conceal malformed input.")

    initial = base["deploy_result"]["state"]
    event, refusal = proposal(base, initial, "no-clock-sample", failure="CLOCK_UNAVAILABLE")
    add("step", step_input(base, initial, event), qualifying_withholding(base, initial, event, refusal, arm=False),
        "With no retained sample, authority UNAVAILABLE with null revision is consistent. Its complete evaluation remains WAITING and grants no permission.")

    deployed = json.loads((CASES / "sepsis-timing/C3-ST-001.json").read_bytes())["input"]
    changed = copy.deepcopy(deployed)
    changed["event_anchors"][0]["record_digest"] = "sha256:" + "0" * 64
    add("deploy", changed, {"status": "REFUSED", "code": "DIGEST_MISMATCH", "path": "", "profile": deployed["profile"], "role": deployed["role"]},
        "TIME-003 checks the native record digest before its wrapper's authorization vector. A wrong native digest is DIGEST_MISMATCH, independently of wrapper-pin mismatch.")

    changed = copy.deepcopy(deployed)
    changed["event_anchors"][0]["record"]["fields"].pop()
    from corpus_common import digest
    changed["event_anchors"][0]["record_digest"] = digest("event-anchor-record", changed["event_anchors"][0]["record"])
    add("deploy", changed, {"status": "REFUSED", "code": "BINDING_MISMATCH", "path": "", "profile": deployed["profile"], "role": deployed["role"]},
        "A native field-name inventory different from the exact declaration refuses BINDING_MISMATCH before authorization-vector comparison.")

    definition = deployed["definition"]
    identity = next(row["id"] for row in definition["types"] if row["kind"] == "IDENTITY")
    instant = next(row["id"] for row in definition["types"] if row["kind"] == "INSTANT")
    for variant in ("time", "binding"):
        changed = copy.deepcopy(definition)
        anchor = changed["event_anchors"][0]
        if variant == "time":
            anchor["time"] = {"kind": "EVENT_TIME", "type_ref": identity}
        else:
            subject = anchor["subject_fields"][0]
            next(row for row in anchor["fields"] if row["name"] == subject)["type_ref"] = instant
        supplied = {"specification_pin": changed["specification_pin"], "kind": "WORK_CLASS",
            "artifact_bytes_base64": base64.b64encode(canonical_bytes(changed)).decode()}
        add("validate", supplied, {"status": "REFUSED", "code": "DEFINITION_INVALID", "path": ""},
            "TIME-003 refuses the schema-valid resolved static " + variant + " type error as DEFINITION_INVALID. Missing references and malformed dynamic values have their separately defined codes.")
    return rows


if __name__ == "__main__":
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print(json.dumps({"timing_admission_cases": len(rows), "consumer_or_output_consulted": False}))
