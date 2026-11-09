"""Serialized single-process host foundations for draft 2."""

from __future__ import annotations

import copy
import threading

from . import dispatch_gate, lifecycle, recovery, reservation_v2 as reservation
from .common import IDENTIFIER_PATTERN, PREFIX, Refusal, canonical, digest, parse_json, schema_valid


class SerializedReservationHost:
    """Own one complete reservation state and serialize submitted events.

    The class supplies the reference host's process-local ordering guarantee.
    It does not provide durable storage, external observation authenticity or
    distributed coordination.
    """

    def __init__(self, state, selected_pin):
        if not reservation._replay_state(state, selected_pin):
            raise ValueError("invalid restart state")
        self._pin = selected_pin
        self._state = copy.deepcopy(state)
        self._lock = threading.RLock()

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def submit(self, event, host_evidence):
        with self._lock:
            request = {
                "schema": reservation.PREFIX + "reservation-input",
                "specification_pin": self._pin,
                "state": copy.deepcopy(self._state),
                "state_digest": reservation._state_digest(self._state),
                "event": copy.deepcopy(event),
                "host_evidence": copy.deepcopy(host_evidence),
            }
            result = reservation.aggregate_step(request, self._pin)
            response = copy.deepcopy(result)
            if result.get("status") == "TRANSITION":
                self._state = copy.deepcopy(result["state"])
            return response

    def restart(self, state):
        with self._lock:
            if not reservation._replay_state(state, self._pin):
                raise ValueError("invalid restart state")
            self._state = copy.deepcopy(state)


def _budget_rows(event):
    return event.get("budget_inputs", []) if isinstance(event, dict) else []


def _budget_digest_rows(rows, state_key="state"):
    result = []
    for row in rows:
        state = row[state_key]
        result.append({
            "registry_digest": row["registry_digest"],
            "affected_anchors": copy.deepcopy(row["affected_anchors"]),
            "state_digest": reservation._state_digest(state),
        })
    return sorted(result, key=lambda row: row["registry_digest"].encode("utf-8"))


