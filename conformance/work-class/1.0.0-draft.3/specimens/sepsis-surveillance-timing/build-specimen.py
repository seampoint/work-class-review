#!/usr/bin/env python3
"""Construct the fictional v5 timing successor independently of consumers.

Fixed specimen constructor, not a general evaluator. Every expected judgment, state
and digest follows DERIVATIONS.md, written before successor fixture construction.
Copied inherited construction helpers preserve the original specimen untouched.
No consumer imports, adapter calls or runtime-derived expectations.
"""

from __future__ import annotations

import base64
import copy
import datetime
import hashlib
import json
import argparse
from pathlib import Path


HERE = Path(__file__).resolve().parent
PIN = "sha256:" + hashlib.sha256(
    (HERE.parents[4] / "library/work-class-specification/1.0.0-draft.3/contract-manifest.json").read_bytes()
).hexdigest()
PREFIX = b"seampoint.work-class/1.0.0-draft.3/"
SCHEMA = "seampoint.work-class/1.0.0-draft.3/"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"
PROFILE = "PARALLEL_FANOUT"
ROLE = "PARALLEL_FANOUT_RUNTIME"
INSTANCE = "sepsis-timing-instance-1"
ORG = "sample-hospital"
CLOCK_SOURCE = "ward-clock"
PROVIDER = "hospital-identity-provider"
REVOCATION_SOURCE = "authority-revocations"
CHANNEL = "authority-return-channel"
T0 = "2026-09-12T08:00:00Z"
DEPLOYMENT_AUTHORIZED_AT = "2026-09-12T07:59:00Z"
DEPLOYMENT_CLOCK_AT = "2026-09-12T07:59:00Z"
DEPLOYMENT_EXPIRES = "2026-09-13T00:00:00Z"
VALIDITY = {"valid_from": "2026-09-01T00:00:00Z", "valid_until": "2026-12-01T00:00:00Z"}
GRANT_AT = "2026-09-01T09:00:00Z"
ATTEST_AT = "2026-09-01T09:01:00Z"
MAX_AGE = "900"
PATIENT = "patient-1"
ALERT = "alert-4471"
RECOGNITION = "2026-09-12T07:58:00Z"
RECOGNITION_OBSERVED = "2026-09-12T07:58:30Z"
HOUR_ONE_DUE = "2026-09-12T08:58:00Z"
ANCHOR_REF = "alert-recognition"
PROXY = "synthetic:specimen-proxy-"


def key_order(value: str) -> bytes:
    return value.encode("utf-16-be")


