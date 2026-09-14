"""Serialized single-process host foundations for draft 2."""

from __future__ import annotations

import copy
import threading

from . import reservation_v2 as reservation
from .common import canonical, digest, schema_valid


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
            if result.get("status") == "TRANSITION":
                self._state = copy.deepcopy(result["state"])
            return copy.deepcopy(result)

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
        self._roots = {}
        self._budgets = {}
        self._lock = threading.RLock()

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
            for registry_digest, row in proposed_budgets.items():
                self._budgets[(key[0], registry_digest)] = row
            self._roots[key] = {
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
            return result

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

    def submit(self, organization, request, failure_reference=None):
        """Evaluate and atomically commit one event against the owned root."""
        key = (organization, request["state"]["instance_id"])
        with self._lock:
            root = self._roots.get(key)
            if root is None:
                raise ValueError("instance is not installed")
            event = request["event"]
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
            for row in supplied_budgets:
                current = self._budgets.get((organization, row["registry_digest"]))
                supplied = row["request"]["state"]
                supplied_digest = row["request"]["state_digest"]
                if current is None or (
                    supplied_digest != current["state_digest"] or canonical(supplied) != current["state"]
                ):
                    return self._stateful_refusal(organization, root, request, "REVISION_CONFLICT")

            result = self._consumer.step(copy.deepcopy(request))
            if result.get("status") != "STEP":
                return copy.deepcopy(result)
            if result["replay"]:
                raise RuntimeError("consumer replay was not retained by the host")

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

            for row in result["budget_results"]:
                budget_state = row["result"]["state"]
                self._budgets[(organization, row["registry_digest"])] = {
                    "state": canonical(budget_state),
                    "state_value": copy.deepcopy(budget_state),
                    "state_digest": reservation._state_digest(budget_state),
                    "affected_anchors": copy.deepcopy(row["affected_anchors"]),
                }
                if row["registry_digest"] not in root["registry_digests"]:
                    root["registry_digests"].append(row["registry_digest"])
            root["registry_digests"].sort(key=lambda value: value.encode("utf-8"))
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
            }
            self._roots[key] = new_root
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
            return {"transition": copy.deepcopy(result), "host_commit": committed}
