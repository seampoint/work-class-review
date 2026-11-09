#!/usr/bin/env python3
"""Freeze source-derived host assertions, then exercise both independent hosts.

--prepare imports only review fixture constructors. --run verifies those frozen
bytes before importing a consumer or launching the TypeScript host bridge.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
CANDIDATE = HERE.parent
DEFAULT_RUN = ROOT / "runs/2026-10-07-recovery-implementation"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output: Path) -> None:
    from authority_fixture import authority_specimen
    from corpus_common import candidate_pin, canonical_bytes, digest
    from fixture_factory import deployment, work_class
    from equipment_dispatch_fixture import authorization_event, authorization_result
    from equipment_observation_fixture import authority_mutator
    from lifecycle_budget_fixture import permitted_budget_proposal, reserve_for_proposal
    from lifecycle_factory import base_lifecycle, step_input
    from recovery_fixture import (
        configuration, disposition_expected, dispose_request, disputed, evidence_for, facts_for,
        policy_issue, registered,
    )
    from recovery_lifecycle_fixture import (
        PBR, dispute_prerequisite, supplier_chain, work_dispose_expected, work_dispose_request,
    )
    from reservation_fixture import fixture as reservation_fixture, host_and_event, native, request

    facts = facts_for("2")
    initial = disputed(facts)
    issue, issued = policy_issue(facts, initial)
    pd = issue["event"]["payload"]["policy_digest"]
    accept = dispose_request(facts, issued["state"], "ACCEPT_UNRESOLVED", policy_digest=pd)
    accepted = disposition_expected(accept)
    accepted_disposition = accepted["state"]["core"]["recovery"]["dispositions"][0]
    organization = facts["configuration"]["principal"]
    owner, _ = deployment(work_class(), instance_id="instance-1", organization_id=organization,
        authorization_time=facts["clock"]["instant"], evidence_expires_at="2026-09-11T00:00:00Z")

    expanded = dispose_request(facts, accepted["state"], "ACCEPT_UNRESOLVED", event_id="host-new-third-attempt",
        evidence=evidence_for(facts, accepted["state"], attempts=3), policy_digest=pd, supersedes=accepted_disposition["id"])

    def bind_packet(supplied):
        packet = supplied["event"]["payload"]["evidence"]
        supplied["host_evidence"]["recovery"]["authenticated_records"] = [{"kind": "RECOVERY_EVIDENCE",
            "record_digest": digest("recovery-evidence", packet), "provider": packet["provider"], "source": packet["source"]}]

    wrong_request = copy.deepcopy(expanded)
    wrong_request["event"]["id"] = "host-attributable-changed-request"
    packet = wrong_request["event"]["payload"]["evidence"]
    next(row for row in packet["request"]["fields"] if row["name"] == "amount")["value"]["value"] = "3"
    for attempt in packet["attempts"]:
        attempt["request_digest"] = digest("reservation-native-request", packet["request"])
    bind_packet(wrong_request)
    controls = []
    for name in ("unknown-target", "unselected-provider", "unauthenticated-packet", "malformed-packet"):
        supplied = copy.deepcopy(expanded)
        supplied["event"]["id"] = "host-nonattributable-" + name
        packet = supplied["event"]["payload"]["evidence"]
        if name == "unknown-target":
            supplied["event"]["payload"]["target"]["reservation"] = "unknown-reservation"
            packet["target"]["reservation"] = "unknown-reservation"
        elif name == "unselected-provider":
            packet["provider"] = "unselected-provider"
        elif name == "malformed-packet":
            packet.pop("request")
        bind_packet(supplied)
        if name == "unauthenticated-packet":
            supplied["host_evidence"]["recovery"]["authenticated_records"] = []
        controls.append({"name": name, "input": supplied})

    def reserve_candidate(beneficiary: str, event_id: str) -> dict:
        def alter(supplied, _original):
            def replace(value):
                if isinstance(value, list):
                    return [replace(item) for item in value]
                if isinstance(value, dict):
                    return {key: replace(item) for key, item in value.items()}
                return beneficiary if value == "employee-7" else value
            rewritten = replace(supplied)
            supplied.clear()
            supplied.update(rewritten)
        authority, _ = authority_specimen(instance_id="instance-2", occurrence_id="issue:2", mutator=alter)
        authority["clock"] = copy.deepcopy(facts["clock"])
        event, host = host_and_event(facts, "RESERVE", event_id, accepted["state"]["core"]["revision"], {
            "authority": authority, "histories": [facts["history"]],
        }, administration=False)
        return request(accepted["state"], event, host)

    version2, issued2 = policy_issue(facts, accepted["state"], version="2", supersedes=pd)
    accept2 = dispose_request(facts, issued2["state"], "ACCEPT_UNRESOLVED", event_id="host-accept-version-2",
        policy_digest=version2["event"]["payload"]["policy_digest"], supersedes=accepted_disposition["id"])
    accepted2 = disposition_expected(accept2)
    second = next(row for row in accepted2["state"]["core"]["recovery"]["dispositions"] if row["policy_digest"] == version2["event"]["payload"]["policy_digest"])
    version3, issued3 = policy_issue(facts, accepted2["state"], version="3", supersedes=version2["event"]["payload"]["policy_digest"])
    accept3 = dispose_request(facts, issued3["state"], "ACCEPT_UNRESOLVED", event_id="host-accept-version-3",
        policy_digest=version3["event"]["payload"]["policy_digest"], supersedes=second["id"])
    denied3 = disposition_expected(accept3, reasons=["RECOVERY_ALLOWANCE_EXCEEDED"], effective_result="LEAVE_UNRESOLVED")

    chain = supplier_chain()
    conflict, conflicted = dispute_prerequisite(chain)
    local = work_dispose_request(chain, conflicted["state"])
    local_expected = work_dispose_expected(local)
    proposal = copy.deepcopy(supplier_chain(permitted_payment=True)["requests"][-1][1])
    proposal["event"]["event_id"] = "host-proposal-awaiting-evidence-classification"
    tampered = copy.deepcopy(local_expected["state"])
    tampered["recovery_records"][0]["after_projection"]["active"][0]["status"] = "BLOCKED_DISPUTE"
    clock_event = {"schema": PBR["SCHEMA"] + "runtime-event", "event_id": "host-rehashed-recovery-checkpoint",
        "kind": "CLOCK", "instance_id": tampered["instance_id"], "expected_state_revision": tampered["revision"],
        "expected_state_digest": PBR["work_state_digest"](tampered),
        "clock": {"source": "governance-clock", "revision": "2", "status": "AVAILABLE", "observed_time": PBR["NOW"],
            "evidence_digest": digest("host-clock-evidence", {"case": "rehashed-recovery-checkpoint"})}, "activation_clocks": []}
    tampered_input = PBR["lifecycle_input"](chain["definition"], chain["definition_digest"], tampered, clock_event)

    def budget_root(state):
        return {"registry_digest": digest("reservation-registry", state["core"]["configuration"]),
            "affected_anchors": [row["anchor"] for row in state["core"]["configuration"]["slots"]],
            "state": copy.deepcopy(state), "state_digest": digest("reservation-state", state)}

    dispatch_base = base_lifecycle(shared_budget=True, instance_id="host-recovery-current-dispatch",
        authority_mutator=authority_mutator, definition_mutator=lambda definition: definition.update(recovery=configuration()))
    dispatch_facts = reservation_fixture()
    dispatch_facts["configuration"]["recovery"] = configuration()
    dispatch_facts["authority_a"] = copy.deepcopy(dispatch_base["authority_input"])
    dispatch_facts["authority_a_result"] = copy.deepcopy(dispatch_base["authority_result"])
    dispatch_facts["amount"] = "150"
    completion = next(row for row in dispatch_base["definition"]["steps"] if row["kind"] == "OPERATION")["completion"]
    dispatch_facts["budget"]["reservation_policy"]["settlement"] = {"provider": completion["effect_provider"], "source": completion["effect_source"]}
    dispatch_facts["budget"]["reservation_policy"]["no_effect"] = {"provider": completion["no_effect_provider"], "source": completion["no_effect_source"]}
    dispatch_budget_digest = digest("budget-definition", dispatch_facts["budget"])
    authorization = dispatch_facts["authorizations"][0]
    authorization.update(budget_digest=dispatch_budget_digest,
        work_class_digest=digest("authority-work-class", dispatch_base["authority_input"]["work_class"]),
        envelope_digest=digest("authority-envelope", dispatch_base["authority_input"]["envelope"]),
        authority_definition={"schema": "seampoint.work-class/1.0.0-draft.3/authority-definition",
            **{key: copy.deepcopy(dispatch_base["authority_input"][key]) for key in ("source", "work_class", "envelope")}})
    dispatch_facts["history"]["budget_digest"] = dispatch_budget_digest
    dispatch_initial = registered(dispatch_facts)
    dispatch_proposal = copy.deepcopy(dispatch_base["proposal_event"])
    dispatch_input, dispatch_output, _ = reserve_for_proposal(dispatch_base, dispatch_facts, dispatch_initial, dispatch_proposal)
    dispatch_proposal["budget_inputs"] = [dispatch_input]
    dispatch_permitted = permitted_budget_proposal(dispatch_base, dispatch_proposal, dispatch_output)
    dispatch_event = authorization_event(dispatch_base, dispatch_permitted, event_id="host-current-dispatch-authorize")
    dispatch_authorized = authorization_result(dispatch_base, dispatch_permitted, dispatch_event)
    dispatch_reserved = dispatch_output["result"]["state"]
    dispatch_authorize_input = step_input(dispatch_base, dispatch_permitted["state"], dispatch_event)
    dispatch_authorize_input["recovery_registries"] = [{"state": copy.deepcopy(dispatch_reserved),
        "state_digest": digest("reservation-state", dispatch_reserved),
        "host_evidence": {"registry_digest": dispatch_input["registry_digest"], "selection_evidence": "source-derived-current-registry",
            "administration_bases": [], "authenticated_records": []}}]
    later_facts = copy.deepcopy(dispatch_facts)
    later_facts["clock"]["instant"] = "2026-09-10T04:30:01Z"
    later_issue, _ = policy_issue(later_facts, dispatch_reserved)
    pending_packet = dispose_request(dispatch_facts, dispatch_reserved, "LEAVE_UNRESOLVED",
        event_id="host-pending-dispatch-changed-request", evidence=evidence_for(dispatch_facts, dispatch_reserved))
    dispatch_packet = pending_packet["event"]["payload"]["evidence"]
    next(row for row in dispatch_packet["request"]["fields"] if row["name"] == "amount")["value"]["value"] = "151"
    for attempt in dispatch_packet["attempts"]:
        attempt["request_digest"] = digest("reservation-native-request", dispatch_packet["request"])
    bind_packet(pending_packet)
    open_leave = dispose_request(dispatch_facts, dispatch_reserved, "LEAVE_UNRESOLVED",
        event_id="host-open-reservation-leave-unresolved")
    open_leave_expected = disposition_expected(open_leave)
    pending_native = native(dispatch_facts, "UNKNOWN", "host-pending-native-before-dispatch",
        reservation_id=dispatch_output["result"]["receipt"]["reservation"], completion_mismatch=True,
        mismatch_reason="UNEXPECTED_EFFECT")
    pending_native.update(provider=completion["effect_provider"], source=completion["effect_source"])
    pending_event, pending_host = host_and_event(dispatch_facts, "SETTLE", "host-pending-native-before-dispatch",
        dispatch_reserved["core"]["revision"], {"native": pending_native, "histories": [dispatch_facts["history"]]}, administration=False)
    pending_dispatch = request(dispatch_reserved, pending_event, pending_host)
    dispatch_fixture = {"organization": dispatch_base["deploy_input"]["deployment_authorization"]["organization_id"],
        "instance": dispatch_base["deploy_input"]["instance_id"], "deployment": dispatch_base["deploy_input"],
        "initial_root": budget_root(dispatch_initial), "requests": [
            step_input(dispatch_base, dispatch_base["deploy_result"]["state"], dispatch_base["clock_event"]),
            step_input(dispatch_base, dispatch_base["clock_result"]["state"], dispatch_proposal),
            dispatch_authorize_input],
        "permit": dispatch_permitted["permit"], "authorization": dispatch_authorized["state"]["authorizations"][0],
        "later_registry_issue": later_issue, "pending_packet": pending_packet, "pending_native": pending_dispatch,
        "open_leave": open_leave, "open_leave_core": open_leave_expected["state"]["core"],
        "observation": {"attempt": {"attempt_id": "host-spy-not-sent", "status": "NOT_SENT",
            "request_digest": digest("dispatch-native-request", {"instance_id": dispatch_base["deploy_input"]["instance_id"],
                "occurrence_id": dispatch_permitted["permit"]["occurrence"]["occurrence_id"], **dispatch_permitted["permit"]["native_request"]}),
            "attempted_at": dispatch_facts["clock"]["instant"]},
            "acknowledgement": {"status": "NONE", "reference": None, "observed_at": None}}}

    tampered_registry = copy.deepcopy(accepted["state"])
    tampered_registry["core"]["recovery"]["contingent"] = []
    fixture = {
        "candidate_pin": candidate_pin(), "expected_source": "REC-001 through REC-016 and supplier-payment revision 2",
        "implementation_or_output_consulted": False,
        "registry": {"organization": organization, "instance": "instance-1", "deployment": owner,
            "initial_root": budget_root(initial), "accepted_root": budget_root(accepted["state"]),
            "tampered_root": budget_root(tampered_registry), "issue": issue, "issue_core": issued["state"]["core"],
            "accept": accept, "accept_core": accepted["state"]["core"], "expanded": expanded,
            "custody_refusal": wrong_request, "nonattributable_controls": controls,
            "same_partition": reserve_candidate("employee-7", "host-pending-same-partition"),
            "unrelated_partition": reserve_candidate("employee-8", "host-pending-other-partition"),
            "cap_steps": [{"input": version2, "decision": "POLICY_RECORDED"},
                {"input": accept2, "decision": "DISPOSITION_RECORDED"}, {"input": version3, "decision": "POLICY_RECORDED"},
                {"input": accept3, "decision": "WITHHELD", "reasons": ["RECOVERY_ALLOWANCE_EXCEEDED"]}],
            "cap_core": denied3["state"]["core"]},
        "work": {"organization": chain["requests"][0][1]["deployment_authorization"]["organization_id"],
            "instance": chain["requests"][0][1]["instance_id"], "requests": [{"operation": op, "input": inp} for op, inp in chain["requests"]],
            "conflict": conflict, "dispose": local, "restored_projection": local_expected["state"]["recovery_records"][0]["after_projection"],
            "pending_proposal": proposal, "tampered_input": tampered_input},
        "dispatch": dispatch_fixture,
        "expected_limits": {"one_case_allowance": "4", "accepted_case_contingent_rows": "1", "cap_retained_budget_allowance": "8"},
        "limits": ["Process-local serialized host only", "Registry checkpoint reconstruction is not lifecycle or process restart",
            "Protected pending evidence persistence across process loss is not established", "No production provider or all-writer authenticity proof"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_bytes(fixture) + b"\n")
    dependencies = [Path(__file__), HERE / "recovery-host-probe.ts", HERE / "recovery_fixture.py", HERE / "recovery_lifecycle_fixture.py",
        HERE / "reservation_fixture.py", HERE / "authority_fixture.py", HERE / "fixture_factory.py", HERE / "lifecycle_factory.py",
        HERE / "build-prior-binding-restart-cases.py", HERE / "dependency_dispute_common.py", HERE / "corpus_common.py",
        HERE / "equipment_dispatch_fixture.py", HERE / "equipment_observation_fixture.py", HERE / "lifecycle_budget_fixture.py",
        CANDIDATE / "specimens/supplier-payment/build-specimen.py", output]
    manifest = {"candidate_pin": fixture["candidate_pin"], "status": "FROZEN_BEFORE_HOST_EXECUTION",
        "implementation_or_output_consulted_for_expectations": False,
        "files": [{"path": str(path.relative_to(ROOT)), "sha256": sha(path)} for path in dependencies]}
    freeze = output.with_suffix(".freeze.json")
    freeze.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"fixtures": str(output), "freeze": str(freeze), "fixture_sha256": sha(output), "execution_started": False}))


class TypeScriptBridge:
    def __init__(self, node: str):
        self.process = subprocess.Popen([node, str(HERE / "recovery-host-probe.ts")], cwd=CANDIDATE / "typescript",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

    def call(self, operation: str, host: str, **kwargs):
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps({"operation": operation, "host": host, **kwargs}, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            assert self.process.stderr
            raise AssertionError("TypeScript bridge exited: " + self.process.stderr.read())
        return json.loads(line)

    def close(self):
        if self.process.stdin:
            self.process.stdin.close()
        code = self.process.wait(timeout=30)
        if code:
            assert self.process.stderr
            raise AssertionError("TypeScript bridge failed: " + self.process.stderr.read())


class PythonBridge:
    def __init__(self):
        sys.path.insert(0, str(CANDIDATE / "python"))
        from consumer import Consumer
        from implementation.reference_host import SingleProcessReferenceHost
        self.consumer = Consumer()
        self.host_type = SingleProcessReferenceHost
        self.hosts = {}

    def call(self, operation: str, host: str, **kwargs):
        try:
            if operation == "NEW":
                self.hosts[host] = self.host_type(self.consumer)
                result = {"created": True}
            elif operation == "CHECK_STEP":
                result = self.consumer.step(copy.deepcopy(kwargs["request"]))
            else:
                selected = self.hosts[host]
                organization = kwargs.get("organization")
                if operation == "INSTALL": result = selected.install(copy.deepcopy(kwargs["request"]), copy.deepcopy(kwargs.get("budget_roots", [])))
                elif operation == "SNAPSHOT": result = selected.snapshot(organization, kwargs["instance"])
                elif operation == "PENDING": result = selected.pending_evidence(organization, kwargs["instance"])
                elif operation == "REGISTRY": result = selected.submit_registry(organization, copy.deepcopy(kwargs["request"]), kwargs.get("failure_reference"))
                elif operation == "SUBMIT": result = selected.submit(organization, copy.deepcopy(kwargs["request"]), kwargs.get("failure_reference"))
                elif operation == "DISPATCH":
                    invocations = 0
                    def invoke(_payload):
                        nonlocal invocations
                        invocations += 1
                        return copy.deepcopy(kwargs["observation"])
                    connector = {**copy.deepcopy(kwargs["authorization"]["connector"]), "invoke": invoke}
                    try:
                        response = selected.dispatch(organization, kwargs["instance"], kwargs["authorization"]["authorization_digest"], connector, kwargs["event_id"])
                        result = {"invocations": invocations, "response": response}
                    except Exception as error:
                        result = {"invocations": invocations, "error_code": getattr(error, "code", type(error).__name__)}
                elif operation == "CONTEND":
                    with concurrent.futures.ThreadPoolExecutor(max_workers=len(kwargs["requests"])) as pool:
                        result = list(pool.map(lambda request: selected.submit_registry(organization, copy.deepcopy(request)), kwargs["requests"]))
                else: raise ValueError("Unknown harness operation")
            return {"ok": True, "result": result}
        except Exception as error:
            return {"ok": False, "error_code": getattr(error, "code", type(error).__name__), "error_message": str(error)}

    def close(self):
        pass


def exercise(bridge, fixture: dict) -> list[str]:
    from corpus_common import canonical_bytes, digest
    passed = []
    reg, work = fixture["registry"], fixture["work"]

    def call(operation, host, **kwargs):
        response = bridge.call(operation, host, **kwargs)
        assert response["ok"], response
        return response["result"]

    def install(host, root):
        call("NEW", host, pin=fixture["candidate_pin"])
        value = call("INSTALL", host, request=reg["deployment"], budget_roots=[root])
        assert value["disposition"] == "INSTALLED", value

    def snapshot(host):
        return call("SNAPSHOT", host, organization=reg["organization"], instance=reg["instance"])

    def current_registry(host, template):
        value = copy.deepcopy(template)
        root = snapshot(host)["budget_states"][0]
        value["state"], value["state_digest"] = root["state"], root["state_digest"]
        value["event"]["expected_revision"] = root["state"]["core"]["revision"]
        return value

    def submit_registry(host, value, failure_reference=None):
        return call("REGISTRY", host, organization=reg["organization"], request=value, failure_reference=failure_reference)

    def pending(host):
        rows = call("PENDING", host, organization=reg["organization"], instance=reg["instance"])
        for row in rows:
            assert set(row) == {"evidence_digest", "event_id", "instance_id", "occurrence_id", "registry_digests", "status"}
            assert row["status"] == "PENDING"
        return rows

    install("registry-atomic", reg["initial_root"])
    before = snapshot("registry-atomic")
    failure = submit_registry("registry-atomic", current_registry("registry-atomic", reg["issue"]), "policy-before-swap")
    assert failure["transition"]["receipt"]["decision"] == "POLICY_RECORDED" and failure["committed"] is False
    assert snapshot("registry-atomic") == before
    success = submit_registry("registry-atomic", current_registry("registry-atomic", reg["issue"]))
    assert success["committed"] is True and success["transition"]["replay"] is False
    assert snapshot("registry-atomic")["budget_states"][0]["state"]["core"] == reg["issue_core"]
    before = snapshot("registry-atomic")
    accept = current_registry("registry-atomic", reg["accept"])
    failure = submit_registry("registry-atomic", accept, "disposition-before-swap")
    assert failure["transition"]["receipt"]["decision"] == "DISPOSITION_RECORDED" and failure["committed"] is False
    assert snapshot("registry-atomic") == before and len(pending("registry-atomic")) == 1
    success = submit_registry("registry-atomic", accept)
    assert success["committed"] is True and success["transition"]["replay"] is False
    assert snapshot("registry-atomic")["budget_states"][0]["state"]["core"] == reg["accept_core"]
    assert pending("registry-atomic") == []
    passed.append("registry policy/disposition write failures retain roots and no committed replay; retry consumes pending packet once")

    install("registry-contention", reg["initial_root"])
    submit_registry("registry-contention", current_registry("registry-contention", reg["issue"]))
    first = current_registry("registry-contention", reg["accept"])
    second = copy.deepcopy(first); second["event"]["id"] = "host-contending-wrapper"
    results = call("CONTEND", "registry-contention", organization=reg["organization"], requests=[first, second])
    assert sum(row["committed"] is True for row in results) == 1, results
    assert sorted(row["transition"].get("code", row["transition"].get("receipt", {}).get("decision")) for row in results) == ["DISPOSITION_RECORDED", "REVISION_CONFLICT"], results
    reused = submit_registry("registry-contention", current_registry("registry-contention", second))
    assert reused["transition"]["receipt"]["decision"] == "DISPOSITION_REUSED"
    core = snapshot("registry-contention")["budget_states"][0]["state"]["core"]
    assert len(core["recovery"]["contingent"]) == 1 and len(core["recovery"]["allowances"]) == 3
    assert [row["amount"] for row in core["recovery"]["allowances"] if row["actor_kind"] == "BUDGET"] == ["4"]
    passed.append("same-incident concurrent requests commit one admission; fresh wrapper reuse adds no exposure or allowance")

    install("registry-pending", reg["accepted_root"])
    before = snapshot("registry-pending")
    failed = submit_registry("registry-pending", current_registry("registry-pending", reg["expanded"]), "new-evidence-before-swap")
    assert failed["committed"] is False and failed["transition"]["receipt"]["decision"] == "WITHHELD"
    assert "RECOVERY_INCIDENT_LIMIT_EXCEEDED" in failed["transition"]["receipt"]["reasons"]
    assert snapshot("registry-pending") == before and len(pending("registry-pending")) == 1
    blocked = submit_registry("registry-pending", current_registry("registry-pending", reg["same_partition"]))
    assert blocked["committed"] is False and blocked["transition"]["code"] == "EVIDENCE_UNAVAILABLE", blocked
    unrelated = submit_registry("registry-pending", current_registry("registry-pending", reg["unrelated_partition"]))
    assert unrelated["committed"] is True and unrelated["transition"]["receipt"]["decision"] == "RESERVED", unrelated
    assert len(pending("registry-pending")) == 1
    final = submit_registry("registry-pending", current_registry("registry-pending", reg["expanded"]))
    assert final["committed"] is True and final["transition"]["receipt"]["decision"] == "WITHHELD"
    assert len(snapshot("registry-pending")["budget_states"][0]["state"]["core"]["recovery"]["contingent"]) == 2
    assert pending("registry-pending") == []
    passed.append("pending new evidence after rollback blocks exact budget partition while unrelated partition remains eligible")

    install("registry-admission-custody", reg["accepted_root"])
    before = snapshot("registry-admission-custody")
    refused = submit_registry("registry-admission-custody", current_registry("registry-admission-custody", reg["custody_refusal"]))
    assert refused["committed"] is False and refused["transition"]["code"] == "DEPENDENCY_MISMATCH", refused
    assert snapshot("registry-admission-custody") == before and len(pending("registry-admission-custody")) == 1
    blocked = submit_registry("registry-admission-custody", current_registry("registry-admission-custody", reg["same_partition"]))
    assert blocked["transition"]["code"] == "EVIDENCE_UNAVAILABLE" and blocked["committed"] is False
    unrelated = submit_registry("registry-admission-custody", current_registry("registry-admission-custody", reg["unrelated_partition"]))
    assert unrelated["committed"] is True and unrelated["transition"]["receipt"]["decision"] == "RESERVED"
    for control in reg["nonattributable_controls"]:
        selected = "registry-control-" + control["name"]
        install(selected, reg["accepted_root"])
        before = snapshot(selected)
        refused = submit_registry(selected, current_registry(selected, control["input"]))
        assert refused["committed"] is False and refused["transition"]["status"] == "REFUSED", refused
        assert snapshot(selected) == before and pending(selected) == [], control["name"]
        ordinary = submit_registry(selected, current_registry(selected, reg["same_partition"]))
        assert ordinary["committed"] is True and ordinary["transition"]["receipt"]["decision"] == "RESERVED", ordinary
    passed.append("authenticated known-target evidence survives admission refusal and blocks only its partition; unknown, unselected, unauthenticated and malformed controls create no barrier")

    install("registry-caps", reg["accepted_root"])
    for row in reg["cap_steps"]:
        result = submit_registry("registry-caps", current_registry("registry-caps", row["input"]))
        assert result["committed"] is True and result["transition"]["receipt"]["decision"] == row["decision"], result
        if "reasons" in row: assert result["transition"]["receipt"]["reasons"] == row["reasons"]
    core = snapshot("registry-caps")["budget_states"][0]["state"]["core"]
    assert core == reg["cap_core"]
    assert len(core["recovery"]["allowances"]) == 6 and len(core["recovery"]["contingent"]) == 1
    passed.append("policy versions preserve family allowance; failed third acceptance atomically retains all six prior attribution rows")

    install("checkpoint-valid", reg["accepted_root"])
    assert snapshot("checkpoint-valid")["budget_states"][0]["state"]["core"] == reg["accept_core"]
    call("NEW", "checkpoint-tampered", pin=fixture["candidate_pin"])
    invalid = bridge.call("INSTALL", "checkpoint-tampered", request=reg["deployment"], budget_roots=[reg["tampered_root"]])
    assert invalid["ok"] is False, invalid
    valid = call("INSTALL", "checkpoint-tampered", request=reg["deployment"], budget_roots=[reg["accepted_root"]])
    assert valid["disposition"] == "INSTALLED" and valid["replay"] is False
    passed.append("fresh registry checkpoint reconstruction accepts retained state and rejects rehashed omitted contingent exposure before installation")

    host = "work-atomic"
    call("NEW", host, pin=fixture["candidate_pin"])
    for row in work["requests"]:
        if row["operation"] == "deploy":
            assert call("INSTALL", host, request=row["input"])["disposition"] == "INSTALLED"
        else:
            value = call("SUBMIT", host, organization=work["organization"], request=row["input"])
            assert value["host_commit"]["disposition"] == "COMMITTED", value

    def work_snapshot(): return call("SNAPSHOT", host, organization=work["organization"], instance=work["instance"])

    def current_work(template, event_revision=True):
        value = copy.deepcopy(template); snap = work_snapshot()
        value["state"], value["state_digest"] = snap["state"], snap["state_digest"]
        if event_revision:
            value["event"]["expected_state_revision"], value["event"]["expected_state_digest"] = snap["state"]["revision"], snap["state_digest"]
            controller = value["event"].get("controller")
            if controller:
                subject = {key: copy.deepcopy(item) for key, item in value["event"].items() if key != "controller"}
                controller["act"]["subject_digest"] = digest("recovery-subject", subject)
                returned = controller["returned"]
                returned["act_digest"] = digest("recovery-act", controller["act"])
                returned["act_bytes_base64"] = base64.b64encode(canonical_bytes(controller["act"])).decode()
                host = value["recovery_host"]
                host["authenticated_records"] = [row for row in host["authenticated_records"] if row["kind"] != "RECOVERY_RETURN"]
                host["authenticated_records"].append({"kind": "RECOVERY_RETURN", "record_digest": digest("recovery-return", returned),
                    "provider": returned["provider"], "source": returned["source"]})
                host["authenticated_records"].sort(key=canonical_bytes)
        return value

    before = work_snapshot()
    conflict = current_work(work["conflict"])
    failed = call("SUBMIT", host, organization=work["organization"], request=conflict, failure_reference="native-conflict-before-swap")
    assert failed["host_commit"]["disposition"] == "COMMIT_FAILED" and work_snapshot() == before
    pending_rows = call("PENDING", host, organization=work["organization"], instance=work["instance"])
    assert len(pending_rows) == 1, pending_rows
    blocked = call("SUBMIT", host, organization=work["organization"], request=current_work(work["pending_proposal"]))
    assert blocked["status"] == "REFUSED" and blocked["code"] == "EVIDENCE_UNAVAILABLE", blocked
    committed = call("SUBMIT", host, organization=work["organization"], request=conflict)
    assert committed["host_commit"]["disposition"] == "COMMITTED" and committed["transition"]["replay"] is False
    before = work_snapshot()
    local = current_work(work["dispose"])
    failed = call("SUBMIT", host, organization=work["organization"], request=local, failure_reference="local-disposition-before-swap")
    assert failed["host_commit"]["disposition"] == "COMMIT_FAILED" and work_snapshot() == before
    assert len(call("PENDING", host, organization=work["organization"], instance=work["instance"])) == 1
    committed = call("SUBMIT", host, organization=work["organization"], request=local)
    assert committed["host_commit"]["disposition"] == "COMMITTED" and committed["transition"]["replay"] is False
    assert committed["transition"]["decision"]["disposition"] == "DISPOSITION_RECORDED"
    assert committed["transition"]["state"]["recovery_records"][-1]["after_projection"] == work["restored_projection"]
    assert call("PENDING", host, organization=work["organization"], instance=work["instance"]) == []
    replayed = call("SUBMIT", host, organization=work["organization"], request=current_work(local, event_revision=False))
    assert replayed["transition"]["replay"] is True and replayed["host_commit"] is None
    assert call("PENDING", host, organization=work["organization"], instance=work["instance"]) == []
    proposed = call("SUBMIT", host, organization=work["organization"], request=current_work(work["pending_proposal"]))
    assert proposed["host_commit"]["disposition"] == "COMMITTED", proposed
    assert proposed["transition"]["decision"]["disposition"] == "PERMITTED", proposed
    tampered_result = call("CHECK_STEP", host, request=work["tampered_input"])
    assert tampered_result["status"] == "REFUSED" and tampered_result["code"] == "STATE_INVALID", tampered_result
    passed.append("local native/disposition rollback preserves roots and replay log, retains custody and blocks descendant permission; valid retry restores exact original basis")
    passed.append("rehashed altered retained lifecycle recovery projection fails independent state admission")
    passed.append("exact local disposition replay preserves classified empty pending custody and subsequent eligible proposal")

    dispatch = fixture["dispatch"]
    for mode in ("control", "open-leave", "stale-clock", "pending-packet", "pending-native"):
        host = "actual-dispatch-" + mode
        call("NEW", host, pin=fixture["candidate_pin"])
        assert call("INSTALL", host, request=dispatch["deployment"], budget_roots=[dispatch["initial_root"]])["disposition"] == "INSTALLED"
        for request in dispatch["requests"]:
            submitted = call("SUBMIT", host, organization=dispatch["organization"], request=request)
            assert submitted["host_commit"]["disposition"] == "COMMITTED", submitted
        if mode != "control":
            request = dispatch[{"open-leave": "open_leave", "stale-clock": "later_registry_issue",
                "pending-packet": "pending_packet", "pending-native": "pending_native"}[mode]]
            submitted = call("REGISTRY", host, organization=dispatch["organization"], request=request,
                failure_reference="pending-native-before-swap" if mode == "pending-native" else None)
            if mode == "stale-clock":
                assert submitted["committed"] is True and submitted["transition"]["receipt"]["decision"] == "POLICY_RECORDED", submitted
            elif mode == "open-leave":
                assert submitted["committed"] is True and submitted["transition"]["receipt"]["decision"] == "DISPOSITION_RECORDED", submitted
                assert submitted["transition"]["state"]["core"] == dispatch["open_leave_core"]
            else:
                assert submitted["committed"] is False, submitted
                if mode == "pending-packet":
                    assert submitted["transition"]["code"] == "DEPENDENCY_MISMATCH", submitted
                else:
                    assert submitted["transition"]["receipt"]["decision"] == "EFFECT_DISPUTED", submitted
                assert len(call("PENDING", host, organization=dispatch["organization"], instance=dispatch["instance"])) == 1
        before = call("SNAPSHOT", host, organization=dispatch["organization"], instance=dispatch["instance"])
        result = call("DISPATCH", host, organization=dispatch["organization"], instance=dispatch["instance"],
            permit=dispatch["permit"], authorization=dispatch["authorization"], observation=dispatch["observation"],
            event_id="host-observe-safe-dispatch-" + mode)
        if mode in ("control", "open-leave"):
            assert result["invocations"] == 1 and "error_code" not in result, result
        else:
            assert result == {"invocations": 0, "error_code": "CLOCK_INVALID" if mode == "stale-clock" else "EVIDENCE_UNAVAILABLE"}, result
            assert call("SNAPSHOT", host, organization=dispatch["organization"], instance=dispatch["instance"]) == before
    passed.append("actual gated host dispatch invokes the isolated NOT_SENT connector once for current and conservative OPEN-LEAVE controls; registry-ahead clock and both recovery-packet and failed-native-write custody prevent invocation")
    return passed


def run(fixtures: Path, node: str) -> None:
    fixture = json.loads(fixtures.read_text())
    frozen = json.loads(fixtures.with_suffix(".freeze.json").read_text())
    for row in frozen["files"]:
        assert sha(ROOT / row["path"]) == row["sha256"], "Frozen host evidence changed: " + row["path"]
    assert fixture["candidate_pin"] == "sha256:" + sha(ROOT / "library/work-class-specification/1.0.0-draft.3/contract-manifest.json")
    outputs = {}
    for name, bridge in [("typescript", TypeScriptBridge(node)), ("python", PythonBridge())]:
        try:
            outputs[name] = exercise(bridge, fixture)
        finally:
            bridge.close()
    assert outputs["typescript"] == outputs["python"]
    report = {"candidate_pin": fixture["candidate_pin"], "status": "PASS", "assertion_groups": outputs,
        "fixture_sha256": sha(fixtures), "fixture_freeze_sha256": sha(fixtures.with_suffix(".freeze.json")), "limits": fixture["limits"]}
    path = fixtures.with_suffix(".results.json")
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "groups_per_consumer": str(len(outputs["typescript"])), "report": str(path)}))


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--run", action="store_true")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_RUN / "recovery-host-fixtures.json")
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    args.fixtures = args.fixtures.resolve()
    if args.prepare: prepare(args.fixtures)
    else: run(args.fixtures, args.node)


if __name__ == "__main__":
    main()
