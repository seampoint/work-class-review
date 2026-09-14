#!/usr/bin/env python3
"""Build the roe-engagement specimen from the draft-2 normative contract.

Fixed specimen constructor, not an evaluator. Every expected judgment, state and
digest is the executable form of DERIVATIONS.md, derived from the specification
text before either draft-2 implementation ran on this specimen. Synthetic
scenario: no claim about any weapons system, doctrine, engagement or perception
model, and no endorsement by the SEI, CMU, Andrew Mellinger or the DoD.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
PIN = "sha256:" + hashlib.sha256(
    (HERE.parents[4] / "library/work-class-specification/1.0.0-draft.2/contract-manifest.json").read_bytes()
).hexdigest()
PREFIX = b"seampoint.work-class/1.0.0-draft.2/"
SCHEMA = "seampoint.work-class/1.0.0-draft.2/"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.2"
PROFILE = "DEADLINES"
ROLE = "DEADLINE_RUNTIME"
ORG = "sample-force-organization"
CLOCK = "mission-clock"
ANCHOR = "engagements-per-window"
STEP = "engage-track"
INSTANCE_A = "roe-engagement-instance-a"
INSTANCE_B = "roe-engagement-instance-b"

T_AUTH = "2026-09-13T09:50:00Z"
T_DEPLOY_CLOCK = "2026-09-13T09:55:00Z"
T0 = "2026-09-13T10:00:00Z"
T1 = "2026-09-13T10:01:00Z"
T2 = "2026-09-13T10:02:00Z"
T3 = "2026-09-13T10:05:00Z"
T_EXPIRY = "2026-09-13T10:03:00Z"
T_DUE = "2026-09-13T10:10:00Z"
T_B3 = "2026-09-13T10:06:00Z"
GRANT_AT = "2026-09-13T06:00:00Z"
GRANT_ATTEST_AT = "2026-09-13T06:01:00Z"
DISPATCH_AT = "2026-09-13T10:01:30Z"
ACK_AT = "2026-09-13T10:01:45Z"
EFFECT_TIME = "2026-09-13T10:01:50Z"
EFFECT_OBSERVED = "2026-09-13T10:04:30Z"
FOREIGN_TIME = "2026-09-13T10:01:55Z"
FOREIGN_OBSERVED = "2026-09-13T10:04:40Z"
HISTORY_1 = "2026-09-13T09:20:00Z"
HISTORY_2 = "2026-09-13T09:40:00Z"
ENVELOPE_FROM = "2026-09-13T06:00:00Z"
ENVELOPE_UNTIL = "2026-09-14T06:00:00Z"
VALID_FROM = "2026-09-01T00:00:00Z"
VALID_UNTIL = "2026-10-01T00:00:00Z"
DEPLOY_EXPIRES = "2026-09-14T00:00:00Z"
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
        return "[" + ",".join(canonical_text(row) for row in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(canonical_text(key) + ":" + canonical_text(value[key]) for key in sorted(value, key=key_order)) + "}"
    raise TypeError(type(value).__name__)


def canonical_bytes(value) -> bytes:
    return canonical_text(value).encode("utf-8")


def digest(kind: str, value) -> str:
    return "sha256:" + hashlib.sha256(PREFIX + kind.encode() + b"\n" + canonical_bytes(value)).hexdigest()


def raw_sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def omit(value: dict, *keys: str) -> dict:
    answer = copy.deepcopy(value)
    for key in keys:
        answer.pop(key, None)
    return answer


def sorted_utf8(values):
    return sorted(values, key=lambda row: row.encode("utf-8") if isinstance(row, str) else canonical_bytes(row))


def write(relative: str, value) -> None:
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def write_lines(relative: str, rows: list) -> None:
    (HERE / relative).write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))


def typed(type_ref: str, value: str) -> dict:
    return {"type_ref": type_ref, "value": value}


def field(name: str, type_ref: str, value: str) -> dict:
    return {"name": name, "value": typed(type_ref, value)}


def add_seconds(instant: str, seconds: int) -> str:
    value = dt.datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return (value + dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def available_clock(revision: str, observed_time: str, source: str = CLOCK) -> dict:
    return {"source": source, "revision": revision, "status": "AVAILABLE", "observed_time": observed_time,
            "evidence_digest": digest("specimen-clock-evidence", {"source": source, "revision": revision, "time": observed_time})}


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
    return sorted(lines, key=lambda line: line["path"].encode("utf-8"))


def work_state_digest(state: dict) -> str:
    projection = copy.deepcopy(state)
    for replay in projection["replays"]:
        replay.pop("transaction_digest")
    return digest("work-state", projection)


def work_transition(before: dict, event: dict, *, disposition: str, reasons: list[str], details: list[dict],
                    permit: dict | None, budget_results: list[dict], authority_result_digest: str | None,
                    reservation_receipt_digests: list[str], mutate) -> tuple[dict, dict]:
    event_digest = digest("runtime-event", event)
    after = copy.deepcopy(before)
    after["revision"] = str(int(before["revision"]) + 1)
    mutate(after, event_digest)
    core = copy.deepcopy(after)
    core["receipts"] = []
    core["replays"] = []
    core_digest = digest("work-state-core", core)
    receipt = {
        "schema": SCHEMA + "decision-receipt", "decision_id": "sha256:" + "0" * 64, "instance_id": event["instance_id"],
        "sequence": after["revision"], "event_id": event["event_id"], "event_digest": event_digest, "event_kind": event["kind"],
        "disposition": disposition, "reason_codes": sorted_utf8(reasons), "details": details,
        "permit_digest": permit["permit_id"] if permit else (event.get("permit") or {}).get("permit_id"),
        "authority_result_digest": authority_result_digest, "reservation_receipt_digests": reservation_receipt_digests,
        "state_before_digest": work_state_digest(before), "state_after_core_digest": core_digest,
    }
    receipt["decision_id"] = digest("decision-receipt", omit(receipt, "decision_id"))
    transaction_digest = digest("lifecycle-transaction", {
        "state_before_digest": receipt["state_before_digest"], "event_digest": event_digest,
        "decision_receipt_digest": receipt["decision_id"], "state_after_core_digest": core_digest, "budget_results": budget_results,
    })
    replay = {"event_id": event["event_id"], "event_digest": event_digest, "decision": receipt, "decision_receipt_digest": receipt["decision_id"],
              "permit": permit, "budget_results": budget_results, "transition_state_digest": core_digest, "transaction_digest": transaction_digest}
    after["receipts"].append(receipt)
    after["replays"].append(replay)
    after["replays"].sort(key=lambda row: row["event_id"].encode("utf-8"))
    return after, {"status": "STEP", "profile": PROFILE, "role": ROLE, "decision": receipt, "decision_digest": receipt["decision_id"],
                   "permit": permit, "budget_results": budget_results, "state": after, "state_digest": work_state_digest(after),
                   "transition_state_digest": core_digest, "transaction_digest": transaction_digest, "replay": False}


def reservation_state_digest(state: dict) -> str:
    return digest("reservation-state", state)


def reservation_transition(before: dict, event: dict, host: dict, *, decision: str, reservation_id: str | None,
                           budgets: list[dict], authority_result, reasons: list[str], mutate) -> tuple[dict, dict]:
    event_digest = digest("reservation-event", event)
    after = copy.deepcopy(before)
    after["core"]["revision"] = str(int(before["core"]["revision"]) + 1)
    if event["clock"]["status"] == "AVAILABLE":
        after["core"]["last_clock"] = event["clock"]["instant"]
    mutate(after)
    core_digest = digest("reservation-core", after["core"])
    receipt = {"event_digest": event_digest, "prior_state_digest": reservation_state_digest(before), "revision": after["core"]["revision"],
               "next_core_digest": core_digest, "decision": decision, "reservation": reservation_id, "budgets": budgets,
               "authority_result": authority_result, "reasons": sorted_utf8(reasons)}
    after["receipts"].append({"event": event, "host_evidence": host, "receipt": receipt})
    return after, {"status": "TRANSITION", "receipt": receipt, "receipt_digest": digest("reservation-receipt", receipt),
                   "state": after, "state_digest": reservation_state_digest(after), "replay": False}


def occurrence(definition_digest: str, instance_id: str, step_id: str, ordinal: str, predecessors: list[str]) -> dict:
    subject = {"specification_pin": PIN, "work_class_digest": definition_digest, "instance_id": instance_id, "step_id": step_id,
               "ordinal": ordinal, "predecessor_occurrence_ids": sorted_utf8(predecessors), "enclosing": [], "object_key": None}
    return {"occurrence_id": digest("occurrence", subject), **subject}


def step_request(request_id: str, work_class: dict, state: dict, event: dict) -> dict:
    return {"protocol": PROTOCOL, "request_id": request_id, "operation": "step",
            "input": {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class,
                      "definition_digest": digest("work-class-definition", work_class), "state": state,
                      "state_digest": work_state_digest(state), "event": event}}


def response(request: dict, result: dict) -> dict:
    return {"protocol": PROTOCOL, "request_id": request["request_id"], "operation": request["operation"], "result": result}


# ---------------------------------------------------------------------------
# Static contract: source policy, work class, authority projections.
# ---------------------------------------------------------------------------

OBLIGATIONS = [
    ("roe-01-deadly-force-threat", "Fire may be proposed against a track only when the observation record shows the track fires at, aims a weapon at, or otherwise demonstrates an intent to imminently attack the unit, friendly forces, or persons or property under designated protection. The declared intent values are AIMS_WEAPON_AT_FRIENDLY, FIRES_AT_FRIENDLY and DEMONSTRATES_IMMINENT_ATTACK; any other value withholds the proposal.", "RA 2.3.1 rule a and (1)"),
    ("roe-02-protected-status-bars-fire", "A track whose protected status is other than NONE is never a permitted subject.", "RA 4.3, protected entities marked as an invalid target; a synthetic extension, since RA 2.3.1 (1) names protected persons as parties whose endangerment justifies fire, not as barred targets"),
    ("roe-03-declared-threat-class-and-confidence", "The nominated track carries a declared threat class (ARMED_ADULT or ARMED_QUADRUPED) with classification confidence at or above 0.9. A lower confidence or an undeclared class withholds the proposal until a fresh observation is proposed.", "RA 2.3.1 requirement 1; RA 5.7.2 confidence thresholds; RA Appendix A classes"),
    ("roe-04-rules-held-as-one-admitted-grant", "The rules of engagement are one reusable grant issued by the engagement commander at an exact revision, valid for the mission window and withdrawable through the command revocation source. A withdrawn or expired grant withholds every later proposal and leaves committed engagements and their evidence in place.", "RA 2.3.1 requirement 1; RA 5.7.2"),
    ("roe-05-operator-decision-per-engagement", "Every engagement requires an accepted per-instance decision by the engagement authority operator on the exact nominated track, organizationally attested. The resulting permit authorizes at most one dispatch of the exact request and expires 120 seconds after the proposal clock; after expiry a fresh proposal and a fresh operator decision are required.", "RA 2.1.3; RA 5.5.7; RA 2.4.1 finding 1"),
    ("roe-06-direction-or-safe-state", "When a nomination diverges from these rules the proposal is withheld and the operator's direction is required. If no direction produces a permitted engagement within ten minutes of the occurrence's activation on the mission clock, the engagement occurrence stops and no dispatch may follow.", "RA 2.3.1 requirement 3; GB 3.3.13"),
    ("roe-07-engagement-count-budget", "At most three engagements per mission may be committed or reserved within any rolling one-hour window on the mission clock, counted across every platform sharing the mission budget and including reserved engagements whose effect is not yet established.", "RA 5.7.2; RA 2.1.4; synthetic bound"),
    ("roe-08-effect-established-only-by-assessment", "An engagement completes only on attributable battle damage assessment evidence for the exact dispatched request. A dispatch acknowledgement is not an effect. An unavailable assessment keeps the engagement open and its reservation charged. An assessment naming another entity, or conflicting evidence, is retained as disputed and blocks further engagements on the affected budget partition.", "RA 5.5.8; RA 4.6"),
    ("roe-09-runtime-traceability", "Every rule ingestion, proposal, permit, dispatch observation, effect observation and clock is retained as a record bound by digest to its predecessors, and every decision carries its reason codes so the record shows how the system decided.", "RA 2.3.1 requirements 2 and 4; GB 3.3.14"),
]

ENGAGE_FIELDS = [
    {"name": "classification", "type_ref": "t.label"},
    {"name": "confidence", "type_ref": "t.confidence"},
    {"name": "demonstrated_intent", "type_ref": "t.label"},
    {"name": "mission_id", "type_ref": "t.identity"},
    {"name": "protected_status", "type_ref": "t.label"},
    {"name": "track_id", "type_ref": "t.identity"},
]


def proposal_fields(track_id: str, *, classification: str = "ARMED_ADULT", confidence: str = "0.96",
                    demonstrated_intent: str = "AIMS_WEAPON_AT_FRIENDLY", protected_status: str = "NONE") -> list[dict]:
    return [field("classification", "t.label", classification), field("confidence", "t.confidence", confidence),
            field("demonstrated_intent", "t.label", demonstrated_intent), field("mission_id", "t.identity", "mission-1"),
            field("protected_status", "t.label", protected_status), field("track_id", "t.identity", track_id)]


def build_static_contract() -> tuple[dict, dict, dict, dict]:
    source = {
        "artifact_kind": "NON_NORMATIVE_SYNTHETIC_SOURCE_POLICY",
        "candidate_pin": PIN,
        "id": "roe-engagement-rules",
        "revision": "r1",
        "status": "SYNTHETIC_DERIVED_FROM_RA_2_3_1_PENDING_INDEPENDENT_REVIEW",
        "claim_boundary": "Synthetic scenario. No claim about any weapons system, doctrine, the lawfulness of any engagement or the accuracy of any perception model. No endorsement by the SEI, Carnegie Mellon University, Andrew Mellinger or the Department of Defense is implied.",
        "sources": [
            {"citation": "Mellinger, Heim, Schellenberg, Newman, Brooks and Loughin, Reference Architecture for Assuring Ethical Conduct in LAWS, SEI, April 2025, DOI 10.1184/R1/28700720, Distribution Statement A", "sections": ["2.1.4", "2.3", "2.3.1", "4.1", "4.3", "4.6", "5.1", "5.5.6", "5.5.7", "5.5.8", "5.7.1", "5.7.2", "Appendix A"]},
            {"citation": "Mellinger, Brooks, Fairfax and Justice, CaTE Guidebook for the Development and TEVV of LAWS to Promote Trustworthiness, SEI, April 2025, DOI 10.1184/R1/28701104, Distribution Statement A", "sections": ["2.1", "3.3.13", "3.3.14"]},
        ],
        "rule_paraphrase": "A unit may open fire only when it, friendly forces, or persons or property under its protection are threatened with deadly force, which includes an individual who fires or aims a weapon at them or otherwise demonstrates an intent to attack imminently (RA 2.3.1, from the Operational Law Handbook). RA 2.3.1 derives four requirements: configurable predefined principles, runtime traceability of their ingestion, storage and use, user direction when a situation diverges with a safe state otherwise, and communication of how the system decided.",
        "obligations": [{"id": oid, "text": text, "basis": basis} for oid, text, basis in OBLIGATIONS],
        "observation_declarations": [
            {"field": "track_id", "type_ref": "t.identity", "produced_by": "path tracker and entity registrar (RA 5.5.2, 5.5.3)", "condition": None, "role": "scope subject binding"},
            {"field": "mission_id", "type_ref": "t.identity", "produced_by": "mission goals (RA 5.7)", "condition": None, "role": "scope resource constant mission-1 and budget key"},
            {"field": "classification", "type_ref": "t.label", "produced_by": "object detector and classifier (RA 5.5.1, Appendix A)", "condition": "roe-classification-is-declared-threat", "role": "MEMBER of ARMED_ADULT, ARMED_QUADRUPED"},
            {"field": "confidence", "type_ref": "t.confidence", "produced_by": "classifier (RA Appendix A)", "condition": "roe-confidence-at-or-above-bound", "role": "COMPARE GTE 0.9"},
            {"field": "protected_status", "type_ref": "t.label", "produced_by": "scene understanding (RA 5.5.5)", "condition": "roe-target-not-protected", "role": "EQUAL NONE"},
            {"field": "demonstrated_intent", "type_ref": "t.label", "produced_by": "activity recognizer (RA 5.5.4)", "condition": "roe-demonstrated-intent-present", "role": "MEMBER of AIMS_WEAPON_AT_FRIENDLY, DEMONSTRATES_IMMINENT_ATTACK, FIRES_AT_FRIENDLY"},
        ],
        "required_scenarios": [
            "threat observed, engagement proposed, grant current, operator authorization inside its window, dispatch, effect evidence, completion",
            "classification confidence below the configured bound: withheld, occurrence held",
            "target of designated protected status: withheld",
            "operator authorization expires before dispatch: dispatch refused, fresh proposal required",
            "demonstrated intent absent: withheld; no direction by the deadline: stop",
            "dispatch arguments name a different track: refused as outside the permit",
            "dispatch acknowledged, damage assessment unavailable: unknown outcome, occurrence open",
            "effect evidence names a different entity: foreign effect, disputed, retained",
            "rules of engagement withdrawn mid-mission: next proposal withheld, committed effects stand",
            "engagement count per window as a shared budget: two proposals against the last allocation",
            "restart between every lifecycle stage and exact replay",
        ],
    }
    types = [
        {"id": "t.confidence", "kind": "DECIMAL", "nonnegative": True, "unit": None},
        {"id": "t.identity", "kind": "IDENTITY", "nonnegative": False, "unit": None},
        {"id": "t.label", "kind": "STRING", "nonnegative": False, "unit": None},
        {"id": "t.status", "kind": "STRING", "nonnegative": False, "unit": None},
    ]
    completion = {
        "effect_provider": "bda-provider", "effect_source": "bda-assessment-ledger", "effect_record_type": "engagement-effect",
        "no_effect_provider": "bda-provider", "no_effect_source": "bda-assessment-ledger", "no_effect_record_type": "engagement-no-effect",
        "status_field": "status", "status_type_ref": "t.status",
        "success_values": [typed("t.status", "NEUTRALIZED")], "failure_values": [typed("t.status", "MISSED")],
        "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": row["name"], "evidence_field": row["name"]} for row in ENGAGE_FIELDS],
    }
    engage_step = {
        "id": STEP, "kind": "OPERATION", "executor_role": "fire-control-agent", "interface": "fire-control", "operation": "engage-track",
        "fields": ENGAGE_FIELDS, "scope_fields": {"subjects": ["track_id"], "resources": ["mission_id"]},
        "required_credentials": ["fire-control-credential"], "authority_requirements": ["roe-engagement-authority"],
        "shared_budgets": [ANCHOR], "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": "120",
        "failure_behavior": "STOP", "completion": completion,
    }
    terminal = {"id": "complete", "kind": "TERMINAL", "executor_role": None, "interface": None, "operation": None, "fields": [],
                "scope_fields": None, "required_credentials": [], "authority_requirements": [], "shared_budgets": [],
                "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": None, "failure_behavior": None, "completion": None}
    work_class = {
        "schema": SCHEMA + "work-class-definition", "specification_pin": PIN, "id": "roe-engagement", "revision": "r1", "profile": PROFILE,
        "root": STEP,
        "participants": [
            {"id": "commanding-officer-person", "role": "engagement-commander", "kind": "PERSON"},
            {"id": "fire-control-agent-1", "role": "fire-control-agent", "kind": "AGENT"},
            {"id": "operator-person-1", "role": "engagement-authority-operator", "kind": "PERSON"},
        ],
        "objects": [], "types": types, "steps": [terminal, engage_step],
        "relationships": [{"kind": "SEQUENCE", "from": STEP, "to": "complete"}],
        "choices": [], "occurrence_limits": [{"step_id": STEP, "maximum": "1"}], "loops": [],
        "deadlines": [{"id": "operator-direction-deadline", "step_id": STEP, "clock_source": CLOCK,
                       "due": {"kind": "ELAPSED_DURATION", "value": "10", "unit": "MINUTE"}, "boundary": "AT_OR_AFTER", "expiry_target": None}],
        "parallel_blocks": [], "fanouts": [], "shared_budgets": [ANCHOR],
        "limits": {"maximum_proposals": "8", "maximum_activations": "1", "maximum_actuations": "1", "maximum_active_obligations": "0", "maximum_fanout_objects": "0"},
        "source": {"id": source["id"], "revision": source["revision"], "obligations": [row[0] for row in OBLIGATIONS]},
    }
    authority_source = {"schema": SCHEMA + "authority-source", "id": source["id"], "revision": source["revision"],
                        "obligations": [{"id": oid, "text": text} for oid, text, _ in OBLIGATIONS]}
    authority_work_class = {
        "schema": SCHEMA + "authority-work-class", "id": work_class["id"], "revision": work_class["revision"],
        "types": [row for row in types if row["id"] != "t.status"],
        "steps": [{"id": engage_step["id"], "operation": engage_step["operation"], "interface": engage_step["interface"],
                   "executor_role": engage_step["executor_role"], "fields": engage_step["fields"], "scope_fields": engage_step["scope_fields"],
                   "required_credentials": engage_step["required_credentials"]}],
    }
    return source, work_class, authority_source, authority_work_class


# ---------------------------------------------------------------------------
# Authority: the reusable grant (rules of engagement) and the per-instance operator act.
# ---------------------------------------------------------------------------

CONDITIONS = [
    {"id": "roe-classification-is-declared-threat", "step": STEP,
     "predicate": {"kind": "MEMBER", "value": {"kind": "FIELD", "name": "classification"}, "members": [typed("t.label", "ARMED_ADULT"), typed("t.label", "ARMED_QUADRUPED")]}},
    {"id": "roe-confidence-at-or-above-bound", "step": STEP,
     "predicate": {"kind": "COMPARE", "left": {"kind": "FIELD", "name": "confidence"}, "right": {"kind": "LITERAL", "value": typed("t.confidence", "0.9")}, "operator": "GTE"}},
    {"id": "roe-demonstrated-intent-present", "step": STEP,
     "predicate": {"kind": "MEMBER", "value": {"kind": "FIELD", "name": "demonstrated_intent"},
                   "members": [typed("t.label", "AIMS_WEAPON_AT_FRIENDLY"), typed("t.label", "DEMONSTRATES_IMMINENT_ATTACK"), typed("t.label", "FIRES_AT_FRIENDLY")]}},
    {"id": "roe-target-not-protected", "step": STEP,
     "predicate": {"kind": "EQUAL", "left": {"kind": "FIELD", "name": "protected_status"}, "right": {"kind": "LITERAL", "value": typed("t.label", "NONE")}}},
]
CRITERION = "engage-track-operator-confirms-exact-proposal"
REVOCATION = {"provider": "command-authority-provider", "source": "roe-revocations", "max_age_seconds": "300"}
IDP = "command-identity-provider"
CHANNEL = "command-authority-return-channel"
GRANTOR = "commanding-officer-person"
GRANTOR_ROLE = "engagement-commander"
ATTESTER = "command-attester-person"
OPERATOR = "operator-person-1"
OPERATOR_ROLE = "engagement-authority-operator"
EXECUTOR = "fire-control-agent-1"
EXECUTOR_ROLE = "fire-control-agent"
ENVELOPE_ID = "roe-engagement-authority"


def build_authority(authority_source: dict, authority_work_class: dict, *, instance_id: str, occurrence_row: dict,
                    fields: list[dict], now: str, decide_at: str, attest_at: str, revoked: bool = False,
                    conditions: list[dict] | None = None, escalation: dict | None = None) -> dict:
    conditions = CONDITIONS if conditions is None else conditions
    escalation = {"kind": "REQUIRED", "destination_role": OPERATOR_ROLE, "authority_ref": ENVELOPE_ID, "decision_required": "operator-direction-on-divergence"} if escalation is None else escalation
    step = authority_work_class["steps"][0]
    source_digest = digest("authority-source", authority_source)
    work_class_digest = digest("authority-work-class", authority_work_class)
    binding_id = f"{STEP}-track_id-binding"
    envelope = {
        "schema": SCHEMA + "authority-envelope", "id": ENVELOPE_ID, "source_digest": source_digest, "work_class_digest": work_class_digest,
        "source_obligations": [row["id"] for row in authority_source["obligations"]], "principal": ORG,
        "grantor_role": GRANTOR_ROLE, "executor_role": EXECUTOR_ROLE, "attester_role": "organizational-attester",
        "grant_ref": f"{STEP}-grant", "clock_source": CLOCK,
        "bindings": [{"id": binding_id, "step": STEP, "field": "track_id", "type_ref": "t.identity"}],
        "scope": {"id": f"{STEP}-scope", "subjects": [{"kind": "BINDING", "binding": binding_id}], "resources": [{"kind": "CONSTANT", "value": "mission-1"}]},
        "operations": [{"step": STEP, "operation": step["operation"], "interface": step["interface"]}],
        "limits": {"per_action": [], "shared_budgets": [ANCHOR]},
        "conditions": conditions,
        "enforcement": {"mechanisms": ["ATOMIC_SHARED_RESERVATION", "AUTHORITY_BEFORE_RESERVATION"], "safe_state": "NO_NEW_DISPATCH", "out_of_envelope": "REFUSE"},
        "escalation": escalation,
        "revocation": REVOCATION,
        "temporal_validity": {"valid_from": ENVELOPE_FROM, "valid_until": ENVELOPE_UNTIL},
        "gate": {"materiality": "HIGH", "reversibility": "NONE", "kind": "DECIDE", "role": OPERATOR_ROLE,
                 "criteria": [{"id": CRITERION, "step": STEP, "predicate": {"kind": "BOOLEAN", "value": True}}]},
        "limitations": [],
    }
    envelope_digest = digest("authority-envelope", envelope)
    executor_occupancy = f"{STEP}-executor-occupancy"
    grantor_occupancy = f"{STEP}-grantor-occupancy"
    gate_occupancy = f"{STEP}-operator-occupancy"
    attester_occupancy = f"{STEP}-attester-occupancy"
    occupancy_specs = [
        (attester_occupancy, ATTESTER, "organizational-attester", "HUMAN"),
        (executor_occupancy, EXECUTOR, EXECUTOR_ROLE, "MACHINE"),
        (grantor_occupancy, GRANTOR, GRANTOR_ROLE, "HUMAN"),
        (gate_occupancy, OPERATOR, OPERATOR_ROLE, "HUMAN"),
    ]
    validity = {"valid_from": VALID_FROM, "valid_until": VALID_UNTIL}
    occupancies = sorted([{"id": oid, "actor": actor, "role": role, "principal": ORG, "kind": kind, "validity": validity, "provider": IDP,
                           "evidence_ref": oid + "-evidence"} for oid, actor, role, kind in occupancy_specs], key=lambda row: row["id"].encode())
    capacity_specs = [
        (f"{STEP}-attester-capacity", ATTESTER, "organizational-attester", attester_occupancy, ["ORGANISATIONAL_ATTESTATION"]),
        (f"{STEP}-grantor-capacity", GRANTOR, GRANTOR_ROLE, grantor_occupancy, ["GRANT"]),
        (f"{STEP}-operator-capacity", OPERATOR, OPERATOR_ROLE, gate_occupancy, ["INSTANCE_DECISION"]),
    ]
    root = {
        "schema": SCHEMA + "authority-root", "id": f"{STEP}-authority-root", "revision": "r1", "designator": "sample-command-authority-office",
        "principal": ORG, "source_digest": source_digest, "work_class_digest": work_class_digest, "envelope_digest": envelope_digest,
        "capacity_ids": sorted_utf8([row[0] for row in capacity_specs]), "occupancy_ids": sorted_utf8([row[0] for row in occupancy_specs]),
        "providers": sorted_utf8([IDP, REVOCATION["provider"]]),
        "channels": [{"id": CHANNEL, "provider": IDP, "validity": validity, "prior_returns_survive_expiry": False}],
        "validity": validity, "revocation": REVOCATION, "prior_acts_survive_expiry": False, "allow_self_attestation": False, "limitations": [],
    }
    root_digest = digest("authority-root", root)
    capacities = sorted([{"id": cid, "root_digest": root_digest, "envelope_digest": envelope_digest, "actor": actor, "role": role, "principal": ORG,
                          "occupancy": occ, "act_kinds": kinds, "validity": validity, "revocation": REVOCATION, "reliance": {"kind": "CURRENT_ONLY"},
                          "may_self_attest": False, "provider": IDP, "evidence_ref": cid + "-evidence"}
                         for cid, actor, role, occ, kinds in capacity_specs], key=lambda row: row["id"].encode())
    credential = {"id": f"{STEP}-fire-control-credential", "actor": EXECUTOR, "occupancy": executor_occupancy, "kind": "fire-control-credential",
                  "step": STEP, "operation": step["operation"], "interface": step["interface"], "validity": validity, "revocation": REVOCATION,
                  "provider": IDP, "evidence_ref": f"{STEP}-credential-evidence"}
    executor = {"actor": EXECUTOR, "role": EXECUTOR_ROLE, "principal": ORG, "occupancy": executor_occupancy}
    authority_proposal = {"schema": SCHEMA + "authority-proposal", "work_class_digest": work_class_digest, "work_class": authority_work_class["id"],
                          "instance": instance_id, "occurrence": occurrence_row["occurrence_id"], "step": STEP, "operation": step["operation"],
                          "interface": step["interface"], "executor": executor, "fields": fields}
    proposal_digest = digest("authority-proposal", authority_proposal)
    operation_digest = digest("authority-operation", {"envelope_digest": envelope_digest, "work_class_digest": work_class_digest, "proposal_digest": proposal_digest})
    capacity_by_kind = {kind: row for row in capacities for kind in row["act_kinds"]}
    grant = {"id": f"{STEP}-grant", "kind": "GRANT", "actor": GRANTOR, "role": GRANTOR_ROLE, "principal": ORG, "occupancy": grantor_occupancy,
             "capacity": capacity_by_kind["GRANT"]["id"], "recorder": "command-authority-recorder", "occurred_at": GRANT_AT, "disposition": "ACCEPT",
             "subject_digest": envelope_digest, "attested_actor": None, "criteria": []}
    grant_attestation = {"id": f"{STEP}-grant-attestation", "kind": "ORGANISATIONAL_ATTESTATION", "actor": ATTESTER, "role": "organizational-attester",
                         "principal": ORG, "occupancy": attester_occupancy, "capacity": capacity_by_kind["ORGANISATIONAL_ATTESTATION"]["id"],
                         "recorder": "command-authority-recorder", "occurred_at": GRANT_ATTEST_AT, "disposition": "ACCEPT",
                         "subject_digest": digest("authority-act", grant), "attested_actor": GRANTOR, "criteria": []}
    decision = {"id": f"{STEP}-operator-decision", "kind": "INSTANCE_DECISION", "actor": OPERATOR, "role": OPERATOR_ROLE, "principal": ORG,
                "occupancy": gate_occupancy, "capacity": capacity_by_kind["INSTANCE_DECISION"]["id"], "recorder": "command-authority-recorder",
                "occurred_at": decide_at, "disposition": "ACCEPT", "subject_digest": operation_digest, "attested_actor": None, "criteria": [CRITERION]}
    decision_attestation = {"id": f"{STEP}-operator-decision-attestation", "kind": "ORGANISATIONAL_ATTESTATION", "actor": ATTESTER,
                            "role": "organizational-attester", "principal": ORG, "occupancy": attester_occupancy,
                            "capacity": capacity_by_kind["ORGANISATIONAL_ATTESTATION"]["id"], "recorder": "command-authority-recorder",
                            "occurred_at": attest_at, "disposition": "ACCEPT", "subject_digest": digest("authority-act", decision),
                            "attested_actor": OPERATOR, "criteria": []}
    acts = sorted([grant, grant_attestation, decision, decision_attestation], key=lambda row: digest("authority-act", row).encode())
    returns = sorted([{"id": f"return-{act['id']}", "actor": act["actor"], "provider": IDP, "channel": CHANNEL, "act_digest": digest("authority-act", act),
                       "act_bytes_base64": base64.b64encode(canonical_bytes(act)).decode(), "returned_at": act["occurred_at"],
                       "evidence_ref": f"return-{act['id']}-evidence"} for act in acts], key=lambda row: row["id"].encode())
    query_rows = {}
    for act in acts:
        capacity_digest = digest("authority-capacity", next(row for row in capacities if row["id"] == act["capacity"]))
        for subject in [root_digest, capacity_digest]:
            for at in [act["occurred_at"], now]:
                query = {"purpose": "REVOCATION", "subject_digest": subject, "at": at, "provider": REVOCATION["provider"], "source": REVOCATION["source"]}
                query_rows[canonical_text(query)] = query
    credential_digest = digest("authority-credential", credential)
    for subject in [envelope_digest, credential_digest]:
        query = {"purpose": "REVOCATION", "subject_digest": subject, "at": now, "provider": REVOCATION["provider"], "source": REVOCATION["source"]}
        query_rows[canonical_text(query)] = query
    queries = list(query_rows.values())
    observations = [{"query": query, "query_digest": digest("authority-query", query), "status": "AVAILABLE", "as_of": query["at"],
                     "revision": f"rev-{index}", "revoked": bool(revoked and query["subject_digest"] == envelope_digest and query["at"] == now),
                     "evidence_ref": f"roe-revocation-evidence-{index}"} for index, query in enumerate(queries, 1)]
    authenticated = sorted_utf8(
        [{"kind": "OCCUPANCY", "record_digest": digest("authority-occupancy", row), "provider": IDP, "channel": None} for row in occupancies]
        + [{"kind": "CAPACITY", "record_digest": digest("authority-capacity", row), "provider": IDP, "channel": None} for row in capacities]
        + [{"kind": "CREDENTIAL", "record_digest": credential_digest, "provider": IDP, "channel": None}]
        + [{"kind": "RETURN", "record_digest": digest("authority-return", row), "provider": IDP, "channel": CHANNEL} for row in returns])
    host_selection = {"root": root, "selection_evidence": f"{STEP}-root-selection", "authenticated_records": authenticated}
    clock = {"source": CLOCK, "status": "AVAILABLE", "instant": now}
    authority_input = {"schema": SCHEMA + "authority-input", "specification_pin": PIN, "source": authority_source, "work_class": authority_work_class,
                       "envelope": envelope, "proposal": authority_proposal, "clock": clock, "host_selection": host_selection,
                       "occupancies": occupancies, "capacities": capacities, "credentials": [credential], "acts": acts, "returns": returns,
                       "observations": observations}
    actual = {row["name"]: row["value"]["value"] for row in fields}
    resolved_scope = {"subjects": [actual["track_id"]], "resources": ["mission-1"]}
    check_rows = [
        {"purpose": "SOURCE_BINDING", "subject_digest": envelope_digest, "requirement_ref": authority_source["id"], "at": now},
        {"purpose": "ROOT_BINDING", "subject_digest": envelope_digest, "requirement_ref": root["id"], "at": now},
        {"purpose": "INPUT_SUPPORT", "subject_digest": operation_digest, "requirement_ref": STEP, "at": now},
        {"purpose": "BINDING", "subject_digest": operation_digest, "requirement_ref": envelope["scope"]["id"], "at": now},
        {"purpose": "GATE_FLOOR", "subject_digest": envelope_digest, "requirement_ref": ENVELOPE_ID, "at": now},
        {"purpose": "ENVELOPE_VALIDITY", "subject_digest": envelope_digest, "requirement_ref": ENVELOPE_ID, "at": now},
        {"purpose": "EXECUTOR_OCCUPANCY", "subject_digest": operation_digest, "requirement_ref": executor_occupancy, "at": now},
        {"purpose": "CREDENTIAL", "subject_digest": operation_digest, "requirement_ref": credential["id"], "at": now},
    ]
    for condition in conditions:
        check_rows.append({"purpose": "CONDITION", "subject_digest": operation_digest, "requirement_ref": condition["id"], "at": now})
    return_by_digest = {row["act_digest"]: row for row in returns}
    for act in acts:
        act_digest = digest("authority-act", act)
        check_rows.extend([
            {"purpose": "ACT_CAPACITY", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": act["occurred_at"]},
            {"purpose": "ACT_OCCUPANCY", "subject_digest": act_digest, "requirement_ref": act["occupancy"], "at": act["occurred_at"]},
            {"purpose": "ACT_RELIANCE", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": now},
            {"purpose": "RETURN", "subject_digest": act_digest, "requirement_ref": return_by_digest[act_digest]["id"], "at": now},
        ])
        if act["kind"] == "ORGANISATIONAL_ATTESTATION":
            check_rows.append({"purpose": "SEPARATION", "subject_digest": act_digest, "requirement_ref": act["capacity"], "at": now})
        if act["kind"] == "INSTANCE_DECISION":
            check_rows.append({"purpose": "GATE_CRITERION", "subject_digest": act_digest, "requirement_ref": CRITERION, "at": act["occurred_at"]})
    for query in queries:
        check_rows.append({"purpose": "REVOCATION", "subject_digest": query["subject_digest"], "requirement_ref": digest("authority-query", query), "at": query["at"]})
    evidence_subject = {"host_selection": host_selection, "occupancies": occupancies, "capacities": capacities, "credentials": [credential],
                        "acts": acts, "returns": returns, "observations": observations, "clock": clock}
    result = {"schema": SCHEMA + "authority-result", "specification_pin": PIN, "status": "READY_FOR_RESERVATION", "source_digest": source_digest,
              "work_class_digest": work_class_digest, "envelope_digest": envelope_digest, "proposal_digest": proposal_digest,
              "operation_digest": operation_digest, "scope": resolved_scope, "actual_scope": resolved_scope,
              "act_digests": sorted_utf8([digest("authority-act", row) for row in acts]), "checks": sorted_utf8(check_rows),
              "required_budgets": [ANCHOR], "evidence_digest": digest("authority-evidence", evidence_subject)}
    definition = {"schema": SCHEMA + "authority-definition", "source": authority_source, "work_class": authority_work_class, "envelope": envelope}
    return {"definition": definition, "input": authority_input, "result": result, "result_digest": digest("authority-result", result),
            "envelope_digest": envelope_digest, "proposal_digest": proposal_digest, "operation_digest": operation_digest, "credential": credential, "executor": executor,
            "acts": acts, "clock": clock}


def authority_refusal(failed_checks: list[dict]) -> dict:
    return {"status": "REFUSED", "code": "AUTHORITY_NOT_ESTABLISHED", "path": "", "reasons": sorted_utf8({row["reason"] for row in failed_checks}),
            "failed_checks": sorted_utf8(failed_checks)}


def failed_condition(auth: dict, condition_id: str, now: str) -> dict:
    """AUTHORITY-CHECKS construction table, CONDITION row, with the reason it contributes."""
    return {"purpose": "CONDITION", "subject_digest": auth["operation_digest"], "requirement_ref": condition_id, "at": now, "reason": "CONDITION_VIOLATED"}


def failed_revocation(auth: dict, subject_digest: str, at: str) -> dict:
    """AUTHORITY-CHECKS construction table, REVOCATION row, for a query whose observation is revoked."""
    query = {"purpose": "REVOCATION", "subject_digest": subject_digest, "at": at, "provider": REVOCATION["provider"], "source": REVOCATION["source"]}
    return {"purpose": "REVOCATION", "subject_digest": subject_digest, "requirement_ref": digest("authority-query", query), "at": at, "reason": "REVOKED"}


# ---------------------------------------------------------------------------
# Review evidence: readback, hand-mapped correspondence, LIFE-003 proxy records.
# ---------------------------------------------------------------------------

def build_review_evidence(work_class: dict) -> tuple[dict, dict, dict, tuple[dict, dict, dict]]:
    definition_digest = digest("work-class-definition", work_class)
    readback_lines = readback(work_class)
    readback_result = {"status": "READBACK", "digest": definition_digest, "lines": readback_lines}
    engage = "/steps/1"
    fields = {name: [f"{engage}/fields/{index}/name", f"{engage}/fields/{index}/type_ref"] for index, name in enumerate(row["name"] for row in ENGAGE_FIELDS)}
    label_type = ["/types/2/id", "/types/2/kind"]
    identity_type = ["/types/1/id", "/types/1/kind"]
    authority_ref = [f"{engage}/authority_requirements/0"]
    supported = {
        "roe-01-deadly-force-threat": ["/source/obligations/0", f"{engage}/id", f"{engage}/kind", f"{engage}/interface", f"{engage}/operation"] + fields["demonstrated_intent"] + label_type + authority_ref,
        "roe-02-protected-status-bars-fire": ["/source/obligations/1"] + fields["protected_status"] + label_type + authority_ref,
        "roe-03-declared-threat-class-and-confidence": ["/source/obligations/2", "/types/0/id", "/types/0/kind", "/types/0/nonnegative", "/types/0/unit"] + fields["classification"] + fields["confidence"] + label_type + authority_ref,
        "roe-04-rules-held-as-one-admitted-grant": ["/source/obligations/3", "/schema", "/specification_pin", "/id", "/revision", "/profile", "/source/id", "/source/revision",
                                                    "/participants/0/id", "/participants/0/role", "/participants/0/kind",
                                                    f"{engage}/scope_fields/subjects/0", f"{engage}/scope_fields/resources/0"] + fields["mission_id"] + fields["track_id"] + identity_type + authority_ref,
        "roe-05-operator-decision-per-engagement": ["/source/obligations/4", "/root", f"{engage}/permit_seconds", f"{engage}/executor_role", f"{engage}/required_credentials/0",
                                                    "/participants/1/id", "/participants/1/role", "/participants/1/kind",
                                                    "/participants/2/id", "/participants/2/role", "/participants/2/kind",
                                                    "/occurrence_limits/0/step_id", "/occurrence_limits/0/maximum",
                                                    "/limits/maximum_actuations", "/limits/maximum_activations", "/limits/maximum_proposals"] + authority_ref,
        "roe-06-direction-or-safe-state": ["/source/obligations/5", "/deadlines/0/id", "/deadlines/0/step_id", "/deadlines/0/clock_source", "/deadlines/0/due/kind",
                                           "/deadlines/0/due/value", "/deadlines/0/due/unit", "/deadlines/0/boundary", "/deadlines/0/expiry_target",
                                           f"{engage}/failure_behavior"] + authority_ref,
        "roe-07-engagement-count-budget": ["/source/obligations/6", "/shared_budgets/0", f"{engage}/shared_budgets/0"] + fields["mission_id"] + identity_type,
        "roe-08-effect-established-only-by-assessment": ["/source/obligations/7", f"{engage}/failure_behavior", "/types/3/id", "/types/3/kind",
                                                          "/relationships/0/from", "/relationships/0/kind", "/relationships/0/to", "/steps/0/id", "/steps/0/kind"]
                                                         + [line["path"] for line in readback_lines if line["path"].startswith(f"{engage}/completion/") and "route_label" not in line["path"]],
    }
    uncovered = ["roe-09-runtime-traceability"]
    path_set = {line["path"] for line in readback_lines}
    mapped_paths = set().union(*(set(rows) for rows in supported.values()))
    unknown = mapped_paths - path_set
    if unknown:
        raise ValueError(f"correspondence names absent readback paths: {sorted_utf8(unknown)}")
    unsupported_paths = sorted_utf8(path_set - mapped_paths)
    residue = [{"kind": "ARTIFACT_PROVISION", "subject": path, "disposition": "UNSUPPORTED",
                "explanation": "The synthetic source policy does not state this representation or execution detail."} for path in unsupported_paths]
    residue.append({"kind": "SOURCE_OBLIGATION", "subject": "roe-09-runtime-traceability", "disposition": "EXCLUDED",
                    "explanation": "Runtime traceability is carried by the protocol (LIFE-006 decision receipts, LIFE-019 state integrity, WCS2-005 readback), not by a provision of this definition."})
    residue.sort(key=lambda row: (row["kind"].encode(), row["subject"].encode()))
    mappings = [{"source_obligation_id": oid, "provision_paths": sorted_utf8(set(supported[oid]))} for oid in work_class["source"]["obligations"] if oid in supported]
    base = {"schema": SCHEMA + "evidence-record", "evidence_id": "roe-engagement-correspondence", "kind": "CORRESPONDENCE", "status": "ACCEPTED",
            "subject_digest": definition_digest, "source_id": work_class["source"]["id"], "source_revision": work_class["source"]["revision"],
            "work_class_digest": definition_digest, "mappings": mappings, "uncovered_source_obligation_ids": uncovered,
            "unsupported_provision_paths": unsupported_paths, "residue": residue, "recorded_at": T_AUTH,
            "provenance_digest": digest("specimen-provenance", {"id": "roe-engagement-correspondence"})}
    review = {"schema": SCHEMA + "evidence-record", "evidence_id": "roe-engagement-correspondence-review", "kind": "REVIEW", "status": "ACCEPTED",
              "subject_digest": digest("correspondence-subject", base), "reviewer_id": PROXY + "reviewer:20260913", "paragraph_ids": [],
              "case_ids": ["roe-engagement-correspondence"], "finding_ids": [], "recorded_at": T_AUTH,
              "provenance_digest": digest("specimen-provenance", {"id": "roe-engagement-correspondence-review"})}
    correspondence = {**base, "review": review}
    correspondence_input = {"profile": PROFILE, "role": "REVIEW_EVIDENCE", "specification_pin": PIN,
                            "subject": {"kind": "WORK_CLASS", "subject_id": work_class["id"], "subject_digest": definition_digest,
                                        "candidate_identity": "seampoint.work-class/1.0.0-draft.2", "specification_pin": PIN},
                            "work_class": work_class, "work_class_digest": definition_digest, "evidence": correspondence}
    source_confirmation = {"schema": SCHEMA + "evidence-record", "evidence_id": "roe-engagement-source-confirmation", "kind": "SOURCE_CONFIRMATION",
                           "status": "ACCEPTED", "subject_digest": digest("work-class-source", work_class["source"]), "actor_id": PROXY + "source-confirmer:20260913",
                           "scope_ids": list(work_class["source"]["obligations"]), "recorded_at": T_AUTH,
                           "provenance_digest": digest("specimen-provenance", {"id": "roe-engagement-source-confirmation"})}
    policy_decision = {"schema": SCHEMA + "evidence-record", "evidence_id": "roe-engagement-policy-decision", "kind": "POLICY_DECISION", "status": "ACCEPTED",
                       "subject_digest": definition_digest, "decision_maker_id": PROXY + "policy-owner:20260913",
                       "decision_ids": ["roe-engagement-policy-decision-1"], "recorded_at": T_AUTH,
                       "provenance_digest": digest("specimen-provenance", {"id": "roe-engagement-policy-decision"})}
    return readback_result, correspondence, correspondence_input, (correspondence, source_confirmation, policy_decision)


# ---------------------------------------------------------------------------
# Deployment with the root deadline installed from the initial mission clock.
# ---------------------------------------------------------------------------

def build_deployment(work_class: dict, instance_id: str, review_evidence: tuple[dict, dict, dict], initial_clock: dict) -> tuple[dict, dict, dict, dict]:
    definition_digest = digest("work-class-definition", work_class)
    correspondence, source_confirmation, policy_decision = review_evidence
    correspondence_digest, source_confirmation_digest, policy_decision_digest = (digest("evidence", row) for row in review_evidence)
    root_occurrence = occurrence(definition_digest, instance_id, work_class["root"], "1", [])
    auth_partial = {"schema": SCHEMA + "deployment-authorization", "authorization_id": f"deploy-{instance_id}", "specification_pin": PIN,
                    "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE, "instance_id": instance_id, "organization_id": ORG,
                    "status": "AUTHORIZED", "authorized_at": T_AUTH, "expires_at": DEPLOY_EXPIRES,
                    "correspondence_evidence_digest": correspondence_digest, "source_confirmation_evidence_digest": source_confirmation_digest,
                    "policy_decision_evidence_digest": policy_decision_digest}
    subject_digest = digest("deployment-authorization-subject", auth_partial)
    evidence = {"schema": SCHEMA + "evidence-record", "evidence_id": f"deployment-evidence-{instance_id}", "kind": "ORGANIZATIONAL_AUTHORIZATION",
                "status": "ACCEPTED", "subject_digest": subject_digest, "organization_id": ORG, "authorizer_id": "mission-deployment-authorizer",
                "authorization_scope": sorted_utf8([PIN, definition_digest, PROFILE, ROLE, instance_id]), "recorded_at": T_AUTH, "expires_at": DEPLOY_EXPIRES,
                "provenance_digest": digest("specimen-provenance", {"id": f"deployment-evidence-{instance_id}"})}
    evidence_digest = digest("evidence", evidence)
    authorization = {**auth_partial, "authorization_evidence_digest": evidence_digest}
    authorization_digest = digest("deployment-authorization", authorization)
    authorization_clock = available_clock("1", T_DEPLOY_CLOCK, source="deployment-clock")
    activation_digest = digest("deployment-activation", {"deployment_authorization_digest": authorization_digest, "instance_id": instance_id,
                                                         "occurrence_id": root_occurrence["occurrence_id"]})
    deadline = work_class["deadlines"][0]
    due = add_seconds(initial_clock["observed_time"], int(deadline["due"]["value"]) * 60)
    activation_subject = {"deadline_id": deadline["id"], "occurrence_id": root_occurrence["occurrence_id"], "trigger_digest": activation_digest,
                          "source": deadline["clock_source"], "activation_revision": "0", "activation_clock_revision": initial_clock["revision"],
                          "activation_instant": initial_clock["observed_time"], "activation_clock_evidence_digest": initial_clock["evidence_digest"],
                          "due": due, "boundary": deadline["boundary"]}
    deadline_state = {"deadline_id": deadline["id"], "occurrence_id": root_occurrence["occurrence_id"], "source": deadline["clock_source"],
                      "activation_revision": "0", "activation_digest": digest("deadline-activation", activation_subject), "trigger_digest": activation_digest,
                      "activation_clock_revision": initial_clock["revision"], "activation_instant": initial_clock["observed_time"],
                      "activation_clock_evidence_digest": initial_clock["evidence_digest"], "due": due, "boundary": deadline["boundary"],
                      "status": "PENDING", "expiry_event_digest": None}
    state = {"schema": SCHEMA + "work-state", "specification_pin": PIN, "work_class_digest": definition_digest, "profile": PROFILE, "role": ROLE,
             "instance_id": instance_id, "deployment_authorization": authorization, "deployment_authorization_subject_digest": subject_digest,
             "deployment_authorization_digest": authorization_digest, "deployment_authorization_evidence": evidence,
             "deployment_authorization_evidence_digest": evidence_digest, "deployment_correspondence_evidence": correspondence,
             "deployment_correspondence_evidence_digest": correspondence_digest, "deployment_source_confirmation_evidence": source_confirmation,
             "deployment_source_confirmation_evidence_digest": source_confirmation_digest, "deployment_policy_decision_evidence": policy_decision,
             "deployment_policy_decision_evidence_digest": policy_decision_digest, "deployment_authorization_clock": authorization_clock,
             "deployment_organization_id": ORG, "revision": "0", "status": "ACTIVE", "total_activations": "1", "total_actuations": "0",
             "step_counters": [{"step_id": STEP, "activations": "1", "actuations": "0"}],
             "active": [{"occurrence": root_occurrence, "activation_event_digest": activation_digest, "status": "ACTIVE", "deadline_ids": [deadline["id"]]}],
             "completed": [], "obligations": [], "proposals": [], "permits": [], "dispatches": [], "outcomes": [], "clocks": [initial_clock],
             "deadlines": [deadline_state], "fanout_passes": [], "receipts": [], "replays": []}
    deploy_input = {"profile": PROFILE, "role": ROLE, "specification_pin": PIN, "definition": work_class, "definition_digest": definition_digest,
                    "instance_id": instance_id, "deployment_authorization": authorization, "authorization_evidence": evidence,
                    "correspondence_evidence": correspondence, "source_confirmation_evidence": source_confirmation, "policy_decision_evidence": policy_decision,
                    "authorization_clock": authorization_clock, "initial_clocks": [initial_clock]}
    deploy_result = {"status": "DEPLOYED", "profile": PROFILE, "role": ROLE, "instance_id": instance_id, "work_class_digest": definition_digest,
                     "deployment_authorization_digest": authorization_digest, "state": state, "state_digest": work_state_digest(state)}
    return deploy_input, deploy_result, state, root_occurrence


# ---------------------------------------------------------------------------
# Transition constructors shared by the trace and the variants.
# ---------------------------------------------------------------------------

def clock_event(state: dict, event_id: str, clock: dict) -> dict:
    return {"schema": SCHEMA + "runtime-event", "event_id": event_id, "kind": "CLOCK", "instance_id": state["instance_id"],
            "expected_state_revision": state["revision"], "expected_state_digest": work_state_digest(state), "clock": clock, "activation_clocks": []}


def record_clock(state: dict, event: dict) -> tuple[dict, dict]:
    clock = event["clock"]

    def mutate(after, _):
        after["clocks"].append(clock)
        after["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))

    return work_transition(state, event, disposition="CLOCK_RECORDED", reasons=[],
                           details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]}],
                           permit=None, budget_results=[], authority_result_digest=None, reservation_receipt_digests=[], mutate=mutate)


def expire_with_stop(state: dict, event: dict) -> tuple[dict, dict]:
    clock = event["clock"]
    event_digest = digest("runtime-event", event)
    deadline = state["deadlines"][0]
    active = next(row for row in state["active"] if row["occurrence"]["occurrence_id"] == deadline["occurrence_id"])

    def mutate(after, _):
        after["clocks"].append(clock)
        after["clocks"].sort(key=lambda row: (row["source"].encode(), int(row["revision"])))
        after["active"] = [row for row in after["active"] if row["occurrence"]["occurrence_id"] != active["occurrence"]["occurrence_id"]]
        after["completed"].append({"occurrence": active["occurrence"], "disposition": "EXPIRED", "evidence_digest": clock["evidence_digest"],
                                   "occurred_at": clock["observed_time"], "route_label": None, "selected_relationship_digest": None, "late": False})
        after["completed"].sort(key=lambda row: canonical_bytes(row["occurrence"]))
        target = after["deadlines"][0]
        target["status"] = "EXPIRED"
        target["expiry_event_digest"] = event_digest
        after["status"] = "STOPPED"

    return work_transition(state, event, disposition="STOPPED", reasons=["EXPIRY_STOP"],
                           details=[{"kind": "CLOCK", "source": clock["source"], "revision": clock["revision"], "status": clock["status"]},
                                    {"kind": "DEADLINE", "deadline_ids": [deadline["deadline_id"]], "reasons": ["EXPIRY_STOP"]}],
                           permit=None, budget_results=[], authority_result_digest=None, reservation_receipt_digests=[], mutate=mutate)


def propose_event(state: dict, event_id: str, occurrence_row: dict, auth: dict, fields: list[dict], clock_revision: str, budget_inputs: list[dict]) -> dict:
    native_request = {"interface": "fire-control", "operation": "engage-track", "fields": fields}
    executor = {"participant_id": EXECUTOR, "role": EXECUTOR_ROLE, "binding_digest": digest("executor-binding", auth["executor"])}
    return {"schema": SCHEMA + "runtime-event", "event_id": event_id, "kind": "PROPOSE", "instance_id": state["instance_id"],
            "expected_state_revision": state["revision"], "expected_state_digest": work_state_digest(state), "occurrence": occurrence_row,
            "native_request": native_request, "executor": executor, "credential_ids": [auth["credential"]["id"]], "authority_input": auth["input"],
            "budget_inputs": budget_inputs, "clock_revision": clock_revision,
            "observation_digests": sorted_utf8([digest("authority-observation", row) for row in auth["input"]["observations"]])}


def reservation_event_id(instance_id: str, lifecycle_event_id: str, lifecycle_kind: str, reservation_kind: str, registry_digest: str) -> str:
    return digest("lifecycle-reservation-event", {"instance_id": instance_id, "lifecycle_event_id": lifecycle_event_id, "lifecycle_event_kind": lifecycle_kind,
                                                  "reservation_event_kind": reservation_kind, "registry_digest": registry_digest})


def withhold_authority(state: dict, event: dict, failed_checks: list[dict]) -> tuple[dict, dict]:
    refusal = authority_refusal(failed_checks)
    refusal_digest = digest("authority-result", refusal)
    proposal_digest = digest("proposal", event)

    def mutate(after, event_digest):
        after["proposals"].append({"event_id": event["event_id"], "event_digest": event_digest, "proposal_digest": proposal_digest,
                                   "occurrence_id": event["occurrence"]["occurrence_id"], "disposition": "WITHHELD", "permit_digest": None,
                                   "authority_result_digest": refusal_digest, "reservation_receipt_digests": [], "prior_permit_digest": None})
        after["proposals"].sort(key=lambda row: row["event_id"].encode())

    return work_transition(state, event, disposition="WITHHELD", reasons=["AUTHORITY_REQUIRED", "AUTHORITY_NOT_ESTABLISHED", *refusal["reasons"]],
                           details=[{"kind": "AUTHORITY", "authority_result_digest": refusal_digest, "code": "AUTHORITY_NOT_ESTABLISHED",
                                     "reasons": refusal["reasons"], "failed_checks": refusal["failed_checks"]}],
                           permit=None, budget_results=[], authority_result_digest=refusal_digest, reservation_receipt_digests=[], mutate=mutate)


def main() -> None:
    source, work_class, authority_source, authority_work_class = build_static_contract()
    definition_digest = digest("work-class-definition", work_class)
    relationship_digest = digest("relationship", work_class["relationships"][0])

    # Shared budget: engagement count per mission per rolling hour, two committed.
    aggregate_definition = {
        "schema": SCHEMA + "aggregate-definition",
        "types": [{"id": "b.count", "kind": "INTEGER", "unit": None, "nonnegative": True}, {"id": "b.identity", "kind": "IDENTITY", "unit": None, "nonnegative": False}],
        "aggregate": {"id": "engagement-count-per-mission-window", "reducer": "COUNT", "result_type": "b.count", "element_type": None, "key_types": ["b.identity"],
                      "mappings": [{"id": "engage-track-count", "step_ids": [STEP], "qualifier": {"kind": "BOOLEAN", "value": True}, "key_fields": ["mission_id"], "contribution": {"kind": "COUNT"}}],
                      "time": {"clock_source": CLOCK, "precision": "SECOND"},
                      "window": {"kind": "ROLLING", "duration_seconds": "3600", "start_inclusive": False, "end_inclusive": True},
                      "committed_source": {"provider": "bda-provider", "source": "bda-assessment-ledger", "freshness": {"kind": "NONE"}, "key_fields": ["mission_id"],
                                           "qualifier": {"kind": "BOOLEAN", "value": True}, "contribution": {"kind": "COUNT"}},
                      "pending_policy": "INCLUDE_ALL_RESERVED", "operator": "LTE", "bound": typed("b.count", "3")},
    }
    aggregate_digest = digest("aggregate-definition", aggregate_definition)
    budget_definition = {"schema": SCHEMA + "budget-definition", "anchor": ANCHOR, "exposure_domain": "mission-1-engagements", "principal": ORG,
                         "aggregate": aggregate_definition, "contributor_classes": [work_class["id"]],
                         "reservation_policy": {"permit_seconds": "120", "pending_across_windows": True, "unexpected_effect": "BLOCK_AFFECTED_PARTITIONS",
                                                "unprojectable_effect": "BLOCK_ANCHOR", "settlement": {"provider": "bda-provider", "source": "bda-assessment-ledger"},
                                                "no_effect": {"provider": "bda-provider", "source": "bda-assessment-ledger"}}}
    budget_digest = digest("budget-definition", budget_definition)
    committed = [{"sequence": "1", "event": {"id": "committed-engagement-1", "state": "ACTIVE", "occurred_at": HISTORY_1, "fields": [field("mission_id", "b.identity", "mission-1")]}},
                 {"sequence": "2", "event": {"id": "committed-engagement-2", "state": "ACTIVE", "occurred_at": HISTORY_2, "fields": [field("mission_id", "b.identity", "mission-1")]}}]
    initial_history = {"budget_digest": budget_digest, "provider": "bda-provider", "source": "bda-assessment-ledger", "status": "AVAILABLE", "as_of": T0,
                       "complete": True, "revision": "2", "journal": committed, "evidence_ref": "bda-history-2-engagements"}
    registry_config = {"schema": SCHEMA + "reservation-registry", "id": "mission-1-engagement-registry", "principal": ORG, "clock_source": CLOCK,
                       "administration_provider": "command-governance-provider", "administration_source": "engagement-budget-administration",
                       "administration_role": "engagement-budget-administrator", "slots": [{"anchor": ANCHOR, "exposure_domain": "mission-1-engagements"}]}
    registry_digest = digest("reservation-registry", registry_config)
    registry_empty = {"schema": SCHEMA + "reservation-state", "specification_pin": PIN,
                      "core": {"configuration": registry_config, "revision": "0", "last_clock": None, "budgets": [], "reservations": [], "effects": []}, "receipts": []}

    # Placeholder authority evaluation fixes the envelope digest for the class authorization.
    occ_a = occurrence(definition_digest, INSTANCE_A, STEP, "1", [])
    occ_b = occurrence(definition_digest, INSTANCE_B, STEP, "1", [])
    fields_a = proposal_fields("track-17")
    auth_a = build_authority(authority_source, authority_work_class, instance_id=INSTANCE_A, occurrence_row=occ_a, fields=fields_a, now=T1,
                             decide_at="2026-09-13T10:00:30Z", attest_at="2026-09-13T10:00:40Z")
    class_authorization = {"id": "roe-engagement-budget-authorization", "budget_digest": budget_digest, "work_class": work_class["id"],
                           "work_class_digest": digest("authority-work-class", authority_work_class), "envelope_digest": auth_a["envelope_digest"],
                           "principal": ORG, "step": STEP, "authority_definition": auth_a["definition"],
                           "projection": [{"native_field": "mission_id", "native_type": "t.identity", "budget_field": "mission_id", "budget_type": "b.identity"}]}
    register_payload = {"definition": budget_definition, "authorizations": [class_authorization], "history": initial_history}
    register_clock = {"source": CLOCK, "status": "AVAILABLE", "instant": T0}
    admin_subject = digest("reservation-administration-subject", {"registry_digest": registry_digest, "event_id": "register-engagement-budget", "expected_revision": "0",
                                                                  "kind": "REGISTER", "clock": register_clock, "payload": register_payload})
    admin_basis = {"id": "engagement-budget-admin-basis", "registry_digest": registry_digest, "actor": "engagement-budget-admin-person", "principal": ORG,
                   "role": "engagement-budget-administrator", "kind": "HUMAN", "operations": ["REGISTER", "RELEASE"],
                   "validity": {"valid_from": VALID_FROM, "valid_until": VALID_UNTIL}, "at": T0, "revoked": False,
                   "provider": "command-governance-provider", "source": "engagement-budget-administration", "evidence_ref": "engagement-budget-admin-evidence"}
    admin_act = {"id": "register-engagement-budget-act", "basis": admin_basis["id"], "actor": admin_basis["actor"], "principal": ORG, "role": admin_basis["role"],
                 "kind": "REGISTER", "subject_digest": admin_subject, "occurred_at": T0, "disposition": "ACCEPT"}
    admin_return = {"id": "register-engagement-budget-return", "act_digest": digest("reservation-administration-act", admin_act),
                    "act_bytes_base64": base64.b64encode(canonical_bytes(admin_act)).decode(), "actor": admin_act["actor"],
                    "provider": "command-governance-provider", "source": "engagement-budget-administration", "returned_at": T0,
                    "evidence_ref": "engagement-budget-admin-return-evidence"}
    register_event = {"id": "register-engagement-budget", "expected_revision": "0", "kind": "REGISTER", "clock": register_clock, "payload": register_payload,
                      "administration": {"act": admin_act, "returned": admin_return}}
    history_record = {"kind": "HISTORY", "record_digest": digest("budget-history", initial_history), "provider": "bda-provider", "source": "bda-assessment-ledger"}
    register_host = {"registry_digest": registry_digest, "selection_evidence": "mission-1-registry-selection", "administration_bases": [admin_basis],
                     "authenticated_records": sorted_utf8([history_record, {"kind": "ADMIN_RETURN", "record_digest": digest("reservation-administration-return", admin_return),
                                                                             "provider": "command-governance-provider", "source": "engagement-budget-administration"}])}

    def apply_register(state):
        state["core"]["budgets"] = [{"definition": budget_definition, "definition_digest": budget_digest, "authorizations": [class_authorization], "history": initial_history}]

    registry_registered, register_result = reservation_transition(registry_empty, register_event, register_host, decision="REGISTERED", reservation_id=None,
                                                                  budgets=[], authority_result=None, reasons=[], mutate=apply_register)
    register_input = {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_empty, "state_digest": reservation_state_digest(registry_empty),
                      "event": register_event, "host_evidence": register_host}

    readback_result, correspondence_record, correspondence_input, review_evidence = build_review_evidence(work_class)
    write("source-policy.json", source)
    write("work-class.json", work_class)
    write("authority-definition.json", auth_a["definition"])
    write("shared-budget-definition.json", budget_definition)
    write("shared-budget-register-input.json", register_input)
    write("shared-budget-register-result-derived.json", register_result)
    write("readback-derived.json", readback_result)
    write("correspondence-record.json", correspondence_record)
    write("correspondence-input.json", correspondence_input)

    def reserve_input(registry_state: dict, auth: dict, res_event_id: str, histories: list[dict]) -> dict:
        event = {"id": res_event_id, "expected_revision": registry_state["core"]["revision"], "kind": "RESERVE", "clock": auth["clock"],
                 "payload": {"authority": auth["input"], "histories": histories}, "administration": None}
        host = {"registry_digest": registry_digest, "selection_evidence": "mission-1-registry-selection", "administration_bases": [],
                "authenticated_records": [{"kind": "HISTORY", "record_digest": digest("budget-history", histories[0]), "provider": "bda-provider", "source": "bda-assessment-ledger"}]}
        return {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_state, "state_digest": reservation_state_digest(registry_state),
                "event": event, "host_evidence": host}

    def budget_input(registry_state: dict, request: dict) -> dict:
        return {"registry_digest": registry_digest, "affected_anchors": [ANCHOR], "expected_revision": registry_state["core"]["revision"], "request": request}

    def aggregate_result(value: str, status: str) -> dict:
        return {"schema": SCHEMA + "aggregate-result", "specification_pin": PIN, "definition_digest": aggregate_digest, "status": status,
                "partitions": [{"occurrence": None, "key": [typed("b.identity", "mission-1")], "status": status, "accumulator": {"kind": "SCALAR", "value": value},
                                "result": value, "reasons": [] if status == "SATISFIED" else ["BOUND_VIOLATED"]}],
                "reasons": [] if status == "SATISFIED" else ["BOUND_VIOLATED"]}

    def permitted_proposal(state: dict, occ: dict, auth: dict, fields: list[dict], event_id: str, clock_revision: str, registry_state: dict,
                           accumulator: str) -> dict:
        res_id = reservation_event_id(state["instance_id"], event_id, "PROPOSE", "RESERVE", registry_digest)
        r_input = reserve_input(registry_state, auth, res_id, [initial_history])
        event = propose_event(state, event_id, occ, auth, fields, clock_revision, [budget_input(registry_state, r_input)])
        occurrence_key = digest("reservation-occurrence", {"work_class": work_class["id"], "instance": state["instance_id"], "occurrence": occ["occurrence_id"]})
        reservation = {"id": res_id, "occurrence_key": occurrence_key, "proposal_digest": auth["proposal_digest"], "envelope_digest": auth["envelope_digest"],
                       "authority": auth["input"], "authority_result": auth["result"],
                       "contributions": [{"anchor": ANCHOR, "mapping": "engage-track-count", "occurrence": occurrence_key, "key": [typed("b.identity", "mission-1")], "value": typed("b.count", "1")}],
                       "created_at": auth["clock"]["instant"], "permit_until": add_seconds(auth["clock"]["instant"], 120), "status": "OPEN", "matched_effect": None}

        def apply_reserve(rs):
            rs["core"]["reservations"].append(reservation)
            rs["core"]["reservations"].sort(key=lambda row: row["id"].encode())

        registry_after, reserve_result = reservation_transition(registry_state, r_input["event"], r_input["host_evidence"], decision="RESERVED", reservation_id=res_id,
                                                                budgets=[{"anchor": ANCHOR, "result": aggregate_result(accumulator, "SATISFIED")}],
                                                                authority_result=auth["result"], reasons=[], mutate=apply_reserve)
        budget_result = {"registry_digest": registry_digest, "affected_anchors": [ANCHOR], "result": reserve_result}
        proposal_digest = digest("proposal", event)
        permit = {"schema": SCHEMA + "permit", "permit_id": "sha256:" + "0" * 64, "instance_id": state["instance_id"], "work_class_digest": definition_digest,
                  "profile": PROFILE, "role": ROLE, "occurrence": occ, "proposal_digest": proposal_digest, "native_request": event["native_request"],
                  "executor": event["executor"], "credential_ids": [auth["credential"]["id"]], "authority_result": auth["result"],
                  "authority_result_digest": auth["result_digest"], "authority_evidence_digest": auth["result"]["evidence_digest"],
                  "authority_act_bases": sorted([{"act_digest": digest("authority-act", row), "act": row} for row in auth["acts"]], key=lambda row: row["act_digest"].encode()),
                  "prior_effect_bases": [], "separation_bases": [], "observation_digests": event["observation_digests"], "supersedes_permit_digest": None,
                  "budget_revisions": [{"registry_digest": registry_digest, "affected_anchors": [ANCHOR], "revision": registry_after["core"]["revision"],
                                        "reservation_id": res_id, "receipt_digest": reserve_result["receipt_digest"]}],
                  "clock_source": CLOCK, "clock_revision": clock_revision, "expires_at": add_seconds(auth["clock"]["instant"], 120)}
        permit["permit_id"] = digest("permit", omit(permit, "permit_id"))

        def apply_proposal(after, event_digest):
            after["total_actuations"] = str(int(after["total_actuations"]) + 1)
            after["step_counters"][0]["actuations"] = str(int(after["step_counters"][0]["actuations"]) + 1)
            after["active"][0]["status"] = "PERMITTED"
            after["proposals"].append({"event_id": event_id, "event_digest": event_digest, "proposal_digest": proposal_digest, "occurrence_id": occ["occurrence_id"],
                                       "disposition": "PERMITTED", "permit_digest": permit["permit_id"], "authority_result_digest": auth["result_digest"],
                                       "reservation_receipt_digests": [reserve_result["receipt_digest"]], "prior_permit_digest": None})
            after["proposals"].sort(key=lambda row: row["event_id"].encode())
            after["permits"].append(permit)
            after["permits"].sort(key=lambda row: row["permit_id"].encode())

        next_state, result = work_transition(state, event, disposition="PERMITTED", reasons=[], details=[], permit=permit, budget_results=[budget_result],
                                             authority_result_digest=auth["result_digest"], reservation_receipt_digests=[reserve_result["receipt_digest"]], mutate=apply_proposal)
        return {"event": event, "state": next_state, "result": result, "permit": permit, "reservation": reservation, "reservation_id": res_id,
                "registry_after": registry_after, "reserve_result": reserve_result, "request": step_request(event_id, work_class, state, event)}

    # ---------------------------------------------------------------- instance A
    initial_clock = available_clock("1", T0)
    deploy_input_a, deploy_result_a, state_a0, _ = build_deployment(work_class, INSTANCE_A, review_evidence, initial_clock)
    deploy_request_a = {"protocol": PROTOCOL, "request_id": "deploy-a", "operation": "deploy", "input": deploy_input_a}
    clock_2 = available_clock("2", T1)
    clock_event_a2 = clock_event(state_a0, "clock-a-2", clock_2)
    state_a1, clock_result_a2 = record_clock(state_a0, clock_event_a2)
    request_a2 = step_request("clock-a-2", work_class, state_a0, clock_event_a2)

    proposal_a = permitted_proposal(state_a1, occ_a, auth_a, fields_a, "propose-engage-a-1", "2", registry_registered, "3")
    state_a2 = proposal_a["state"]
    permit_a = proposal_a["permit"]
    registry_after_first = proposal_a["registry_after"]

    clock_3 = available_clock("3", T2)
    clock_event_a3 = clock_event(state_a2, "clock-a-3", clock_3)
    state_a3, clock_result_a3 = record_clock(state_a2, clock_event_a3)
    request_a3 = step_request("clock-a-3", work_class, state_a2, clock_event_a3)

    connector = {"id": "fire-control-connector", "version": "v1", "binding_digest": "sha256:" + "0" * 64}
    connector["binding_digest"] = digest("connector-binding", omit(connector, "binding_digest"))

    def dispatch(state: dict, event_id: str, permit: dict, native_request: dict, attempt_id: str, status: str, attempted_at: str, acknowledgement: dict,
                 clock_revision: str, *, disposition: str, reasons: list[str], occurrence_status: str) -> tuple[dict, dict, dict, dict]:
        attempt = {"attempt_id": attempt_id, "status": status,
                   "request_digest": digest("dispatch-native-request", {"instance_id": state["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
                                                                         "interface": native_request["interface"], "operation": native_request["operation"], "fields": native_request["fields"]}),
                   "attempted_at": attempted_at}
        event = {"schema": SCHEMA + "runtime-event", "event_id": event_id, "kind": "DISPATCH_OBSERVED", "instance_id": state["instance_id"],
                 "expected_state_revision": state["revision"], "expected_state_digest": work_state_digest(state), "permit": permit, "native_request": native_request,
                 "connector": connector, "attempt": attempt, "acknowledgement": acknowledgement, "clock_revision": clock_revision}
        event_digest = digest("runtime-event", event)
        attempt_digest = digest("dispatch-attempt", {"permit_id": permit["permit_id"], "native_request": native_request, "connector": connector, "attempt": attempt})
        record = {"dispatch_digest": "sha256:" + "0" * 64, "dispatch_attempt_digest": attempt_digest, "event_id": event_id, "event_digest": event_digest,
                  "permit_digest": permit["permit_id"], "native_request": native_request, "connector": connector, "attempt": attempt, "acknowledgement": acknowledgement,
                  "clock_revision": clock_revision}
        record["dispatch_digest"] = digest("dispatch", omit(record, "dispatch_digest"))

        def mutate(after, _):
            after["active"][0]["status"] = occurrence_status
            after["dispatches"].append(record)
            after["dispatches"].sort(key=lambda row: row["dispatch_digest"].encode())

        next_state, result = work_transition(state, event, disposition=disposition, reasons=reasons,
                                             details=[{"kind": "DISPATCH", "attempt_id": attempt_id, "reasons": sorted_utf8(reasons)}], permit=None,
                                             budget_results=[], authority_result_digest=None, reservation_receipt_digests=[], mutate=mutate)
        return event, record, next_state, result

    ack_a = {"status": "ACCEPTED", "reference": "fire-control-ack-a-1", "observed_at": ACK_AT}
    dispatch_event_a, dispatch_record_a, state_a4, dispatch_result_a = dispatch(state_a3, "dispatch-engage-a-1", permit_a, permit_a["native_request"], "engage-attempt-a-1",
                                                                                "SENT", DISPATCH_AT, ack_a, "3", disposition="ACKNOWLEDGED", reasons=[], occurrence_status="DISPATCHED")
    request_dispatch_a = step_request("dispatch-engage-a-1", work_class, state_a3, dispatch_event_a)

    clock_4 = available_clock("4", T3)
    clock_event_a4 = clock_event(state_a4, "clock-a-4", clock_4)
    state_a5, clock_result_a4 = record_clock(state_a4, clock_event_a4)
    request_a4 = step_request("clock-a-4", work_class, state_a4, clock_event_a4)

    attributed_a = {"work_class": work_class["id"], "instance": INSTANCE_A, "occurrence": occ_a["occurrence_id"], "step": STEP, "operation": "engage-track",
                    "interface": "fire-control", "fields": fields_a}
    settle_clock = {"source": CLOCK, "status": "AVAILABLE", "instant": T3}

    def native_evidence(evidence_id: str, native_operation_id: str, status: str, attributed: dict, actual_fields: list[dict], event_time, observed_at: str) -> dict:
        return {"evidence_id": evidence_id, "native_operation_id": native_operation_id, "provider": "bda-provider", "source": "bda-assessment-ledger",
                "record_type": "engagement-effect", "record_digest": digest("specimen-native-record", {"id": evidence_id, "actual_fields": actual_fields}),
                "evidence_ref": f"bda-record-{evidence_id}", "attributed_request": attributed, "native_request_digest": digest("native-request", attributed),
                "status": status, "actual_fields": actual_fields, "collections": [], "event_time": event_time, "observed_at": observed_at,
                "rules_out_past_and_future_effects": False}

    def settle_input(registry_state: dict, res_event_id: str, native: dict, histories: list[dict]) -> dict:
        event = {"id": res_event_id, "expected_revision": registry_state["core"]["revision"], "kind": "SETTLE", "clock": settle_clock,
                 "payload": {"native": native, "histories": histories}, "administration": None}
        host = {"registry_digest": registry_digest, "selection_evidence": "mission-1-registry-selection", "administration_bases": [],
                "authenticated_records": sorted_utf8([
                    {"kind": "HISTORY", "record_digest": digest("budget-history", histories[0]), "provider": "bda-provider", "source": "bda-assessment-ledger"},
                    {"kind": "NATIVE_OUTCOME", "record_digest": digest("reservation-native-outcome", native), "provider": "bda-provider", "source": "bda-assessment-ledger"}])}
        return {"schema": SCHEMA + "reservation-input", "specification_pin": PIN, "state": registry_state, "state_digest": reservation_state_digest(registry_state),
                "event": event, "host_evidence": host}

    def governed_effect_event(state: dict, event_id: str, permit: dict, dispatch_record: dict, evidence: dict, registry_state: dict, settle: dict) -> dict:
        return {"schema": SCHEMA + "runtime-event", "event_id": event_id, "kind": "EFFECT_OBSERVED", "instance_id": state["instance_id"],
                "expected_state_revision": state["revision"], "expected_state_digest": work_state_digest(state), "permit": permit,
                "dispatch_digest": dispatch_record["dispatch_digest"], "native_evidence": evidence, "completion_authorization": None,
                "budget_inputs": [budget_input(registry_state, settle)], "clock_revision": "4", "activation_clocks": []}

    # Valid settlement.
    actual_a = sorted(fields_a + [field("status", "t.status", "NEUTRALIZED")], key=lambda row: row["name"].encode())
    settled_evidence = native_evidence("bda-effect-a-1", "bda-native-a-1", "EFFECT_ESTABLISHED", attributed_a, actual_a, EFFECT_TIME, EFFECT_OBSERVED)
    committed_event = {"id": digest("reservation-committed-event", {"budget_digest": budget_digest, "effect_id": "bda-native-a-1", "mapping": "engage-track-count"}),
                       "state": "ACTIVE", "occurred_at": EFFECT_TIME, "fields": [field("mission_id", "b.identity", "mission-1")]}
    settled_history = {**initial_history, "revision": "3", "as_of": T3, "journal": committed + [{"sequence": "3", "event": committed_event}], "evidence_ref": "bda-history-3-engagements"}
    settled_native = {"id": settled_evidence["evidence_id"], "provider": "bda-provider", "source": "bda-assessment-ledger", "reservation": proposal_a["reservation_id"],
                      "outcome": "EFFECT", "request": attributed_a, "effect_id": "bda-native-a-1", "occurred_at": EFFECT_TIME, "rules_out_past_and_future_effects": False,
                      "evidence_ref": settled_evidence["evidence_ref"], "observed_request": attributed_a, "actual_fields": actual_a, "collections": [],
                      "completion_mismatch": False, "mismatch_reason": None}
    settle_id = reservation_event_id(INSTANCE_A, "effect-engage-a-1", "EFFECT_OBSERVED", "SETTLE", registry_digest)
    settle_a = settle_input(registry_after_first, settle_id, settled_native, [settled_history])

    def apply_settled(rs):
        rs["core"]["budgets"][0]["history"] = settled_history
        rs["core"]["reservations"][0]["status"] = "SETTLED"
        rs["core"]["reservations"][0]["matched_effect"] = "bda-native-a-1"
        rs["core"]["effects"].append({"id": settled_native["id"], "native": settled_native, "native_digest": digest("reservation-native-outcome", settled_native),
                                      "reservation": proposal_a["reservation_id"], "disposition": "MATCHED", "affected_anchors": [ANCHOR], "blocked_partitions": [], "reason": "MATCHED_EFFECT"})
        rs["core"]["effects"].sort(key=lambda row: row["id"].encode())

    registry_settled, settled_result = reservation_transition(registry_after_first, settle_a["event"], settle_a["host_evidence"], decision="SETTLED",
                                                              reservation_id=proposal_a["reservation_id"], budgets=[], authority_result=None, reasons=[], mutate=apply_settled)
    settled_budget = {"registry_digest": registry_digest, "affected_anchors": [ANCHOR], "result": settled_result}
    effect_event_a = governed_effect_event(state_a5, "effect-engage-a-1", permit_a, dispatch_record_a, settled_evidence, registry_after_first, settle_a)
    effect_event_digest_a = digest("runtime-event", effect_event_a)
    settled_outcome = {"kind": "GOVERNED", "outcome_digest": "sha256:" + "0" * 64, "event_id": "effect-engage-a-1", "event_digest": effect_event_digest_a,
                       "permit_digest": permit_a["permit_id"], "dispatch_digest": dispatch_record_a["dispatch_digest"],
                       "dispatch_attempt_digest": dispatch_record_a["dispatch_attempt_digest"], "native_evidence": settled_evidence, "classification": "MATCHED",
                       "reservation_receipt_digests": [settled_result["receipt_digest"]], "conflicts_with_evidence_ids": [], "disputed": False}
    settled_outcome["outcome_digest"] = digest("outcome", omit(settled_outcome, "outcome_digest"))

    def apply_completed(after, _):
        after["status"] = "COMPLETE"
        after["active"] = []
        after["completed"].append({"occurrence": occ_a, "disposition": "SUCCEEDED", "evidence_digest": digest("native-evidence", settled_evidence),
                                   "occurred_at": EFFECT_TIME, "route_label": None, "selected_relationship_digest": relationship_digest, "late": False})
        after["outcomes"].append(settled_outcome)
        after["outcomes"].sort(key=lambda row: row["outcome_digest"].encode())
        after["deadlines"][0]["status"] = "DISCHARGED"

    state_complete, effect_result_a = work_transition(state_a5, effect_event_a, disposition="COMPLETED", reasons=[],
                                                      details=[{"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": settled_result["receipt_digest"], "reasons": []},
                                                               {"kind": "EFFECT", "classification": "MATCHED", "evidence_id": settled_evidence["evidence_id"]},
                                                               {"kind": "ROUTE", "relationship_digests": [relationship_digest], "construct_ids": []}],
                                                      permit=None, budget_results=[settled_budget], authority_result_digest=None,
                                                      reservation_receipt_digests=[settled_result["receipt_digest"]], mutate=apply_completed)
    request_effect_a = step_request("effect-engage-a-1", work_class, state_a5, effect_event_a)

    valid_requests = [deploy_request_a, request_a2, proposal_a["request"], request_a3, request_dispatch_a, request_a4, request_effect_a]
    valid_results = [deploy_result_a, clock_result_a2, proposal_a["result"], clock_result_a3, dispatch_result_a, clock_result_a4, effect_result_a]
    valid_responses = [response(req, res) for req, res in zip(valid_requests, valid_results)]

    write("authority-input.json", auth_a["input"])
    write("authority-result-derived.json", auth_a["result"])
    write("deployment-input.json", deploy_input_a)
    write("deployment-result-derived.json", deploy_result_a)

    scenarios: list[tuple[dict, dict]] = []

    # Variant 2: confidence below the configured bound.
    auth_conf = build_authority(authority_source, authority_work_class, instance_id=INSTANCE_A, occurrence_row=occ_a, fields=proposal_fields("track-17", confidence="0.72"),
                                now=T1, decide_at="2026-09-13T10:00:30Z", attest_at="2026-09-13T10:00:40Z")
    conf_res_id = reservation_event_id(INSTANCE_A, "propose-a-confidence-below-bound", "PROPOSE", "RESERVE", registry_digest)
    conf_event = propose_event(state_a1, "propose-a-confidence-below-bound", occ_a, auth_conf, proposal_fields("track-17", confidence="0.72"), "2",
                               [budget_input(registry_registered, reserve_input(registry_registered, auth_conf, conf_res_id, [initial_history]))])
    _, conf_result = withhold_authority(state_a1, conf_event, [failed_condition(auth_conf, "roe-confidence-at-or-above-bound", T1)])
    scenarios.append((step_request("propose-a-confidence-below-bound", work_class, state_a1, conf_event), conf_result))

    # Variant 3: designated protected status.
    auth_prot = build_authority(authority_source, authority_work_class, instance_id=INSTANCE_A, occurrence_row=occ_a, fields=proposal_fields("track-17", protected_status="PDSS"),
                                now=T1, decide_at="2026-09-13T10:00:30Z", attest_at="2026-09-13T10:00:40Z")
    prot_res_id = reservation_event_id(INSTANCE_A, "propose-a-protected-status", "PROPOSE", "RESERVE", registry_digest)
    prot_event = propose_event(state_a1, "propose-a-protected-status", occ_a, auth_prot, proposal_fields("track-17", protected_status="PDSS"), "2",
                               [budget_input(registry_registered, reserve_input(registry_registered, auth_prot, prot_res_id, [initial_history]))])
    _, prot_result = withhold_authority(state_a1, prot_event, [failed_condition(auth_prot, "roe-target-not-protected", T1)])
    scenarios.append((step_request("propose-a-protected-status", work_class, state_a1, prot_event), prot_result))

    # Variant 5: demonstrated intent absent, then no direction by the deadline.
    auth_intent = build_authority(authority_source, authority_work_class, instance_id=INSTANCE_A, occurrence_row=occ_a, fields=proposal_fields("track-17", demonstrated_intent="NONE"),
                                  now=T1, decide_at="2026-09-13T10:00:30Z", attest_at="2026-09-13T10:00:40Z")
    intent_res_id = reservation_event_id(INSTANCE_A, "propose-a-intent-absent", "PROPOSE", "RESERVE", registry_digest)
    intent_event = propose_event(state_a1, "propose-a-intent-absent", occ_a, auth_intent, proposal_fields("track-17", demonstrated_intent="NONE"), "2",
                                 [budget_input(registry_registered, reserve_input(registry_registered, auth_intent, intent_res_id, [initial_history]))])
    state_a2_withheld, intent_result = withhold_authority(state_a1, intent_event, [failed_condition(auth_intent, "roe-demonstrated-intent-present", T1)])
    scenarios.append((step_request("propose-a-intent-absent", work_class, state_a1, intent_event), intent_result))
    due_clock = available_clock("3", T_DUE)
    due_event = clock_event(state_a2_withheld, "clock-a-3-deadline-due", due_clock)
    state_a3_stopped, stop_result = expire_with_stop(state_a2_withheld, due_event)
    scenarios.append((step_request("clock-a-3-deadline-due", work_class, state_a2_withheld, due_event), stop_result))

    # Variant 4: operator authorization (permit) expires before dispatch.
    expiry_clock = available_clock("3", T_EXPIRY)
    expiry_clock_event = clock_event(state_a2, "clock-a-3-at-expiry", expiry_clock)
    state_a3_expiry, expiry_clock_result = record_clock(state_a2, expiry_clock_event)
    scenarios.append((step_request("clock-a-3-at-expiry", work_class, state_a2, expiry_clock_event), expiry_clock_result))
    expired_event, _, state_a4_expired, expired_result = dispatch(state_a3_expiry, "dispatch-engage-a-expired", permit_a, permit_a["native_request"], "engage-attempt-a-expired",
                                                                   "NOT_SENT", T_EXPIRY, {"status": "NONE", "reference": None, "observed_at": None}, "3",
                                                                   disposition="DISPATCH_REFUSED", reasons=["NATIVE_NOT_SENT", "PERMIT_EXPIRED"], occurrence_status="PERMITTED")
    scenarios.append((step_request("dispatch-engage-a-expired", work_class, state_a3_expiry, expired_event), expired_result))

    # Variant 6: dispatch arguments name a different track.
    other_track_request = {"interface": "fire-control", "operation": "engage-track", "fields": proposal_fields("track-21")}
    other_event, _, _, other_result = dispatch(state_a3, "dispatch-engage-a-other-track", permit_a, other_track_request, "engage-attempt-a-other-track", "NOT_SENT", DISPATCH_AT,
                                               {"status": "NONE", "reference": None, "observed_at": None}, "3",
                                               disposition="DISPATCH_REFUSED", reasons=["NATIVE_ARGUMENT_MISMATCH", "NATIVE_NOT_SENT"], occurrence_status="PERMITTED")
    scenarios.append((step_request("dispatch-engage-a-other-track", work_class, state_a3, other_event), other_result))

    # Variant 7: damage assessment unavailable.
    unknown_evidence = native_evidence("bda-unknown-a-1", "bda-native-a-1", "OUTCOME_UNKNOWN", attributed_a, [], None, EFFECT_OBSERVED)
    unknown_native = {"id": unknown_evidence["evidence_id"], "provider": "bda-provider", "source": "bda-assessment-ledger", "reservation": proposal_a["reservation_id"],
                      "outcome": "UNKNOWN", "request": attributed_a, "effect_id": None, "occurred_at": None, "rules_out_past_and_future_effects": False,
                      "evidence_ref": unknown_evidence["evidence_ref"], "observed_request": None, "actual_fields": [], "collections": [], "completion_mismatch": False, "mismatch_reason": None}
    unknown_settle = settle_input(registry_after_first, reservation_event_id(INSTANCE_A, "effect-engage-a-unknown", "EFFECT_OBSERVED", "SETTLE", registry_digest), unknown_native, [initial_history])

    def apply_unknown(rs):
        rs["core"]["reservations"][0]["status"] = "UNKNOWN"
        rs["core"]["effects"].append({"id": unknown_native["id"], "native": unknown_native, "native_digest": digest("reservation-native-outcome", unknown_native),
                                      "reservation": proposal_a["reservation_id"], "disposition": "UNKNOWN", "affected_anchors": [ANCHOR], "blocked_partitions": [], "reason": "UNKNOWN_OUTCOME"})

    _, unknown_reg_result = reservation_transition(registry_after_first, unknown_settle["event"], unknown_settle["host_evidence"], decision="UNKNOWN",
                                                   reservation_id=proposal_a["reservation_id"], budgets=[], authority_result=None, reasons=[], mutate=apply_unknown)
    unknown_event = governed_effect_event(state_a5, "effect-engage-a-unknown", permit_a, dispatch_record_a, unknown_evidence, registry_after_first, unknown_settle)
    unknown_outcome = {"kind": "GOVERNED", "outcome_digest": "sha256:" + "0" * 64, "event_id": "effect-engage-a-unknown", "event_digest": digest("runtime-event", unknown_event),
                       "permit_digest": permit_a["permit_id"], "dispatch_digest": dispatch_record_a["dispatch_digest"], "dispatch_attempt_digest": dispatch_record_a["dispatch_attempt_digest"],
                       "native_evidence": unknown_evidence, "classification": "UNKNOWN", "reservation_receipt_digests": [unknown_reg_result["receipt_digest"]],
                       "conflicts_with_evidence_ids": [], "disputed": False}
    unknown_outcome["outcome_digest"] = digest("outcome", omit(unknown_outcome, "outcome_digest"))

    def apply_unknown_work(after, _):
        after["active"][0]["status"] = "OUTCOME_UNKNOWN"
        after["outcomes"].append(unknown_outcome)

    _, unknown_result = work_transition(state_a5, unknown_event, disposition="OUTCOME_RETAINED", reasons=["UNKNOWN_OUTCOME"],
                                        details=[{"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": unknown_reg_result["receipt_digest"], "reasons": []},
                                                 {"kind": "EFFECT", "classification": "UNKNOWN", "evidence_id": unknown_evidence["evidence_id"]}],
                                        permit=None, budget_results=[{"registry_digest": registry_digest, "affected_anchors": [ANCHOR], "result": unknown_reg_result}],
                                        authority_result_digest=None, reservation_receipt_digests=[unknown_reg_result["receipt_digest"]], mutate=apply_unknown_work)
    scenarios.append((step_request("effect-engage-a-unknown", work_class, state_a5, unknown_event), unknown_result))

    # Variant 8: effect evidence names a different entity (foreign branch).
    foreign_fields = proposal_fields("track-21")
    foreign_attributed = {**attributed_a, "fields": foreign_fields}
    foreign_actual = sorted(foreign_fields + [field("status", "t.status", "NEUTRALIZED")], key=lambda row: row["name"].encode())
    foreign_evidence = native_evidence("bda-foreign-a-1", "bda-native-foreign-1", "EFFECT_ESTABLISHED", foreign_attributed, foreign_actual, FOREIGN_TIME, FOREIGN_OBSERVED)
    foreign_native = {"id": foreign_evidence["evidence_id"], "provider": "bda-provider", "source": "bda-assessment-ledger", "reservation": proposal_a["reservation_id"],
                      "outcome": "EFFECT", "request": attributed_a, "effect_id": "bda-native-foreign-1", "occurred_at": FOREIGN_TIME, "rules_out_past_and_future_effects": False,
                      "evidence_ref": foreign_evidence["evidence_ref"], "observed_request": foreign_attributed, "actual_fields": foreign_actual, "collections": [],
                      "completion_mismatch": True, "mismatch_reason": "UNEXPECTED_EFFECT"}
    foreign_settle = settle_input(registry_after_first, reservation_event_id(INSTANCE_A, "effect-foreign-other-entity", "EFFECT_OBSERVED", "SETTLE", registry_digest), foreign_native, [initial_history])

    def apply_foreign(rs):
        rs["core"]["reservations"][0]["status"] = "DISPUTED"
        rs["core"]["effects"].append({"id": foreign_native["id"], "native": foreign_native, "native_digest": digest("reservation-native-outcome", foreign_native),
                                      "reservation": proposal_a["reservation_id"], "disposition": "DISPUTED", "affected_anchors": [ANCHOR],
                                      "blocked_partitions": [{"anchor": ANCHOR, "key": [typed("b.identity", "mission-1")]}], "reason": "UNEXPECTED_EFFECT"})

    _, foreign_reg_result = reservation_transition(registry_after_first, foreign_settle["event"], foreign_settle["host_evidence"], decision="EFFECT_DISPUTED",
                                                   reservation_id=proposal_a["reservation_id"], budgets=[], authority_result=None, reasons=["UNEXPECTED_EFFECT"], mutate=apply_foreign)
    foreign_event = {"schema": SCHEMA + "runtime-event", "event_id": "effect-foreign-other-entity", "kind": "EFFECT_OBSERVED", "instance_id": INSTANCE_A,
                     "expected_state_revision": state_a5["revision"], "expected_state_digest": work_state_digest(state_a5), "permit": None, "dispatch_digest": None,
                     "native_evidence": foreign_evidence, "completion_authorization": None, "reservation_id": proposal_a["reservation_id"], "affected_budget_anchors": [ANCHOR],
                     "budget_inputs": [budget_input(registry_after_first, foreign_settle)], "clock_revision": "4", "activation_clocks": []}
    foreign_outcome = {"kind": "FOREIGN", "outcome_digest": "sha256:" + "0" * 64, "event_id": "effect-foreign-other-entity", "event_digest": digest("runtime-event", foreign_event),
                       "permit_digest": None, "dispatch_digest": None, "dispatch_attempt_digest": None, "native_evidence": foreign_evidence, "classification": "FOREIGN",
                       "affected_budget_anchors": [ANCHOR], "reservation_receipt_digests": [foreign_reg_result["receipt_digest"]], "conflicts_with_evidence_ids": [], "disputed": True}
    foreign_outcome["outcome_digest"] = digest("outcome", omit(foreign_outcome, "outcome_digest"))

    def apply_foreign_work(after, _):
        after["outcomes"].append(foreign_outcome)

    _, foreign_result = work_transition(state_a5, foreign_event, disposition="DISPUTED", reasons=["FOREIGN_EFFECT", "BUDGET_EFFECT_DISPUTED", "UNEXPECTED_EFFECT"],
                                        details=[{"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": foreign_reg_result["receipt_digest"], "reasons": ["UNEXPECTED_EFFECT"]},
                                                 {"kind": "EFFECT", "classification": "FOREIGN", "evidence_id": foreign_evidence["evidence_id"]}],
                                        permit=None, budget_results=[{"registry_digest": registry_digest, "affected_anchors": [ANCHOR], "result": foreign_reg_result}],
                                        authority_result_digest=None, reservation_receipt_digests=[foreign_reg_result["receipt_digest"]], mutate=apply_foreign_work)
    scenarios.append((step_request("effect-foreign-other-entity", work_class, state_a5, foreign_event), foreign_result))

    # ---------------------------------------------------------------- instance B
    deploy_input_b, deploy_result_b, state_b0, _ = build_deployment(work_class, INSTANCE_B, review_evidence, initial_clock)
    deploy_request_b = {"protocol": PROTOCOL, "request_id": "deploy-b", "operation": "deploy", "input": deploy_input_b}
    scenarios.append((deploy_request_b, deploy_result_b))
    clock_event_b2 = clock_event(state_b0, "clock-b-2", clock_2)
    state_b1, clock_result_b2 = record_clock(state_b0, clock_event_b2)
    scenarios.append((step_request("clock-b-2", work_class, state_b0, clock_event_b2), clock_result_b2))

    fields_b = proposal_fields("track-18")
    auth_b1 = build_authority(authority_source, authority_work_class, instance_id=INSTANCE_B, occurrence_row=occ_b, fields=fields_b, now=T1,
                              decide_at="2026-09-13T10:00:45Z", attest_at="2026-09-13T10:00:50Z")
    # Variant 10a: second proposal against registry revision 1, individually admissible.
    proposal_b1 = permitted_proposal(state_b1, occ_b, auth_b1, fields_b, "propose-engage-b-1", "2", registry_registered, "3")
    scenarios.append((proposal_b1["request"], proposal_b1["result"]))

    # Variant 10b: retry against revision 2 after A's reservation: 2 committed + 1 pending + 1 = 4 > 3.
    retry_res_id = reservation_event_id(INSTANCE_B, "propose-engage-b-2-retry", "PROPOSE", "RESERVE", registry_digest)
    retry_reserve = reserve_input(registry_after_first, auth_b1, retry_res_id, [initial_history])
    retry_event = propose_event(state_b1, "propose-engage-b-2-retry", occ_b, auth_b1, fields_b, "2", [budget_input(registry_after_first, retry_reserve)])
    _, retry_reg_result = reservation_transition(registry_after_first, retry_reserve["event"], retry_reserve["host_evidence"], decision="WITHHELD", reservation_id=None,
                                                 budgets=[{"anchor": ANCHOR, "result": aggregate_result("4", "VIOLATED")}], authority_result=auth_b1["result"],
                                                 reasons=["BOUND_VIOLATED"], mutate=lambda rs: None)
    retry_proposal_digest = digest("proposal", retry_event)

    def apply_retry(after, event_digest):
        after["proposals"].append({"event_id": retry_event["event_id"], "event_digest": event_digest, "proposal_digest": retry_proposal_digest, "occurrence_id": occ_b["occurrence_id"],
                                   "disposition": "WITHHELD", "permit_digest": None, "authority_result_digest": auth_b1["result_digest"],
                                   "reservation_receipt_digests": [retry_reg_result["receipt_digest"]], "prior_permit_digest": None})

    _, retry_result = work_transition(state_b1, retry_event, disposition="WITHHELD", reasons=["BUDGET_WITHHELD", "BOUND_VIOLATED"],
                                      details=[{"kind": "BUDGET", "registry_digest": registry_digest, "receipt_digest": retry_reg_result["receipt_digest"], "reasons": ["BOUND_VIOLATED"]}],
                                      permit=None, budget_results=[{"registry_digest": registry_digest, "affected_anchors": [ANCHOR], "result": retry_reg_result}],
                                      authority_result_digest=auth_b1["result_digest"], reservation_receipt_digests=[retry_reg_result["receipt_digest"]], mutate=apply_retry)
    scenarios.append((step_request("propose-engage-b-2-retry", work_class, state_b1, retry_event), retry_result))

    # Variant 9: rules of engagement withdrawn; next proposal withheld. A revocation after a permit is not exercised.
    clock_b3 = available_clock("3", T_B3)
    clock_event_b3 = clock_event(state_b1, "clock-b-3", clock_b3)
    state_b2, clock_result_b3 = record_clock(state_b1, clock_event_b3)
    scenarios.append((step_request("clock-b-3", work_class, state_b1, clock_event_b3), clock_result_b3))
    auth_b3 = build_authority(authority_source, authority_work_class, instance_id=INSTANCE_B, occurrence_row=occ_b, fields=fields_b, now=T_B3,
                              decide_at="2026-09-13T10:05:30Z", attest_at="2026-09-13T10:05:40Z", revoked=True)
    withdrawn_res_id = reservation_event_id(INSTANCE_B, "propose-engage-b-3-withdrawn", "PROPOSE", "RESERVE", registry_digest)
    withdrawn_event = propose_event(state_b2, "propose-engage-b-3-withdrawn", occ_b, auth_b3, fields_b, "3",
                                    [budget_input(registry_settled, reserve_input(registry_settled, auth_b3, withdrawn_res_id, [settled_history]))])
    _, withdrawn_result = withhold_authority(state_b2, withdrawn_event, [failed_revocation(auth_b3, auth_b3["envelope_digest"], T_B3)])
    scenarios.append((step_request("propose-engage-b-3-withdrawn", work_class, state_b2, withdrawn_event), withdrawn_result))

    # Variant 11: exact replay of the final effect against the complete final state.
    replay_request = copy.deepcopy(request_effect_a)
    replay_request["request_id"] = "effect-engage-a-1-replay"
    replay_request["input"]["state"] = state_complete
    replay_request["input"]["state_digest"] = work_state_digest(state_complete)
    replay_result = {"status": "STEP", "profile": PROFILE, "role": ROLE, "decision": effect_result_a["decision"], "decision_digest": effect_result_a["decision_digest"],
                     "permit": None, "budget_results": effect_result_a["budget_results"], "state": state_complete, "state_digest": work_state_digest(state_complete),
                     "transition_state_digest": effect_result_a["transition_state_digest"], "transaction_digest": effect_result_a["transaction_digest"], "replay": True}
    scenarios.append((replay_request, replay_result))

    write("instances/b/deployment-input.json", deploy_input_b)
    write("instances/b/deployment-result-derived.json", deploy_result_b)
    write("instances/b/authority-input-revision-1.json", auth_b1["input"])
    write("instances/b/authority-input-withdrawn.json", auth_b3["input"])
    write("instances/b/state-after-clock-3.json", state_b2)

    scenario_requests = [row[0] for row in scenarios]
    scenario_results = [response(req, res) for req, res in scenarios]

    # Expectations: verifier-style assertions derived from the same rules.
    derivations_sha256 = "sha256:" + hashlib.sha256((HERE / "DERIVATIONS.md").read_bytes()).hexdigest()
    exact = {
        "roe-valid": {"response_dispositions": ["DEPLOYED", "CLOCK_RECORDED", "PERMITTED", "CLOCK_RECORDED", "ACKNOWLEDGED", "CLOCK_RECORDED", "COMPLETED"],
                      "final_work_status": "COMPLETE", "final_work_revision": "6", "final_budget_revision": "3", "final_reservation_status": "SETTLED",
                      "committed_count": "3", "pending_count": "0", "final_deadline_status": "DISCHARGED"},
        "roe-confidence-below-bound": {"status": "STEP", "disposition": "WITHHELD", "reason_codes": ["AUTHORITY_NOT_ESTABLISHED", "AUTHORITY_REQUIRED", "CONDITION_VIOLATED"],
                                       "authority_code": "AUTHORITY_NOT_ESTABLISHED", "authority_reasons": ["CONDITION_VIOLATED"],
                                       "authority_failed_checks": [{"purpose": "CONDITION", "requirement_ref": "roe-confidence-at-or-above-bound", "at": T1, "reason": "CONDITION_VIOLATED"}],
                                       "permit": None, "budget_results": [], "occurrence_status": "ACTIVE", "work_revision": "2"},
        "roe-protected-status": {"status": "STEP", "disposition": "WITHHELD", "reason_codes": ["AUTHORITY_NOT_ESTABLISHED", "AUTHORITY_REQUIRED", "CONDITION_VIOLATED"],
                                 "authority_code": "AUTHORITY_NOT_ESTABLISHED", "authority_reasons": ["CONDITION_VIOLATED"],
                                 "authority_failed_checks": [{"purpose": "CONDITION", "requirement_ref": "roe-target-not-protected", "at": T1, "reason": "CONDITION_VIOLATED"}],
                                 "permit": None, "budget_results": [], "occurrence_status": "ACTIVE", "work_revision": "2"},
        "roe-intent-absent-withheld": {"status": "STEP", "disposition": "WITHHELD", "reason_codes": ["AUTHORITY_NOT_ESTABLISHED", "AUTHORITY_REQUIRED", "CONDITION_VIOLATED"],
                                       "authority_failed_checks": [{"purpose": "CONDITION", "requirement_ref": "roe-demonstrated-intent-present", "at": T1, "reason": "CONDITION_VIOLATED"}],
                                       "occurrence_status": "ACTIVE", "permit": None, "budget_results": [], "work_revision": "2"},
        "roe-no-direction-by-deadline-stop": {"status": "STEP", "disposition": "STOPPED", "reason_codes": ["EXPIRY_STOP"], "work_status": "STOPPED", "work_revision": "3",
                                              "completed_disposition": "EXPIRED", "deadline_status": "EXPIRED", "active_count": "0", "permit": None, "budget_results": []},
        "roe-authorization-expired-before-dispatch": {"status": "STEP", "disposition": "DISPATCH_REFUSED", "reason_codes": ["NATIVE_NOT_SENT", "PERMIT_EXPIRED"],
                                                      "occurrence_status": "PERMITTED", "dispatch_record_added": True, "budget_results": [], "work_revision": "4"},
        "roe-dispatch-names-other-track": {"status": "STEP", "disposition": "DISPATCH_REFUSED", "reason_codes": ["NATIVE_ARGUMENT_MISMATCH", "NATIVE_NOT_SENT"],
                                           "occurrence_status": "PERMITTED", "dispatch_record_added": True, "budget_results": [], "work_revision": "4"},
        "roe-assessment-unavailable-unknown": {"status": "STEP", "disposition": "OUTCOME_RETAINED", "reason_codes": ["UNKNOWN_OUTCOME"], "classification": "UNKNOWN",
                                               "occurrence_status": "OUTCOME_UNKNOWN", "budget_decision": "UNKNOWN", "reservation_status": "UNKNOWN", "pending_contribution": "1",
                                               "work_status": "ACTIVE", "deadline_status": "PENDING"},
        "roe-foreign-effect-other-entity": {"status": "STEP", "disposition": "DISPUTED", "reason_codes": ["BUDGET_EFFECT_DISPUTED", "FOREIGN_EFFECT", "UNEXPECTED_EFFECT"],
                                            "classification": "FOREIGN", "occurrence_status": "DISPATCHED", "budget_decision": "EFFECT_DISPUTED", "budget_reasons": ["UNEXPECTED_EFFECT"],
                                            "reservation_status": "DISPUTED", "blocked_partitions": [{"anchor": ANCHOR, "key": [typed("b.identity", "mission-1")]}],
                                            "outcome_disputed": True, "work_status": "ACTIVE"},
        "roe-grant-withdrawn-next-proposal-withheld": {"status": "STEP", "disposition": "WITHHELD", "reason_codes": ["AUTHORITY_NOT_ESTABLISHED", "AUTHORITY_REQUIRED", "REVOKED"],
                                                       "authority_code": "AUTHORITY_NOT_ESTABLISHED", "authority_reasons": ["REVOKED"],
                                                       "authority_failed_checks": [{"purpose": "REVOCATION", "subject": "envelope digest", "at": T_B3, "reason": "REVOKED"}],
                                                       "permit": None, "budget_results": [],
                                                       "budget_unchanged": True, "supplied_registry_revision": "3", "supplied_committed_count": "3"},
        "roe-second-proposal-against-revision-1": {"status": "STEP", "disposition": "PERMITTED", "reason_codes": [], "budget_decision": "RESERVED", "candidate_accumulator": "3",
                                                   "next_registry_revision": "2", "reservation_status": "OPEN"},
        "roe-second-proposal-retry-withheld": {"status": "STEP", "disposition": "WITHHELD", "reason_codes": ["BOUND_VIOLATED", "BUDGET_WITHHELD"], "budget_decision": "WITHHELD",
                                               "budget_reasons": ["BOUND_VIOLATED"], "candidate_accumulator": "4", "next_registry_revision": "3", "permit": None, "work_revision": "2"},
        "roe-restart-every-stage": {"checkpoint_index": "restart/checkpoints.json", "requires_process_local_history": False, "exact_replay": True,
                                    "replay_changes_work_revision": False, "replay_changes_budget_revision": False},
    }
    expectations = {
        "candidate_pin": PIN,
        "status": "DERIVED_PENDING_INDEPENDENT_REVIEW",
        "derivations": {"path": "DERIVATIONS.md", "sha256": derivations_sha256},
        "method": "Every judgment was derived from the cited normative contract in DERIVATIONS.md before either draft-2 implementation or its output was inspected. scenarios/results-derived.jsonl carries the exact expected response bytes; expected_assertions restate the decisive facts.",
        "claim_boundary": source["claim_boundary"],
        "scenarios": [
            {"id": "roe-valid", "direction_variant": "1", "input": {"trace": "valid-trace/requests.jsonl"},
             "expected_judgment": "Deployment installs the root deadline; the operator-decided proposal is permitted and reserves one engagement; the timely dispatch is acknowledged; assessment evidence observed after permit expiry completes the engagement because the dispatch was timely.",
             "state_and_budget_consequence": "The instance is COMPLETE at revision 6; the mission partition holds 3 committed engagements with no pending charge; the deadline is DISCHARGED.",
             "normative_references": ["LIFE-003", "LIFE-007", "LIFE-008", "LIFE-009", "LIFE-010", "LIFE-012", "LIFE-014", "RES-005", "RES-007"]},
            {"id": "roe-confidence-below-bound", "direction_variant": "2", "input": {"request_id": "propose-a-confidence-below-bound"},
             "expected_judgment": "STEP/WITHHELD with AUTHORITY_REQUIRED, AUTHORITY_NOT_ESTABLISHED and CONDITION_VIOLATED; the refusal and AUTHORITY detail name the failed check roe-confidence-at-or-above-bound; the occurrence is held ACTIVE",
             "state_and_budget_consequence": "A withheld proposal record is retained; no permit or reservation exists; the registry is untouched.",
             "normative_references": ["AUTH-001", "AUTH-005", "AUTH-006", "LIFE-007"]},
            {"id": "roe-protected-status", "direction_variant": "3", "input": {"request_id": "propose-a-protected-status"},
             "expected_judgment": "STEP/WITHHELD with the same reason set as variant 2; the refusal and AUTHORITY detail name the failed check roe-target-not-protected, so the record differs from variant 2 by the condition it names (EXPOSED-RULES E2, closed in draft 2)",
             "state_and_budget_consequence": "No permit or reservation; registry untouched.", "normative_references": ["AUTH-005", "AUTH-006", "LIFE-007"]},
            {"id": "roe-authorization-expired-before-dispatch", "direction_variant": "4", "input": {"request_ids": ["clock-a-3-at-expiry", "dispatch-engage-a-expired"], "request_id": "dispatch-engage-a-expired"},
             "expected_judgment": "STEP/DISPATCH_REFUSED with NATIVE_NOT_SENT and PERMIT_EXPIRED at the permit's exclusive expiry",
             "state_and_budget_consequence": "The safe NOT_SENT observation is retained; the occurrence stays PERMITTED; a fresh proposal with fresh authority is required (LIFE-007 renewal).",
             "normative_references": ["LIFE-008", "LIFE-009", "LIFE-014"]},
            {"id": "roe-intent-absent-withheld", "direction_variant": "5", "input": {"request_id": "propose-a-intent-absent"},
             "expected_judgment": "STEP/WITHHELD with CONDITION_VIOLATED naming roe-demonstrated-intent-present: the divergence that requires operator direction",
             "state_and_budget_consequence": "Occurrence ACTIVE, deadline PENDING, no permit or reservation.", "normative_references": ["AUTH-005", "LIFE-007"]},
            {"id": "roe-no-direction-by-deadline-stop", "direction_variant": "5", "input": {"request_id": "clock-a-3-deadline-due"},
             "expected_judgment": "STEP/STOPPED with EXPIRY_STOP when the mission clock reaches the AT_OR_AFTER due instant with no permitted engagement",
             "state_and_budget_consequence": "The occurrence completes as EXPIRED with the clock evidence, the deadline is EXPIRED, the instance is STOPPED, no dispatch can follow.",
             "normative_references": ["COMPOSITION 5.1", "COMPOSITION 5.2", "LIFE-014"]},
            {"id": "roe-dispatch-names-other-track", "direction_variant": "6", "input": {"request_id": "dispatch-engage-a-other-track"},
             "expected_judgment": "STEP/DISPATCH_REFUSED with NATIVE_ARGUMENT_MISMATCH and NATIVE_NOT_SENT",
             "state_and_budget_consequence": "The exact committed permit remains the only authority; the safe observation is retained; no effect is claimed.",
             "normative_references": ["LIFE-008", "LIFE-009"]},
            {"id": "roe-assessment-unavailable-unknown", "direction_variant": "7", "input": {"request_id": "effect-engage-a-unknown"},
             "expected_judgment": "STEP/OUTCOME_RETAINED with UNKNOWN_OUTCOME and reservation UNKNOWN",
             "state_and_budget_consequence": "The occurrence is OUTCOME_UNKNOWN, the engagement remains charged once, the deadline stays PENDING, nothing completes.",
             "normative_references": ["LIFE-010", "LIFE-011", "RES-007"]},
            {"id": "roe-foreign-effect-other-entity", "direction_variant": "8", "input": {"request_id": "effect-foreign-other-entity"},
             "expected_judgment": "STEP/DISPUTED with FOREIGN_EFFECT, BUDGET_EFFECT_DISPUTED and UNEXPECTED_EFFECT; reservation DISPUTED; mission partition blocked",
             "state_and_budget_consequence": "The evidence is retained as a FOREIGN outcome; the current occurrence is unchanged; the reservation stays DISPUTED with no exit in draft 2 (EXPOSED-RULES E1).",
             "normative_references": ["LIFE-006", "LIFE-010", "RES-007", "RESERVATION-RECORDS prior-state table"]},
            {"id": "roe-grant-withdrawn-next-proposal-withheld", "direction_variant": "9", "input": {"request_ids": ["deploy-b", "clock-b-2", "clock-b-3", "propose-engage-b-3-withdrawn"], "request_id": "propose-engage-b-3-withdrawn"},
             "expected_judgment": "STEP/WITHHELD with AUTHORITY_REQUIRED, AUTHORITY_NOT_ESTABLISHED and REVOKED; the failed check is the REVOCATION query on the envelope at the proposal clock",
             "state_and_budget_consequence": "No permit or reservation for instance B; the supplied settled registry (revision 3, 3 committed) is unchanged. A withholding never reaches the registry, so this does not show that instance A's committed effect stands; no revocation is observed on instance A.",
             "normative_references": ["AUTH-005", "AUTH-006", "LIFE-006", "LIFE-007", "LIFE-008"]},
            {"id": "roe-second-proposal-against-revision-1", "direction_variant": "10", "input": {"request_id": "propose-engage-b-1"},
             "expected_judgment": "STEP/PERMITTED with RESERVED at accumulator 3 against registry revision 1; individually admissible, only one of A and B can commit at a serialized host",
             "state_and_budget_consequence": "A second OPEN reservation would advance the registry to revision 2; the host contention itself is demonstrated by the supplier-payment specimen.",
             "normative_references": ["RES-003", "RES-005", "RES-009", "LIFE-020"]},
            {"id": "roe-second-proposal-retry-withheld", "direction_variant": "10", "input": {"request_id": "propose-engage-b-2-retry"},
             "expected_judgment": "STEP/WITHHELD with BUDGET_WITHHELD and BOUND_VIOLATED; 2 committed + 1 pending + 1 = 4 exceeds 3",
             "state_and_budget_consequence": "A withholding receipt advances the registry to revision 3 with no new reservation; only A's pending engagement remains.",
             "normative_references": ["AGG-004", "AGG-008", "RES-005", "LIFE-007"]},
            {"id": "roe-restart-every-stage", "direction_variant": "11", "input": {"states": ["deployment", "clock", "proposal", "clock", "dispatch", "clock", "settlement"]},
             "expected_judgment": "Every request supplies its complete prior work and registry state; exact replay of the settlement changes no revision",
             "state_and_budget_consequence": "restart/checkpoints.json binds every stage state by digest; effect-engage-a-1-replay returns the original transition with replay:true.",
             "normative_references": ["LIFE-013", "LIFE-019", "RES-WIRE-003"]},
        ],
    }
    for scenario in expectations["scenarios"]:
        scenario["expected_assertions"] = exact[scenario["id"]]

    restart_artifacts = {
        "restart/after-deployment-work-state.json": state_a0,
        "restart/after-clock-2-work-state.json": state_a1,
        "restart/after-proposal-permit-work-state.json": state_a2,
        "restart/after-proposal-permit-budget-state.json": registry_after_first,
        "restart/after-clock-3-work-state.json": state_a3,
        "restart/after-dispatch-work-state.json": state_a4,
        "restart/after-clock-4-work-state.json": state_a5,
        "restart/after-settlement-work-state.json": state_complete,
        "restart/after-settlement-budget-state.json": registry_settled,
        "restart/registered-budget-state.json": registry_registered,
    }
    checkpoints = {"candidate_pin": PIN,
                   "note": "Proposal admission, permit creation and reservation commit form one transition, so the proposal and permit checkpoint is one exact state. Each scenario request in scenarios/requests.jsonl also carries its complete prior state.",
                   "checkpoints": []}
    for path, state in restart_artifacts.items():
        kind = "reservation-state" if "budget-state" in path else "work-state"
        checkpoints["checkpoints"].append({"path": path, "digest_kind": kind, "state_digest": reservation_state_digest(state) if kind == "reservation-state" else work_state_digest(state)})
        write(path, state)
    checkpoints["checkpoints"].sort(key=lambda row: row["path"].encode())
    write("restart/checkpoints.json", checkpoints)

    write("valid-trace/requests.json", valid_requests)
    write("valid-trace/results-derived.json", valid_responses)
    write("valid-trace/final-work-state.json", state_complete)
    write("valid-trace/final-budget-state.json", registry_settled)
    write_lines("valid-trace/requests.jsonl", valid_requests)
    write_lines("valid-trace/results-derived.jsonl", valid_responses)
    write("scenarios/requests.json", scenario_requests)
    write("scenarios/results-derived.json", scenario_results)
    write("scenarios/expectations.json", expectations)
    write_lines("scenarios/requests.jsonl", scenario_requests)
    write_lines("scenarios/results-derived.jsonl", scenario_results)

    index = {"candidate_pin": PIN, "construction": "INDEPENDENT_FROM_DRAFT2_IMPLEMENTATIONS", "status": "CONTRACT_DERIVED_CROSS_LANGUAGE_VERIFIED_NON_NORMATIVE",
             "derivations_sha256": derivations_sha256, "files": []}
    for path in sorted(HERE.rglob("*.json")) + sorted(HERE.rglob("*.jsonl")):
        if path.name == "artifact-index.json":
            continue
        index["files"].append({"path": path.relative_to(HERE).as_posix(), "sha256": raw_sha(path.read_bytes())})
    write("artifact-index.json", index)


if __name__ == "__main__":
    main()