def canonical_text(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(canonical_text(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            canonical_text(key) + ":" + canonical_text(value[key]) for key in sorted(value, key=key_order)
        ) + "}"
    raise TypeError(f"restricted JSON excludes {type(value).__name__}")


def canonical_bytes(value) -> bytes:
    return canonical_text(value).encode("utf-8")


def digest(kind: str, value) -> str:
    return "sha256:" + hashlib.sha256(PREFIX + kind.encode() + b"\n" + canonical_bytes(value)).hexdigest()


def raw_sha(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def omit(value: dict, *keys: str) -> dict:
    result = copy.deepcopy(value)
    for key in keys:
        result.pop(key, None)
    return result


def utf8(value: str) -> bytes:
    return value.encode("utf-8")


def sorted_utf8(values):
    return sorted(values, key=lambda item: canonical_bytes(item) if not isinstance(item, str) else utf8(item))


def plus_seconds(instant: str, seconds: int) -> str:
    moment = datetime.datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ") + datetime.timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def write(name: str, value) -> None:
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def write_lines(name: str, rows) -> None:
    (HERE / name).write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))


def typed(type_ref: str, value):
    return {"type_ref": type_ref, "value": value}


def field(name: str, type_ref: str, value):
    return {"name": name, "value": typed(type_ref, value)}


def fields_sorted(rows):
    return sorted(rows, key=lambda row: utf8(row["name"]))


def readback(value):
    lines = []

    def token(text: str) -> str:
        return text.replace("~", "~0").replace("/", "~1")

    def walk(node, pointer: str):
        if isinstance(node, dict):
            if not node:
                lines.append({"path": pointer, "value": canonical_text(node)})
            else:
                for key, child in node.items():
                    walk(child, pointer + "/" + token(key))
        elif isinstance(node, list):
            if not node:
                lines.append({"path": pointer, "value": canonical_text(node)})
            else:
                for index, child in enumerate(node):
                    walk(child, pointer + "/" + str(index))
        else:
            lines.append({"path": pointer, "value": canonical_text(node)})

    walk(value, "")
    return sorted(lines, key=lambda line: utf8(line["path"]))


def clock_record(revision: str, instant: str, source: str = CLOCK_SOURCE) -> dict:
    return {
        "source": source, "revision": revision, "status": "AVAILABLE", "observed_time": instant,
        "evidence_digest": digest("specimen-clock-evidence", {"source": source, "revision": revision, "time": instant}),
    }


# ---------------------------------------------------------------------------
# Source policy and work-class definition
# ---------------------------------------------------------------------------

SOURCE_POLICY = {
    "artifact_kind": "NON_NORMATIVE_SYNTHETIC_SOURCE_POLICY",
    "candidate_pin": PIN,
    "id": "sepsis-surveillance-policy",
    "revision": "v4",
    "claim_boundary": "Synthetic and illustrative. Draws on public sepsis bundle practice as motivation only. Not clinical guidance, not a description of any hospital, and no claim about the accuracy of any prediction model.",
    "obligations": [
        {"id": "alert-window-cap", "text": "A patient receives at most two sepsis alerts in any rolling six-hour window; a further alert inside the window is refused by the alert-count aggregate and recorded as suppressed before any instance is deployed."},
        {"id": "antibiotic-requires-physician-order", "text": "An antibiotic order requires the attending physician's per-instance order naming the patient, drug, dose and route, verified by pharmacy; the surveillance agent's proposal is a candidate and the physician's order is the act."},
        {"id": "bundle-completion-is-reconciled", "text": "The bundle completes only on native records: the laboratory result record and the medication administration record. An order with no administration record is an unknown outcome that neither completes nor releases the obligation, and a result that arrives after its deadline counts as evidence for what it shows without making the missed deadline met."},
        {"id": "cultures-before-antibiotics-unless-overridden", "text": "Blood cultures are drawn before antibiotics are administered unless drawing them would delay antibiotics more than forty-five minutes, in which case the attending may authorize administration first and the reason is recorded with the order."},
        {"id": "escalate-unacknowledged-page", "text": "The attending is paged on alert; if no acknowledgement is recorded within fifteen minutes of the page, the agent escalates to the rapid-response team and the bundle continues."},
        {"id": "hour-one-bundle", "text": "Time zero is the alert's recorded recognition time. Screening labs are resulted and antibiotics administered, each with native evidence, within one hour of time zero."},
        {"id": "screening-under-standing-protocol", "text": "A registered nurse may order the sepsis screening set (lactate, blood cultures, complete blood count) under the standing protocol without a physician order; the grant is limited to the named tests, bound to the protocol version, and withdrawn when the version is retired."},
        {"id": "vitals-freshness", "text": "Vitals older than fifteen minutes are indeterminate for any decision that depends on them; an indeterminate observation holds the dependent action and a fresh observation re-evaluates it."},
    ],
}
SOURCE_IDS = [row["id"] for row in SOURCE_POLICY["obligations"]]
SOURCE_POLICY["successor_choices"] = {
    "recognition": "Immutable fictional sepsis-recognition-system/recognition-log/sepsis-recognition record binds patient and alert; native event_time is time zero.",
    "page": "The first admitted SENT or UNKNOWN attempt, or ACCEPTED acknowledgement, starts a conservative possible-send interval. NOT_SENT without ACCEPTED does not start it. Connector acceptance is not attending acknowledgement or delivery.",
    "vitals": "Current applicable monitoring-feed/vitals-stream/current-vitals-measurement record binds patient and measured_at. Readiness and antibiotic decisions require exact measured age <=900 seconds; refresh requests do not.",
    "labs_expiry": "Stop without a native laboratory result; timeout cannot satisfy the bundle join.",
    "culture_limit": "The prospective delay greater than45 minutes is not represented by the retained cultures-first-or-recorded-reason gate and remains uncovered.",
}

TYPES = [
    {"id": "t.boolean", "kind": "BOOLEAN", "nonnegative": False, "unit": None},
    {"id": "t.count", "kind": "INTEGER", "nonnegative": True, "unit": None},
    {"id": "t.dose", "kind": "DECIMAL", "nonnegative": True, "unit": "mg"},
    {"id": "t.identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
    {"id": "t.instant", "kind": "INSTANT", "nonnegative": False, "unit": None},
    {"id": "t.readiness", "kind": "STRING", "nonnegative": False, "unit": None},
    {"id": "t.score", "kind": "DECIMAL", "nonnegative": True, "unit": None},
    {"id": "t.seconds", "kind": "INTEGER", "nonnegative": True, "unit": None},
    {"id": "t.status", "kind": "STRING", "nonnegative": False, "unit": None},
    {"id": "t.text", "kind": "STRING", "nonnegative": False, "unit": None},
]
TYPE_KIND = {row["id"]: row["kind"] for row in TYPES}


def declared(name: str, type_ref: str) -> dict:
    return {"name": name, "type_ref": type_ref}


def completion(provider, source, record_type, no_effect_record_type, success, failure, field_names, route_label=None):
    return {
        "terminal_policy": "LEGACY_NONTERMINAL", "effect_provider": provider, "effect_source": source, "effect_record_type": record_type,
        "no_effect_provider": provider, "no_effect_source": source, "no_effect_record_type": no_effect_record_type,
        "status_field": "status", "status_type_ref": "t.status",
        "success_values": [typed("t.status", success)], "failure_values": [typed("t.status", failure)],
        "route_label_field": route_label, "route_label_type_ref": "t.readiness" if route_label else None,
        "evidence_bindings": [{"request_field": name, "evidence_field": name} for name in field_names],
    }


def structural(step_id: str, kind: str) -> dict:
    return {
        "id": step_id, "kind": kind, "exclusive_keys": [], "executor_role": None, "interface": None, "operation": None, "fields": [],
        "scope_fields": None, "required_credentials": [], "authority_requirements": [], "shared_budgets": [],
        "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": None, "failure_behavior": None,
        "completion": None,
    }


def operation(step_id, executor_role, interface, op, fields, subject, resource, credential, authority, permit_seconds, carrier):
    return {
        "id": step_id, "kind": "OPERATION", "quantity_mode": "BOUNDED", "exclusive_keys": [], "executor_role": executor_role, "interface": interface, "operation": op,
        "fields": sorted(fields, key=lambda row: utf8(row["name"])),
        "scope_fields": {"subjects": [subject], "resources": [resource]},
        "required_credentials": [credential], "authority_requirements": [authority], "shared_budgets": [],
        "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": permit_seconds,
        "failure_behavior": "STOP", "completion": carrier,
    }


STEPS = sorted([
    operation("raise-alert", "surveillance-agent", "nurse-notification", "raise-sepsis-alert",
              [declared("alert_id", "t.identity"), declared("patient_id", "t.identity"), declared("risk_score", "t.score")],
              "patient_id", "alert_id", "surveillance-agent-credential", "alert-authority", "300",
              completion("nurse-notification-system", "alert-log", "alert-delivery", "alert-no-effect", "DELIVERED", "UNDELIVERED",
                         ["alert_id", "patient_id", "risk_score"])),
    operation("order-screening-labs", "registered-nurse", "order-entry", "order-screening-set",
              [declared("alert_id", "t.identity"), declared("order_set_id", "t.identity"), declared("panel", "t.text"), declared("patient_id", "t.identity"), declared("test_count", "t.count")],
              "patient_id", "order_set_id", "registered-nurse-licence", "protocol-labs-authority", "300",
              completion("laboratory-information-system", "lis", "screening-result-set", "screening-no-result", "RESULTED", "CANCELLED",
                         ["alert_id", "order_set_id", "panel", "patient_id", "test_count"])),
    operation("page-attending", "surveillance-agent", "paging-system", "page-attending-physician",
              [declared("attempt_number", "t.count"), declared("page_id", "t.identity"), declared("patient_id", "t.identity")],
              "patient_id", "page_id", "surveillance-agent-credential", "page-authority", "300",
              completion("paging-system", "page-log", "page-acknowledgement", "page-no-effect", "ACKNOWLEDGED", "DECLINED",
                         ["attempt_number", "page_id", "patient_id"])),
    operation("escalate-rapid-response", "surveillance-agent", "paging-system", "page-rapid-response",
              [declared("attempt_number", "t.count"), declared("page_id", "t.identity"), declared("patient_id", "t.identity")],
              "patient_id", "page_id", "surveillance-agent-credential", "escalation-authority", "300",
              completion("paging-system", "page-log", "rapid-response-acknowledgement", "rapid-response-no-effect", "ACKNOWLEDGED", "DECLINED",
                         ["attempt_number", "page_id", "patient_id"])),
    operation("assess-readiness", "surveillance-agent", "monitoring-feed", "assess-antibiotic-readiness",
              [declared("assessment_id", "t.identity"), declared("lookback_seconds", "t.seconds"), declared("patient_id", "t.identity")],
              "patient_id", "assessment_id", "surveillance-agent-credential", "assessment-authority", "300",
              completion("monitoring-feed", "vitals-stream", "readiness-assessment", "assessment-no-effect", "COMPLETED", "ABORTED",
                         ["assessment_id", "lookback_seconds", "patient_id"], route_label="readiness")),
    operation("refresh-vitals", "surveillance-agent", "monitoring-feed", "request-vitals-refresh",
              [declared("attempt_number", "t.count"), declared("patient_id", "t.identity"), declared("refresh_id", "t.identity")],
              "patient_id", "refresh_id", "surveillance-agent-credential", "refresh-authority", "300",
              completion("monitoring-feed", "vitals-stream", "vitals-refresh", "refresh-no-effect", "REFRESHED", "FAILED",
                         ["attempt_number", "patient_id", "refresh_id"])),
    operation("order-antibiotic", "attending-physician", "order-entry", "place-antibiotic-order",
              [declared("alert_id", "t.identity"), declared("cultures_drawn_first", "t.boolean"), declared("dose_mg", "t.dose"), declared("drug", "t.text"),
               declared("order_id", "t.identity"), declared("override_reason", "t.text"), declared("patient_id", "t.identity"),
               declared("route", "t.text"), declared("vitals_age_seconds", "t.seconds")],
              "patient_id", "order_id", "physician-licence", "antibiotic-order-authority", "900",
              completion("medication-administration-record", "mar", "antibiotic-administration", "administration-no-effect", "ADMINISTERED", "NOT_GIVEN",
                         ["alert_id", "cultures_drawn_first", "dose_mg", "drug", "order_id", "override_reason", "patient_id", "route", "vitals_age_seconds"])),
    structural("bundle-split", "PARALLEL_SPLIT"),
    structural("bundle-join", "PARALLEL_JOIN"),
    structural("bundle-complete", "TERMINAL"),
], key=lambda row: utf8(row["id"]))
STEP = {row["id"]: row for row in STEPS}
for timed_step in ("assess-readiness", "order-antibiotic"):
    STEP[timed_step]["authority_type_refs"] = ["t.instant"]
PROPOSAL_STEPS = [row for row in STEPS if row["kind"] == "OPERATION"]

RELATIONSHIPS = [
    {"kind": "SEQUENCE", "from": "raise-alert", "to": "bundle-split"},
    {"kind": "SEQUENCE", "from": "order-screening-labs", "to": "bundle-join"},
    {"kind": "SEQUENCE", "from": "page-attending", "to": "bundle-join"},
    {"kind": "EXPIRY", "from": "page-attending", "to": "escalate-rapid-response", "deadline_ref": "attending-acknowledgement"},
    {"kind": "SEQUENCE", "from": "escalate-rapid-response", "to": "bundle-join"},
    {"kind": "SEQUENCE", "from": "bundle-join", "to": "assess-readiness"},
    {"kind": "LABEL", "from": "assess-readiness", "to": "order-antibiotic", "label": typed("t.readiness", "READY")},
    {"kind": "LABEL", "from": "assess-readiness", "to": "refresh-vitals", "label": typed("t.readiness", "REASSESS")},
    {"kind": "SEQUENCE", "from": "refresh-vitals", "to": "assess-readiness"},
    {"kind": "SEQUENCE", "from": "order-antibiotic", "to": "bundle-complete"},
]


def relationship(kind: str, source: str, target: str) -> dict:
    return next(row for row in RELATIONSHIPS if row["kind"] == kind and row["from"] == source and row["to"] == target)


def relationship_digest(kind: str, source: str, target: str) -> str:
    return digest("relationship", relationship(kind, source, target))


DEADLINES = sorted([
    {"id": "antibiotic-window", "step_id": "order-antibiotic", "clock_source": CLOCK_SOURCE,
     "due": {"kind": "ELAPSED_FROM_EVENT_ANCHOR", "value": "60", "unit": "MINUTE", "anchor_ref": ANCHOR_REF}, "boundary": "AT_OR_AFTER", "expiry_target": None},
    {"id": "attending-acknowledgement", "step_id": "page-attending", "clock_source": CLOCK_SOURCE,
     "due": {"kind": "ELAPSED_FROM_FIRST_DISPATCH", "value": "15", "unit": "MINUTE"}, "boundary": "AT_OR_AFTER", "expiry_target": "escalate-rapid-response"},
    {"id": "labs-hour-one", "step_id": "order-screening-labs", "clock_source": CLOCK_SOURCE,
     "due": {"kind": "ELAPSED_FROM_EVENT_ANCHOR", "value": "60", "unit": "MINUTE", "anchor_ref": ANCHOR_REF}, "boundary": "AT_OR_AFTER", "expiry_target": None},
], key=lambda row: utf8(row["id"]))
DEADLINE = {row["id"]: row for row in DEADLINES}
DEADLINE_BY_STEP = {row["step_id"]: row for row in DEADLINES}
DEADLINE_SECONDS = {"SECOND": 1, "MINUTE": 60, "HOUR": 3600, "DAY": 86400}

WORK_CLASS = {
    "schema": SCHEMA + "work-class-definition",
    "specification_pin": PIN,
    "id": "sepsis-surveillance-timing-bundle",
    "revision": "r1",
    "profile": PROFILE,
    "root": "raise-alert",
    "participants": [
        {"id": "attending-hospitalist-1", "role": "attending-physician", "kind": "PERSON"},
        {"id": "nurse-bedside-1", "role": "registered-nurse", "kind": "PERSON"},
        {"id": "sepsis-surveillance-agent", "role": "surveillance-agent", "kind": "AGENT"},
    ],
    "objects": [],
    "types": TYPES,
    "steps": STEPS,
    "relationships": RELATIONSHIPS,
    "choices": [{"step_id": "assess-readiness", "label_type_ref": "t.readiness",
                 "label_values": [typed("t.readiness", "READY"), typed("t.readiness", "REASSESS")]}],
    "occurrence_limits": sorted([
        {"step_id": "assess-readiness", "maximum": "3"}, {"step_id": "escalate-rapid-response", "maximum": "1"},
        {"step_id": "order-antibiotic", "maximum": "1"}, {"step_id": "order-screening-labs", "maximum": "1"},
        {"step_id": "page-attending", "maximum": "1"}, {"step_id": "raise-alert", "maximum": "1"},
        {"step_id": "refresh-vitals", "maximum": "3"},
    ], key=lambda row: utf8(row["step_id"])),
    "loops": [{"id": "vitals-reassessment", "entry_step_id": "assess-readiness",
               "member_step_ids": ["assess-readiness", "refresh-vitals"], "back_edge_from_step_id": "refresh-vitals",
               "maximum_passes": "3"}],
    "deadlines": DEADLINES,
    "event_anchors": [{"id": ANCHOR_REF, "provider": "sepsis-recognition-system", "source": "recognition-log",
                       "record_type": "sepsis-recognition", "time": {"kind": "EVENT_TIME", "type_ref": "t.instant"},
                       "fields": [declared("alert_id", "t.identity"), declared("patient_id", "t.identity")],
                       "subject_fields": ["alert_id", "patient_id"],
                       "request_bindings": [{"step_id": step, "subject_field": name, "target_request_field": name}
                                            for step in ("order-antibiotic", "order-screening-labs", "raise-alert")
                                            for name in ("alert_id", "patient_id")]}],
    "parallel_blocks": [{"id": "hour-one-bundle", "split_step_id": "bundle-split",
                         "branches": [{"id": "labs", "head_step_id": "order-screening-labs"}, {"id": "page", "head_step_id": "page-attending"}],
                         "join_step_id": "bundle-join"}],
    "fanouts": [],
    "shared_budgets": [],
    "limits": {"maximum_proposals": "64", "maximum_activations": "16", "maximum_actuations": "16",
               "maximum_active_obligations": "2", "maximum_fanout_objects": "0"},
    "source": {"id": SOURCE_POLICY["id"], "revision": SOURCE_POLICY["revision"], "obligations": SOURCE_IDS},
}
DEFINITION_DIGEST = digest("work-class-definition", WORK_CLASS)

# ---------------------------------------------------------------------------
# Authority material (AUTHORITY.md, AUTHORITY-CHECKS.md)
# ---------------------------------------------------------------------------

AUTHORITY_SOURCE = {
    "schema": SCHEMA + "authority-source", "id": SOURCE_POLICY["id"], "revision": SOURCE_POLICY["revision"],
    "obligations": [{"id": row["id"], "text": row["text"]} for row in SOURCE_POLICY["obligations"]],
}
SOURCE_DIGEST = digest("authority-source", AUTHORITY_SOURCE)
AUTHORITY_TYPE_IDS = sorted({f["type_ref"] for step in PROPOSAL_STEPS for f in step["fields"]}
                            | {ref for step in PROPOSAL_STEPS for ref in step.get("authority_type_refs", [])}, key=utf8)
AUTHORITY_WORK_CLASS = {
    "schema": SCHEMA + "authority-work-class", "id": WORK_CLASS["id"], "revision": WORK_CLASS["revision"],
    "types": [row for row in TYPES if row["id"] in AUTHORITY_TYPE_IDS],
    "steps": [{"id": s["id"], "operation": s["operation"], "interface": s["interface"], "executor_role": s["executor_role"],
               "fields": s["fields"], "scope_fields": s["scope_fields"], "required_credentials": s["required_credentials"], "quantity_mode": s["quantity_mode"], "exclusive_keys": s["exclusive_keys"],
               **({"authority_type_refs": s["authority_type_refs"]} if "authority_type_refs" in s else {})}
              for s in PROPOSAL_STEPS],
}
AUTHORITY_WORK_CLASS_DIGEST = digest("authority-work-class", AUTHORITY_WORK_CLASS)

OCCUPANCIES = {
    "occupancy-attending-1": {"actor": "attending-hospitalist-1", "role": "attending-physician", "kind": "HUMAN"},
    "occupancy-medical-director": {"actor": "person-medical-director", "role": "medical-director", "kind": "HUMAN"},
    "occupancy-nurse-bedside-1": {"actor": "nurse-bedside-1", "role": "registered-nurse", "kind": "HUMAN"},
    "occupancy-pharmacist-1": {"actor": "pharmacist-1", "role": "pharmacist", "kind": "HUMAN"},
    "occupancy-quality-officer": {"actor": "person-quality-officer", "role": "clinical-governance-attester", "kind": "HUMAN"},
    "occupancy-surveillance-agent": {"actor": "sepsis-surveillance-agent", "role": "surveillance-agent", "kind": "MACHINE"},
}


def occupancy_record(occupancy_id: str) -> dict:
    row = OCCUPANCIES[occupancy_id]
    return {"id": occupancy_id, "actor": row["actor"], "role": row["role"], "principal": ORG, "kind": row["kind"],
            "validity": VALIDITY, "provider": PROVIDER, "evidence_ref": occupancy_id + "-evidence"}


def executor_for(occupancy_id: str) -> dict:
    row = OCCUPANCIES[occupancy_id]
    return {"actor": row["actor"], "role": row["role"], "principal": ORG, "occupancy": occupancy_id}


REVOCATION = {"provider": PROVIDER, "source": REVOCATION_SOURCE, "max_age_seconds": MAX_AGE}
NONE_GATE = {"materiality": "LOW", "reversibility": "HIGH", "kind": "NONE", "role": None, "criteria": []}


def limit(limit_id, step_id, field_name, type_ref, bound):
    return {"id": limit_id, "step": step_id, "field": field_name, "operator": "LTE", "bound": typed(type_ref, bound)}


def field_operand(name):
    return {"kind": "FIELD", "name": name}


def literal(type_ref, value):
    return {"kind": "LITERAL", "value": typed(type_ref, value)}


ENVELOPE_SPECS = {
    "raise-alert": {"id": "alert-authority", "grant_ref": "grant-alert-authority", "executor": "occupancy-surveillance-agent",
                    "attester": "occupancy-quality-officer", "gate": NONE_GATE, "escalation": {"kind": "DECLARED_NONE"},
                    "conditions": [], "per_action": [limit("risk-score-bound", "raise-alert", "risk_score", "t.score", "1")]},
    "order-screening-labs": {"id": "protocol-labs-authority", "grant_ref": "grant-sepsis-protocol-v3", "executor": "occupancy-nurse-bedside-1",
                             "attester": "occupancy-quality-officer", "gate": NONE_GATE, "escalation": {"kind": "DECLARED_NONE"},
                             "conditions": [{"id": "screening-set-only", "step": "order-screening-labs",
                                             "predicate": {"kind": "EQUAL", "left": field_operand("panel"), "right": literal("t.text", "sepsis-screening-set")}}],
                             "per_action": [limit("test-count-bound", "order-screening-labs", "test_count", "t.count", "3")]},
    "page-attending": {"id": "page-authority", "grant_ref": "grant-page-authority", "executor": "occupancy-surveillance-agent",
                       "attester": "occupancy-quality-officer", "gate": NONE_GATE,
                       "escalation": {"kind": "REQUIRED", "destination_role": "rapid-response-team", "authority_ref": "escalation-authority",
                                      "decision_required": "rapid-response-acknowledgement"},
                       "conditions": [], "per_action": [limit("page-attempt-bound", "page-attending", "attempt_number", "t.count", "3")]},
    "escalate-rapid-response": {"id": "escalation-authority", "grant_ref": "grant-escalation-authority", "executor": "occupancy-surveillance-agent",
                                "attester": "occupancy-quality-officer", "gate": NONE_GATE, "escalation": {"kind": "DECLARED_NONE"},
                                "conditions": [], "per_action": [limit("escalation-attempt-bound", "escalate-rapid-response", "attempt_number", "t.count", "1")]},
    "assess-readiness": {"id": "assessment-authority", "grant_ref": "grant-assessment-authority", "executor": "occupancy-surveillance-agent",
                         "attester": "occupancy-quality-officer", "gate": NONE_GATE, "escalation": {"kind": "DECLARED_NONE"},
                         "conditions": [], "per_action": [limit("lookback-bound", "assess-readiness", "lookback_seconds", "t.seconds", "900")]},
    "refresh-vitals": {"id": "refresh-authority", "grant_ref": "grant-refresh-authority", "executor": "occupancy-surveillance-agent",
                       "attester": "occupancy-quality-officer", "gate": NONE_GATE, "escalation": {"kind": "DECLARED_NONE"},
                       "conditions": [], "per_action": [limit("refresh-attempt-bound", "refresh-vitals", "attempt_number", "t.count", "3")]},
    "order-antibiotic": {"id": "antibiotic-order-authority", "grant_ref": "grant-antibiotic-order-authority", "executor": "occupancy-attending-1",
                         "attester": "occupancy-pharmacist-1",
                         "gate": {"materiality": "HIGH", "reversibility": "LOW", "kind": "DECIDE", "role": "attending-physician",
                                  "criteria": [{"id": "cultures-first-or-override", "step": "order-antibiotic",
                                                "predicate": {"kind": "ANY", "operands": [
                                                    {"kind": "EQUAL", "left": field_operand("cultures_drawn_first"), "right": literal("t.boolean", True)},
                                                    {"kind": "NOT", "operand": {"kind": "EQUAL", "left": field_operand("override_reason"), "right": literal("t.text", "")}},
                                                ]}}]},
                         "escalation": {"kind": "DECLARED_NONE"}, "conditions": [],
                         "per_action": [limit("dose-bound", "order-antibiotic", "dose_mg", "t.dose", "2000")]},
}


def measurement_requirement(step_id: str) -> dict:
    return {"id": "current-vitals-" + step_id, "step": step_id, "purpose": "SAFETY_HOLD",
            "provider": "monitoring-feed", "source": "vitals-stream", "record_type": "current-vitals-measurement",
            "subject": {"kind": "PROPOSAL_FIELD", "field": "patient_id"}, "record_id": None,
            "at": "CLOCK", "freshness_seconds": "0", "expected_status": "AVAILABLE",
            "fields": [declared("measured_at", "t.instant"), declared("patient_id", "t.identity")],
            "relations": [
                {"id": "measurement-age", "kind": "ELAPSED_LTE", "left": "measured_at",
                 "right": {"kind": "CLOCK", "type_ref": "t.instant"}, "maximum_seconds": "900"},
                {"id": "measurement-patient", "kind": "EQUALS", "left": "patient_id",
                 "right": {"kind": "PROPOSAL_FIELD", "field": "patient_id"}},
            ]}


def standing_material(step_id: str) -> dict:
    """Envelope, root, capacities, occupancies, credential, standing acts and returns for one step."""
    step = STEP[step_id]
    spec = ENVELOPE_SPECS[step_id]
    subject_field = step["scope_fields"]["subjects"][0]
    resource_field = step["scope_fields"]["resources"][0]
    bindings = sorted([
        {"id": f"{spec['id']}-subject-binding", "step": step_id, "field": subject_field, "type_ref": "t.identity"},
        {"id": f"{spec['id']}-resource-binding", "step": step_id, "field": resource_field, "type_ref": "t.identity"},
    ], key=lambda row: utf8(row["id"]))
    envelope = {
        "schema": SCHEMA + "authority-envelope", "id": spec["id"], "source_digest": SOURCE_DIGEST,
        "work_class_digest": AUTHORITY_WORK_CLASS_DIGEST, "source_obligations": SOURCE_IDS, "principal": ORG,
        "grantor_role": "medical-director", "executor_role": step["executor_role"],
        "attester_role": OCCUPANCIES[spec["attester"]]["role"], "grant_ref": spec["grant_ref"], "clock_source": CLOCK_SOURCE,
        "bindings": bindings,
        "scope": {"id": f"{spec['id']}-scope",
                  "subjects": [{"kind": "BINDING", "binding": f"{spec['id']}-subject-binding"}],
                  "resources": [{"kind": "BINDING", "binding": f"{spec['id']}-resource-binding"}]},
        "operations": [{"step": step_id, "operation": step["operation"], "interface": step["interface"]}],
        "limits": {"per_action": sorted(spec["per_action"], key=lambda row: utf8(row["id"])), "shared_budgets": []},
        "conditions": spec["conditions"],
        "enforcement": {"mechanisms": ["AUTHORITY_BEFORE_RESERVATION"], "safe_state": "NO_NEW_DISPATCH", "out_of_envelope": "REFUSE"},
        "escalation": spec["escalation"], "revocation": REVOCATION, "temporal_validity": VALIDITY,
        "gate": spec["gate"], "limitations": [],
    }
    if step_id in ("assess-readiness", "order-antibiotic"):
        envelope["source_observation_requirements"] = [measurement_requirement(step_id)]
    envelope_digest = digest("authority-envelope", envelope)
    grantor_capacity_id = f"capacity-{spec['id']}-grantor"
    attester_capacity_id = f"capacity-{spec['id']}-attester"
    capacity_ids = [attester_capacity_id, grantor_capacity_id]
    occupancy_ids = ["occupancy-medical-director", spec["attester"], spec["executor"]]
    if spec["gate"]["kind"] == "DECIDE":
        capacity_ids.append(f"capacity-{spec['id']}-decision")
        # The deciding attending also executes the order; one occupancy serves both roles.
    root = {
        "schema": SCHEMA + "authority-root", "id": f"root-{spec['id']}", "revision": "1", "designator": "hospital-authority-office",
        "principal": ORG, "source_digest": SOURCE_DIGEST, "work_class_digest": AUTHORITY_WORK_CLASS_DIGEST,
        "envelope_digest": envelope_digest, "capacity_ids": sorted(capacity_ids, key=utf8),
        "occupancy_ids": sorted(set(occupancy_ids), key=utf8),
        "providers": sorted({PROVIDER, *(row["provider"] for row in envelope.get("source_observation_requirements", []))}, key=utf8),
        "channels": [{"id": CHANNEL, "provider": PROVIDER, "validity": VALIDITY, "prior_returns_survive_expiry": False}],
        "validity": VALIDITY, "revocation": REVOCATION, "prior_acts_survive_expiry": False, "allow_self_attestation": False,
        "limitations": [],
    }
    root_digest = digest("authority-root", root)

    def capacity(capacity_id, occupancy_id, act_kinds):
        row = OCCUPANCIES[occupancy_id]
        return {"id": capacity_id, "root_digest": root_digest, "envelope_digest": envelope_digest, "actor": row["actor"],
                "role": row["role"], "principal": ORG, "occupancy": occupancy_id, "act_kinds": act_kinds, "validity": VALIDITY,
                "revocation": REVOCATION, "reliance": {"kind": "CURRENT_ONLY"}, "may_self_attest": False, "provider": PROVIDER,
                "evidence_ref": capacity_id + "-evidence"}

    capacities = [capacity(attester_capacity_id, spec["attester"], ["ORGANISATIONAL_ATTESTATION"]),
                  capacity(grantor_capacity_id, "occupancy-medical-director", ["GRANT"])]
    if spec["gate"]["kind"] == "DECIDE":
        capacities.append(capacity(f"capacity-{spec['id']}-decision", spec["executor"], ["INSTANCE_DECISION"]))
    capacities.sort(key=lambda row: utf8(row["id"]))
    occupancies = sorted([occupancy_record(i) for i in root["occupancy_ids"]], key=lambda row: utf8(row["id"]))
    executor_row = OCCUPANCIES[spec["executor"]]
    credential = {"id": f"credential-{step_id}", "actor": executor_row["actor"], "occupancy": spec["executor"],
                  "kind": step["required_credentials"][0], "step": step_id, "operation": step["operation"],
                  "interface": step["interface"], "validity": VALIDITY, "revocation": REVOCATION, "provider": PROVIDER,
                  "evidence_ref": f"credential-{step_id}-evidence"}
    grant = act(spec["grant_ref"], "GRANT", "occupancy-medical-director", grantor_capacity_id, GRANT_AT, envelope_digest, None, [])
    attestation = act(f"attest-{spec['grant_ref']}", "ORGANISATIONAL_ATTESTATION", spec["attester"], attester_capacity_id, ATTEST_AT,
                      digest("authority-act", grant), "person-medical-director", [])
    return {"spec": spec, "envelope": envelope, "envelope_digest": envelope_digest, "root": root, "root_digest": root_digest,
            "capacities": capacities, "occupancies": occupancies, "credential": credential,
            "standing_acts": [grant, attestation], "attester_capacity_id": attester_capacity_id,
            "decision_capacity_id": f"capacity-{spec['id']}-decision"}


def act(act_id, kind, occupancy_id, capacity_id, occurred_at, subject_digest, attested_actor, criteria):
    row = OCCUPANCIES[occupancy_id]
    return {"id": act_id, "kind": kind, "actor": row["actor"], "role": row["role"], "principal": ORG, "occupancy": occupancy_id,
            "capacity": capacity_id, "recorder": "authority-recorder", "occurred_at": occurred_at, "disposition": "ACCEPT",
            "subject_digest": subject_digest, "attested_actor": attested_actor, "criteria": criteria}


def act_return(act_row: dict) -> dict:
    return {"id": f"return-{act_row['id']}", "actor": act_row["actor"], "provider": PROVIDER, "channel": CHANNEL,
            "act_digest": digest("authority-act", act_row), "act_bytes_base64": base64.b64encode(canonical_bytes(act_row)).decode(),
            "returned_at": act_row["occurred_at"], "evidence_ref": f"return-{act_row['id']}-evidence"}


MATERIAL = {step["id"]: standing_material(step["id"]) for step in PROPOSAL_STEPS}


def authority_case(step_id, occurrence_id, proposal_fields, now, *, decision=None, include_gate_acts=True,
                   revoked_subjects=(), expect_refusal=None, measured_at=None):
    """Complete authority input and its derived result for one proposal.

    decision: {"at": instant, "attested_at": instant} for a DECIDE envelope. expect_refusal: (code, reasons) derived in
    DERIVATIONS.md when the input is meant to be withheld; None means READY_FOR_RESERVATION.
    """
    material = MATERIAL[step_id]
    spec, envelope, root = material["spec"], material["envelope"], material["root"]
    envelope_digest, root_digest = material["envelope_digest"], material["root_digest"]
    step = STEP[step_id]
    executor = executor_for(spec["executor"])
    proposal = {"schema": SCHEMA + "authority-proposal", "work_class_digest": AUTHORITY_WORK_CLASS_DIGEST, "work_class": WORK_CLASS["id"],
                "instance": INSTANCE, "occurrence": occurrence_id, "step": step_id, "operation": step["operation"],
                "interface": step["interface"], "executor": executor, "fields": fields_sorted(proposal_fields)}
    proposal_digest = digest("authority-proposal", proposal)
    operation_digest = digest("authority-operation", {"envelope_digest": envelope_digest, "work_class_digest": AUTHORITY_WORK_CLASS_DIGEST,
                                                      "proposal_digest": proposal_digest})
    acts = list(material["standing_acts"])
    if spec["gate"]["kind"] == "DECIDE" and include_gate_acts:
        criteria_ids = [row["id"] for row in spec["gate"]["criteria"]]
        decision_act = act(f"order-decision-{occurrence_id[7:19]}-{decision['at'][11:16].replace(':', '')}-{decision.get('tag', 'a')}",
                           "INSTANCE_DECISION", spec["executor"], material["decision_capacity_id"], decision["at"], operation_digest, None, criteria_ids)
        decision_attestation = act(f"verify-{decision_act['id']}", "ORGANISATIONAL_ATTESTATION", spec["attester"], material["attester_capacity_id"],
                                   decision["attested_at"], digest("authority-act", decision_act), OCCUPANCIES[spec["executor"]]["actor"], [])
        acts.extend([decision_act, decision_attestation])
    acts = sorted(acts, key=lambda row: utf8(digest("authority-act", row)))
    returns = sorted([act_return(row) for row in acts], key=lambda row: utf8(row["id"]))
    capacity_by_id = {row["id"]: row for row in material["capacities"]}
    credential = material["credential"]

    queries = []

    def add_query(subject_digest, at):
        query = {"purpose": "REVOCATION", "subject_digest": subject_digest, "at": at, "provider": PROVIDER, "source": REVOCATION_SOURCE}
        if query not in queries:
            queries.append(query)

    for row in acts:
        add_query(root_digest, row["occurred_at"])
    add_query(root_digest, now)
    for row in acts:
        capacity_digest = digest("authority-capacity", capacity_by_id[row["capacity"]])
        add_query(capacity_digest, row["occurred_at"])
        add_query(capacity_digest, now)
    add_query(envelope_digest, now)
    add_query(digest("authority-credential", credential), now)
    observations = []
    for index, query in enumerate(queries, 1):
        observations.append({"query": query, "query_digest": digest("authority-query", query), "status": "AVAILABLE", "as_of": query["at"],
                             "revision": f"revocation-rev-{index}", "revoked": query["subject_digest"] in revoked_subjects,
                             "evidence_ref": f"revocation-{spec['id']}-{index}"})
    source_checks = []
    for requirement in envelope.get("source_observation_requirements", []):
        patient = next(row["value"]["value"] for row in proposal["fields"] if row["name"] == "patient_id")
        measured_at = measured_at or plus_seconds(now, -900 if step_id == "assess-readiness" else -120)
        query = {"requirement_id": requirement["id"], **{name: copy.deepcopy(requirement[name]) for name in
                 ("step", "provider", "source", "record_type", "record_id", "purpose", "freshness_seconds", "expected_status", "fields", "relations")},
                 "at": now, "subject": patient}
        query_digest = digest("authority-query", query)
        observations.append({"query": query, "query_digest": query_digest, "status": "AVAILABLE", "as_of": now,
                             "revision": "vitals-measurement-r1", "provider_record_id": "current-vitals-" + patient,
                             "fields": [field("measured_at", "t.instant", measured_at), field("patient_id", "t.identity", patient)],
                             "relations": copy.deepcopy(requirement["relations"]), "evidence_ref": "current-vitals-evidence-" + step_id,
                             "provenance_digest": digest("specimen-vitals-provenance", {"query_digest": query_digest, "measured_at": measured_at})})
        source_checks.append({"purpose": "SOURCE_OBSERVATION", "subject_digest": envelope_digest,
                              "requirement_ref": requirement["id"], "at": now})
    authenticated = []
    for row in material["occupancies"]:
        authenticated.append({"kind": "OCCUPANCY", "record_digest": digest("authority-occupancy", row), "provider": PROVIDER, "channel": None})
    for row in material["capacities"]:
        authenticated.append({"kind": "CAPACITY", "record_digest": digest("authority-capacity", row), "provider": PROVIDER, "channel": None})
    authenticated.append({"kind": "CREDENTIAL", "record_digest": digest("authority-credential", credential), "provider": PROVIDER, "channel": None})
    for row in returns:
        authenticated.append({"kind": "RETURN", "record_digest": digest("authority-return", row), "provider": PROVIDER, "channel": CHANNEL})
    host_selection = {"root": root, "selection_evidence": f"root-selection-{spec['id']}", "authenticated_records": sorted_utf8(authenticated)}
    clock = {"source": CLOCK_SOURCE, "status": "AVAILABLE", "instant": now}
    authority_input = {"schema": SCHEMA + "authority-input", "specification_pin": PIN, "source": AUTHORITY_SOURCE,
                       "work_class": AUTHORITY_WORK_CLASS, "envelope": envelope, "proposal": proposal, "clock": clock,
                       "host_selection": host_selection, "occupancies": material["occupancies"], "capacities": material["capacities"],
                       "credentials": [credential], "acts": acts, "returns": returns, "observations": observations}
    checks = [
        {"purpose": "SOURCE_BINDING", "subject_digest": envelope_digest, "requirement_ref": AUTHORITY_SOURCE["id"], "at": now},
        {"purpose": "ROOT_BINDING", "subject_digest": envelope_digest, "requirement_ref": root["id"], "at": now},
        {"purpose": "INPUT_SUPPORT", "subject_digest": operation_digest, "requirement_ref": step_id, "at": now},
        {"purpose": "BINDING", "subject_digest": operation_digest, "requirement_ref": envelope["scope"]["id"], "at": now},
        {"purpose": "GATE_FLOOR", "subject_digest": envelope_digest, "requirement_ref": envelope["id"], "at": now},
        {"purpose": "ENVELOPE_VALIDITY", "subject_digest": envelope_digest, "requirement_ref": envelope["id"], "at": now},
        {"purpose": "EXECUTOR_OCCUPANCY", "subject_digest": operation_digest, "requirement_ref": executor["occupancy"], "at": now},
        {"purpose": "CREDENTIAL", "subject_digest": operation_digest, "requirement_ref": credential["id"], "at": now},
    ]
    for row in envelope["conditions"]:
        checks.append({"purpose": "CONDITION", "subject_digest": operation_digest, "requirement_ref": row["id"], "at": now})
    for row in envelope["limits"]["per_action"]:
        checks.append({"purpose": "PER_ACTION_LIMIT", "subject_digest": operation_digest, "requirement_ref": row["id"], "at": now})
    return_by_act = {row["act_digest"]: row for row in returns}
    for row in acts:
        act_digest = digest("authority-act", row)
        checks.extend([
            {"purpose": "ACT_CAPACITY", "subject_digest": act_digest, "requirement_ref": row["capacity"], "at": row["occurred_at"]},
            {"purpose": "ACT_OCCUPANCY", "subject_digest": act_digest, "requirement_ref": row["occupancy"], "at": row["occurred_at"]},
            {"purpose": "ACT_RELIANCE", "subject_digest": act_digest, "requirement_ref": row["capacity"], "at": now},
            {"purpose": "RETURN", "subject_digest": act_digest, "requirement_ref": return_by_act[act_digest]["id"], "at": now},
        ])
        if row["kind"] == "ORGANISATIONAL_ATTESTATION":
            checks.append({"purpose": "SEPARATION", "subject_digest": act_digest, "requirement_ref": row["capacity"], "at": now})
        if row["kind"] == "INSTANCE_DECISION":
            for criterion in spec["gate"]["criteria"]:
                checks.append({"purpose": "GATE_CRITERION", "subject_digest": act_digest, "requirement_ref": criterion["id"], "at": row["occurred_at"]})
    for query in queries:
        checks.append({"purpose": "REVOCATION", "subject_digest": query["subject_digest"], "requirement_ref": digest("authority-query", query), "at": query["at"]})
    checks = sorted_utf8(checks + source_checks)
    if expect_refusal is not None:
        # failures: (exact field match identifying one constructed check, the one reason it contributes) per DERIVATIONS.md.
        code, failures = expect_refusal
        failed_checks = []
        for match, reason in failures:
            selected = [row for row in checks if all(row[key] == value for key, value in match.items())]
            if len(selected) != 1:
                raise ValueError(f"failed check {match} selects {len(selected)} constructed checks")
            failed_checks.append({**selected[0], "reason": reason})
        result = {"status": "REFUSED", "code": code, "path": "", "reasons": sorted({reason for _, reason in failures}, key=utf8),
                  "failed_checks": sorted_utf8(failed_checks)}
        return {"input": authority_input, "result": result, "result_digest": digest("authority-result", result), "ready": False,
                "executor": executor, "proposal": proposal}
    subject_value = next(f["value"]["value"] for f in proposal["fields"] if f["name"] == step["scope_fields"]["subjects"][0])
    resource_value = next(f["value"]["value"] for f in proposal["fields"] if f["name"] == step["scope_fields"]["resources"][0])
    evidence_subject = {"host_selection": host_selection, "occupancies": material["occupancies"], "capacities": material["capacities"],
                        "credentials": [credential], "acts": acts, "returns": returns, "observations": observations, "clock": clock}
    result = {"schema": SCHEMA + "authority-result", "specification_pin": PIN, "status": "READY_FOR_RESERVATION",
              "source_digest": SOURCE_DIGEST, "work_class_digest": AUTHORITY_WORK_CLASS_DIGEST, "envelope_digest": envelope_digest,
              "proposal_digest": proposal_digest, "operation_digest": operation_digest,
              "scope": {"subjects": [subject_value], "resources": [resource_value]},
              "actual_scope": {"subjects": [subject_value], "resources": [resource_value]},
              "act_digests": sorted([digest("authority-act", row) for row in acts], key=utf8), "checks": checks,
              "required_budgets": [], "evidence_digest": digest("authority-evidence", evidence_subject)}
    return {"input": authority_input, "result": result, "result_digest": digest("authority-result", result), "ready": True,
            "executor": executor, "proposal": proposal, "acts": acts}


# ---------------------------------------------------------------------------
# Lifecycle constructions (LIFECYCLE.md, COMPOSITION.md)
# ---------------------------------------------------------------------------

def occurrence(step_id: str, ordinal: str, predecessors: list[str], enclosing: list[dict]) -> dict:
    subject = {"specification_pin": PIN, "work_class_digest": DEFINITION_DIGEST, "instance_id": INSTANCE, "step_id": step_id,
               "ordinal": ordinal, "predecessor_occurrence_ids": sorted(predecessors, key=utf8), "enclosing": enclosing, "object_key": None}
    return {"occurrence_id": digest("occurrence", subject), **subject}


def branch_segment(branch_id: str) -> dict:
    return {"kind": "BRANCH", "construct_id": "hour-one-bundle", "pass": "1", "branch_id": branch_id, "object_key": None}


def loop_segment(pass_number: str) -> dict:
    return {"kind": "LOOP", "construct_id": "vitals-reassessment", "pass": pass_number, "branch_id": None, "object_key": None}


def obligation(branch_id: str, source_ids: list[str], creation_event_digest: str, expected: dict) -> dict:
    subject = {"kind": "PARALLEL_BRANCH", "construct_id": "hour-one-bundle", "pass": "1", "source_occurrence_ids": sorted(source_ids, key=utf8),
               "branch_id": branch_id, "object_key": None, "join_step_id": "bundle-join"}
    return {"obligation_id": digest("obligation", subject), **subject, "creation_event_digest": creation_event_digest, "status": "OPEN",
            "expected_occurrence_id": expected["occurrence_id"], "required_operation": STEP[expected["step_id"]]["operation"],
            "waiting_on": None, "completion_basis": None}


def discharge(row: dict, event_digest: str, occurrence_row: dict, evidence_digest: str) -> None:
    row["status"] = "DISCHARGED"
    row["expected_occurrence_id"] = None
    row["required_operation"] = None
    row["completion_basis"] = {"kind": "DIRECT_EVENT", "event_digest": event_digest, "occurrence_id": occurrence_row["occurrence_id"],
                               "operation": STEP[occurrence_row["step_id"]]["operation"], "evidence_digest": evidence_digest}


def anchor_occurred_at(state: dict, occurrence_row: dict, anchor_step_id: str) -> str:
    """COMPOSITION 5.1: the one completed anchor occurrence in the recursive predecessor closure."""
    rows = {row["occurrence"]["occurrence_id"]: row for row in state["active"] + state["completed"]}
    seen, pending, anchors = set(), list(occurrence_row["predecessor_occurrence_ids"]), []
    while pending:
        occurrence_id = pending.pop()
        if occurrence_id in seen:
            continue
        seen.add(occurrence_id)
        row = rows[occurrence_id]
        pending.extend(row["occurrence"]["predecessor_occurrence_ids"])
        if row["occurrence"]["step_id"] == anchor_step_id and "disposition" in row:
            anchors.append(row)
    if len(anchors) != 1:
        raise ValueError(f"anchor {anchor_step_id} is not unique in the closure of {occurrence_row['step_id']}")
    return anchors[0]["occurred_at"]


def deadline_state(state: dict, deadline_id: str, occurrence_row: dict, trigger_digest: str, activation_revision: str, clock: dict) -> dict:
    declared_deadline = DEADLINE[deadline_id]
    due_seconds = int(declared_deadline["due"]["value"]) * DEADLINE_SECONDS[declared_deadline["due"]["unit"]]
    if declared_deadline["due"]["kind"] == "ELAPSED_FROM_ANCESTOR":
        due = plus_seconds(anchor_occurred_at(state, occurrence_row, declared_deadline["due"]["anchor_step_id"]), due_seconds)
    else:
        due = plus_seconds(clock["observed_time"], due_seconds)
    subject = {"deadline_id": deadline_id, "occurrence_id": occurrence_row["occurrence_id"], "trigger_digest": trigger_digest,
               "source": declared_deadline["clock_source"], "activation_revision": activation_revision,
               "activation_clock_revision": clock["revision"], "activation_instant": clock["observed_time"],
               "activation_clock_evidence_digest": clock["evidence_digest"], "due": due, "boundary": declared_deadline["boundary"]}
    return {"deadline_id": deadline_id, "occurrence_id": occurrence_row["occurrence_id"], "source": declared_deadline["clock_source"],
            "activation_revision": activation_revision, "activation_digest": digest("deadline-activation", subject),
            "trigger_digest": trigger_digest, "activation_clock_revision": clock["revision"], "activation_instant": clock["observed_time"],
            "activation_clock_evidence_digest": clock["evidence_digest"], "due": due, "boundary": declared_deadline["boundary"],
            "status": "PENDING", "expiry_event_digest": None}


def sort_state(state: dict) -> None:
    state["active"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
    state["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
    state["obligations"].sort(key=lambda row: utf8(row["obligation_id"]))
    state["proposals"].sort(key=lambda row: utf8(row["event_id"]))
    state["permits"].sort(key=lambda row: utf8(row["permit_id"]))
    state["dispatches"].sort(key=lambda row: utf8(row["dispatch_digest"]))
    state["outcomes"].sort(key=lambda row: utf8(row["outcome_digest"]))
    state["clocks"].sort(key=lambda row: (utf8(row["source"]), int(row["revision"])))
    occurrence_records = {row["occurrence"]["occurrence_id"]: row["occurrence"] for row in state["active"] + state["completed"]}
    state["deadlines"].sort(key=lambda row: (utf8(row["due"]), canonical_bytes(occurrence_records[row["occurrence_id"]]), utf8(row["deadline_id"])))
    state["event_duties"].sort(key=lambda row: utf8(row["deadline_id"]))
    state["deferred_deadlines"].sort(key=lambda row: (canonical_bytes(occurrence_records[row["occurrence_id"]]), utf8(row["deadline_id"])))
    state["timing_clock_events"].sort(key=lambda row: utf8(row["event_id"]))
    state["step_counters"].sort(key=lambda row: utf8(row["step_id"]))
    state["replays"].sort(key=lambda row: utf8(row["event_id"]))


def active_row(state: dict, occurrence_id: str) -> dict:
    return next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == occurrence_id)


def counter(state: dict, step_id: str) -> dict:
    return next(row for row in state["step_counters"] if row["step_id"] == step_id)


def activate(state: dict, occurrence_row: dict, event_digest: str, clock: dict | None, activation_revision: str) -> None:
    """Create one active occurrence, its counters and its deadline record under LIFE-014."""
    deadline = DEADLINE_BY_STEP.get(occurrence_row["step_id"])
    state["active"].append({"occurrence": occurrence_row, "activation_event_digest": event_digest, "status": "ACTIVE",
                            "deadline_ids": [deadline["id"]] if deadline else []})
    counter(state, occurrence_row["step_id"])["activations"] = str(int(counter(state, occurrence_row["step_id"])["activations"]) + 1)
    state["total_activations"] = str(int(state["total_activations"]) + 1)
    if deadline:
        if deadline["due"]["kind"] == "ELAPSED_FROM_EVENT_ANCHOR":
            duty = next(row for row in state["event_duties"] if row["deadline_id"] == deadline["id"])
            duty.update(occurrence_id=occurrence_row["occurrence_id"], binding_event_digest=event_digest)
        elif deadline["due"]["kind"] == "ELAPSED_FROM_FIRST_DISPATCH":
            subject = {"specification_pin": PIN, "work_class_digest": DEFINITION_DIGEST, "instance_id": INSTANCE,
                       "deadline_id": deadline["id"], "occurrence_id": occurrence_row["occurrence_id"], "activation_event_digest": event_digest}
            state["deferred_deadlines"].append({"deadline_id": deadline["id"], "occurrence_id": occurrence_row["occurrence_id"],
                                               "source": deadline["clock_source"], "boundary": deadline["boundary"],
                                               "activation_event_digest": event_digest, "creation_digest": digest("deferred-deadline", subject),
                                               "status": "WAITING"})
        else:
            state["deadlines"].append(deadline_state(state, deadline["id"], occurrence_row, event_digest, activation_revision, clock))


def close(state: dict, occurrence_row: dict, disposition: str, evidence_digest: str, occurred_at: str, route_label, relationship_ref, late: bool = False,
          completion_event_digest=None) -> None:
    state["active"] = [row for row in state["active"] if row["occurrence"]["occurrence_id"] != occurrence_row["occurrence_id"]]
    state["completed"].append({"occurrence": occurrence_row, "disposition": disposition, "evidence_digest": evidence_digest,
                               "occurred_at": occurred_at, "route_label": route_label, "selected_relationship_digest": relationship_ref, "late": late})
    for row in state["deadlines"]:
        if row["occurrence_id"] == occurrence_row["occurrence_id"] and row["status"] == "PENDING":
            row["status"] = "DISCHARGED"
    if disposition == "SUCCEEDED":
        for row in state["event_duties"] + state["deferred_deadlines"]:
            if row.get("occurrence_id") == occurrence_row["occurrence_id"] and row["status"] in ("PENDING", "WAITING"):
                if completion_event_digest is None:
                    raise ValueError("a timing discharge needs its exact completion event")
                row["status"] = "DISCHARGED"
                row["discharge_basis"] = {"kind": "COMPLETION", "event_digest": completion_event_digest,
                                          "occurrence_id": occurrence_row["occurrence_id"], "evidence_digest": evidence_digest}


def expire_deadline(state: dict, deadline_id: str, occurrence_id: str, event_digest: str) -> None:
    for row in state["deadlines"]:
        if row["deadline_id"] == deadline_id and row["occurrence_id"] == occurrence_id:
            row["status"] = "EXPIRED"
            row["expiry_event_digest"] = event_digest


def work_state_digest(state: dict) -> str:
    projected = copy.deepcopy(state)
    for replay in projected["replays"]:
        replay.pop("transaction_digest")
    return digest("work-state", projected)


def work_transition(before: dict, event: dict, *, disposition: str, reason_codes: list, details: list, permit, authority_result_digest=None, mutate=None):
    event_digest = digest("runtime-event", event)
    after = copy.deepcopy(before)
    after["revision"] = str(int(before["revision"]) + 1)
    if mutate:
        mutate(after, event_digest)
    sort_state(after)
    core = copy.deepcopy(after)
    core["receipts"] = []
    core["replays"] = []
    core_digest = digest("work-state-core", core)
    receipt = {
        "schema": SCHEMA + "decision-receipt", "decision_id": "sha256:" + "0" * 64, "instance_id": INSTANCE, "sequence": after["revision"],
        "event_id": event["event_id"], "event_digest": event_digest, "event_kind": event["kind"], "disposition": disposition,
        "reason_codes": sorted(reason_codes, key=utf8), "details": details,
        "permit_digest": permit["permit_id"] if permit else (event.get("permit") or {}).get("permit_id"),
        "authority_result_digest": authority_result_digest, "reservation_receipt_digests": [],
        "state_before_digest": work_state_digest(before), "state_after_core_digest": core_digest,
    }
    receipt["decision_id"] = digest("decision-receipt", omit(receipt, "decision_id"))
    transaction_digest = digest("lifecycle-transaction", {"state_before_digest": receipt["state_before_digest"], "event_digest": event_digest,
                                                          "decision_receipt_digest": receipt["decision_id"], "state_after_core_digest": core_digest,
                                                          "budget_results": []})
    after["receipts"].append(receipt)
    after["replays"].append({"event_id": event["event_id"], "event_digest": event_digest, "decision": receipt, "decision_receipt_digest": receipt["decision_id"],
                             "permit": permit, "budget_results": [], "transition_state_digest": core_digest, "transaction_digest": transaction_digest})
    after["replays"].sort(key=lambda row: utf8(row["event_id"]))
    result = {"status": "STEP", "profile": PROFILE, "role": ROLE, "decision": receipt, "decision_digest": receipt["decision_id"], "permit": permit,
              "budget_results": [], "state": after, "state_digest": work_state_digest(after), "transition_state_digest": core_digest,
              "transaction_digest": transaction_digest, "replay": False}
    return after, result


def step_request(request_id: str, state: dict, event: dict) -> dict:
    return {"protocol": PROTOCOL, "request_id": request_id, "operation": "step",
            "input": {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": WORK_CLASS, "definition_digest": DEFINITION_DIGEST,
                      "state": state, "state_digest": work_state_digest(state), "event": event}}


def response(request: dict, result: dict) -> dict:
    return {"protocol": PROTOCOL, "request_id": request["request_id"], "operation": request["operation"], "result": result}


def event_header(event_id: str, kind: str, state: dict) -> dict:
    return {"schema": SCHEMA + "runtime-event", "event_id": event_id, "kind": kind, "instance_id": INSTANCE,
            "expected_state_revision": state["revision"], "expected_state_digest": work_state_digest(state)}


def latest_clock(state: dict) -> dict:
    return max((row for row in state["clocks"] if row["source"] == CLOCK_SOURCE and row["status"] == "AVAILABLE"), key=lambda row: int(row["revision"]))


def clock_step(state: dict, event_id: str, revision: str, instant: str | None, *, status="AVAILABLE"):
    """Fixed specimen clock consequences, including the two declared expiry responses."""
    clock = clock_record(revision, instant)
    clock["status"] = status
    event = {**event_header(event_id, "CLOCK", state), "clock": clock, "activation_clocks": []}
    occurrences = {row["occurrence"]["occurrence_id"]: row["occurrence"] for row in state["active"] + state["completed"]}
    due = []
    if status == "AVAILABLE":
        due = [row for row in state["event_duties"] + state["deferred_deadlines"]
               if row["status"] == "PENDING" and row["source"] == CLOCK_SOURCE and row["due"] <= instant]
    due.sort(key=lambda row: (utf8(row["due"]), row.get("occurrence_id") is None,
                             canonical_bytes(occurrences[row["occurrence_id"]]) if row.get("occurrence_id") else canonical_bytes({"step_id": row["target_step_id"]}),
                             utf8(row["deadline_id"])))
    eligible = []
    if state["status"] == "ACTIVE":
        for row in due:
            active = next((active for active in state["active"] if active["occurrence"]["occurrence_id"] == row.get("occurrence_id")), None)
            if active and active["status"] not in ("BLOCKED_DISPUTE", "WAITING_CHILDREN"):
                eligible.append(row)
    stopped = any(DEADLINE[row["deadline_id"]]["expiry_target"] is None for row in eligible)
    reasons = ["EXPIRY_STOP"] if stopped else (["CLOCK_UNAVAILABLE"] if status != "AVAILABLE" else [])
    details = [{"kind": "CLOCK", "source": CLOCK_SOURCE, "revision": revision, "status": status}]
    if due:
        details.append({"kind": "DEADLINE", "deadline_ids": sorted({row["deadline_id"] for row in due}, key=utf8), "reasons": ["EXPIRY_STOP"] if stopped else []})
    if not stopped and any(DEADLINE[row["deadline_id"]]["expiry_target"] for row in eligible):
        details.append(route_detail([relationship_digest("EXPIRY", "page-attending", "escalate-rapid-response")], []))

    def mutate(after, event_digest):
        after["clocks"].append(clock)
        after["timing_clock_events"].append(copy.deepcopy(event))
        for before_row in due:
            row = next(row for row in after["event_duties"] + after["deferred_deadlines"]
                       if row["deadline_id"] == before_row["deadline_id"] and row.get("occurrence_id") == before_row.get("occurrence_id"))
            row.update(status="EXPIRED", expiry_basis={"kind": "CLOCK", "event_digest": event_digest, "clock": copy.deepcopy(clock)})
        for row in eligible:
            occurrence_row = occurrences[row["occurrence_id"]]
            target = DEADLINE[row["deadline_id"]]["expiry_target"]
            relationship_ref = relationship_digest("EXPIRY", occurrence_row["step_id"], target) if target and not stopped else None
            close(after, occurrence_row, "EXPIRED", clock["evidence_digest"], instant, None, relationship_ref)
            if target and not stopped:
                escalation = occurrence(target, "1", [occurrence_row["occurrence_id"]], [branch_segment("page")])
                activate(after, escalation, event_digest, None, after["revision"])
                branch = next(item for item in after["obligations"] if item["branch_id"] == "page")
                branch.update(expected_occurrence_id=escalation["occurrence_id"], required_operation=STEP[target]["operation"])
            if stopped:
                for branch in after["obligations"]:
                    if branch["status"] in ("OPEN", "BLOCKED") and branch["expected_occurrence_id"] == occurrence_row["occurrence_id"]:
                        discharge(branch, event_digest, occurrence_row, clock["evidence_digest"])
        if stopped:
            after["status"] = "STOPPED"

    disposition = "STOPPED" if stopped else ("EXPIRED" if due else "CLOCK_RECORDED")
    after, result = work_transition(state, event, disposition=disposition, reason_codes=reasons, details=details, permit=None, mutate=mutate)
    return after, result, event


def propose(state: dict, event_id: str, occurrence_row: dict, proposal_fields: list, authority, *, initial_actuation=True):
    """PROPOSE under LIFE-007 and LIFE-008. authority is an authority_case() record."""
    step = STEP[occurrence_row["step_id"]]
    clock = latest_clock(state)
    assert clock["observed_time"] == authority["input"]["clock"]["instant"]
    native_request = {"interface": step["interface"], "operation": step["operation"], "fields": fields_sorted(proposal_fields)}
    lifecycle_executor = {"participant_id": authority["executor"]["actor"], "role": authority["executor"]["role"],
                          "binding_digest": digest("executor-binding", authority["executor"])}
    observation_digests = sorted([digest("authority-observation", row) for row in authority["input"]["observations"]], key=utf8)
    event = {**event_header(event_id, "PROPOSE", state), "occurrence": occurrence_row, "native_request": native_request,
             "executor": lifecycle_executor, "credential_ids": [authority["input"]["credentials"][0]["id"]], "authority_input": authority["input"],
             "budget_inputs": [], "clock_revision": clock["revision"], "observation_digests": observation_digests}
    proposal_digest = digest("proposal", event)
    if not authority["ready"]:
        refusal = authority["result"]

        def mutate_withheld(after, event_digest):
            after["proposals"].append({"event_id": event_id, "event_digest": event_digest, "proposal_digest": proposal_digest,
                                       "occurrence_id": occurrence_row["occurrence_id"], "disposition": "WITHHELD", "permit_digest": None,
                                       "authority_result_digest": authority["result_digest"], "reservation_receipt_digests": [], "prior_permit_digest": None})

        reason_codes = sorted({"AUTHORITY_REQUIRED", refusal["code"], *refusal["reasons"]}, key=utf8)
        details = [{"kind": "AUTHORITY", "authority_result_digest": authority["result_digest"], "code": refusal["code"], "reasons": refusal["reasons"],
                    "failed_checks": refusal["failed_checks"]}]
        after, result = work_transition(state, event, disposition="WITHHELD", reason_codes=reason_codes, details=details, permit=None,
                                        authority_result_digest=authority["result_digest"], mutate=mutate_withheld)
        return after, result, event, None
    act_bases = sorted([{"act_digest": digest("authority-act", row), "act": row} for row in authority["acts"]], key=lambda row: utf8(row["act_digest"]))
    permit = {"schema": SCHEMA + "permit", "permit_id": "sha256:" + "0" * 64, "instance_id": INSTANCE, "work_class_digest": DEFINITION_DIGEST,
              "profile": PROFILE, "role": ROLE, "occurrence": occurrence_row, "proposal_digest": proposal_digest, "native_request": native_request,
              "executor": lifecycle_executor, "credential_ids": event["credential_ids"], "authority_result": authority["result"],
              "authority_result_digest": authority["result_digest"], "authority_evidence_digest": authority["result"]["evidence_digest"],
              "authority_act_bases": act_bases, "prior_effect_bases": [], "separation_bases": [], "observation_digests": observation_digests,
              "supersedes_permit_digest": None, "budget_revisions": [], "clock_source": CLOCK_SOURCE, "clock_revision": clock["revision"],
              "expires_at": plus_seconds(clock["observed_time"], int(step["permit_seconds"]))}
    permit["permit_id"] = digest("permit", omit(permit, "permit_id"))

    def mutate_permitted(after, event_digest):
        active_row(after, occurrence_row["occurrence_id"])["status"] = "PERMITTED"
        if initial_actuation:
            counter(after, step["id"])["actuations"] = str(int(counter(after, step["id"])["actuations"]) + 1)
            after["total_actuations"] = str(int(after["total_actuations"]) + 1)
        after["proposals"].append({"event_id": event_id, "event_digest": event_digest, "proposal_digest": proposal_digest,
                                   "occurrence_id": occurrence_row["occurrence_id"], "disposition": "PERMITTED", "permit_digest": permit["permit_id"],
                                   "authority_result_digest": authority["result_digest"], "reservation_receipt_digests": [], "prior_permit_digest": None})
        after["permits"].append(permit)

    after, result = work_transition(state, event, disposition="PERMITTED", reason_codes=[], details=[], permit=permit,
                                    authority_result_digest=authority["result_digest"], mutate=mutate_permitted)
    return after, result, event, permit


CONNECTOR = {"id": "hospital-integration-connector", "version": "v2", "binding_digest": "sha256:" + "0" * 64}
CONNECTOR["binding_digest"] = digest("connector-binding", omit(CONNECTOR, "binding_digest"))


def dispatch(state: dict, event_id: str, permit: dict, attempt_id: str, attempted_at: str, *, status="SENT", acknowledgement=None,
             clock_revision=None, disposition="ACKNOWLEDGED", reasons=(), occurrence_status="DISPATCHED"):
    """DISPATCH_OBSERVED under LIFE-009; the derived row of the dispatch table is supplied by the caller."""
    native_request = permit["native_request"]
    occurrence_row = permit["occurrence"]
    if acknowledgement is None:
        acknowledgement = {"status": "ACCEPTED", "reference": f"{attempt_id}-ack", "observed_at": attempted_at}
    attempt = {"attempt_id": attempt_id, "status": status,
               "request_digest": digest("dispatch-native-request", {"instance_id": INSTANCE, "occurrence_id": occurrence_row["occurrence_id"],
                                                                     "interface": native_request["interface"], "operation": native_request["operation"],
                                                                     "fields": native_request["fields"]}),
               "attempted_at": attempted_at}
    clock_revision = clock_revision or latest_clock(state)["revision"]
    event = {**event_header(event_id, "DISPATCH_OBSERVED", state), "permit": permit, "native_request": native_request, "connector": CONNECTOR,
             "attempt": attempt, "acknowledgement": acknowledgement, "clock_revision": clock_revision}
    event_digest = digest("runtime-event", event)
    record = {"dispatch_digest": "sha256:" + "0" * 64,
              "dispatch_attempt_digest": digest("dispatch-attempt", {"permit_id": permit["permit_id"], "native_request": native_request, "connector": CONNECTOR, "attempt": attempt}),
              "event_id": event_id, "event_digest": event_digest, "permit_digest": permit["permit_id"], "native_request": native_request,
              "connector": CONNECTOR, "attempt": attempt, "acknowledgement": acknowledgement, "clock_revision": clock_revision}
    record["dispatch_digest"] = digest("dispatch", omit(record, "dispatch_digest"))
    before_timer = next((row for row in state["deferred_deadlines"] if row["occurrence_id"] == occurrence_row["occurrence_id"]), None)
    timeline_clock = next(row for row in state["clocks"] if row["source"] == permit["clock_source"] and row["revision"] == clock_revision)
    arms = before_timer and before_timer["status"] == "WAITING" and (status in ("SENT", "UNKNOWN") or acknowledgement["status"] == "ACCEPTED")
    immediately_due = bool(arms and plus_seconds(attempted_at, 900) <= timeline_clock["observed_time"])

    def mutate(after, _event_digest):
        active_row(after, occurrence_row["occurrence_id"])["status"] = occurrence_status
        after["dispatches"].append(record)
        timer = next((row for row in after["deferred_deadlines"] if row["occurrence_id"] == occurrence_row["occurrence_id"]), None)
        if timer and timer["status"] == "WAITING" and (status in ("SENT", "UNKNOWN") or acknowledgement["status"] == "ACCEPTED"):
            timer.update(status="PENDING", due=plus_seconds(attempted_at, 900),
                         trigger={"kind": "FIRST_DISPATCH", "event_digest": event_digest, "sequence": after["revision"],
                                  "dispatch_digest": record["dispatch_digest"], "dispatch_attempt_digest": record["dispatch_attempt_digest"],
                                  "clock": copy.deepcopy(timeline_clock)})
            if immediately_due:
                timer.update(status="EXPIRED", expiry_basis={"kind": "DISPATCH", "event_digest": event_digest, "clock": copy.deepcopy(timeline_clock)})
                close(after, occurrence_row, "EXPIRED", timeline_clock["evidence_digest"], timeline_clock["observed_time"], None,
                      relationship_digest("EXPIRY", "page-attending", "escalate-rapid-response"))
                escalation = occurrence("escalate-rapid-response", "1", [occurrence_row["occurrence_id"]], [branch_segment("page")])
                activate(after, escalation, event_digest, None, after["revision"])
                branch = next(row for row in after["obligations"] if row["branch_id"] == "page")
                branch.update(expected_occurrence_id=escalation["occurrence_id"], required_operation=STEP["escalate-rapid-response"]["operation"])

    details = [{"kind": "DISPATCH", "attempt_id": attempt_id, "reasons": sorted(reasons, key=utf8)}]
    if immediately_due:
        details.extend([{"kind": "DEADLINE", "deadline_ids": ["attending-acknowledgement"], "reasons": []},
                        route_detail([relationship_digest("EXPIRY", "page-attending", "escalate-rapid-response")], [])])
    after, result = work_transition(state, event, disposition="EXPIRED" if immediately_due else disposition,
                                    reason_codes=list(reasons), details=details, permit=None, mutate=mutate)
    return after, result, record, event


def native_evidence(evidence_id: str, permit: dict, status_value: str, event_time: str, observed_at: str, *, extra_fields=(), status="EFFECT_ESTABLISHED",
                    request_override=None) -> dict:
    step = STEP[permit["occurrence"]["step_id"]]
    carrier = step["completion"]
    attributed = request_override or {"work_class": WORK_CLASS["id"], "instance": INSTANCE, "occurrence": permit["occurrence"]["occurrence_id"],
                                      "step": step["id"], "operation": step["operation"], "interface": step["interface"], "fields": permit["native_request"]["fields"]}
    if status == "EFFECT_ESTABLISHED":
        actual = fields_sorted(list(attributed["fields"]) + [field(carrier["status_field"], carrier["status_type_ref"], status_value)] + list(extra_fields))
    else:
        actual = []
    native_operation_id = f"{carrier['effect_provider']}-operation-{evidence_id}"
    return {"evidence_id": evidence_id, "native_operation_id": native_operation_id, "provider": carrier["effect_provider"], "source": carrier["effect_source"],
            "record_type": carrier["effect_record_type"], "record_digest": digest("specimen-native-record", {"native_operation_id": native_operation_id, "actual_fields": actual}),
            "evidence_ref": f"{evidence_id}-record", "attributed_request": attributed, "native_request_digest": digest("native-request", attributed),
            "status": status, "actual_fields": actual, "collections": [], "event_time": event_time if status == "EFFECT_ESTABLISHED" else None,
            "observed_at": observed_at, "rules_out_past_and_future_effects": False}


def governed_effect_event(state: dict, event_id: str, permit: dict, dispatch_record: dict, evidence: dict, activation_clocks: list) -> dict:
    return {**event_header(event_id, "EFFECT_OBSERVED", state), "permit": permit, "dispatch_digest": dispatch_record["dispatch_digest"],
            "native_evidence": evidence, "completion_authorization": None, "budget_inputs": [], "clock_revision": None, "activation_clocks": activation_clocks}


def outcome_record(event: dict, event_digest: str, permit: dict, dispatch_record: dict, evidence: dict, classification: str, disputed: bool = False) -> dict:
    row = {"kind": "GOVERNED", "outcome_digest": "sha256:" + "0" * 64, "event_id": event["event_id"], "event_digest": event_digest, "source_event": copy.deepcopy(event), "permit_digest": permit["permit_id"],
           "dispatch_digest": dispatch_record["dispatch_digest"], "dispatch_attempt_digest": dispatch_record["dispatch_attempt_digest"],
           "native_evidence": evidence, "classification": classification, "reservation_receipt_digests": [], "conflicts_with_evidence_ids": [], "disputed": disputed}
    row["outcome_digest"] = digest("outcome", omit(row, "outcome_digest"))
    return row


def route_detail(relationships: list[str], constructs: list[str]) -> dict:
    return {"kind": "ROUTE", "relationship_digests": sorted(relationships, key=utf8), "construct_ids": sorted(constructs, key=utf8)}


# ---------------------------------------------------------------------------
# Review evidence and deployment (WCS2-005, LIFE-003)
# ---------------------------------------------------------------------------

def step_index(step_id: str) -> int:
    return next(index for index, row in enumerate(STEPS) if row["id"] == step_id)


def relationship_index(kind: str, source: str, target: str) -> int:
    return RELATIONSHIPS.index(relationship(kind, source, target))


def deadline_index(deadline_id: str) -> int:
    return next(index for index, row in enumerate(DEADLINES) if row["id"] == deadline_id)


def type_index(type_id: str) -> int:
    return next(index for index, row in enumerate(TYPES) if row["id"] == type_id)


def limit_index(step_id: str) -> int:
    return next(index for index, row in enumerate(WORK_CLASS["occurrence_limits"]) if row["step_id"] == step_id)


def participant_index(participant_id: str) -> int:
    return next(index for index, row in enumerate(WORK_CLASS["participants"]) if row["id"] == participant_id)


def field_index(step_id: str, name: str) -> int:
    return next(index for index, row in enumerate(STEP[step_id]["fields"]) if row["name"] == name)


def build_review_evidence():
    lines = readback(WORK_CLASS)
    paths = [line["path"] for line in lines]

    def under(prefix: str):
        return {path for path in paths if path == prefix or path.startswith(prefix + "/")}

    def step_paths(step_id, *members):
        base = f"/steps/{step_index(step_id)}"
        if not members:
            return under(base)
        result = set()
        for member in members:
            result |= under(f"{base}/{member}")
        return result

    def field_paths(step_id, *names):
        return set().union(*(under(f"/steps/{step_index(step_id)}/fields/{field_index(step_id, name)}") for name in names))

    def rel(kind, source, target):
        return under(f"/relationships/{relationship_index(kind, source, target)}")

    def obligation_path(obligation_id):
        return {f"/source/obligations/{SOURCE_IDS.index(obligation_id)}"}

    supported = {
        "antibiotic-requires-physician-order": obligation_path("antibiotic-requires-physician-order")
            | step_paths("order-antibiotic", "id", "kind", "operation", "interface", "executor_role", "required_credentials", "authority_requirements", "scope_fields", "permit_seconds")
            | field_paths("order-antibiotic", "dose_mg", "drug", "order_id", "patient_id", "route")
            | under(f"/participants/{participant_index('attending-hospitalist-1')}") | under(f"/types/{type_index('t.dose')}") | under(f"/types/{type_index('t.identity')}"),
        "bundle-completion-is-reconciled": obligation_path("bundle-completion-is-reconciled")
            | step_paths("order-antibiotic", "completion", "failure_behavior") | step_paths("order-screening-labs", "completion", "failure_behavior")
            | rel("SEQUENCE", "order-antibiotic", "bundle-complete") | step_paths("bundle-complete") | under(f"/types/{type_index('t.status')}"),
        "escalate-unacknowledged-page": obligation_path("escalate-unacknowledged-page")
            | under(f"/deadlines/{deadline_index('attending-acknowledgement')}") | rel("EXPIRY", "page-attending", "escalate-rapid-response")
            | rel("SEQUENCE", "escalate-rapid-response", "bundle-join") | step_paths("page-attending") | step_paths("escalate-rapid-response")
            | under(f"/occurrence_limits/{limit_index('page-attending')}") | under(f"/occurrence_limits/{limit_index('escalate-rapid-response')}")
            | under("/parallel_blocks/0/branches/1") | under(f"/types/{type_index('t.count')}"),
        "hour-one-bundle": obligation_path("hour-one-bundle")
            | under(f"/deadlines/{deadline_index('labs-hour-one')}") | under(f"/deadlines/{deadline_index('antibiotic-window')}") | under("/event_anchors") | under(f"/types/{type_index('t.instant')}")
            | rel("SEQUENCE", "raise-alert", "bundle-split") | rel("SEQUENCE", "order-screening-labs", "bundle-join") | rel("SEQUENCE", "page-attending", "bundle-join")
            | rel("SEQUENCE", "bundle-join", "assess-readiness") | step_paths("raise-alert") | step_paths("bundle-split") | step_paths("bundle-join")
            | {"/root", "/parallel_blocks/0/id", "/parallel_blocks/0/split_step_id", "/parallel_blocks/0/join_step_id"} | under("/parallel_blocks/0/branches/0")
            | under(f"/participants/{participant_index('sepsis-surveillance-agent')}") | under(f"/types/{type_index('t.score')}"),
        "screening-under-standing-protocol": obligation_path("screening-under-standing-protocol")
            | step_paths("order-screening-labs", "id", "kind", "operation", "interface", "executor_role", "required_credentials", "authority_requirements", "scope_fields", "fields")
            | under(f"/participants/{participant_index('nurse-bedside-1')}") | under(f"/occurrence_limits/{limit_index('order-screening-labs')}"),
        "vitals-freshness": obligation_path("vitals-freshness")
            | step_paths("assess-readiness") | step_paths("refresh-vitals") | under("/choices/0") | under("/loops/0")
            | rel("LABEL", "assess-readiness", "order-antibiotic") | rel("LABEL", "assess-readiness", "refresh-vitals") | rel("SEQUENCE", "refresh-vitals", "assess-readiness")
            | under(f"/occurrence_limits/{limit_index('assess-readiness')}") | under(f"/occurrence_limits/{limit_index('refresh-vitals')}")
            | step_paths("order-antibiotic", "authority_type_refs") | under(f"/types/{type_index('t.readiness')}") | under(f"/types/{type_index('t.seconds')}"),
    }
    mappings = [{"source_obligation_id": obligation_id, "provision_paths": sorted(paths_for, key=utf8)} for obligation_id, paths_for in sorted(supported.items(), key=lambda row: utf8(row[0]))]
    mapped = set().union(*supported.values())
    unknown = mapped - set(paths)
    if unknown:
        raise ValueError(f"correspondence names absent readback paths: {sorted(unknown)}")
    unsupported = sorted(set(paths) - mapped, key=utf8)
    residue = [{"kind": "ARTIFACT_PROVISION", "subject": path, "disposition": "UNSUPPORTED",
                "explanation": "The synthetic source policy does not state this representation or execution detail."}
               for path in unsupported]
    residue.append({"kind": "SOURCE_OBLIGATION", "subject": "alert-window-cap", "disposition": "EXCLUDED",
                    "explanation": "Carried by the separate aggregate definition alert-count-definition.json and evaluated by the host before deployment; this work class declares no shared budget."})
    residue.append({"kind": "SOURCE_OBLIGATION", "subject": "cultures-before-antibiotics-unless-overridden", "disposition": "UNSUPPORTED",
                    "explanation": "The preserved cultures-first-or-recorded-reason physician gate is partial. No attributable prospective delay assertion establishes that drawing cultures would delay antibiotics more than45 minutes; recognition elapsed time and a nonempty reason cannot prove that threshold."})
    residue.sort(key=lambda row: (utf8(row["kind"]), utf8(row["subject"])))
    base = {"schema": SCHEMA + "evidence-record", "evidence_id": "sepsis-surveillance-correspondence", "kind": "CORRESPONDENCE", "status": "ACCEPTED",
            "subject_digest": DEFINITION_DIGEST, "source_id": SOURCE_POLICY["id"], "source_revision": SOURCE_POLICY["revision"], "work_class_digest": DEFINITION_DIGEST,
            "mappings": mappings, "uncovered_source_obligation_ids": ["alert-window-cap", "cultures-before-antibiotics-unless-overridden"], "unsupported_provision_paths": unsupported, "residue": residue,
            "recorded_at": DEPLOYMENT_AUTHORIZED_AT, "provenance_digest": digest("specimen-provenance", {"id": "sepsis-surveillance-correspondence"})}
    review = {"schema": SCHEMA + "evidence-record", "evidence_id": "sepsis-surveillance-correspondence-review", "kind": "REVIEW", "status": "ACCEPTED",
              "subject_digest": digest("correspondence-subject", base), "reviewer_id": PROXY + "reviewer:20261007", "paragraph_ids": [],
              "case_ids": ["sepsis-surveillance-correspondence"], "finding_ids": [], "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
              "provenance_digest": digest("specimen-provenance", {"id": "sepsis-surveillance-correspondence-review"})}
    correspondence = {**base, "review": review}
    source_confirmation = {"schema": SCHEMA + "evidence-record", "evidence_id": "sepsis-surveillance-source-confirmation", "kind": "SOURCE_CONFIRMATION", "status": "ACCEPTED",
                           "subject_digest": digest("work-class-source", WORK_CLASS["source"]), "actor_id": PROXY + "source-confirmer:20261007",
                           "scope_ids": list(SOURCE_IDS), "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
                           "provenance_digest": digest("specimen-provenance", {"id": "sepsis-surveillance-source-confirmation"})}
    policy_decision = {"schema": SCHEMA + "evidence-record", "evidence_id": "sepsis-surveillance-policy-decision", "kind": "POLICY_DECISION", "status": "ACCEPTED",
                       "subject_digest": DEFINITION_DIGEST, "decision_maker_id": PROXY + "policy-owner:20261007",
                       "decision_ids": ["sepsis-surveillance-policy-decision-1"], "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
                       "provenance_digest": digest("specimen-provenance", {"id": "sepsis-surveillance-policy-decision"})}
    readback_result = {"status": "READBACK", "digest": DEFINITION_DIGEST, "lines": lines}
    correspondence_input = {"profile": PROFILE, "role": "REVIEW_EVIDENCE", "specification_pin": PIN,
                            "subject": {"kind": "WORK_CLASS", "subject_id": WORK_CLASS["id"], "subject_digest": DEFINITION_DIGEST,
                                        "candidate_identity": "seampoint.work-class/1.0.0-draft.3", "specification_pin": PIN},
                            "work_class": WORK_CLASS, "work_class_digest": DEFINITION_DIGEST, "evidence": correspondence}
    return readback_result, correspondence, correspondence_input, source_confirmation, policy_decision


def build_deployment(correspondence, source_confirmation, policy_decision, *, initial_clock=None):
    digests = [digest("evidence", row) for row in (correspondence, source_confirmation, policy_decision)]
    root = occurrence("raise-alert", "1", [], [])
    native_record = {"provider": "sepsis-recognition-system", "source": "recognition-log", "record_type": "sepsis-recognition",
                     "provider_record_id": "recognition-4471", "provider_revision": "recognition-r1",
                     "event_time": RECOGNITION, "observed_at": RECOGNITION_OBSERVED,
                     "fields": [field("alert_id", "t.identity", ALERT), field("patient_id", "t.identity", PATIENT)],
                     "evidence_ref": "fictional-recognition-4471-evidence",
                     "provenance_digest": digest("specimen-recognition-provenance", {"record": "recognition-4471", "revision": "recognition-r1"})}
    wrapper = {"anchor_ref": ANCHOR_REF, "specification_pin": PIN, "work_class_digest": DEFINITION_DIGEST,
               "organization_id": ORG, "instance_id": INSTANCE, "record": native_record,
               "record_digest": digest("event-anchor-record", native_record)}
    anchor_digest = digest("initial-event-anchor", wrapper)
    partial = {"schema": SCHEMA + "deployment-authorization", "authorization_id": f"deploy-{INSTANCE}", "specification_pin": PIN, "work_class_digest": DEFINITION_DIGEST,
               "profile": PROFILE, "role": ROLE, "instance_id": INSTANCE, "organization_id": ORG, "status": "AUTHORIZED", "authorized_at": DEPLOYMENT_AUTHORIZED_AT,
               "expires_at": DEPLOYMENT_EXPIRES, "correspondence_evidence_digest": digests[0], "source_confirmation_evidence_digest": digests[1],
               "policy_decision_evidence_digest": digests[2], "event_anchor_digests": [{"anchor_ref": ANCHOR_REF, "anchor_digest": anchor_digest}]}
    subject_digest = digest("deployment-authorization-subject", partial)
    evidence = {"schema": SCHEMA + "evidence-record", "evidence_id": f"deployment-evidence-{INSTANCE}", "kind": "ORGANIZATIONAL_AUTHORIZATION", "status": "ACCEPTED",
                "subject_digest": subject_digest, "organization_id": ORG, "authorizer_id": PROXY + "deployment-authorizer:20261007",
                "authorization_scope": sorted([PIN, DEFINITION_DIGEST, PROFILE, ROLE, INSTANCE], key=utf8), "recorded_at": DEPLOYMENT_AUTHORIZED_AT,
                "expires_at": DEPLOYMENT_EXPIRES, "provenance_digest": digest("specimen-provenance", {"id": f"deployment-evidence-{INSTANCE}"})}
    evidence_digest = digest("evidence", evidence)
    authorization = {**partial, "authorization_evidence_digest": evidence_digest}
    authorization_digest = digest("deployment-authorization", authorization)
    authorization_clock = clock_record("1", DEPLOYMENT_CLOCK_AT, source="deployment-clock")
    initial_clock = copy.deepcopy(initial_clock or clock_record("0", DEPLOYMENT_CLOCK_AT))
    activation_digest = digest("deployment-activation", {"deployment_authorization_digest": authorization_digest, "instance_id": INSTANCE, "occurrence_id": root["occurrence_id"]})
    state = {"schema": SCHEMA + "work-state", "specification_pin": PIN, "work_class_digest": DEFINITION_DIGEST, "profile": PROFILE, "role": ROLE, "instance_id": INSTANCE,
             "deployment_authorization": authorization, "deployment_authorization_subject_digest": subject_digest, "deployment_authorization_digest": authorization_digest,
             "deployment_authorization_evidence": evidence, "deployment_authorization_evidence_digest": evidence_digest,
             "deployment_correspondence_evidence": correspondence, "deployment_correspondence_evidence_digest": digests[0],
             "deployment_source_confirmation_evidence": source_confirmation, "deployment_source_confirmation_evidence_digest": digests[1],
             "deployment_policy_decision_evidence": policy_decision, "deployment_policy_decision_evidence_digest": digests[2],
             "deployment_authorization_clock": authorization_clock, "deployment_organization_id": ORG, "revision": "0", "status": "ACTIVE",
             "total_activations": "1", "total_actuations": "0",
             "step_counters": [{"step_id": row["id"], "activations": "1" if row["id"] == "raise-alert" else "0", "actuations": "0"} for row in PROPOSAL_STEPS],
             "active": [{"occurrence": root, "activation_event_digest": activation_digest, "status": "ACTIVE", "deadline_ids": []}],
             "completed": [], "obligations": [], "proposals": [], "permits": [], "dispatches": [], "outcomes": [],
             "clocks": [initial_clock], "deadlines": [], "fanout_passes": [],
             "initial_event_anchors": [wrapper], "event_duties": [], "deferred_deadlines": [], "timing_clock_events": [],
             "receipts": [], "replays": []}
    for deadline in DEADLINES:
        if deadline["due"]["kind"] != "ELAPSED_FROM_EVENT_ANCHOR":
            continue
        creation = {"specification_pin": PIN, "work_class_digest": DEFINITION_DIGEST, "instance_id": INSTANCE,
                    "deadline_id": deadline["id"], "anchor_digest": anchor_digest, "due": HOUR_ONE_DUE,
                    "boundary": deadline["boundary"], "source": deadline["clock_source"]}
        state["event_duties"].append({"deadline_id": deadline["id"], "target_step_id": deadline["step_id"],
                                     "source": deadline["clock_source"], "boundary": deadline["boundary"], "anchor_ref": ANCHOR_REF,
                                     "anchor_digest": anchor_digest, "due": HOUR_ONE_DUE, "creation_digest": digest("initial-event-duty", creation),
                                     "status": "PENDING", "occurrence_id": None, "binding_event_digest": None})
        if initial_clock["status"] == "AVAILABLE" and initial_clock["observed_time"] >= HOUR_ONE_DUE:
            state["event_duties"][-1].update(status="EXPIRED", expiry_basis={"kind": "DEPLOYMENT", "deployment_authorization_digest": authorization_digest,
                                                                          "clock": copy.deepcopy(initial_clock)})
    deploy_input = {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": WORK_CLASS, "definition_digest": DEFINITION_DIGEST, "instance_id": INSTANCE,
                    "deployment_authorization": authorization, "authorization_evidence": evidence, "correspondence_evidence": correspondence,
                    "source_confirmation_evidence": source_confirmation, "policy_decision_evidence": policy_decision, "authorization_clock": authorization_clock,
                    "initial_clocks": [initial_clock], "event_anchors": [wrapper]}
    deploy_result = {"status": "DEPLOYED", "profile": PROFILE, "role": ROLE, "instance_id": INSTANCE, "work_class_digest": DEFINITION_DIGEST,
                     "deployment_authorization_digest": authorization_digest, "state": state, "state_digest": work_state_digest(state)}
    return deploy_input, deploy_result, state, root


# ---------------------------------------------------------------------------
# Valid trace (DERIVATIONS.md section 2)
# ---------------------------------------------------------------------------

ALERT_FIELDS = [field("alert_id", "t.identity", "alert-4471"), field("patient_id", "t.identity", PATIENT), field("risk_score", "t.score", "0.82")]
LABS_FIELDS = [field("alert_id", "t.identity", ALERT), field("order_set_id", "t.identity", "orderset-9012"), field("panel", "t.text", "sepsis-screening-set"), field("patient_id", "t.identity", PATIENT),
               field("test_count", "t.count", "3")]
PAGE_FIELDS = [field("attempt_number", "t.count", "1"), field("page_id", "t.identity", "page-3301"), field("patient_id", "t.identity", PATIENT)]
ESCALATION_FIELDS = [field("attempt_number", "t.count", "1"), field("page_id", "t.identity", "page-3302"), field("patient_id", "t.identity", PATIENT)]
ASSESS_FIELDS = [field("assessment_id", "t.identity", "assessment-5501"), field("lookback_seconds", "t.seconds", "600"), field("patient_id", "t.identity", PATIENT)]


def antibiotic_fields(*, cultures_first=True, override_reason="", vitals_age="120", patient=PATIENT):
    return [field("alert_id", "t.identity", ALERT), field("cultures_drawn_first", "t.boolean", cultures_first), field("dose_mg", "t.dose", "2000"), field("drug", "t.text", "ceftriaxone"),
            field("order_id", "t.identity", "order-7788"), field("override_reason", "t.text", override_reason), field("patient_id", "t.identity", patient),
            field("route", "t.text", "intravenous"), field("vitals_age_seconds", "t.seconds", vitals_age)]


def build_trace():
    readback_result, correspondence, correspondence_input, source_confirmation, policy_decision = build_review_evidence()
    deploy_input, deploy_result, state0, alert_occ = build_deployment(correspondence, source_confirmation, policy_decision)
    requests, results, states = [], [], {"after-deployment": state0}
    named = {}

    def record(request_id, request, result, state=None, name=None):
        requests.append(request)
        results.append(response(request, result))
        if name:
            states[name] = state

    record("sepsis-deploy", {"protocol": PROTOCOL, "request_id": "sepsis-deploy", "operation": "deploy", "input": deploy_input}, deploy_result)

    # Rev 1: time zero clock.
    state1, result, clock_event = clock_step(state0, "clock-ward-1", "1", T0)
    record("sepsis-clock-1", step_request("sepsis-clock-1", state0, clock_event), result)
    # Rev 2: alert proposal.
    alert_authority = authority_case("raise-alert", alert_occ["occurrence_id"], ALERT_FIELDS, T0)
    state2, result, alert_event, alert_permit = propose(state1, "propose-raise-alert-1", alert_occ, ALERT_FIELDS, alert_authority)
    record("sepsis-propose-alert", step_request("sepsis-propose-alert", state1, alert_event), result)
    # Rev 3: alert dispatch.
    state3, result, alert_dispatch, dispatch_event = dispatch(state2, "dispatch-raise-alert-1", alert_permit, "alert-attempt-1", T0)
    record("sepsis-dispatch-alert", step_request("sepsis-dispatch-alert", state2, dispatch_event), result, state3, "after-alert-dispatch")
    # Rev 4: delivery08:01 binds the existing labs duty and creates a WAITING page timer.
    delivery_at = plus_seconds(T0, 60)
    alert_evidence = native_evidence("alert-delivery-1", alert_permit, "DELIVERED", delivery_at, delivery_at)
    clock1 = clock_record("1", T0)
    labs_occ = occurrence("order-screening-labs", "1", [alert_occ["occurrence_id"]], [branch_segment("labs")])
    page_occ = occurrence("page-attending", "1", [alert_occ["occurrence_id"]], [branch_segment("page")])
    alert_effect = governed_effect_event(state3, "effect-raise-alert-1", alert_permit, alert_dispatch, alert_evidence, [])

    def mutate_alert_effect(after, event_digest):
        close(after, alert_occ, "SUCCEEDED", digest("native-evidence", alert_evidence), delivery_at, None, relationship_digest("SEQUENCE", "raise-alert", "bundle-split"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(alert_effect, event_digest, alert_permit, alert_dispatch, alert_evidence, "MATCHED"))
        for occ in (labs_occ, page_occ):
            activate(after, occ, event_digest, clock1, after["revision"])
        after["obligations"].append(obligation("labs", [alert_occ["occurrence_id"]], event_digest, labs_occ))
        after["obligations"].append(obligation("page", [alert_occ["occurrence_id"]], event_digest, page_occ))

    state4, result = work_transition(state3, alert_effect, disposition="COMPLETED", reason_codes=[],
                                     details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": alert_evidence["evidence_id"]},
                                              route_detail([relationship_digest("SEQUENCE", "raise-alert", "bundle-split")], ["hour-one-bundle"])],
                                     permit=None, mutate=mutate_alert_effect)
    record("sepsis-effect-alert", step_request("sepsis-effect-alert", state3, alert_effect), result, state4, "after-alert-split")
    # Rev 5: clock at 08:02.
    T_0802 = plus_seconds(T0, 120)
    state5, result, clock_event = clock_step(state4, "clock-ward-2", "2", T_0802)
    record("sepsis-clock-2", step_request("sepsis-clock-2", state4, clock_event), result, state5, "after-clock-2")
    # Rev 6, 7: page and labs proposals.
    page_authority = authority_case("page-attending", page_occ["occurrence_id"], PAGE_FIELDS, T_0802)
    state6, result, page_event, page_permit = propose(state5, "propose-page-attending-1", page_occ, PAGE_FIELDS, page_authority)
    record("sepsis-propose-page", step_request("sepsis-propose-page", state5, page_event), result)
    labs_authority = authority_case("order-screening-labs", labs_occ["occurrence_id"], LABS_FIELDS, T_0802)
    state7, result, labs_event, labs_permit = propose(state6, "propose-order-screening-labs-1", labs_occ, LABS_FIELDS, labs_authority)
    record("sepsis-propose-labs", step_request("sepsis-propose-labs", state6, labs_event), result, state7, "before-page-dispatch")
    # Rev 8, 9: dispatches.
    state8, result, page_dispatch, dispatch_event = dispatch(state7, "dispatch-page-attending-1", page_permit, "page-attempt-1", T_0802)
    record("sepsis-dispatch-page", step_request("sepsis-dispatch-page", state7, dispatch_event), result)
    state9, result, labs_dispatch, dispatch_event = dispatch(state8, "dispatch-order-screening-labs-1", labs_permit, "labs-attempt-1", T_0802)
    record("sepsis-dispatch-labs", step_request("sepsis-dispatch-labs", state8, dispatch_event), result, state9, "after-branch-dispatches")
    # Rev 10: attending acknowledges the page at 08:06; page obligation discharged, join waits.
    T_0806 = plus_seconds(T0, 360)
    page_evidence = native_evidence("page-acknowledgement-1", page_permit, "ACKNOWLEDGED", T_0806, T_0806)
    page_effect = governed_effect_event(state9, "effect-page-attending-1", page_permit, page_dispatch, page_evidence, [])

    def mutate_page_effect(after, event_digest):
        close(after, page_occ, "SUCCEEDED", digest("native-evidence", page_evidence), T_0806, None, relationship_digest("SEQUENCE", "page-attending", "bundle-join"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(page_effect, event_digest, page_permit, page_dispatch, page_evidence, "MATCHED"))
        discharge(next(row for row in after["obligations"] if row["branch_id"] == "page"), event_digest, page_occ, digest("native-evidence", page_evidence))

    state10, result = work_transition(state9, page_effect, disposition="COMPLETED", reason_codes=[],
                                      details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": page_evidence["evidence_id"]},
                                               route_detail([relationship_digest("SEQUENCE", "page-attending", "bundle-join")], ["hour-one-bundle"])],
                                      permit=None, mutate=mutate_page_effect)
    record("sepsis-effect-page", step_request("sepsis-effect-page", state9, page_effect), result, state10, "after-page-effect")
    # Rev 11: labs resulted at 08:25; join fires; readiness assessment activates as loop pass 1.
    T_0825 = plus_seconds(T0, 1500)
    labs_evidence = native_evidence("screening-result-set-1", labs_permit, "RESULTED", T_0825, T_0825)
    labs_effect = governed_effect_event(state10, "effect-order-screening-labs-1", labs_permit, labs_dispatch, labs_evidence, [])
    assess_occ = occurrence("assess-readiness", "1", [labs_occ["occurrence_id"], page_occ["occurrence_id"]], [loop_segment("1")])

    def mutate_labs_effect(after, event_digest):
        close(after, labs_occ, "SUCCEEDED", digest("native-evidence", labs_evidence), T_0825, None, relationship_digest("SEQUENCE", "order-screening-labs", "bundle-join"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(labs_effect, event_digest, labs_permit, labs_dispatch, labs_evidence, "MATCHED"))
        discharge(next(row for row in after["obligations"] if row["branch_id"] == "labs"), event_digest, labs_occ, digest("native-evidence", labs_evidence))
        for row in after["obligations"]:
            row["status"] = "JOINED"
        activate(after, assess_occ, event_digest, None, after["revision"])

    state11, result = work_transition(state10, labs_effect, disposition="COMPLETED", reason_codes=[],
                                      details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": labs_evidence["evidence_id"]},
                                               route_detail([relationship_digest("SEQUENCE", "order-screening-labs", "bundle-join"), relationship_digest("SEQUENCE", "bundle-join", "assess-readiness")], ["hour-one-bundle"])],
                                      permit=None, mutate=mutate_labs_effect)
    record("sepsis-effect-labs", step_request("sepsis-effect-labs", state10, labs_effect), result, state11, "after-join")
    # Rev 12 to 14: clock 08:30, readiness proposal and dispatch.
    T_0830 = plus_seconds(T0, 1800)
    state12, result, clock_event = clock_step(state11, "clock-ward-3", "3", T_0830)
    record("sepsis-clock-3", step_request("sepsis-clock-3", state11, clock_event), result, state12, "before-readiness")
    assess_authority = authority_case("assess-readiness", assess_occ["occurrence_id"], ASSESS_FIELDS, T_0830)
    state13, result, assess_event, assess_permit = propose(state12, "propose-assess-readiness-1", assess_occ, ASSESS_FIELDS, assess_authority)
    record("sepsis-propose-assess", step_request("sepsis-propose-assess", state12, assess_event), result)
    state14, result, assess_dispatch, dispatch_event = dispatch(state13, "dispatch-assess-readiness-1", assess_permit, "assess-attempt-1", T_0830)
    record("sepsis-dispatch-assess", step_request("sepsis-dispatch-assess", state13, dispatch_event), result, state14, "after-assess-dispatch")
    # Rev 15: readiness READY at 08:31; antibiotic step activates with its deadline from the 08:30 sample.
    T_0831 = plus_seconds(T0, 1860)
    assess_evidence = native_evidence("readiness-assessment-1", assess_permit, "COMPLETED", T_0831, T_0831, extra_fields=[field("readiness", "t.readiness", "READY")])
    clock3 = clock_record("3", T_0830)
    assess_effect = governed_effect_event(state14, "effect-assess-readiness-1", assess_permit, assess_dispatch, assess_evidence, [])
    antibiotic_occ = occurrence("order-antibiotic", "1", [assess_occ["occurrence_id"]], [])

    def mutate_assess_effect(after, event_digest):
        close(after, assess_occ, "SUCCEEDED", digest("native-evidence", assess_evidence), T_0831, typed("t.readiness", "READY"),
              relationship_digest("LABEL", "assess-readiness", "order-antibiotic"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(assess_effect, event_digest, assess_permit, assess_dispatch, assess_evidence, "MATCHED"))
        activate(after, antibiotic_occ, event_digest, clock3, after["revision"])

    state15, result = work_transition(state14, assess_effect, disposition="COMPLETED", reason_codes=[],
                                      details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": assess_evidence["evidence_id"]},
                                               route_detail([relationship_digest("LABEL", "assess-readiness", "order-antibiotic")], []),
                                               {"kind": "LABEL", "step_id": "assess-readiness", "observed_value": typed("t.readiness", "READY")}],
                                      permit=None, mutate=mutate_assess_effect)
    record("sepsis-effect-assess", step_request("sepsis-effect-assess", state14, assess_effect), result, state15, "after-readiness")
    # Rev 16 to 18: clock 08:35, physician order permitted and dispatched.
    T_0835 = plus_seconds(T0, 2100)
    T_0834 = plus_seconds(T0, 2040)
    state16, result, clock_event = clock_step(state15, "clock-ward-4", "4", T_0835)
    record("sepsis-clock-4", step_request("sepsis-clock-4", state15, clock_event), result, state16, "after-clock-4")
    order_fields = antibiotic_fields()
    order_authority = authority_case("order-antibiotic", antibiotic_occ["occurrence_id"], order_fields, T_0835, decision={"at": T_0834, "attested_at": T_0835})
    state17, result, order_event, order_permit = propose(state16, "propose-order-antibiotic-1", antibiotic_occ, order_fields, order_authority)
    record("sepsis-propose-antibiotic", step_request("sepsis-propose-antibiotic", state16, order_event), result, state17, "after-antibiotic-permit")
    state18, result, order_dispatch, dispatch_event = dispatch(state17, "dispatch-order-antibiotic-1", order_permit, "order-attempt-1", T_0835)
    record("sepsis-dispatch-antibiotic", step_request("sepsis-dispatch-antibiotic", state17, dispatch_event), result, state18, "after-antibiotic-dispatch")
    # Rev 19: administration record at 08:50, observed 08:52; terminal closure completes the instance.
    T_0850 = plus_seconds(T0, 3000)
    T_0852 = plus_seconds(T0, 3120)
    order_evidence = native_evidence("antibiotic-administration-1", order_permit, "ADMINISTERED", T_0850, T_0852)
    order_effect = governed_effect_event(state18, "effect-order-antibiotic-1", order_permit, order_dispatch, order_evidence, [])

    def mutate_order_effect(after, event_digest):
        close(after, antibiotic_occ, "SUCCEEDED", digest("native-evidence", order_evidence), T_0850, None, relationship_digest("SEQUENCE", "order-antibiotic", "bundle-complete"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(order_effect, event_digest, order_permit, order_dispatch, order_evidence, "MATCHED"))
        after["status"] = "COMPLETE"

    state19, result = work_transition(state18, order_effect, disposition="COMPLETED", reason_codes=[],
                                      details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": order_evidence["evidence_id"]},
                                               route_detail([relationship_digest("SEQUENCE", "order-antibiotic", "bundle-complete")], [])],
                                      permit=None, mutate=mutate_order_effect)
    record("sepsis-effect-antibiotic", step_request("sepsis-effect-antibiotic", state18, order_effect), result, state19, "after-completion")

    named.update({"alert_occ": alert_occ, "labs_occ": labs_occ, "page_occ": page_occ, "assess_occ": assess_occ, "antibiotic_occ": antibiotic_occ,
                  "alert_permit": alert_permit, "alert_dispatch": alert_dispatch,
                  "labs_permit": labs_permit, "labs_dispatch": labs_dispatch, "page_permit": page_permit, "assess_permit": assess_permit,
                  "assess_dispatch": assess_dispatch, "order_permit": order_permit, "order_dispatch": order_dispatch, "order_fields": order_fields,
                  "T_0802": T_0802, "T_0830": T_0830, "T_0834": T_0834, "T_0835": T_0835})
    artifacts = {"readback": readback_result, "correspondence": correspondence, "correspondence_input": correspondence_input,
                 "source_confirmation": source_confirmation, "policy_decision": policy_decision, "deploy_input": deploy_input, "deploy_result": deploy_result}
    return requests, results, states, named, artifacts



# ---------------------------------------------------------------------------
# Alert-count aggregate (AGGREGATES.md), the source policy's alert cap
# ---------------------------------------------------------------------------

AGGREGATE_DEFINITION = {
    "schema": SCHEMA + "aggregate-definition",
    "types": [{"id": "b.count", "kind": "INTEGER", "unit": None, "nonnegative": True}, {"id": "b.identity", "kind": "IDENTITY", "unit": None, "nonnegative": False}],
    "aggregate": {"id": "alerts-per-patient-count", "reducer": "COUNT", "result_type": "b.count", "element_type": None, "key_types": ["b.identity"],
                  "mappings": [{"id": "raise-alert-count", "step_ids": ["raise-alert"], "qualifier": {"kind": "BOOLEAN", "value": True}, "key_fields": ["patient_id"], "contribution": {"kind": "COUNT"}}],
                  "time": {"clock_source": CLOCK_SOURCE, "precision": "SECOND"},
                  "window": {"kind": "ROLLING", "duration_seconds": "21600", "start_inclusive": False, "end_inclusive": True},
                  "committed_source": {"provider": "nurse-notification-system", "source": "alert-log", "freshness": {"kind": "MAX_AGE", "seconds": "900"},
                                       "key_fields": ["patient_id"], "qualifier": {"kind": "BOOLEAN", "value": True}, "contribution": {"kind": "COUNT"}},
                  "pending_policy": "EXCLUDE_RESERVED", "operator": "LTE", "bound": typed("b.count", "2")},
}
AGGREGATE_DIGEST = digest("aggregate-definition", AGGREGATE_DEFINITION)


def aggregate_request(request_id: str, occurrence_id: str, prior_alert_times: list[str], as_of: str):
    interval = {"start": plus_seconds(T0, -21600), "end": T0, "start_inclusive": False, "end_inclusive": True}
    key = [typed("b.identity", PATIENT)]
    query = {"definition_digest": AGGREGATE_DIGEST, "interval": interval, "keys": [key]}
    observation = {"provider": "nurse-notification-system", "source": "alert-log", "request_digest": digest("aggregate-query", query), "status": "AVAILABLE",
                   "revision": "alert-log-r7", "as_of": as_of, "coverage": interval, "kind": "EVENT_SNAPSHOT",
                   "events": [{"id": f"alert-{4400 + index}", "state": "ACTIVE", "occurred_at": when, "fields": [field("patient_id", "b.identity", PATIENT)]}
                              for index, when in enumerate(prior_alert_times)],
                   "evidence_ref": f"alert-log-snapshot-{request_id}"}
    request = {"schema": SCHEMA + "aggregate-input", "specification_pin": PIN, "definition": AGGREGATE_DEFINITION, "definition_digest": AGGREGATE_DIGEST,
               "operations": [{"occurrence": occurrence_id, "step": "raise-alert", "fields": [field("patient_id", "b.identity", PATIENT)]}], "pending": [],
               "clock": {"source": CLOCK_SOURCE, "status": "AVAILABLE", "instant": T0}, "observations": [observation]}
    return {"protocol": PROTOCOL, "request_id": request_id, "operation": "evaluate", "input": {"kind": "AGGREGATE", "request": request}}, key


def aggregate_result(key, status, count, reasons):
    partition = {"occurrence": None, "key": key, "status": status, "accumulator": {"kind": "SCALAR", "value": count} if count else None,
                 "result": count, "reasons": reasons}
    return {"schema": SCHEMA + "aggregate-result", "specification_pin": PIN, "definition_digest": AGGREGATE_DIGEST, "status": status, "partitions": [partition], "reasons": reasons}


def unknown_effect(state, event_id, permit, dispatch_record, observed_at):
    evidence = native_evidence(event_id + "-native", permit, None, None, observed_at, status="OUTCOME_UNKNOWN")
    event = governed_effect_event(state, event_id, permit, dispatch_record, evidence, [])

    def mutate(after, event_digest):
        active_row(after, permit["occurrence"]["occurrence_id"])["status"] = "OUTCOME_UNKNOWN"
        after["outcomes"].append(outcome_record(event, event_digest, permit, dispatch_record, evidence, "UNKNOWN"))

    after, result = work_transition(state, event, disposition="OUTCOME_RETAINED", reason_codes=["UNKNOWN_OUTCOME"],
                                    details=[{"kind": "EFFECT", "classification": "UNKNOWN", "evidence_id": evidence["evidence_id"]}],
                                    permit=None, mutate=mutate)
    return after, result, event


def unchanged_refusal(state, code):
    return {"status": "REFUSED", "profile": PROFILE, "role": ROLE, "code": code, "path": "", "state": state,
            "state_digest": work_state_digest(state), "budget_states": []}


def rebind_initial_anchor(deploy_input):
    """Recompute all acyclic commitments so negative cases isolate the named fault."""
    wrapper = deploy_input["event_anchors"][0]
    wrapper["record_digest"] = digest("event-anchor-record", wrapper["record"])
    authorization = deploy_input["deployment_authorization"]
    authorization["event_anchor_digests"] = [{"anchor_ref": wrapper["anchor_ref"], "anchor_digest": digest("initial-event-anchor", wrapper)}]
    evidence = deploy_input["authorization_evidence"]
    evidence["subject_digest"] = digest("deployment-authorization-subject", omit(authorization, "authorization_evidence_digest"))
    authorization["authorization_evidence_digest"] = digest("evidence", evidence)


def build_scenarios(states, named, trace_requests, trace_results, artifacts):
    requests, results, judgments, checkpoints = [], [], [], {}

    def record(request_id, before, event, after, result, judgment, consequence, checkpoint=None):
        request = step_request(request_id, before, event)
        requests.append(request)
        results.append(response(request, result))
        judgments.append({"id": request_id, "expected_judgment": judgment, "state_and_budget_consequence": consequence})
        if checkpoint:
            checkpoints[checkpoint] = after

    def record_clock(request_id, before, revision, instant, judgment, consequence, *, status="AVAILABLE", checkpoint=None):
        after, result, event = clock_step(before, request_id + "-event", revision, instant, status=status)
        record(request_id, before, event, after, result, judgment, consequence, checkpoint)
        return after

    before = states["after-alert-dispatch"]
    unknown, result, event = unknown_effect(before, "unknown-alert-outcome", named["alert_permit"], named["alert_dispatch"], plus_seconds(T0, 120))
    record("timing-alert-outcome-unknown", before, event, unknown, result, "OUTCOME_RETAINED/UNKNOWN_OUTCOME",
           "Only the root is active, with OUTCOME_UNKNOWN. Both unbound event duties retain due08:58.", "after-unknown-alert")
    before_due = record_clock("timing-unbound-before-due", unknown, "2", plus_seconds(HOUR_ONE_DUE, -1), "CLOCK_RECORDED",
                              "Both unbound duties remain PENDING one second before due.")
    record_clock("timing-unbound-at-due", before_due, "3", HOUR_ONE_DUE, "EXPIRED",
                 "Both unbound duties expire as evidence. No target, join, route or actuation is created.", checkpoint="after-unbound-expiry")
    unavailable = record_clock("timing-unbound-clock-unavailable", unknown, "2", None, "CLOCK_RECORDED/CLOCK_UNAVAILABLE",
                               "Watermark advances; fixed due and root outcome remain.", status="UNAVAILABLE", checkpoint="after-clock-outage")
    record_clock("timing-unbound-clock-resumed", unavailable, "3", plus_seconds(T0, 3900), "EXPIRED",
                 "Resumed09:05 evaluates the original08:58 due, without a replacement interval.", checkpoint="after-clock-resume-expiry")

    before = states["before-readiness"]
    authority = authority_case("assess-readiness", named["assess_occ"]["occurrence_id"], ASSESS_FIELDS, named["T_0830"],
                               measured_at=plus_seconds(named["T_0830"], -901),
                               expect_refusal=("AUTHORITY_NOT_ESTABLISHED", [({"purpose": "SOURCE_OBSERVATION", "requirement_ref": "current-vitals-assess-readiness"}, "SOURCE_OBSERVATION_RELATIONS")]))
    after, result, event, _ = propose(before, "readiness-measurement-age901", named["assess_occ"], ASSESS_FIELDS, authority)
    record("timing-readiness-measurement-age901", before, event, after, result, "WITHHELD/SOURCE_OBSERVATION_RELATIONS",
           "Current response as_of08:30 does not renew measured_at08:14:59. No permit or actuation.", "after-stale-readiness")
    authority = authority_case("assess-readiness", named["assess_occ"]["occurrence_id"], ASSESS_FIELDS, named["T_0830"], measured_at=plus_seconds(named["T_0830"], -900))
    fresh, result, event, _ = propose(after, "readiness-measurement-age900", named["assess_occ"], ASSESS_FIELDS, authority)
    record("timing-readiness-measurement-age900", after, event, fresh, result, "PERMITTED",
           "Applicable record passes at the inclusive900-second boundary and re-evaluates the held proposal.")

    before = states["after-clock-4"]
    authority = authority_case("order-antibiotic", named["antibiotic_occ"]["occurrence_id"], named["order_fields"], named["T_0835"],
                               decision={"at": named["T_0834"], "attested_at": named["T_0835"], "tag": "stale"}, measured_at=plus_seconds(named["T_0835"], -901),
                               expect_refusal=("AUTHORITY_NOT_ESTABLISHED", [({"purpose": "SOURCE_OBSERVATION", "requirement_ref": "current-vitals-order-antibiotic"}, "SOURCE_OBSERVATION_RELATIONS")]))
    after, result, event, _ = propose(before, "antibiotic-measurement-age901", named["antibiotic_occ"], named["order_fields"], authority)
    record("timing-antibiotic-measurement-age901", before, event, after, result, "WITHHELD/SOURCE_OBSERVATION_RELATIONS",
           "Valid physician order and prior readiness do not excuse current stale measurement. Duty stays due08:58.")
    authority = authority_case("order-antibiotic", named["antibiotic_occ"]["occurrence_id"], named["order_fields"], named["T_0835"],
                               decision={"at": named["T_0834"], "attested_at": named["T_0835"], "tag": "fresh"}, measured_at=plus_seconds(named["T_0835"], -900))
    fresh, result, event, _ = propose(after, "antibiotic-measurement-age900", named["antibiotic_occ"], named["order_fields"], authority)
    record("timing-antibiotic-measurement-age900", after, event, fresh, result, "PERMITTED",
           "Patient-bound measurement passes at900 seconds. Permission does not discharge administration duty.")

    before = states["before-page-dispatch"]
    ack_none = {"status": "NONE", "reference": None, "observed_at": None}
    after, result, _, event = dispatch(before, "page-safe-not-sent", named["page_permit"], "page-safe-attempt", named["T_0802"], status="NOT_SENT",
                                       acknowledgement=ack_none, disposition="DISPATCH_REFUSED", reasons=["NATIVE_NOT_SENT"], occurrence_status="PERMITTED")
    record("timing-page-safe-not-sent", before, event, after, result, "DISPATCH_REFUSED/NATIVE_NOT_SENT", "Page timer stays WAITING without a trigger or due.")
    safe_page = after
    unknown_page, result, _, event = dispatch(before, "page-possible-send", named["page_permit"], "page-unknown-attempt", named["T_0802"], status="UNKNOWN",
                                              acknowledgement=ack_none, disposition="DISPATCH_RECORDED", reasons=["DISPATCH_STATUS_UNKNOWN"])
    record("timing-page-possible-send", before, event, unknown_page, result, "DISPATCH_RECORDED/DISPATCH_STATUS_UNKNOWN",
           "Possible send08:02 arms due08:17, without proving attending acknowledgement.", "after-possible-page-send")
    later = record_clock("timing-page-before-ack-update", unknown_page, "3", plus_seconds(T0, 600), "CLOCK_RECORDED", "First trigger and08:17 due remain.")
    updated, result, _, event = dispatch(later, "page-possible-send-ack-update", named["page_permit"], "page-unknown-attempt", named["T_0802"], status="UNKNOWN",
                                         acknowledgement={"status": "ACCEPTED", "reference": "page-unknown-accepted", "observed_at": plus_seconds(T0, 600)})
    record("timing-page-ack-update-no-reset", later, event, updated, result, "ACKNOWLEDGED",
           "Stable attempt updates connector acknowledgement only. Trigger08:02 and due08:17 remain.")
    late_acceptance = record_clock("timing-safe-page-before-late-acceptance", safe_page, "3", plus_seconds(T0, 600), "CLOCK_RECORDED", "Safe NOT_SENT still leaves timer WAITING.")
    after, result, _, event = dispatch(late_acceptance, "page-safe-attempt-late-acceptance", named["page_permit"], "page-safe-attempt", named["T_0802"], status="NOT_SENT",
                                       acknowledgement={"status": "ACCEPTED", "reference": "safe-page-late-accepted", "observed_at": plus_seconds(T0, 600)},
                                       disposition="DISPUTED", reasons=["DISPATCH_EVIDENCE_CONFLICT"], occurrence_status="OUTCOME_UNKNOWN")
    record("timing-safe-page-late-accepted-trigger", late_acceptance, event, after, result, "DISPUTED/DISPATCH_EVIDENCE_CONFLICT",
           "First qualifying accepted update08:10 uses original attempted_at08:02 and arms due08:17, while retaining original contradictory facts.")
    after, result, _, event = dispatch(before, "page-contradictory-accepted", named["page_permit"], "page-contradictory-attempt", named["T_0802"], status="NOT_SENT",
                                       disposition="DISPUTED", reasons=["DISPATCH_EVIDENCE_CONFLICT"], occurrence_status="OUTCOME_UNKNOWN")
    record("timing-page-contradictory-accepted", before, event, after, result, "DISPUTED/DISPATCH_EVIDENCE_CONFLICT",
           "Accepted acknowledgement establishes possible send despite NOT_SENT, with conservative due08:17.")

    later = record_clock("timing-page-delayed-clock", states["after-alert-split"], "2", plus_seconds(T0, 840), "CLOCK_RECORDED", "Page stays WAITING despite earlier activation.")
    authority = authority_case("page-attending", named["page_occ"]["occurrence_id"], PAGE_FIELDS, plus_seconds(T0, 840))
    permitted, result, event, permit = propose(later, "page-delayed-proposal", named["page_occ"], PAGE_FIELDS, authority)
    record("timing-page-delayed-proposal", later, event, permitted, result, "PERMITTED", "Fresh permit08:14 does not arm the timer.")
    sent, result, _, event = dispatch(permitted, "page-delayed-send", permit, "page-delayed-attempt", plus_seconds(T0, 840))
    record("timing-page-delayed-send", permitted, event, sent, result, "ACKNOWLEDGED", "First08:14 send gives due08:29 independently of activation.", "after-delayed-page-send")
    record_clock("timing-page-expiry-equality", states["after-branch-dispatches"], "3", plus_seconds(T0, 1020), "EXPIRED",
                 "Due08:17 routes page to rapid response; labs and original hour-one bases remain.", checkpoint="after-page-expiry")

    before = states["after-antibiotic-dispatch"]
    unknown_order, result, event = unknown_effect(before, "unknown-antibiotic-administration", named["order_permit"], named["order_dispatch"], plus_seconds(T0, 3420))
    record("timing-antibiotic-outcome-unknown", before, event, unknown_order, result, "OUTCOME_RETAINED/UNKNOWN_OUTCOME", "No administration is proved. Duty remains PENDING.", "after-unknown-antibiotic")
    record_clock("timing-antibiotic-unknown-at-due", unknown_order, "5", HOUR_ONE_DUE, "STOPPED/EXPIRY_STOP", "Original08:58 duty expires; unknown outcome remains.", checkpoint="after-antibiotic-expiry")
    labs_stopped = record_clock("timing-labs-at-due-stop", states["after-page-effect"], "3", HOUR_ONE_DUE, "STOPPED/EXPIRY_STOP",
                                "Labs timeout cannot satisfy join; antibiotic expires unbound without an invented occurrence.", checkpoint="after-labs-expiry")
    evidence = native_evidence("screening-result-late", named["labs_permit"], "RESULTED", plus_seconds(T0, 3900), plus_seconds(T0, 3900))
    event = governed_effect_event(labs_stopped, "labs-native-result-late", named["labs_permit"], named["labs_dispatch"], evidence, [])

    def mutate_late(after, event_digest):
        after["outcomes"].append(outcome_record(event, event_digest, named["labs_permit"], named["labs_dispatch"], evidence, "LATE_MATCHED"))

    after, result = work_transition(labs_stopped, event, disposition="OUTCOME_RETAINED", reason_codes=["LATE_EFFECT"],
                                    details=[{"kind": "EFFECT", "classification": "LATE_MATCHED", "evidence_id": evidence["evidence_id"]}], permit=None, mutate=mutate_late)
    record("timing-labs-native-late-after-stop", labs_stopped, event, after, result, "OUTCOME_RETAINED/LATE_EFFECT",
           "Native result is retained with STOPPED state. No join or antibiotic target is created.", "after-late-labs-evidence")

    before = states["after-assess-dispatch"]
    evidence = native_evidence("readiness-reassess", named["assess_permit"], "COMPLETED", plus_seconds(T0, 1860), plus_seconds(T0, 1860), extra_fields=[field("readiness", "t.readiness", "REASSESS")])
    event = governed_effect_event(before, "readiness-reassess-effect", named["assess_permit"], named["assess_dispatch"], evidence, [])
    refresh_occ = occurrence("refresh-vitals", "1", [named["assess_occ"]["occurrence_id"]], [loop_segment("1")])

    def mutate_reassess(after, event_digest):
        close(after, named["assess_occ"], "SUCCEEDED", digest("native-evidence", evidence), plus_seconds(T0, 1860), typed("t.readiness", "REASSESS"),
              relationship_digest("LABEL", "assess-readiness", "refresh-vitals"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(event, event_digest, named["assess_permit"], named["assess_dispatch"], evidence, "MATCHED"))
        activate(after, refresh_occ, event_digest, None, after["revision"])

    reassess, result = work_transition(before, event, disposition="COMPLETED", reason_codes=[],
                                       details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
                                                route_detail([relationship_digest("LABEL", "assess-readiness", "refresh-vitals")], []),
                                                {"kind": "LABEL", "step_id": "assess-readiness", "observed_value": typed("t.readiness", "REASSESS")}], permit=None, mutate=mutate_reassess)
    record("timing-readiness-reassess", before, event, reassess, result, "COMPLETED/REASSESS", "Refresh activates in the loop; antibiotic duty stays unbound.")
    refresh_clock = record_clock("timing-refresh-after-measurement-stale", reassess, "4", plus_seconds(T0, 2760), "CLOCK_RECORDED", "At08:46 prior08:15 measurement is stale; no duty is due.")
    refresh_fields = [field("attempt_number", "t.count", "1"), field("patient_id", "t.identity", PATIENT), field("refresh_id", "t.identity", "refresh-5502")]
    authority = authority_case("refresh-vitals", refresh_occ["occurrence_id"], refresh_fields, plus_seconds(T0, 2760))
    after, result, event, _ = propose(refresh_clock, "refresh-with-stale-prior-measurement", refresh_occ, refresh_fields, authority)
    record("timing-refresh-with-stale-prior-measurement", refresh_clock, event, after, result, "PERMITTED", "No measurement prerequisite blocks obtaining fresh data.")

    before = states["after-branch-dispatches"]
    original_index = next(i for i, request in enumerate(trace_requests) if request["request_id"] == "sepsis-dispatch-page")
    event = copy.deepcopy(trace_requests[original_index]["input"]["event"])
    result = copy.deepcopy(trace_results[original_index]["result"])
    result.update(state=copy.deepcopy(before), state_digest=work_state_digest(before), replay=True)
    record("timing-exact-page-replay", before, event, before, result, "Historical ACKNOWLEDGED with replay:true", "Current state and original transaction remain; no new trigger or revision.")

    changed = copy.deepcopy(states["after-deployment"])
    changed["event_duties"][0]["due"] = plus_seconds(HOUR_ONE_DUE, 60)
    event = {**event_header("mutated-duty-clock", "CLOCK", changed), "clock": clock_record("1", T0), "activation_clocks": []}
    record("timing-mutated-fixed-due", changed, event, changed, unchanged_refusal(changed, "STATE_INVALID"), "REFUSED/STATE_INVALID", "Recomputed outer digest cannot rewrite fixed due.")

    for request_id, step_id, field_name, wrong_value, before, occurrence_row, proposal_fields in (
        ("timing-root-wrong-patient", "raise-alert", "patient_id", "patient-other", trace_requests[2]["input"]["state"], named["alert_occ"], ALERT_FIELDS),
        ("timing-labs-wrong-alert", "order-screening-labs", "alert_id", "alert-other", states["after-clock-2"], named["labs_occ"], LABS_FIELDS),
    ):
        altered_fields = copy.deepcopy(proposal_fields)
        next(row for row in altered_fields if row["name"] == field_name)["value"]["value"] = wrong_value
        authority = authority_case(step_id, occurrence_row["occurrence_id"], altered_fields, latest_clock(before)["observed_time"])
        _, _, event, _ = propose(before, request_id + "-event", occurrence_row, altered_fields, authority)
        record(request_id, before, event, before, unchanged_refusal(before, "BINDING_MISMATCH"), "REFUSED/BINDING_MISMATCH",
               "Exact initial recognition subjects reject a mismatched request before otherwise ready standing authority.")

    missing_anchor = copy.deepcopy(artifacts["deploy_input"])
    missing_anchor.pop("event_anchors")
    request = {"protocol": PROTOCOL, "request_id": "timing-deploy-missing-recognition", "operation": "deploy", "input": missing_anchor}
    requests.append(request)
    results.append(response(request, {"status": "REFUSED", "profile": PROFILE, "role": ROLE, "code": "EVIDENCE_UNAVAILABLE", "path": ""}))
    judgments.append({"id": request["request_id"], "expected_judgment": "REFUSED/EVIDENCE_UNAVAILABLE", "state_and_budget_consequence": "No initial state; review timestamp cannot supply missing native recognition."})

    for request_id, mutation, code in (
        ("timing-deploy-wrong-recognition-provider", lambda wrapper: wrapper["record"].update(provider="different-recognition-provider"), "BINDING_MISMATCH"),
        ("timing-deploy-recognition-time-order", lambda wrapper: wrapper["record"].update(event_time=DEPLOYMENT_CLOCK_AT), "CLOCK_INVALID"),
        ("timing-deploy-wrong-anchor-organization", lambda wrapper: wrapper.update(organization_id="different-hospital"), "BINDING_MISMATCH"),
        ("timing-deploy-wrong-anchor-definition", lambda wrapper: wrapper.update(work_class_digest="sha256:" + "7" * 64), "DEPENDENCY_MISMATCH"),
    ):
        deploy_input = copy.deepcopy(artifacts["deploy_input"])
        mutation(deploy_input["event_anchors"][0])
        rebind_initial_anchor(deploy_input)
        request = {"protocol": PROTOCOL, "request_id": request_id, "operation": "deploy", "input": deploy_input}
        requests.append(request)
        results.append(response(request, {"status": "REFUSED", "profile": PROFILE, "role": ROLE, "code": code, "path": ""}))
        judgments.append({"id": request_id, "expected_judgment": "REFUSED/" + code, "state_and_budget_consequence": "Coherent record/wrapper/authorization digests cannot excuse the isolated source identity or time fault."})

    unavailable_initial = clock_record("0", None)
    unavailable_initial["status"] = "UNAVAILABLE"
    for suffix, initial in (("overdue", clock_record("0", HOUR_ONE_DUE)), ("unavailable", unavailable_initial)):
        deploy_input, deploy_result, deployed, _ = build_deployment(artifacts["correspondence"], artifacts["source_confirmation"], artifacts["policy_decision"], initial_clock=initial)
        request = {"protocol": PROTOCOL, "request_id": "timing-deploy-initial-" + suffix, "operation": "deploy", "input": deploy_input}
        requests.append(request)
        results.append(response(request, deploy_result))
        judgments.append({"id": request["request_id"], "expected_judgment": "DEPLOYED", "state_and_budget_consequence": "Retain immutable recognition and fixed due; initial " + suffix + " clock invents no target occurrence."})
        checkpoints["after-initial-" + suffix] = deployed
        if suffix == "unavailable":
            record_clock("timing-initial-unavailable-resumed", deployed, "1", plus_seconds(HOUR_ONE_DUE, 60), "EXPIRED",
                         "First available time08:59 expires original unbound08:58 duties.", checkpoint="after-initial-unavailable-resume")

    before = record_clock("timing-antibiotic-before-late-binding", states["after-assess-dispatch"], "4", HOUR_ONE_DUE, "EXPIRED",
                          "Antibiotic duty expires unbound while readiness remains dispatched; no target is created.")
    evidence = native_evidence("readiness-late-binding", named["assess_permit"], "COMPLETED", plus_seconds(T0, 1860), plus_seconds(T0, 3900),
                               extra_fields=[field("readiness", "t.readiness", "READY")])
    event = governed_effect_event(before, "readiness-after-antibiotic-duty-expiry", named["assess_permit"], named["assess_dispatch"], evidence, [])

    def mutate_late_binding(after, event_digest):
        close(after, named["assess_occ"], "SUCCEEDED", digest("native-evidence", evidence), plus_seconds(T0, 1860), typed("t.readiness", "READY"),
              relationship_digest("LABEL", "assess-readiness", "order-antibiotic"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(event, event_digest, named["assess_permit"], named["assess_dispatch"], evidence, "MATCHED"))
        after["status"] = "STOPPED"

    after, result = work_transition(before, event, disposition="STOPPED", reason_codes=["EXPIRY_STOP"],
                                    details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
                                             {"kind": "DEADLINE", "deadline_ids": ["antibiotic-window"], "reasons": ["EXPIRY_STOP"]},
                                             route_detail([relationship_digest("LABEL", "assess-readiness", "order-antibiotic")], []),
                                             {"kind": "LABEL", "step_id": "assess-readiness", "observed_value": typed("t.readiness", "READY")}],
                                    permit=None, mutate=mutate_late_binding)
    record("timing-antibiotic-late-binding-stop", before, event, after, result, "STOPPED/EXPIRY_STOP",
           "Native READY retained. Atomic failed closure creates no target, permit or activation; duty stays EXPIRED unbound on original clock basis.", "after-antibiotic-late-binding")

    before = checkpoints["after-unbound-expiry"]
    evidence = native_evidence("alert-delivery-late-binding", named["alert_permit"], "DELIVERED", plus_seconds(T0, 60), plus_seconds(T0, 3900))
    event = governed_effect_event(before, "alert-delivery-after-unbound-duty-expiry", named["alert_permit"], named["alert_dispatch"], evidence, [])

    def mutate_late_delivery(after, event_digest):
        close(after, named["alert_occ"], "SUCCEEDED", digest("native-evidence", evidence), plus_seconds(T0, 60), None,
              relationship_digest("SEQUENCE", "raise-alert", "bundle-split"), completion_event_digest=event_digest)
        after["outcomes"].append(outcome_record(event, event_digest, named["alert_permit"], named["alert_dispatch"], evidence, "MATCHED"))
        after["status"] = "STOPPED"

    after, result = work_transition(before, event, disposition="STOPPED", reason_codes=["EXPIRY_STOP"],
                                    details=[{"kind": "EFFECT", "classification": "MATCHED", "evidence_id": evidence["evidence_id"]},
                                             {"kind": "DEADLINE", "deadline_ids": ["labs-hour-one"], "reasons": ["EXPIRY_STOP"]},
                                             route_detail([relationship_digest("SEQUENCE", "raise-alert", "bundle-split")], ["hour-one-bundle"])],
                                    permit=None, mutate=mutate_late_delivery)
    record("timing-alert-late-delivery-split-rollback", before, event, after, result, "STOPPED/EXPIRY_STOP",
           "Root delivery and SUCCEEDED survive; atomic failed split creates no branches, obligations, page timer or targets. Both duties stay EXPIRED unbound.", "after-alert-late-binding")

    before = record_clock("timing-page-historical-report-clock", states["before-page-dispatch"], "3", plus_seconds(T0, 2100), "CLOCK_RECORDED",
                          "No page fact has armed the WAITING timer; historical attempt can still be reported.")
    after, result, _, event = dispatch(before, "page-first-send-reported-late", named["page_permit"], "page-historical-attempt", named["T_0802"])
    record("timing-page-first-send-reported-late", before, event, after, result, "EXPIRED",
           "Original08:02 attempt arms08:17 and expires on retained08:35 timeline, routing rapid response without erasing the fact.", "after-page-late-first-report")

    for request_id, original, mutate in (
        ("timing-mutated-native-anchor", states["after-deployment"], lambda state: state["initial_event_anchors"][0]["record"].update(provider_record_id="substituted-recognition")),
        ("timing-mutated-first-trigger", checkpoints["after-possible-page-send"], lambda state: state["deferred_deadlines"][0]["trigger"].update(sequence="1")),
    ):
        changed = copy.deepcopy(original)
        mutate(changed)
        revision = str(max(int(clock["revision"]) for clock in changed["clocks"]) + 1)
        instant = latest_clock(changed)["observed_time"]
        event = {**event_header(request_id + "-event", "CLOCK", changed), "clock": clock_record(revision, instant), "activation_clocks": []}
        record(request_id, changed, event, changed, unchanged_refusal(changed, "STATE_INVALID"), "REFUSED/STATE_INVALID", "Outer digest cannot replace retained original evidence or firstness.")

    for request_id, prior, as_of, judgment in (
        ("timing-alert-cap-boundary", [plus_seconds(T0, -3000)], T0, "SATISFIED"),
        ("timing-alert-cap-exceeded", [plus_seconds(T0, -19800), plus_seconds(T0, -3000)], T0, "VIOLATED"),
        ("timing-alert-cap-stale", [plus_seconds(T0, -3000)], plus_seconds(T0, -1200), "INDETERMINATE"),
    ):
        request, key = aggregate_request(request_id, named["alert_occ"]["occurrence_id"], prior, as_of)
        count = str(len(prior) + 1) if judgment != "INDETERMINATE" else None
        reasons = [] if judgment == "SATISFIED" else (["BOUND_VIOLATED"] if judgment == "VIOLATED" else ["OBSERVATION_STALE"])
        requests.append(request)
        results.append(response(request, aggregate_result(key, judgment, count, reasons)))
        judgments.append({"id": request_id, "expected_judgment": judgment, "state_and_budget_consequence": "Host evaluates the separate aggregate before deployment."})
    return requests, results, judgments, checkpoints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-pin", required=True, help="Finalized timing pin supplied by the coordinating root agent")
    args = parser.parse_args()
    if args.expected_pin != PIN:
        raise SystemExit(f"candidate pin changed: requested {args.expected_pin}, manifest is {PIN}")
    for prerequisite in ("SOURCE-CHOICES.md", "DERIVATIONS.md", "EXPOSED-RULES.md"):
        if not (HERE / prerequisite).is_file():
            raise SystemExit("source judgments must precede construction: " + prerequisite)
    trace_requests, trace_results, states, named, artifacts = build_trace()
    scenario_requests, scenario_results, judgments, extra_checkpoints = build_scenarios(states, named, trace_requests, trace_results, artifacts)
    write("source-policy.json", SOURCE_POLICY)
    write("work-class.json", WORK_CLASS)
    write("alert-count-definition.json", AGGREGATE_DEFINITION)
    for key, name in (("readback", "readback-derived.json"), ("correspondence_input", "correspondence-input.json"),
                      ("correspondence", "correspondence-record.json"), ("source_confirmation", "source-confirmation-record.json"),
                      ("policy_decision", "policy-decision-record.json"), ("deploy_input", "deployment-input.json"),
                      ("deploy_result", "deployment-result-derived.json")):
        write(name, artifacts[key])
    write("initial-recognition-record.json", states["after-deployment"]["initial_event_anchors"][0])
    write("source-mapping.json", {"candidate_pin": PIN, "source_revision": "v5", "status": "DRAFT_SYNTHETIC_PROXY_ONLY",
                                  "mappings": artifacts["correspondence"]["mappings"], "residue": artifacts["correspondence"]["residue"]})
    for step in PROPOSAL_STEPS:
        write(f"authority/{step['id']}-definition.json", {"schema": SCHEMA + "authority-definition", "source": AUTHORITY_SOURCE,
                                                         "work_class": AUTHORITY_WORK_CLASS, "envelope": MATERIAL[step["id"]]["envelope"]})
    for request, result_row in zip(trace_requests, trace_results, strict=True):
        if request["operation"] == "step" and request["input"]["event"]["kind"] == "PROPOSE":
            step_id = request["input"]["event"]["occurrence"]["step_id"]
            write(f"authority/{step_id}-input.json", request["input"]["event"]["authority_input"])
            write(f"authority/{step_id}-result-derived.json", result_row["result"]["permit"]["authority_result"])
    for folder, requests, results in (("valid-trace", trace_requests, trace_results), ("scenarios", scenario_requests, scenario_results)):
        write(f"{folder}/requests.json", requests)
        write(f"{folder}/results-derived.json", results)
        write_lines(f"{folder}/requests.jsonl", requests)
        write_lines(f"{folder}/results-derived.jsonl", results)
    write("valid-trace/final-work-state.json", trace_results[-1]["result"]["state"])
    write("scenarios/expectations.json", {"candidate_pin": PIN, "status": "INDEPENDENT_CONSTRUCTION_NOT_CONSUMER_VERIFIED",
                                          "method": "SOURCE-CHOICES.md and DERIVATIONS.md precede fixture construction. No consumer code is imported or invoked.",
                                          "valid_trace_request_count": str(len(trace_requests)), "scenario_request_count": str(len(scenario_requests)), "scenarios": judgments})
    checkpoints = {"candidate_pin": PIN, "digest_kind": "work-state", "checkpoints": []}
    for name, state in sorted({**states, **extra_checkpoints}.items(), key=lambda item: utf8(item[0])):
        path = f"restart/{name}-work-state.json"
        write(path, state)
        checkpoints["checkpoints"].append({"path": path, "state_digest": work_state_digest(state), "revision": state["revision"]})
    write("restart/checkpoints.json", checkpoints)
    index = {"candidate_pin": PIN, "construction": "INDEPENDENT_FIXED_CONSTRUCTOR", "status": "DRAFT_NOT_CONSUMER_VERIFIED", "files": []}
    for path in sorted(HERE.rglob("*.json")) + sorted(HERE.rglob("*.jsonl")):
        if path.name != "artifact-index.json":
            index["files"].append({"path": path.relative_to(HERE).as_posix(), "sha256": raw_sha(path.read_bytes())})
    write("artifact-index.json", index)
    print(json.dumps({"candidate_pin": PIN, "valid_trace_requests": len(trace_requests), "scenario_requests": len(scenario_requests),
                      "checkpoints": len(checkpoints["checkpoints"]), "consumer_executions": 0}))


if __name__ == "__main__":
    main()
