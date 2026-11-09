"""Process-local permission writers and synchronous native commitment ordering."""
from __future__ import annotations

import copy

from . import holdings, lifecycle
from .common import PIN, Refusal, canonical, digest, parse_json, schema_valid
from .reference_host import SingleProcessReferenceHost


class HoldingsReferenceHost(SingleProcessReferenceHost):
    """Protect internal records; callers separately authorize reads and writers."""

    def __init__(self, consumer):
        super().__init__(consumer)
        self._holdings = {}
        self._holdings_failure = None
        self._commit_in_progress = False

    def install_holdings(self, organization, configuration, state, state_digest):
        with self._lock:
            if self._commit_in_progress:
                raise Refusal("PREREQUISITE_MISSING")
            holdings.validate_configuration(configuration)
            holdings.validate_state(configuration, state, state_digest)
            if state is None:
                raise Refusal("STATE_INVALID")
            key = (organization, holdings.configuration_digest(configuration))
            if key in self._holdings:
                raise Refusal("DEFINITION_CONFLICT")
            self._holdings[key] = {"configuration": copy.deepcopy(configuration), "state": copy.deepcopy(state), "state_digest": state_digest}

    def holdings_snapshot(self, organization, configuration_digest):
        with self._lock:
            return copy.deepcopy(self._holdings[(organization, configuration_digest)])

    def submit_holdings(self, organization, request, fail_before_write=False):
        with self._lock:
            if self._commit_in_progress:
                raise Refusal("PREREQUISITE_MISSING")
            if not isinstance(request, dict) or not isinstance(request.get("configuration"), dict):
                return self._consumer.holdings_step(request)
            key = (organization, holdings.configuration_digest(request["configuration"]))
            current = self._holdings.get(key)
            if current is not None and (request.get("state") != current["state"] or request.get("state_digest") != current["state_digest"]):
                return {"status": "REFUSED", "code": "REVISION_CONFLICT", "path": "",
                    "state": copy.deepcopy(request.get("state")), "state_digest": request.get("state_digest")}
            if current is None and request.get("state") is not None:
                raise Refusal("EVIDENCE_UNAVAILABLE")
            result = self._consumer.holdings_step(copy.deepcopy(request))
            if result.get("status") != "TRANSITION" or result["replay"]:
                return result
            if fail_before_write:
                return {"status": "HOST_COMMIT", "disposition": "COMMIT_FAILED", "dispatch_performed": False}
            self._holdings[key] = {"configuration": copy.deepcopy(request["configuration"]),
                "state": copy.deepcopy(result["state"]), "state_digest": result["state_digest"]}
            return result

    def _owned_bases(self, organization, authority_input):
        for basis in authority_input.get("holdings_bases", []):
            key = (organization, holdings.configuration_digest(basis["configuration"]))
            current = self._holdings.get(key)
            if current is None:
                raise Refusal("EVIDENCE_UNAVAILABLE")
            if basis["configuration"] != current["configuration"] or basis["state_digest"] != current["state_digest"] or basis["state"] != current["state"]:
                raise Refusal("REVISION_CONFLICT")

    def submit(self, organization, request, failure_reference=None):
        with self._lock:
            event = request["event"]
            if event["kind"] in {"PROPOSE", "AUTHORIZE_DISPATCH"} and event.get("authority_input") is not None:
                self._owned_bases(organization, event["authority_input"])
            return super().submit(organization, request, failure_reference)

    def dispatch(self, organization, instance_id, authorization_digest, connector_callable, event_id, failure_stage=None):
        if failure_stage not in {None, "PRE_INTENT", "POST_INTENT", "POST_ACCEPTANCE", "OUTCOME_WRITE"}:
            raise Refusal("INPUT_INVALID")
        with self._lock:
            root = self._roots[(organization, instance_id)]
            state = root["state_value"]
            authorization = next((row for row in state.get("authorizations", []) if row["authorization_digest"] == authorization_digest), None)
            if authorization is None:
                raise Refusal("PREREQUISITE_MISSING")
            if (not isinstance(connector_callable, dict) or set(connector_callable) != {"id", "version", "binding_digest", "invoke"}
                    or not callable(connector_callable["invoke"])):
                raise Refusal("INPUT_INVALID")
            metadata = {name: connector_callable[name] for name in ("id", "version", "binding_digest")}
            if not schema_valid(metadata, "lifecycle.schema.json", "connector"):
                raise Refusal("INPUT_INVALID")
            if metadata != authorization["connector"]:
                raise Refusal("BINDING_MISMATCH")
            claim_key = (organization, instance_id, authorization.get("dispatch_intent_id"))
            retained = self._dispatch_claims.get(claim_key)
            if retained is not None:
                if retained["authorization_digest"] != authorization_digest or retained["authorization"] != authorization:
                    raise Refusal("REPLAY_CONFLICT")
                return {"status": "HOST_DISPATCH", "disposition": retained["status"], "dispatch_performed": False, "replay": True}
            fresh = authorization.get("authority_input")
            if fresh is None:
                raise Refusal("STATE_INVALID")
            self._owned_bases(organization, fresh)
            permit = next(row for row in state["permits"] if row["permit_id"] == authorization["permit_digest"])
            clocks = [row for row in state["clocks"] if row["source"] == permit["clock_source"]]
            current = max(clocks, key=lambda row: int(row["revision"])) if clocks else None
            if current is None or current["status"] != "AVAILABLE":
                raise Refusal("CLOCK_INVALID")
            if not authorization["authorization_fence"]["checked_at"] <= current["observed_time"] < authorization["expires_at"]:
                raise Refusal("PREREQUISITE_MISSING")
            current_input = copy.deepcopy(fresh)
            current_input["clock"] = {"source": current["source"], "status": "AVAILABLE", "instant": current["observed_time"]}
            for basis in current_input.get("holdings_bases", []):
                basis["selection"]["at"] = current["observed_time"]
            checked = holdings.fence_rows(current_input, authorization["authority_result"])
            if checked != authorization["authorization_fence"].get("holdings", []):
                raise Refusal("BINDING_MISMATCH")
            if failure_stage == "PRE_INTENT":
                return {"status": "HOST_COMMIT", "disposition": "COMMIT_FAILED", "dispatch_performed": False}
            invoke = connector_callable["invoke"]

            def synchronous(payload):
                if failure_stage == "POST_INTENT":
                    raise RuntimeError("injected stop after intent retention")
                self._commit_in_progress = True
                try:
                    result = invoke(payload)
                finally:
                    self._commit_in_progress = False
                if failure_stage == "POST_ACCEPTANCE":
                    raise RuntimeError("injected lost acceptance result")
                return result

            connector = {**connector_callable, "invoke": synchronous}
            self._holdings_failure = failure_stage
            try:
                return super().dispatch(organization, instance_id, authorization_digest, connector, event_id)
            finally:
                self._holdings_failure = None

    def _dispatch_observation(self, organization, claim, observation, event_id):
        if self._holdings_failure == "OUTCOME_WRITE":
            return {"status": "HOST_DISPATCH", "disposition": "PENDING", "dispatch_performed": True}
        return super()._dispatch_observation(organization, claim, observation, event_id)

    def export_checkpoint(self):
        """Protected in-process checkpoint, not a portable or durable protocol."""
        with self._lock:
            return copy.deepcopy({"authoritative": self._authoritative, "holdings": self._holdings,
                "dispatch_claims": self._dispatch_claims, "pending_evidence": self._pending_evidence})

    @classmethod
    def from_checkpoint(cls, consumer, checkpoint):
        if not isinstance(checkpoint, dict) or set(checkpoint) != {"authoritative", "holdings", "dispatch_claims", "pending_evidence"}:
            raise Refusal("STATE_INVALID")
        host = cls(consumer)
        try:
            if set(checkpoint["authoritative"]) != {"roots", "budgets"}:
                raise Refusal("STATE_INVALID")
            for (_, registry_digest), row in checkpoint["authoritative"]["budgets"].items():
                admitted = host._admit_budget_roots([{"registry_digest": registry_digest, "affected_anchors": row["affected_anchors"],
                    "state": row["state_value"], "state_digest": row["state_digest"]}], PIN)
                if admitted[registry_digest] != row:
                    raise Refusal("STATE_INVALID")
            for (_, config_digest), row in checkpoint["holdings"].items():
                holdings.validate_configuration(row["configuration"])
                holdings.validate_state(row["configuration"], row["state"], row["state_digest"])
                if config_digest != holdings.configuration_digest(row["configuration"]):
                    raise Refusal("STATE_INVALID")
            for (_, instance_id), root in checkpoint["authoritative"]["roots"].items():
                definition = parse_json(root["deploy_request"])["definition"]
                state = root["state_value"]
                if (state["instance_id"] != instance_id or root["state"] != canonical(state)
                        or root["state_digest"] != lifecycle.state_digest(state)
                        or state["work_class_digest"] != digest("work-class-definition", definition)
                        or not lifecycle._validate_state_integrity(state, definition)):
                    raise Refusal("STATE_INVALID")
            for key, claim in checkpoint["dispatch_claims"].items():
                if key != (claim["organization"], claim["instance_id"], claim["dispatch_intent_id"]) or claim["status"] not in {"PENDING", "CONSUMED", "NOT_SENT"}:
                    raise Refusal("STATE_INVALID")
                root = checkpoint["authoritative"]["roots"][(claim["organization"], claim["instance_id"])]
                authorization = next(row for row in root["state_value"].get("authorizations", []) if row["authorization_digest"] == claim["authorization_digest"])
                permit = next(row for row in root["state_value"]["permits"] if row["permit_id"] == authorization["permit_digest"])
                if claim["authorization"] != authorization or claim["permit"] != permit or claim["dispatch_intent_id"] != authorization["dispatch_intent_id"]:
                    raise Refusal("STATE_INVALID")
        except (KeyError, TypeError, ValueError, StopIteration, Refusal):
            raise Refusal("STATE_INVALID") from None
        host._authoritative = copy.deepcopy(checkpoint["authoritative"])
        host._holdings = copy.deepcopy(checkpoint["holdings"])
        host._dispatch_claims = copy.deepcopy(checkpoint["dispatch_claims"])
        host._pending_evidence = copy.deepcopy(checkpoint["pending_evidence"])
        return host

    @staticmethod
    def public_failure():
        return {"status": "REFUSED", "code": "OPERATION_NOT_ALLOWED"}
