"""Protected process-local flow mediation joined to existing business dispatch."""
from __future__ import annotations

import copy

from . import flow
from .common import Refusal, canonical, parse_json, schema_valid
from .holdings_host import HoldingsReferenceHost


MAX_FRAME_BYTES = 17825792
MAX_CONTAINERS = 128
PUBLIC_STATUS = b"Unable to process this request."


def bounded_frame(raw):
    if not isinstance(raw, bytes):
        raise Refusal("SCHEMA_INVALID")
    if len(raw) > MAX_FRAME_BYTES:
        raise Refusal("LIMIT_EXCEEDED")
    if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
        raise Refusal("SCHEMA_INVALID")
    depth, quoted, escaped = 0, False, False
    for byte in raw[:-1]:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > MAX_CONTAINERS:
                raise Refusal("LIMIT_EXCEEDED")
        elif byte in (93, 125):
            depth -= 1
            if depth < 0:
                raise Refusal("SCHEMA_INVALID")
    try:
        return parse_json(raw[:-1])
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal("SCHEMA_INVALID") from None


class FlowReferenceHost(HoldingsReferenceHost):
    """Trusted callbacks supply actual reader identity and private delivery routes.

    The caller installs all participating writers behind this coordinator. This
    process-local host does not establish durable storage or external isolation.
    authenticate_authority must authenticate every selected record and current
    source selection independently of caller assertions. Actual authentication,
    source freshness and identity mapping remain deployment premises. Tests use
    exact synthetic proof inventories. A response provider owns protected state
    internally and is sampled before and after operations that return it.
    """

    def __init__(self, consumer, current_reader, authenticate_event, authenticate_authority):
        super().__init__(consumer)
        if not all(callable(callback) for callback in (current_reader, authenticate_event, authenticate_authority)):
            raise Refusal("INPUT_INVALID")
        self._current_reader = current_reader
        self._authenticate_event = authenticate_event
        self._authenticate_authority = authenticate_authority
        self._flows = {}
        self._flow_routes = {}
        self._input_routes = {}
        self._exposure_in_progress = False
        self._active_response_requests = None
        self._internal_outcome_in_progress = False

    def _writer(self):
        if self._exposure_in_progress or self._commit_in_progress:
            raise Refusal("ACCESS_NOT_ESTABLISHED")

    def install_flow(self, organization, configuration):
        with self._lock:
            self._writer()
            flow.validate_configuration(configuration)
            key = (organization, configuration["principal"])
            if key in self._flows:
                raise Refusal("DEFINITION_CONFLICT")
            self._flows[key] = {"configuration": copy.deepcopy(configuration), "state": None, "state_digest": None}

    def install_flow_routes(self, organization, principal, routes):
        with self._lock:
            self._writer()
            if (organization, principal) not in self._flows or (organization, principal) in self._flow_routes:
                raise Refusal("DEFINITION_CONFLICT")
            selected = {}
            for row in routes:
                if (not isinstance(row, dict) or set(row) != {"interface", "operation", "recipient_field", "recipient", "channel", "purpose", "connector", "onward_delivery"}
                        or row["onward_delivery"] is not False or not schema_valid(row["connector"], "lifecycle.schema.json", "connector")
                        or (row["interface"], row["operation"]) in selected):
                    raise Refusal("INPUT_INVALID")
                selected[(row["interface"], row["operation"])] = copy.deepcopy(row)
            self._flow_routes[(organization, principal)] = selected

    def install_input_route(self, organization, principal, context_id, actor, deliver):
        with self._lock:
            self._writer()
            key = (organization, principal, context_id)
            if key in self._input_routes or not callable(deliver):
                raise Refusal("DEFINITION_CONFLICT")
            self._input_routes[key] = {"actor": actor, "deliver": deliver}

    def _authenticated_authority(self, organization, configuration, authority):
        if not self._authenticate_authority(copy.deepcopy(configuration), copy.deepcopy(authority)):
            raise Refusal("ACCESS_NOT_ESTABLISHED")
        self._owned_bases(organization, authority)

    def _reader(self, organization, request):
        actual = self._current_reader()
        authority = request["response_authority"]
        executor = authority["proposal"]["executor"]
        if (not isinstance(actual, dict) or set(actual) != {"actor", "role", "principal", "clock"}
                or any(executor[name] != actual[name] for name in ("actor", "role", "principal"))
                or authority["clock"] != actual["clock"]):
            raise Refusal("ACCESS_NOT_ESTABLISHED")
        self._authenticated_authority(organization, request["configuration"], authority)
        flow._access(request["configuration"], authority, flow.response_subject(request),
            request["configuration"]["response_operation"], response=True)

    @staticmethod
    def _unchanged(request, code):
        return {"status": "REFUSED", "code": code, "path": "", "state": copy.deepcopy(request["state"]), "state_digest": request["state_digest"]}

    def _commit_flow(self, organization, request, *, deliver=False, failure_stage=None):
        try:
            flow.admit_input(request)
        except Refusal as error:
            return {"status": "REFUSED", "code": error.code, "path": ""}
        try:
            self._reader(organization, request)
        except Refusal as error:
            return {"status": "REFUSED", "code": error.code, "path": ""}
        configuration = request["configuration"]
        key = (organization, configuration["principal"])
        current = self._flows.get(key)
        if current is None or current["configuration"] != configuration:
            return self._unchanged(request, "DEPENDENCY_MISMATCH")
        if request["state"] != current["state"] or request["state_digest"] != current["state_digest"]:
            return self._unchanged(request, "REVISION_CONFLICT")
        historical = next((row for row in current["state"]["records"] if row["event"]["id"] == request["event"]["id"]), None) if current["state"] else None
        if historical is None and not self._authenticate_event(copy.deepcopy(configuration), copy.deepcopy(request["event"]), copy.deepcopy(request["host_evidence"])):
            return self._unchanged(request, "EVIDENCE_UNAVAILABLE")
        if historical is None:
            payload = request["event"]["payload"]
            ordinary = [payload[name] for name in ("access_authority", "transfer_authority") if name in payload]
            if request["event"]["kind"] == "EXPOSE":
                outgoing = copy.deepcopy(payload["authority_projection"])
                outgoing["flow_bases"][0]["state"] = copy.deepcopy(request["state"])
                ordinary.append(outgoing)
            try:
                for authority in ordinary:
                    self._authenticated_authority(organization, configuration, authority)
            except Refusal as error:
                return self._unchanged(request, error.code)
        route = None
        delivery_error = None
        if deliver:
            kind, payload = request["event"]["kind"], request["event"]["payload"]
            if kind not in {"READ", "IMPORT"}:
                return self._unchanged(request, "UNSUPPORTED_RELATION")
            context_id = payload.get("receiver_context_id", payload.get("context_id"))
            route = self._input_routes.get((organization, configuration["principal"], context_id))
            context = next((row for row in current["state"]["core"]["contexts"] if row["id"] == context_id), None) if current["state"] else None
            if route is None or context is None or route["actor"] != context["actor"]:
                return self._unchanged(request, "ACCESS_NOT_ESTABLISHED")
        result = self._consumer.flow_step(copy.deepcopy(request))
        if result["status"] != "TRANSITION" or result["replay"]:
            return result
        if failure_stage == "PRE_CLAIM":
            return self._unchanged(request, "ACCESS_NOT_ESTABLISHED")
        self._flows[key] = {"configuration": copy.deepcopy(configuration), "state": copy.deepcopy(result["state"]), "state_digest": result["state_digest"]}
        if route is not None and failure_stage != "POST_CLAIM":
            self._exposure_in_progress = True
            try:
                route["deliver"](copy.deepcopy(request["event"]["payload"]))
            except BaseException as error:
                delivery_error = error
            finally:
                self._exposure_in_progress = False
        try:
            self._reader(organization, request)
        except Refusal:
            return {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""}
        if delivery_error is not None:
            raise delivery_error
        return result

    def submit_flow(self, organization, request, *, deliver=False, failure_stage=None):
        if failure_stage not in {None, "PRE_CLAIM", "POST_CLAIM"}:
            raise Refusal("INPUT_INVALID")
        with self._lock:
            self._writer()
            return self._commit_flow(organization, request, deliver=deliver, failure_stage=failure_stage)

    def handle_flow_frame(self, organization, raw):
        try:
            request = bounded_frame(raw)
        except Refusal as error:
            return {"status": "REFUSED", "code": error.code, "path": ""}
        return self.submit_flow(organization, request)

    def _owned_bases(self, organization, authority_input):
        super()._owned_bases(organization, authority_input)
        for basis in authority_input.get("flow_bases", []):
            key = (organization, basis["configuration"]["principal"])
            current = self._flows.get(key)
            if current is None:
                raise Refusal("EVIDENCE_UNAVAILABLE")
            if basis["configuration"] != current["configuration"] or basis["state"] != current["state"] or basis["state_digest"] != current["state_digest"]:
                raise Refusal("REVISION_CONFLICT")

    def _admit_readers(self, response_requests, organization=None):
        requests = list(response_requests() if callable(response_requests) else response_requests)
        for owner, request in requests:
            try:
                flow.admit_input(request)
            except Refusal:
                raise Refusal("ACCESS_NOT_ESTABLISHED") from None
        try:
            self._admit_retained_flows(organization)
        except (KeyError, TypeError, ValueError, Refusal):
            raise Refusal("ACCESS_NOT_ESTABLISHED") from None
        admitted = set()
        for owner, request in requests:
            self._reader(owner, request)
            key = (owner, request["configuration"]["principal"])
            if key not in self._flows or self._flows[key] != {name: request[name] for name in ("configuration", "state", "state_digest")}:
                raise Refusal("ACCESS_NOT_ESTABLISHED")
            admitted.add(key)
        required = {key for key in self._flows if organization is None or key[0] == organization}
        if not required <= admitted:
            raise Refusal("ACCESS_NOT_ESTABLISHED")

    def _protected_result(self, organization, response_requests, action):
        self._admit_readers(response_requests, organization)
        result, action_error = None, None
        try:
            result = action()
        except BaseException as error:
            action_error = error
        try:
            self._admit_readers(response_requests, organization)
        except Refusal:
            return {"status": "REFUSED", "code": "ACCESS_NOT_ESTABLISHED", "path": ""}
        if action_error is not None:
            raise action_error
        return result

    def snapshot(self, organization, instance_id, *, response_requests=()):
        with self._lock:
            self._admit_readers(response_requests, organization)
            return super().snapshot(organization, instance_id)

    def pending_evidence(self, organization, instance_id, *, response_requests=()):
        with self._lock:
            self._admit_readers(response_requests, organization)
            return super().pending_evidence(organization, instance_id)

    def dispatch_claims(self, organization, instance_id, *, response_requests=()):
        with self._lock:
            self._admit_readers(response_requests, organization)
            return super().dispatch_claims(organization, instance_id)

    def holdings_snapshot(self, organization, configuration_digest, *, response_requests=()):
        with self._lock:
            self._admit_readers(response_requests, organization)
            return super().holdings_snapshot(organization, configuration_digest)

    def submit(self, organization, request, failure_reference=None, *, response_requests=()):
        with self._lock:
            self._writer()
            if self._internal_outcome_in_progress:
                return super().submit(organization, request, failure_reference)
            if response_requests == () and self._active_response_requests is not None:
                response_requests = self._active_response_requests
            return self._protected_result(organization, response_requests,
                lambda: super(FlowReferenceHost, self).submit(organization, request, failure_reference))

    def submit_registry(self, organization, request, failure_reference=None, *, response_requests=()):
        with self._lock:
            self._writer()
            return self._protected_result(organization, response_requests,
                lambda: super(FlowReferenceHost, self).submit_registry(organization, request, failure_reference))

    def submit_holdings(self, organization, request, fail_before_write=False, *, response_requests=()):
        with self._lock:
            self._writer()
            return self._protected_result(organization, response_requests,
                lambda: super(FlowReferenceHost, self).submit_holdings(organization, request, fail_before_write))

    def install_holdings(self, organization, configuration, state, state_digest):
        with self._lock:
            self._writer()
            return super().install_holdings(organization, configuration, state, state_digest)

    def install(self, deploy_request, budget_roots=(), *, response_requests=()):
        with self._lock:
            self._writer()
            organization = self._key(deploy_request)[0]
            return self._protected_result(organization, response_requests,
                lambda: super(FlowReferenceHost, self).install(deploy_request, budget_roots))

    def dispatch(self, organization, instance_id, authorization_digest, connector_callable, event_id, failure_stage=None, *, flow_request=None, flow_failure_stage=None, response_requests=()):
        if flow_failure_stage not in {None, "PRE_CLAIM", "POST_CLAIM"}:
            raise Refusal("INPUT_INVALID")
        with self._lock:
            self._writer()
            flow.admit_input(flow_request)
            self._admit_readers(response_requests, organization)
            if (not schema_valid(flow_request, "information-flow.schema.json", "input")
                    or not isinstance(connector_callable, dict)
                    or set(connector_callable) != {"id", "version", "binding_digest", "invoke"}
                    or not callable(connector_callable["invoke"])):
                raise Refusal("INPUT_INVALID")
            root = self._roots[(organization, instance_id)]
            authorization = next((row for row in root["state_value"].get("authorizations", []) if row["authorization_digest"] == authorization_digest), None)
            if authorization is None:
                raise Refusal("PREREQUISITE_MISSING")
            fresh = authorization["authority_input"]
            key = (organization, fresh["envelope"]["principal"])
            native = authorization["native_request"]
            route = self._flow_routes.get(key, {}).get((native["interface"], native["operation"]))
            selected = flow.requirements(fresh)
            if route is None or len(selected) != 1 or flow_request is None:
                raise Refusal("ACCESS_NOT_ESTABLISHED")
            requirement = selected[0]
            recipient = next(row["value"]["value"] for row in native["fields"] if row["name"] == requirement["recipient_field"])
            if (requirement["recipient_field"] != route["recipient_field"] or recipient != route["recipient"]
                    or requirement["channel"] != route["channel"] or requirement["purpose"] != route["purpose"]
                    or authorization["connector"] != route["connector"] or flow_request["event"]["kind"] != "EXPOSE"):
                raise Refusal("BINDING_MISMATCH")
            expanded = copy.deepcopy(flow_request["event"]["payload"]["authority_projection"])
            expanded["flow_bases"][0]["state"] = copy.deepcopy(flow_request["state"])
            if expanded != fresh:
                raise Refusal("BINDING_MISMATCH")
            claim_key = (organization, instance_id, authorization.get("dispatch_intent_id"))
            if claim_key not in self._dispatch_claims:
                self._reader(organization, flow_request)
                self._authenticated_authority(organization, flow_request["configuration"], expanded)
                preview = self._consumer.flow_step(copy.deepcopy(flow_request))
                if preview["status"] != "TRANSITION" or preview["replay"]:
                    raise Refusal(preview.get("code", "ACCESS_NOT_ESTABLISHED"))
            original = connector_callable["invoke"]
            def expose_and_invoke(payload):
                result = self._commit_flow(organization, flow_request, failure_stage=flow_failure_stage)
                if result["status"] != "TRANSITION" or result["replay"]:
                    raise Refusal(result.get("code", "ACCESS_NOT_ESTABLISHED"))
                if flow_failure_stage == "POST_CLAIM":
                    raise RuntimeError("injected stop after possible-exposure claim")
                self._exposure_in_progress = True
                try:
                    return original(payload)
                finally:
                    self._exposure_in_progress = False
            return self._with_response_provider(organization, response_requests,
                lambda: super(FlowReferenceHost, self).dispatch(organization, instance_id, authorization_digest,
                    {**connector_callable, "invoke": expose_and_invoke}, event_id,
                    "PRE_INTENT" if flow_failure_stage == "PRE_CLAIM" else failure_stage))

    def _with_response_provider(self, organization, response_requests, action):
        previous = self._active_response_requests
        self._active_response_requests = response_requests
        try:
            return self._protected_result(organization, response_requests, action)
        finally:
            self._active_response_requests = previous

    def _dispatch_observation(self, organization, claim, observation, event_id):
        # Native evidence remains accountable if the response reader is revoked.
        previous = self._internal_outcome_in_progress
        self._internal_outcome_in_progress = True
        try:
            return super()._dispatch_observation(organization, claim, observation, event_id)
        finally:
            self._internal_outcome_in_progress = previous

    def recover_dispatch(self, organization, instance_id, dispatch_intent_id, event_id, *, response_requests=()):
        with self._lock:
            self._writer()
            return self._with_response_provider(organization, response_requests,
                lambda: super(FlowReferenceHost, self).recover_dispatch(organization, instance_id, dispatch_intent_id, event_id))

    def export_checkpoint(self, response_requests=()):
        with self._lock:
            self._writer()
            self._admit_readers(response_requests)
            return {"business": super().export_checkpoint(), "flows": copy.deepcopy(self._flows), "routes": copy.deepcopy(self._flow_routes)}

    def _admit_retained_flows(self, selected_organization=None):
        admitted = set()
        for (organization, _), root in self._roots.items():
            if selected_organization is not None and organization != selected_organization:
                continue
            state = root["state_value"]
            if organization != state["deployment_organization_id"]:
                raise Refusal("STATE_INVALID")
            inputs = [row["authority_basis"] for row in state["permits"] if "authority_basis" in row]
            inputs.extend(row["authority_input"] for name in ("authorizations", "authorization_evaluations")
                for row in state.get(name, []))
            inputs.extend(row["event"]["authority_input"] for row in state.get("proposal_authority_evaluations", []))
            inputs.extend(detail["authority_basis"] for receipt in state["receipts"] for detail in receipt["details"]
                if detail["kind"] == "SEPARATION" and "authority_basis" in detail)
            inputs.extend(row["permit"]["authority_basis"] for row in state["replays"]
                if row["permit"] is not None and "authority_basis" in row["permit"])
            inputs.extend(detail["authority_basis"] for row in state["replays"] for detail in row["decision"]["details"]
                if detail["kind"] == "SEPARATION" and "authority_basis" in detail)
            for row in root["event_log"].values():
                event = parse_json(row["event"])
                if event["kind"] in {"PROPOSE", "AUTHORIZE_DISPATCH"}:
                    inputs.append(event["authority_input"])
            for authority in inputs:
                for declaration in authority["envelope"].get("flow_requirements", []):
                    current = self._flows.get((organization, authority["envelope"]["principal"]))
                    if (current is None or current["state"] is None
                            or flow.configuration_digest(current["configuration"]) != declaration["configuration_digest"]):
                        raise Refusal("STATE_INVALID")
                for basis in authority.get("flow_bases", []):
                    configuration, historical = basis["configuration"], basis["state"]
                    key = (organization, configuration["principal"])
                    current = self._flows.get(key)
                    if (configuration["principal"] != authority["envelope"]["principal"]
                            or current is None or current["configuration"] != configuration
                            or historical is None or current["state"] is None):
                        raise Refusal("STATE_INVALID")
                    retained = canonical({name: basis[name] for name in ("configuration", "state", "state_digest")})
                    if (organization, retained) in admitted:
                        continue
                    flow.validate_state(configuration, historical, basis["state_digest"])
                    records = historical["records"]
                    if current["state"]["records"][:len(records)] != records:
                        raise Refusal("STATE_INVALID")
                    admitted.add((organization, retained))

    @classmethod
    def from_checkpoint(cls, consumer, current_reader, authenticate_event, authenticate_authority, checkpoint):
        if not isinstance(checkpoint, dict) or set(checkpoint) != {"business", "flows", "routes"}:
            raise Refusal("STATE_INVALID")
        if not isinstance(checkpoint["flows"], dict) or not isinstance(checkpoint["routes"], dict):
            raise Refusal("STATE_INVALID")
        business = HoldingsReferenceHost.from_checkpoint(consumer, checkpoint["business"])
        host = cls(consumer, current_reader, authenticate_event, authenticate_authority)
        for key, row in checkpoint["flows"].items():
            if (not isinstance(key, tuple) or len(key) != 2 or not all(isinstance(member, str) for member in key)
                    or not isinstance(row, dict) or set(row) != {"configuration", "state", "state_digest"}
                    or not schema_valid(row["configuration"], "information-flow.schema.json", "configuration")):
                raise Refusal("STATE_INVALID")
            if key[1] != row["configuration"]["principal"]:
                raise Refusal("STATE_INVALID")
            flow.validate_configuration(row["configuration"])
            flow.validate_state(row["configuration"], row["state"], row["state_digest"])
            host.install_flow(key[0], row["configuration"])
            if key in checkpoint["routes"]:
                if not isinstance(checkpoint["routes"][key], dict):
                    raise Refusal("STATE_INVALID")
                host.install_flow_routes(key[0], key[1], list(checkpoint["routes"][key].values()))
        if set(checkpoint["routes"]) - set(checkpoint["flows"]):
            raise Refusal("STATE_INVALID")
        host._authoritative = copy.deepcopy(business._authoritative)
        host._holdings = copy.deepcopy(business._holdings)
        host._dispatch_claims = copy.deepcopy(business._dispatch_claims)
        host._pending_evidence = copy.deepcopy(business._pending_evidence)
        host._flows = copy.deepcopy(checkpoint["flows"])
        try:
            host._admit_retained_flows()
        except (KeyError, TypeError, ValueError, Refusal):
            raise Refusal("STATE_INVALID") from None
        return host

    @staticmethod
    def public_status():
        return PUBLIC_STATUS