class SingleProcessReferenceHost:
    """Serialize deployment, evaluation, and atomic in-process commits.

    Lifecycle policy stays in the supplied consumer. This class owns the
    authoritative roots and the private canonical replay preimages required by
    the host boundary.
    """

    def __init__(self, consumer):
        self._consumer = consumer
        self._authoritative = {"roots": {}, "budgets": {}}
        self._dispatch_claims = {}
        self._pending_evidence = {}
        self._lock = threading.RLock()

    @property
    def _roots(self):
        return self._authoritative["roots"]

    @property
    def _budgets(self):
        return self._authoritative["budgets"]

    @staticmethod
    def _key(deploy_request):
        authorization = deploy_request["deployment_authorization"]
        return authorization["organization_id"], deploy_request["instance_id"]

    @staticmethod
    def _admit_budget_roots(rows, selected_pin):
        rows = list(rows)
        if len(rows) > 1:
            raise ValueError("at most one reservation registry is supported")
        admitted = {}
        for row in rows:
            try:
                registry_digest = row["registry_digest"]
                state = row["state"]
                state_digest = reservation._state_digest(state)
                anchors = row["affected_anchors"]
                invalid = (
                    registry_digest in admitted
                    or anchors != sorted(anchors, key=lambda value: value.encode("utf-8"))
                    or len(anchors) != len(set(anchors))
                    or state_digest != row["state_digest"]
                    or state["specification_pin"] != selected_pin
                    or registry_digest != digest("reservation-registry",state["core"]["configuration"])
                    or not reservation._replay_state(state, selected_pin)
                )
            except (KeyError,TypeError,ValueError):
                invalid = True
            if invalid:
                raise ValueError("invalid initial reservation root")
            admitted[registry_digest] = {
                "state": canonical(state),
                "state_value": copy.deepcopy(state),
                "state_digest": state_digest,
                "affected_anchors": copy.deepcopy(row["affected_anchors"]),
            }
        return admitted

    def install(self, deploy_request, budget_roots=()):
        """Calculate and install one authoritative initial root."""
        calculated = self._consumer.deploy(copy.deepcopy(deploy_request))
        if calculated.get("status") != "DEPLOYED":
            return copy.deepcopy(calculated)
        proposed_budgets = self._admit_budget_roots(budget_roots, calculated["state"].get("specification_pin", reservation.PIN))
        installation_budget_roots = canonical([
            {
                "registry_digest": registry_digest,
                "affected_anchors": copy.deepcopy(row["affected_anchors"]),
                "state": copy.deepcopy(row["state_value"]),
                "state_digest": row["state_digest"],
            }
            for registry_digest, row in sorted(proposed_budgets.items(), key=lambda item: item[0].encode("utf-8"))
        ])
        key = self._key(deploy_request)
        with self._lock:
            current = self._roots.get(key)
            request_bytes = canonical(deploy_request)
            state_bytes = canonical(calculated["state"])
            registry_digests = sorted(proposed_budgets, key=lambda value: value.encode("utf-8"))
            if current is not None:
                replay = (
                    current["deploy_request"] == request_bytes
                    and current["state"] == state_bytes
                    and current["installation_budget_roots"] == installation_budget_roots
                )
                if replay:
                    return {
                        "status": "HOST_DEPLOY",
                        "disposition": "INSTALLED",
                        "organization": key[0],
                        "instance_id": key[1],
                        "state_digest": current["state_digest"],
                        "replay": True,
                        "dispatch_performed": False,
                    }
                return {
                    "status": "HOST_DEPLOY",
                    "disposition": "INSTANCE_OCCUPIED",
                    "organization": key[0],
                    "instance_id": key[1],
                    "authoritative_state_digest": current["state_digest"],
                    "proposed_state_digest": calculated["state_digest"],
                    "replay": False,
                    "dispatch_performed": False,
                }
            for registry_digest, row in proposed_budgets.items():
                stored = self._budgets.get((key[0], registry_digest))
                if stored is not None and (stored["state_digest"] != row["state_digest"] or stored["state"] != row["state"]):
                    raise ValueError("reservation root revision conflict")
            next_budgets = dict(self._budgets)
            for registry_digest, row in proposed_budgets.items():
                next_budgets[(key[0], registry_digest)] = row
            next_roots = dict(self._roots)
            next_roots[key] = {
                "deploy_request": request_bytes,
                "state": state_bytes,
                "state_value": copy.deepcopy(calculated["state"]),
                "state_digest": calculated["state_digest"],
                "registry_digests": registry_digests,
                "installation_budget_roots": installation_budget_roots,
                "event_log": {},
            }
            result = {
                "status": "HOST_DEPLOY",
                "disposition": "INSTALLED",
                "organization": key[0],
                "instance_id": key[1],
                "state_digest": calculated["state_digest"],
                "replay": False,
                "dispatch_performed": False,
            }
            if not schema_valid(result, "lifecycle.schema.json", "hostDeploymentResult"):
                raise RuntimeError("host produced an invalid deployment result")
            response = copy.deepcopy(result)
            self._authoritative = {"roots": next_roots, "budgets": next_budgets}
            return response

    def snapshot(self, organization, instance_id):
        with self._lock:
            root = self._roots[(organization, instance_id)]
            return {
                "state": copy.deepcopy(root["state_value"]),
                "state_digest": root["state_digest"],
                "budget_states": [
                    {
                        "registry_digest": registry_digest,
                        "affected_anchors": copy.deepcopy(row["affected_anchors"]),
                        "state": copy.deepcopy(row["state_value"]),
                        "state_digest": row["state_digest"],
                    }
                    for registry_digest in root["registry_digests"]
                    for row in (self._budgets[(organization, registry_digest)],)
                ],
            }

    def _stateful_refusal(self, organization, root, request, code):
        result = {
            "status": "REFUSED",
            "profile": request["profile"],
            "role": request["role"],
            "code": code,
            "path": "",
            "state": copy.deepcopy(root["state_value"]),
            "state_digest": root["state_digest"],
            "budget_states": [
                {
                    "registry_digest": registry_digest,
                    "affected_anchors": copy.deepcopy(row["affected_anchors"]),
                    "state": copy.deepcopy(row["state_value"]),
                    "state_digest": row["state_digest"],
                }
                for registry_digest in root["registry_digests"]
                for row in (self._budgets[(organization, registry_digest)],)
            ],
        }
        if not schema_valid(result, "lifecycle.schema.json", "statefulRefusal"):
            raise RuntimeError("host produced an invalid state refusal")
        return result

    def pending_evidence(self, organization, instance_id):
        """Inspect attributable evidence awaiting a committed classification."""
        with self._lock:
            return [{name: copy.deepcopy(row[name]) for name in (
                "evidence_digest", "event_id", "instance_id", "occurrence_id", "registry_digests", "status")}
                for _, row in sorted(self._pending_evidence.items())
                if row["organization"] == organization and row["instance_id"] == instance_id]

    def _custody_registry(self, organization, state, event, host):
        if event.get("kind") in {"SETTLE", "RELEASE"}:
            return self._custody_registry_native(organization, state, event, host)
        if event.get("kind") != "DISPOSE" or not schema_valid(event, "reservation.schema.json", "recoveryDisposeEvent"):
            return None
        payload, core = event["payload"], state["core"]
        evidence, target = payload["evidence"], payload["target"]
        registry_digest = digest("reservation-registry", core["configuration"])
        if target["kind"] != "RESERVATION" or target["registry_digest"] != registry_digest or evidence["target"] != target:
            return None
        row = next((item for item in core["reservations"] if item["id"] == target["reservation"]), None)
        if row is None:
            return None
        evidence_digest = digest("recovery-evidence", evidence)
        trusted = host.get("recovery") or {}
        if not any(item["kind"] == "RECOVERY_EVIDENCE" and item["record_digest"] == evidence_digest and item["provider"] == evidence["provider"] and item["source"] == evidence["source"] for item in trusted.get("authenticated_records", [])):
            return None
        for budget in core["budgets"]:
            if budget["definition"]["anchor"] in {item["anchor"] for item in row["contributions"]}:
                no_effect = payload["requested_result"] == "ESTABLISH_NO_EFFECT" or payload["requested_result"] == "LEAVE_UNRESOLVED" and evidence["conclusion"] == "NO_EFFECT_ESTABLISHED"
                policy = budget["definition"]["reservation_policy"]["no_effect" if no_effect else "settlement"]
                if (evidence["provider"], evidence["source"]) != (policy["provider"], policy["source"]):
                    return None
        if any(digest("recovery-evidence", item["evidence"]) == evidence_digest for item in core.get("recovery", {}).get("dispositions", [])):
            return None
        proposal = row["authority"]["proposal"]
        self._pending_evidence.setdefault((organization, evidence_digest), {
            "organization": organization, "instance_id": proposal["instance"], "occurrence_id": proposal["occurrence"],
            "evidence_digest": evidence_digest, "event_id": event["id"], "registry_digests": [registry_digest],
            "status": "PENDING", "evidence": copy.deepcopy(evidence), "target": copy.deepcopy(target),
            "scopes": [{"registry_digest": registry_digest, "anchor": item["anchor"], "key": copy.deepcopy(item["key"])} for item in row["contributions"]],
        })
        return evidence_digest

    def _custody_registry_native(self, organization, state, event, host):
        if not schema_valid(event, "reservation.schema.json", "event"):
            return None
        native, core = event["payload"]["native"], state["core"]
        row = next((item for item in core["reservations"] if item["id"] == native["reservation"]), None)
        if row is None:
            return None
        native_digest = digest("reservation-native-outcome", native)
        if not any(item["kind"] == "NATIVE_OUTCOME" and item["record_digest"] == native_digest and item["provider"] == native["provider"] and item["source"] == native["source"] for item in host.get("authenticated_records", [])):
            return None
        for budget in core["budgets"]:
            if budget["definition"]["anchor"] in {item["anchor"] for item in row["contributions"]}:
                policy = budget["definition"]["reservation_policy"]["no_effect" if event["kind"] == "RELEASE" else "settlement"]
                if (native["provider"], native["source"]) != (policy["provider"], policy["source"]):
                    return None
        evidence_digest = digest("recovery-fact", recovery.fact(native))
        if any(digest("recovery-fact", recovery.fact(item["native"])) == evidence_digest for item in core["effects"]):
            return None
        registry_digest = digest("reservation-registry", core["configuration"])
        proposal = row["authority"]["proposal"]
        self._pending_evidence.setdefault((organization, evidence_digest), {
            "organization": organization, "instance_id": proposal["instance"], "occurrence_id": proposal["occurrence"],
            "evidence_digest": evidence_digest, "event_id": event["id"], "registry_digests": [registry_digest],
            "status": "PENDING", "evidence": copy.deepcopy(native),
            "target": {"kind": "RESERVATION", "registry_digest": registry_digest, "reservation": row["id"]},
            "scopes": [{"registry_digest": registry_digest, "anchor": item["anchor"], "key": None if native["completion_mismatch"] else copy.deepcopy(item["key"])} for item in row["contributions"]],
        })
        return evidence_digest

    def submit_registry(self, organization, request, failure_reference=None):
        """Commit a registry event against the same root selected by lifecycle."""
        with self._lock:
            registry_digest = request["host_evidence"]["registry_digest"]
            key = (organization, registry_digest)
            current = self._budgets.get(key)
            if current is None:
                raise ValueError("reservation registry is not installed")
            evidence_digest = self._custody_registry(organization, current["state_value"], request["event"], request["host_evidence"])
            if request["state_digest"] != current["state_digest"] or canonical(request["state"]) != current["state"]:
                return {"transition": reservation._refusal("REVISION_CONFLICT", current["state_value"], current["state_digest"]), "committed": False}
            if request["event"]["kind"] in {"RESERVE", "RENEW"}:
                candidate_scopes = []
                authority_input = request["event"]["payload"]["authority"]
                for budget in current["state_value"]["core"]["budgets"]:
                    try:
                        authorization, projected = reservation._projection_for(budget["authorizations"], authority_input, budget)
                        contributions = reservation._contributions(budget, authorization, projected, authority_input)
                    except (KeyError, TypeError, ValueError, reservation._AdmissionError):
                        continue
                    candidate_scopes.extend({"anchor": row["anchor"], "key": row["key"]} for row in contributions)
                if any(row["organization"] == organization and scope["registry_digest"] == registry_digest
                       and scope["anchor"] == candidate["anchor"] and (scope["key"] is None or scope["key"] == candidate["key"])
                       for row in self._pending_evidence.values() for scope in row["scopes"] for candidate in candidate_scopes):
                    return {"transition": reservation._refusal("EVIDENCE_UNAVAILABLE", current["state_value"], current["state_digest"]), "committed": False}
            owned = copy.deepcopy(request)
            if owned["host_evidence"].get("recovery") is not None:
                pending = owned["host_evidence"]["recovery"]["pending_evidence"]
                existing = {canonical(row) for row in pending}
                for row in self._pending_evidence.values():
                    if row["organization"] == organization and registry_digest in row["registry_digests"] and row.get("target") is not None:
                        item = {"target": copy.deepcopy(row["target"]), "record_digest": row["evidence_digest"]}
                        if canonical(item) not in existing:
                            pending.append(item); existing.add(canonical(item))
                pending.sort(key=canonical)
            result = self._consumer.aggregate_step(owned)
            if result.get("status") != "TRANSITION" or failure_reference is not None:
                return {"transition": copy.deepcopy(result), "committed": False}
            next_budgets = dict(self._budgets)
            next_budgets[key] = {**current, "state": canonical(result["state"]), "state_value": copy.deepcopy(result["state"]), "state_digest": result["state_digest"]}
            self._authoritative = {"roots": self._roots, "budgets": next_budgets}
            if evidence_digest is not None:
                self._pending_evidence.pop((organization, evidence_digest), None)
            return {"transition": copy.deepcopy(result), "committed": True}

    def _custody_evidence(self, organization, root, event, recovery_host=None):
        if event.get("kind") == "DISPOSE":
            return self._custody_recovery(organization, root, event, recovery_host)
        if event.get("kind") != "EFFECT_OBSERVED":
            return None
        evidence = event.get("native_evidence")
        if not schema_valid(evidence, "lifecycle.schema.json", "nativeEvidence"):
            return None
        state = root["state_value"]
        permit = event.get("permit")
        if not isinstance(permit, dict):
            return None
        retained = next((row for row in state["permits"] if row["permit_id"] == permit.get("permit_id")), None)
        dispatch = next((row for row in state["dispatches"] if row["dispatch_digest"] == event.get("dispatch_digest")), None)
        if retained is None or retained != permit or dispatch is None or dispatch["permit_digest"] != permit["permit_id"]:
            return None
        definition = parse_json(root["deploy_request"])["definition"]
        step = dispatch_gate.step_definition(definition, permit)
        completion = step["completion"]
        triple = (completion["no_effect_provider"], completion["no_effect_source"], completion["no_effect_record_type"]) if evidence["status"] == "NO_EFFECT_ESTABLISHED" else (completion["effect_provider"], completion["effect_source"], completion["effect_record_type"])
        if (evidence["provider"], evidence["source"], evidence["record_type"]) != triple:
            return None
        evidence_digest = digest("recovery-fact", recovery.fact(evidence))
        if any(recovery.fact(row["native_evidence"]) == recovery.fact(evidence) for row in state["outcomes"]):
            return None
        scopes = []
        targets = []
        for registry_digest in root["registry_digests"]:
            registry = self._budgets[(organization, registry_digest)]["state_value"]
            for reservation_row in registry["core"]["reservations"]:
                proposal = reservation_row["authority"]["proposal"]
                if proposal["instance"] == state["instance_id"] and proposal["occurrence"] == permit["occurrence"]["occurrence_id"]:
                    scopes.extend({"registry_digest": registry_digest, "anchor": row["anchor"], "key": copy.deepcopy(row["key"])} for row in reservation_row["contributions"])
                    targets.append({"kind": "RESERVATION", "registry_digest": registry_digest, "reservation": reservation_row["id"]})
        if not targets:
            original = next((row for row in state["outcomes"] if row["permit_digest"] == permit["permit_id"] and row["classification"] == "MATCHED"), None)
            if original is not None:
                targets.append({"kind": "WORK_OUTCOME", "instance_id": state["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"], "outcome_digest": original["outcome_digest"]})
        self._pending_evidence.setdefault((organization, evidence_digest), {
            "organization": organization, "evidence_digest": evidence_digest, "event_id": event["event_id"],
            "instance_id": state["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"],
            "registry_digests": sorted({row["registry_digest"] for row in scopes}, key=str.encode),
            "status": "PENDING", "evidence": copy.deepcopy(evidence), "scopes": scopes, "target": targets[0] if len(targets) == 1 else None,
        })
        return evidence_digest

    def _custody_recovery(self, organization, root, event, recovery_host):
        evidence, target = event.get("evidence"), event.get("target")
        if not schema_valid(evidence, "reservation.schema.json", "recoveryEvidence") or evidence["target"] != target:
            return None
        state = root["state_value"]
        try:
            outcome, permit = recovery._work_target(state, target)
        except (KeyError, TypeError, Refusal):
            return None
        definition = parse_json(root["deploy_request"])["definition"]
        step = dispatch_gate.step_definition(definition, permit)
        provider = step["completion"]
        no_effect = event["requested_result"] == "ESTABLISH_NO_EFFECT" or event["requested_result"] == "LEAVE_UNRESOLVED" and evidence["conclusion"] == "NO_EFFECT_ESTABLISHED"
        pair = (provider["no_effect_provider"], provider["no_effect_source"]) if no_effect else (provider["effect_provider"], provider["effect_source"])
        if (evidence["provider"], evidence["source"]) != pair:
            return None
        evidence_digest = digest("recovery-evidence", evidence)
        if recovery_host is None or not any(row["kind"] == "RECOVERY_EVIDENCE" and row["record_digest"] == evidence_digest
                and (row["provider"], row["source"]) == pair for row in recovery_host.get("authenticated_records", [])):
            return None
        if any(digest("recovery-evidence", row["disposition"]["evidence"]) == evidence_digest for row in state.get("recovery_records", [])):
            return None
        self._pending_evidence.setdefault((organization, evidence_digest), {
            "organization": organization, "evidence_digest": evidence_digest, "event_id": event["event_id"],
            "instance_id": state["instance_id"], "occurrence_id": target["occurrence_id"], "registry_digests": [],
            "status": "PENDING", "evidence": copy.deepcopy(evidence), "scopes": [], "target": copy.deepcopy(target),
        })
        return evidence_digest

    def _candidate_scopes(self, organization, root, event):
        result = []
        for row in event.get("budget_inputs", []):
            registry = self._budgets.get((organization, row["registry_digest"]))
            if registry is None:
                continue
            for budget in registry["state_value"]["core"]["budgets"]:
                if budget["definition"]["anchor"] not in row["affected_anchors"]:
                    continue
                try:
                    authority_input = event["authority_input"]
                    authorization, projected = reservation._projection_for(budget["authorizations"], authority_input, budget)
                    contributions = reservation._contributions(budget, authorization, projected, authority_input)
                except (KeyError, TypeError, ValueError, reservation._AdmissionError):
                    continue
                result.extend({"registry_digest": row["registry_digest"], "anchor": contribution["anchor"], "key": contribution["key"]} for contribution in contributions)
        permit = event.get("permit")
        if isinstance(permit, dict):
            for binding in permit["budget_revisions"]:
                registry = self._budgets.get((organization, binding["registry_digest"]))
                if registry is None:
                    continue
                reservation_row = next((row for row in registry["state_value"]["core"]["reservations"] if row["id"] == binding["reservation_id"]), None)
                if reservation_row is not None:
                    result.extend({"registry_digest": binding["registry_digest"], "anchor": contribution["anchor"], "key": contribution["key"]} for contribution in reservation_row["contributions"])
        return result

    def _pending_blocks(self, organization, root, occurrence_id, budget_rows=(), event=None):
        state = root["state_value"]
        occurrence = lifecycle._all_occurrences(state).get(occurrence_id)
        ancestors = set() if occurrence is None else lifecycle._predecessor_closure(state, occurrence)
        for row in self._pending_evidence.values():
            if row["organization"] != organization:
                continue
            if row["instance_id"] == state["instance_id"] and row["occurrence_id"] in ancestors | {occurrence_id}:
                return True
            candidate = self._candidate_scopes(organization, root, event or {})
            if any(scope["registry_digest"] == supplied["registry_digest"] and scope["anchor"] == supplied["anchor"] and (scope["key"] is None or scope["key"] == supplied["key"]) for scope in row["scopes"] for supplied in candidate):
                return True
        return False

    def _permit_registries_current(self, organization, root, permit):
        try:
            state = root["state_value"]
            definition = parse_json(root["deploy_request"])["definition"]
            step = next(row for row in definition["steps"] if row["id"] == permit["occurrence"]["step_id"])
            retained = next(row for row in state["permits"] if row["permit_id"] == permit["permit_id"])
            if permit != retained or state["deployment_organization_id"] != organization:
                return False
            bindings = permit["budget_revisions"]
            if not step["shared_budgets"] and not step.get("exclusive_keys"):
                return not bindings
            if len(bindings) != 1:
                return False
            proposal = next(row for row in state["proposals"] if row["permit_digest"] == permit["permit_id"])
            issued_result = next(row for row in state["replays"] if row["event_id"] == proposal["event_id"])
            if issued_result["permit"] != permit:
                return False
            for binding in bindings:
                registry = self._budgets.get((organization, binding["registry_digest"]))
                if registry is None or binding["registry_digest"] not in root["registry_digests"]:
                    return False
                originals = [row for row in issued_result["budget_results"] if row["registry_digest"] == binding["registry_digest"]]
                if len(originals) != 1:
                    return False
                original = originals[0]
                original_reserved = next(row for row in original["result"]["state"]["core"]["reservations"] if row["id"] == binding["reservation_id"])
                authority = original_reserved["authority"]
                if "authority_basis" in permit and permit["authority_basis"] != authority:
                    return False
                current = registry["state_value"]
                core = current["core"]
                if (current["specification_pin"] != state["specification_pin"]
                        or state["specification_pin"] != reservation.PIN
                        or digest("reservation-registry", core["configuration"]) != binding["registry_digest"]
                        or core["configuration"]["principal"] != authority["envelope"]["principal"]
                        or core["revision"] != binding["revision"]
                        or binding["affected_anchors"] != step["shared_budgets"]
                        or registry["state_digest"] != reservation._state_digest(current)
                        or registry["state"] != canonical(current)):
                    return False
                reservations = [row for row in core["reservations"] if row["id"] == binding["reservation_id"]]
                records = [row for row in current["receipts"] if digest("reservation-receipt", row["receipt"]) == binding["receipt_digest"]]
                if len(reservations) != 1 or len(records) != 1:
                    return False
                reserved, record = reservations[0], records[0]
                receipt = record["receipt"]
                kind = "RENEW" if permit["supersedes_permit_digest"] is not None else "RESERVE"
                if (reserved["status"] != "OPEN" or reserved["authority"] != authority
                        or reserved["authority_result"] != permit["authority_result"]
                        or sorted({row["anchor"] for row in reserved["contributions"]}, key=str.encode) != binding["affected_anchors"]
                        or receipt["revision"] != binding["revision"]
                        or receipt["reservation"] != binding["reservation_id"]
                        or receipt["decision"] != ("RENEWED" if kind == "RENEW" else "RESERVED")
                        or receipt["authority_result"] != permit["authority_result"]
                        or [row["anchor"] for row in receipt["budgets"]] != binding["affected_anchors"]
                        or receipt["next_core_digest"] != digest("reservation-core", core)
                        or record["event"]["kind"] != kind
                        or record["event"]["payload"]["authority"] != authority
                        or record["host_evidence"]["registry_digest"] != binding["registry_digest"]
                        or original["affected_anchors"] != binding["affected_anchors"]
                        or original["result"]["receipt_digest"] != binding["receipt_digest"]
                        or original["result"]["receipt"] != receipt
                        or original["result"]["state"] != current):
                    return False
            return True
        except (KeyError, TypeError, ValueError, StopIteration, Refusal):
            return False

    def submit(self, organization, request, failure_reference=None):
        """Evaluate and atomically commit one event against the owned root."""
        key = (organization, request["state"]["instance_id"])
        with self._lock:
            root = self._roots.get(key)
            if root is None:
                raise ValueError("instance is not installed")
            event = request["event"]
            evidence_digest = self._custody_evidence(organization, root, event, request.get("recovery_host"))
            supplied_budgets = _budget_rows(event)
            retained = root["event_log"].get(event["event_id"])
            if retained is not None and canonical(event) != retained["event"]:
                return self._stateful_refusal(organization, root, request, "REPLAY_CONFLICT")
            if request["state_digest"] != root["state_digest"] or canonical(request["state"]) != root["state"]:
                return self._stateful_refusal(organization, root, request, "REVISION_CONFLICT")
            if retained is not None:
                result = self._consumer.step(copy.deepcopy(request))
                if result.get("status") != "STEP":
                    return copy.deepcopy(result)
                if not result["replay"]:
                    raise RuntimeError("consumer did not recognize retained exact replay")
                return {"transition": copy.deepcopy(result), "host_commit": None}
            occurrence_id = event.get("occurrence", event.get("permit", {}).get("occurrence", {})).get("occurrence_id")
            if event.get("kind") in {"AUTHORIZE_DISPATCH", "PROPOSE"} and self._pending_blocks(organization, root, occurrence_id, supplied_budgets, event):
                return self._stateful_refusal(organization, root, request, "EVIDENCE_UNAVAILABLE")
            if event.get("kind") in {"AUTHORIZE_DISPATCH", "PROPOSE"} and any(
                claim["organization"] == organization and claim["instance_id"] == key[1]
                and claim["status"] == "PENDING" for claim in self._dispatch_claims.values()
            ):
                return self._stateful_refusal(organization, root, request, "PREREQUISITE_MISSING")
            for row in supplied_budgets:
                current = self._budgets.get((organization, row["registry_digest"]))
                supplied = row["request"]["state"]
                supplied_digest = row["request"]["state_digest"]
                if current is None or (
                    supplied_digest != current["state_digest"] or canonical(supplied) != current["state"]
                ):
                    return self._stateful_refusal(organization, root, request, "REVISION_CONFLICT")
            selected_recovery = list(request.get("recovery_registries", []))
            if event.get("kind") == "APPLY_DISPOSITION":
                selected_recovery.append(event["registry"])
                if any(row["organization"] == organization and row.get("target") == event["target"] for row in self._pending_evidence.values()):
                    return self._stateful_refusal(organization, root, request, "EVIDENCE_UNAVAILABLE")
            for selection in selected_recovery:
                registry_digest = digest("reservation-registry", selection["state"]["core"]["configuration"])
                current = self._budgets.get((organization, registry_digest))
                if current is None or selection["state_digest"] != current["state_digest"] or canonical(selection["state"]) != current["state"]:
                    return self._stateful_refusal(organization, root, request, "REVISION_CONFLICT")

            owned = copy.deepcopy(request)
            if owned.get("recovery_host") is not None:
                pending = owned["recovery_host"]["pending_evidence"]
                existing = {canonical(row) for row in pending}
                for row in self._pending_evidence.values():
                    if row["organization"] == organization and row["instance_id"] == key[1] and row.get("target") is not None:
                        item = {"target": copy.deepcopy(row["target"]), "record_digest": row["evidence_digest"]}
                        if canonical(item) not in existing:
                            pending.append(item); existing.add(canonical(item))
                pending.sort(key=canonical)
            result = self._consumer.step(owned)
            if result.get("status") != "STEP":
                return copy.deepcopy(result)
            if result["replay"]:
                raise RuntimeError("consumer replay was not retained by the host")
            if event.get("kind") == "AUTHORIZE_DISPATCH" and not self._permit_registries_current(organization, root, event.get("permit")):
                return self._stateful_refusal(organization, root, request, "EVIDENCE_UNAVAILABLE")

            before_budgets = _budget_digest_rows([
                {
                    "registry_digest": row["registry_digest"],
                    "affected_anchors": row["affected_anchors"],
                    "state": row["request"]["state"],
                }
                for row in supplied_budgets
            ])
            after_budgets = _budget_digest_rows([
                {
                    "registry_digest": row["registry_digest"],
                    "affected_anchors": row["affected_anchors"],
                    "state": row["result"]["state"],
                }
                for row in result["budget_results"]
            ])
            if failure_reference is not None:
                failed = {
                    "status": "HOST_COMMIT",
                    "disposition": "COMMIT_FAILED",
                    "transaction_digest": result["transaction_digest"],
                    "state_before_digest": request["state_digest"],
                    "authoritative_state_digest": root["state_digest"],
                    "budget_before": before_budgets,
                    "authoritative_budgets": before_budgets,
                    "failure_reference": failure_reference,
                    "dispatch_performed": False,
                }
                if not schema_valid(failed, "lifecycle.schema.json", "hostCommitResult"):
                    raise RuntimeError("host produced an invalid commit failure")
                return {"transition": copy.deepcopy(result), "host_commit": failed}

            next_budgets = dict(self._budgets)
            registry_digests = list(root["registry_digests"])
            for row in result["budget_results"]:
                budget_state = row["result"]["state"]
                next_budgets[(organization, row["registry_digest"])] = {
                    "state": canonical(budget_state),
                    "state_value": copy.deepcopy(budget_state),
                    "state_digest": reservation._state_digest(budget_state),
                    "affected_anchors": copy.deepcopy(row["affected_anchors"]),
                }
                if row["registry_digest"] not in registry_digests:
                    registry_digests.append(row["registry_digest"])
            registry_digests.sort(key=lambda value: value.encode("utf-8"))
            next_log = copy.deepcopy(root["event_log"])
            next_log[event["event_id"]] = {
                "event_digest": digest("runtime-event", event),
                "transaction_digest": result["transaction_digest"],
                "event": canonical(event),
                "request": canonical(request),
                "response": canonical(result),
            }
            new_root = {
                **root,
                "state": canonical(result["state"]),
                "state_value": copy.deepcopy(result["state"]),
                "state_digest": result["state_digest"],
                "event_log": next_log,
                "registry_digests": registry_digests,
            }
            next_roots = dict(self._roots)
            next_roots[key] = new_root
            committed = {
                "status": "HOST_COMMIT",
                "disposition": "COMMITTED",
                "transaction_digest": result["transaction_digest"],
                "state_before_digest": request["state_digest"],
                "state_after_digest": result["state_digest"],
                "budget_before": before_budgets,
                "budget_after": after_budgets,
                "dispatch_performed": False,
            }
            if not schema_valid(committed, "lifecycle.schema.json", "hostCommitResult"):
                raise RuntimeError("host produced an invalid commit result")
            response = {"transition": copy.deepcopy(result), "host_commit": copy.deepcopy(committed)}
            self._authoritative = {"roots": next_roots, "budgets": next_budgets}
            if evidence_digest is not None:
                self._pending_evidence.pop((organization, evidence_digest), None)
            return response

    def dispatch_claims(self, organization, instance_id):
        """Inspect process-local claims; this is not a durable recovery store."""
        with self._lock:
            return copy.deepcopy(sorted(
                [row for row in self._dispatch_claims.values() if row["organization"] == organization and row["instance_id"] == instance_id],
                key=lambda row: row["dispatch_intent_id"].encode("utf-8"),
            ))

    def _dispatch_observation(self, organization, claim, observation, event_id):
        key = (organization, claim["instance_id"])
        with self._lock:
            root = self._roots[key]
            state = root["state_value"]
            clocks = [row for row in state["clocks"] if row["source"] == claim["permit"]["clock_source"]]
            current = max(clocks, key=lambda row: int(row["revision"]))
            if current["status"] != "AVAILABLE":
                return {"status": "HOST_DISPATCH", "disposition": "PENDING", "dispatch_performed": True}
            event = {
                "schema": PREFIX + "runtime-event", "event_id": event_id, "kind": "DISPATCH_OBSERVED",
                "instance_id": claim["instance_id"], "expected_state_revision": state["revision"],
                "expected_state_digest": root["state_digest"], "permit": copy.deepcopy(claim["permit"]),
                "native_request": copy.deepcopy(claim["authorization"]["native_request"]),
                "connector": copy.deepcopy(claim["authorization"]["connector"]),
                "authorization_digest": claim["authorization_digest"], "clock_revision": current["revision"],
                "attempt": copy.deepcopy(observation["attempt"]), "acknowledgement": copy.deepcopy(observation["acknowledgement"]),
            }
            definition = parse_json(root["deploy_request"])["definition"]
            request = {"specification_pin": state["specification_pin"],
                       "definition": definition, "definition_digest": state["work_class_digest"], "profile": state["profile"],
                       "role": state["role"], "state": copy.deepcopy(state), "state_digest": root["state_digest"], "event": event}
            try:
                result = self.submit(organization, request)
            except Exception:
                return {"status": "HOST_DISPATCH", "disposition": "PENDING", "dispatch_performed": True}
            if (result.get("host_commit") or {}).get("disposition") == "COMMITTED":
                safe = observation["attempt"]["status"] == "NOT_SENT" and observation["acknowledgement"]["status"] != "ACCEPTED"
                retained_observation = copy.deepcopy(observation)
                retained_result = copy.deepcopy(result)
                claim.update(status="NOT_SENT" if safe else "CONSUMED", observation=retained_observation, result=retained_result)
            return result

    @staticmethod
    def _unknown_attempt(claim):
        authorization, permit = claim["authorization"], claim["permit"]
        native = authorization["native_request"]
        return {"attempt": {
            "attempt_id": "attempt:" + digest("dispatch-intent-attempt", {"instance_id": claim["instance_id"], "dispatch_intent_id": claim["dispatch_intent_id"]})[7:],
            "attempted_at": claim["attempted_at"], "status": "UNKNOWN",
            "request_digest": digest("dispatch-native-request", {"instance_id": claim["instance_id"], "occurrence_id": permit["occurrence"]["occurrence_id"], **native}),
        }, "acknowledgement": {"status": "NONE", "observed_at": None, "reference": None}}

    def dispatch(self, organization, instance_id, authorization_digest, connector_callable, event_id):
        """Claim once, invoke once, then retain a conservative observation.

        Claims and commit ordering are process-local. A production host must
        persist the claim before invocation and qualify crash recovery separately.
        A gated connector supplies id, version, binding_digest and invoke.
        The trusted host associates that metadata with the implementation;
        invoke owns the provider's full-vector conditional write.
        """
        if not isinstance(event_id, str) or not IDENTIFIER_PATTERN.fullmatch(event_id):
            raise Refusal("INPUT_INVALID")
        key = (organization, instance_id)
        with self._lock:
            root = self._roots[key]
            state = root["state_value"]
            authorization = next((row for row in state.get("authorizations", []) if row["authorization_digest"] == authorization_digest), None)
            if authorization is None or "dispatch_intent_id" not in authorization:
                raise Refusal("PREREQUISITE_MISSING")
            claim_key = (organization, instance_id, authorization["dispatch_intent_id"])
            retained = self._dispatch_claims.get(claim_key)
            if retained is not None:
                return {"status": "HOST_DISPATCH", "disposition": retained["status"], "dispatch_performed": False, "replay": True}
            if event_id in root["event_log"]:
                raise Refusal("REPLAY_CONFLICT")
            if any(row["organization"] == organization and row["instance_id"] == instance_id and row["status"] == "PENDING" for row in self._dispatch_claims.values()):
                raise Refusal("PREREQUISITE_MISSING")
            permit = next(row for row in state["permits"] if row["permit_id"] == authorization["permit_digest"])
            if not self._permit_registries_current(organization, root, permit):
                raise Refusal("EVIDENCE_UNAVAILABLE")
            if self._pending_blocks(organization, root, permit["occurrence"]["occurrence_id"], [
                {"registry_digest": registry_digest, "affected_anchors": self._budgets[(organization, registry_digest)]["affected_anchors"]}
                for registry_digest in root["registry_digests"]
            ], {"permit": permit}):
                raise Refusal("EVIDENCE_UNAVAILABLE")
            for binding in permit["budget_revisions"]:
                budget = self._budgets.get((organization, binding["registry_digest"]))
                if budget is None:
                    raise Refusal("EVIDENCE_UNAVAILABLE")
                core = budget["state_value"]["core"]
                if core["configuration"].get("recovery") is None:
                    continue
                clocks = [row for row in state["clocks"] if row["source"] == core["configuration"]["clock_source"]]
                current = max(clocks, key=lambda row: int(row["revision"])) if clocks else None
                if current is None or current["status"] != "AVAILABLE":
                    raise Refusal("CLOCK_INVALID")
                recovery._registry_clock(core, current["observed_time"])
                retained = next((row for row in core["reservations"] if row["id"] == binding["reservation_id"]), None)
                if retained is None or any(reservation._blocked(core, row["anchor"], row["key"], current["observed_time"]) for row in retained["contributions"]):
                    raise Refusal("EVIDENCE_UNAVAILABLE")
            definition = parse_json(root["deploy_request"])["definition"]
            recovery.permission_boundary({"definition": definition, "state": state, "event": {"kind": "AUTHORIZE_DISPATCH", "permit": permit},
                "recovery_registries": [{"state": self._budgets[(organization, registry_digest)]["state_value"],
                    "state_digest": self._budgets[(organization, registry_digest)]["state_digest"],
                    "host_evidence": {"registry_digest": registry_digest, "selection_evidence": "reference-host-owned-current-root", "administration_bases": [], "authenticated_records": []}}
                    for registry_digest in root["registry_digests"]]})
            if not dispatch_gate.step_definition(definition, permit).get("dispatch_gate") or not lifecycle._validate_state_integrity(state, definition):
                raise Refusal("STATE_INVALID")
            current_head = dispatch_gate.head(state, permit["permit_id"])
            current_evaluation = dispatch_gate.latest_evaluation(state, permit["permit_id"])
            active = next((row for row in state["active"] if row["occurrence"]["occurrence_id"] == permit["occurrence"]["occurrence_id"]), None)
            clocks = [row for row in state["clocks"] if row["source"] == permit["clock_source"]]
            current = max(clocks, key=lambda row: int(row["revision"]))
            if (current_head is None or current_head["authorization_digest"] != authorization_digest or state["status"] != "ACTIVE"
                    or current_evaluation is None or current_evaluation["disposition"] != "AUTHORIZED"
                    or current_evaluation["authorization_digest"] != authorization_digest
                    or active is None or active["status"] != "PERMITTED" or dispatch_gate.consumed(state, permit["permit_id"])
                    or any(row["supersedes_permit_digest"] == permit["permit_id"] for row in state["permits"])
                    or any(row.get("authorization_digest") == authorization_digest for row in state["dispatches"])):
                raise Refusal("PREREQUISITE_MISSING")
            if current["status"] != "AVAILABLE":
                raise Refusal("CLOCK_INVALID")
            if not lifecycle._parse(authorization["authorization_fence"]["checked_at"]) <= lifecycle._parse(current["observed_time"]) < lifecycle._parse(authorization["expires_at"]):
                raise Refusal("PREREQUISITE_MISSING")
            if (not isinstance(connector_callable, dict) or set(connector_callable) != {"id", "version", "binding_digest", "invoke"}
                    or not callable(connector_callable["invoke"])):
                raise Refusal("INPUT_INVALID")
            metadata = {name: connector_callable[name] for name in ("id", "version", "binding_digest")}
            if not schema_valid(metadata, "lifecycle.schema.json", "connector"):
                raise Refusal("INPUT_INVALID")
            if metadata != authorization["connector"]:
                raise Refusal("BINDING_MISMATCH")
            invoke = connector_callable["invoke"]
            claim = {"organization": organization, "instance_id": instance_id, "dispatch_intent_id": authorization["dispatch_intent_id"],
                     "authorization_digest": authorization_digest, "authorization": copy.deepcopy(authorization), "permit": copy.deepcopy(permit),
                     "attempted_at": current["observed_time"], "status": "PENDING"}
            self._dispatch_claims[claim_key] = claim
        payload = {"instance_id": instance_id, "authorization_digest": authorization_digest,
                   "dispatch_intent_id": authorization["dispatch_intent_id"], "native_request": copy.deepcopy(authorization["native_request"]),
                   "connector": copy.deepcopy(authorization["connector"]), "authorization_fence": copy.deepcopy(authorization["authorization_fence"]),
                   "expires_at": authorization["expires_at"]}
        try:
            observation = invoke(payload)
            valid = (isinstance(observation, dict) and set(observation) == {"attempt", "acknowledgement"}
                     and schema_valid(observation["attempt"], "lifecycle.schema.json", "attempt")
                     and schema_valid(observation["acknowledgement"], "lifecycle.schema.json", "acknowledgement")
                     and observation["attempt"]["request_digest"] == self._unknown_attempt(claim)["attempt"]["request_digest"]
                     and observation["attempt"]["attempted_at"] == claim["attempted_at"])
            if not valid:
                return {"status": "HOST_DISPATCH", "disposition": "PENDING", "dispatch_performed": True}
        except Exception:
            return {"status": "HOST_DISPATCH", "disposition": "PENDING", "dispatch_performed": True}
        return self._dispatch_observation(organization, claim, observation, event_id)

    def recover_dispatch(self, organization, instance_id, dispatch_intent_id, event_id):
        """Retain UNKNOWN for an unresolved process-local claim without retrying."""
        with self._lock:
            claim = self._dispatch_claims[(organization, instance_id, dispatch_intent_id)]
            if claim["status"] != "PENDING":
                return copy.deepcopy(claim.get("result"))
            return self._dispatch_observation(organization, claim, self._unknown_attempt(claim), event_id)
