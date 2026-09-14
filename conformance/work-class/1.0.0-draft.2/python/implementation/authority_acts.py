"""Selected-act, attribution, return, and separation phase."""
from __future__ import annotations

import base64
import json

try:
    from .authority import _inside, _instant, _records, canonical, digest, _refusal
except ImportError:
    from authority import _inside, _instant, _records, canonical, digest, _refusal


def evaluate_acts(request, envelope, root, proposal, step, now, operation_digest):
    acts = _records(request["acts"])
    capacities = _records(request["capacities"])
    occupancies = _records(request["occupancies"])
    envelope_digest = digest("authority-envelope", envelope)
    root_digest = digest("authority-root", root)
    gate = envelope["gate"]

    def candidates(kind, subject=None):
        return [act for act in acts.values() if act["kind"] == kind and (subject is None or act["subject_digest"] == subject)]

    selected = []
    grant_candidates = candidates("GRANT", envelope_digest)
    if len(grant_candidates) > 1:
        return _refusal("ACT_CONFLICT")
    if not grant_candidates:
        if envelope["grant_ref"] in acts:
            return _refusal("ACT_NOT_AUTHORIZED")
        return _refusal("EVIDENCE_UNAVAILABLE")
    grant = grant_candidates[0]
    if grant["id"] != envelope["grant_ref"]:
        return _refusal("ACT_CONFLICT")
    selected.append(grant)

    grant_attestations = candidates("ORGANISATIONAL_ATTESTATION", digest("authority-act", grant))
    if len(grant_attestations) > 1:
        return _refusal("ACT_CONFLICT")
    if not grant_attestations:
        return _refusal("EVIDENCE_UNAVAILABLE")
    selected.append(grant_attestations[0])

    required_kind = {"NONE": None, "VERIFY": "VERIFY", "DECIDE": "INSTANCE_DECISION"}[gate["kind"]]
    if required_kind:
        all_gate_acts = candidates(required_kind, operation_digest)
        if len(all_gate_acts) > 1:
            return _refusal("ACT_CONFLICT")
        if not all_gate_acts:
            return _refusal("GATE_REQUIRED")
        gate_act = all_gate_acts[0]
        selected.append(gate_act)
        if gate["kind"] == "DECIDE":
            decision_attestations = candidates("ORGANISATIONAL_ATTESTATION", digest("authority-act", gate_act))
            if len(decision_attestations) > 1:
                return _refusal("ACT_CONFLICT")
            if not decision_attestations:
                return _refusal("EVIDENCE_UNAVAILABLE")
            selected.append(decision_attestations[0])

    expected_role = {
        "GRANT": envelope["grantor_role"],
        "ORGANISATIONAL_ATTESTATION": envelope["attester_role"],
        "VERIFY": gate["role"],
        "INSTANCE_DECISION": gate["role"],
    }
    unauthorized = False
    not_accepted = False
    for act in selected:
        capacity = capacities.get(act["capacity"])
        occupancy = occupancies.get(act["occupancy"])
        if not capacity or not occupancy:
            unauthorized = True
            continue
        if (
            capacity["root_digest"] != root_digest
            or capacity["envelope_digest"] != envelope_digest
            or capacity["principal"] != envelope["principal"]
            or act["actor"] != capacity["actor"]
            or act["role"] != capacity["role"]
            or act["principal"] != capacity["principal"]
            or act["occupancy"] != capacity["occupancy"]
            or act["kind"] not in capacity["act_kinds"]
            or act["actor"] != occupancy["actor"]
            or act["role"] != occupancy["role"]
            or act["principal"] != occupancy["principal"]
            or occupancy["kind"] != "HUMAN"
            or capacity["provider"] not in root["providers"]
            or occupancy["provider"] not in root["providers"]
            or act["role"] != expected_role[act["kind"]]
        ):
            unauthorized = True
        try:
            occurred = _instant(act["occurred_at"])
            if not _inside(root["validity"], occurred) or not _inside(capacity["validity"], occurred) or not _inside(occupancy["validity"], occurred):
                unauthorized = True
            if now is not None and occurred > now:
                unauthorized = True
        except (TypeError, ValueError):
            unauthorized = True
            occurred = None
        if act["disposition"] != "ACCEPT":
            not_accepted = True
        if act["kind"] == "GRANT":
            if act["subject_digest"] != envelope_digest or act["criteria"] or act["attested_actor"] is not None:
                unauthorized = True
        elif act["kind"] == "ORGANISATIONAL_ATTESTATION":
            subject = next((candidate for candidate in acts.values() if digest("authority-act", candidate) == act["subject_digest"]), None)
            if not subject or subject["kind"] == "ORGANISATIONAL_ATTESTATION" or act["attested_actor"] != subject["actor"] or act["criteria"]:
                unauthorized = True
            else:
                try:
                    if _instant(act["occurred_at"]) < _instant(subject["occurred_at"]):
                        unauthorized = True
                except (TypeError, ValueError):
                    unauthorized = True
            if subject and act["actor"] == subject["actor"] and not (capacity["may_self_attest"] and root["allow_self_attestation"]):
                unauthorized = True
        elif act["kind"] in ("VERIFY", "INSTANCE_DECISION"):
            criterion_ids = [criterion["id"] for criterion in gate["criteria"] if criterion["step"] == proposal["step"]]
            if act["subject_digest"] != operation_digest or act["criteria"] != criterion_ids or act["attested_actor"] is not None:
                unauthorized = True

    # AUTHORITY-CHECKS: accumulate the phase-4 failures and select by the phase order, never by loop order.
    selected_digests = {digest("authority-act", act) for act in selected}
    returns = {}
    missing = False
    for act in selected:
        act_digest = digest("authority-act", act)
        matches = [returned for returned in request["returns"] if returned["act_digest"] == act_digest]
        if len(matches) != 1:
            missing = True
            continue
        returned = matches[0]
        if returned["actor"] != act["actor"]:
            unauthorized = True
            continue
        try:
            raw = base64.b64decode(returned["act_bytes_base64"], validate=True)
            decoded = json.loads(raw.decode("utf-8"))
            returned_at = _instant(returned["returned_at"])
            if decoded != act or raw != canonical(act) or returned_at < _instant(act["occurred_at"]) or (now is not None and returned_at > now):
                unauthorized = True
                continue
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            unauthorized = True
            continue
        channel = next((channel for channel in root["channels"] if channel["id"] == returned["channel"]), None)
        if not channel or channel["provider"] != returned["provider"] or returned["provider"] not in root["providers"] or not _inside(channel["validity"], returned_at):
            unauthorized = True
            continue
        if now is not None and not _inside(channel["validity"], now) and not channel["prior_returns_survive_expiry"]:
            unauthorized = True
        if not any(
            item["kind"] == "RETURN"
            and item["record_digest"] == digest("authority-return", returned)
            and item["provider"] == returned["provider"]
            and item["channel"] == returned["channel"]
            for item in request["host_selection"]["authenticated_records"]
        ):
            unauthorized = True
        returns[act_digest] = returned

    if any(returned["act_digest"] not in selected_digests for returned in request["returns"]):
        unauthorized = True
    if missing:
        return _refusal("EVIDENCE_UNAVAILABLE")
    if unauthorized:
        return _refusal("ACT_NOT_AUTHORIZED")
    if not_accepted:
        return _refusal("ACT_NOT_ACCEPTED")
    return {"selected": selected, "returns": returns}
