from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import adapter
from consumer import Consumer
from implementation.common import IDENTITY, PIN, PROTOCOL, canonical, digest
from implementation.operations import aggregate
from implementation import lifecycle, reservation_v2, work_class
from implementation.reference_host import SingleProcessReferenceHost
from implementation.reservation_v2 import ReferenceHost as ReservationHost


def envelope(operation, value, request_id="request.1"):
    return {"protocol": PROTOCOL, "request_id": request_id, "operation": operation, "input": value}


def rehash_last_lifecycle_decision(state):
    receipt=state["receipts"][-1]
    replay=next(row for row in state["replays"] if row["event_id"]==receipt["event_id"])
    core=copy.deepcopy(state);core["receipts"]=[];core["replays"]=[]
    receipt["state_after_core_digest"]=digest("work-state-core",core)
    receipt_body=copy.deepcopy(receipt);receipt_body.pop("decision_id")
    receipt["decision_id"]=digest("decision-receipt",receipt_body)
    replay["decision"]=copy.deepcopy(receipt)
    replay["decision_receipt_digest"]=receipt["decision_id"]
    replay["transition_state_digest"]=receipt["state_after_core_digest"]
    replay["transaction_digest"]=digest("lifecycle-transaction",{
        "state_before_digest":receipt["state_before_digest"],
        "event_digest":replay["event_digest"],
        "decision_receipt_digest":replay["decision_receipt_digest"],
        "state_after_core_digest":replay["transition_state_digest"],
        "budget_results":replay["budget_results"],
    })
    return lifecycle.state_digest(state)


def linear_deploy_request():
    completion = {
        "effect_provider": "provider.1", "effect_source": "source.1", "effect_record_type": "result.1",
        "no_effect_provider": "provider.1", "no_effect_source": "source.1", "no_effect_record_type": "no-effect.1",
        "status_field": "status", "status_type_ref": "status", "success_values": [{"type_ref": "status", "value": "ok"}],
        "failure_values": [], "route_label_field": None, "route_label_type_ref": None,
        "evidence_bindings": [{"request_field": "subject", "evidence_field": "subject"}],
    }
    definition = {
        "schema": IDENTITY + "/work-class-definition", "specification_pin": PIN, "id": "class.1", "revision": "revision.1",
        "profile": "LINEAR", "root": "operate",
        "participants": [{"id": "participant.1", "role": "operator", "kind": "PERSON"}], "objects": [],
        "types": [{"id": "identity", "kind": "IDENTITY", "nonnegative": False, "unit": None}, {"id": "status", "kind": "STRING", "nonnegative": False, "unit": None}],
        "steps": [
            {"id": "operate", "kind": "OPERATION", "executor_role": "operator", "interface": "service.1", "operation": "operate.1", "fields": [{"name": "subject", "type_ref": "identity"}], "scope_fields": {"subjects": ["subject"], "resources": ["subject"]}, "required_credentials": [], "authority_requirements": ["authority.1"], "shared_budgets": [], "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": "300", "failure_behavior": "STOP", "completion": completion},
            {"id": "terminal", "kind": "TERMINAL", "executor_role": None, "interface": None, "operation": None, "fields": [], "scope_fields": None, "required_credentials": [], "authority_requirements": [], "shared_budgets": [], "prior_effect_bindings": [], "prior_actor_separations": [], "permit_seconds": None, "failure_behavior": None, "completion": None},
        ],
        "relationships": [{"kind": "SEQUENCE", "from": "operate", "to": "terminal"}], "choices": [], "occurrence_limits": [{"step_id":"operate","maximum":"1"}], "loops": [], "deadlines": [], "parallel_blocks": [], "fanouts": [], "shared_budgets": [],
        "limits": {"maximum_proposals": "10", "maximum_activations": "10", "maximum_actuations": "10", "maximum_active_obligations": "0", "maximum_fanout_objects": "0"},
        "source": {"id": "source-policy.1", "revision": "revision.1", "obligations": ["obligation.1"]},
    }
    work_digest = digest("work-class-definition", definition)
    authorization = {
        "schema": IDENTITY + "/deployment-authorization", "authorization_id": "authorization.1", "specification_pin": PIN,
        "work_class_digest": work_digest, "profile": "LINEAR", "role": "LINEAR_WORK_RUNTIME", "instance_id": "instance.1",
        "organization_id": "organization.1", "status": "AUTHORIZED", "authorization_evidence_digest": "sha256:" + "0" * 64,
        "authorized_at": "2026-09-11T00:00:00Z", "expires_at": "2026-09-12T00:00:00Z",
    }
    subject = copy.deepcopy(authorization); subject.pop("authorization_evidence_digest")
    evidence = {
        "schema": IDENTITY + "/evidence-record", "evidence_id": "evidence.1", "kind": "ORGANIZATIONAL_AUTHORIZATION",
        "status": "ACCEPTED", "subject_digest": digest("deployment-authorization-subject", subject), "organization_id": "organization.1",
        "authorizer_id": "authorizer.1", "authorization_scope": sorted([PIN, work_digest, "LINEAR", "LINEAR_WORK_RUNTIME", "instance.1"], key=str.encode),
        "recorded_at": "2026-09-11T00:00:00Z", "expires_at": "2026-09-12T00:00:00Z", "provenance_digest": "sha256:" + "1" * 64,
    }
    authorization["authorization_evidence_digest"] = digest("evidence", evidence)
    return {"profile": "LINEAR", "role": "LINEAR_WORK_RUNTIME", "specification_pin": PIN, "definition": definition, "definition_digest": work_digest, "instance_id": "instance.1", "deployment_authorization": authorization, "authorization_evidence": evidence, "authorization_clock": {"source": "clock.1", "revision": "1", "status": "AVAILABLE", "observed_time": "2026-09-11T01:00:00Z", "evidence_digest": "sha256:" + "2" * 64}, "initial_clocks": []}


def schema_valid_authority_input(definition, occurrence, native_request):
    baseline = Path(__file__).resolve().parents[3] / "1.0.0-draft.1/python/input/examples/authority-access-card.json"
    value = json.loads(baseline.read_text())
    def rewrite(node):
        if isinstance(node, str):
            return node.replace("1.0.0-draft.1", "1.0.0-draft.2").replace("sha256:668b7622967767d65c382f94c7d8bca24c49f365962ea19128dece246ec1ef26", PIN)
        if isinstance(node, list): return [rewrite(row) for row in node]
        if isinstance(node, dict): return {key:rewrite(row) for key,row in node.items()}
        return node
    value = rewrite(value)
    projection = lifecycle._authority_projection(definition)
    projection_digest = digest("authority-work-class", projection)
    value["work_class"] = projection
    value["source"] = {"schema":IDENTITY+"/authority-source","id":definition["source"]["id"],"revision":definition["source"]["revision"],"obligations":[{"id":row,"text":"reviewed obligation"} for row in definition["source"]["obligations"]]}
    executor = {"actor":"participant.1","role":"operator","principal":"principal.1","occupancy":"occupancy.1"}
    value["proposal"] = {"schema":IDENTITY+"/authority-proposal","work_class_digest":projection_digest,"work_class":definition["id"],"instance":"instance.1","occurrence":occurrence["occurrence_id"],"step":occurrence["step_id"],"operation":native_request["operation"],"interface":native_request["interface"],"executor":executor,"fields":copy.deepcopy(native_request["fields"])}
    value["envelope"]["id"] = "authority.1"
    value["envelope"]["work_class_digest"] = projection_digest
    value["envelope"]["source_obligations"] = copy.deepcopy(definition["source"]["obligations"])
    value["clock"] = {"source":"host-clock.1","status":"AVAILABLE","instant":"2026-09-11T02:00:00Z"}
    return value


def draft2_registry_registration(authority_input):
    baseline_root=Path(__file__).resolve().parents[3]/"1.0.0-draft.1/python/input/examples"
    contention=json.loads((baseline_root/"reservation-contention-inputs.json").read_text())
    registration=json.loads((baseline_root/"reservation-register.json").read_text())
    def rewrite(value):
        if isinstance(value,str):
            return value.replace("1.0.0-draft.1","1.0.0-draft.2").replace("sha256:668b7622967767d65c382f94c7d8bca24c49f365962ea19128dece246ec1ef26",PIN)
        if isinstance(value,list): return [rewrite(row) for row in value]
        if isinstance(value,dict): return {key:rewrite(row) for key,row in value.items()}
        return value
    contention=rewrite(contention);registration=rewrite(registration)
    configuration=contention["configuration"]
    budget=contention["budget"]
    budget_digest=digest("budget-definition",budget)
    history=contention["history"];history["budget_digest"]=budget_digest
    authorization=contention["authorizations"][0]
    authority_definition={"schema":IDENTITY+"/authority-definition","source":copy.deepcopy(authority_input["source"]),"work_class":copy.deepcopy(authority_input["work_class"]),"envelope":copy.deepcopy(authority_input["envelope"])}
    authority_definition["envelope"]["source_digest"]=digest("authority-source",authority_definition["source"])
    authority_definition["envelope"]["work_class_digest"]=digest("authority-work-class",authority_definition["work_class"])
    authorization.update({"budget_digest":budget_digest,"work_class":authority_input["work_class"]["id"],"work_class_digest":digest("authority-work-class",authority_definition["work_class"]),"envelope_digest":digest("authority-envelope",authority_definition["envelope"]),"principal":configuration["principal"],"step":authority_input["proposal"]["step"],"authority_definition":authority_definition})
    event={"id":"register-license-budget","expected_revision":"0","kind":"REGISTER","clock":copy.deepcopy(contention["clock"]),"payload":{"definition":budget,"authorizations":[authorization],"history":history},"administration":copy.deepcopy(registration["event"]["administration"])}
    registry_digest=digest("reservation-registry",configuration)
    act=event["administration"]["act"]
    act["subject_digest"]=digest("reservation-administration-subject",reservation_v2._admin_subject(event,configuration))
    returned=event["administration"]["returned"]
    returned["act_digest"]=digest("reservation-administration-act",act)
    returned["act_bytes_base64"]=base64.b64encode(reservation_v2.canon(act)).decode("ascii")
    bases=copy.deepcopy(registration["host_evidence"]["administration_bases"])
    for basis in bases: basis["registry_digest"]=registry_digest
    host_evidence={"registry_digest":registry_digest,"selection_evidence":"selected-license-registry","administration_bases":bases,"authenticated_records":[
        {"kind":"ADMIN_RETURN","record_digest":digest("reservation-administration-return",returned),"provider":configuration["administration_provider"],"source":configuration["administration_source"]},
        {"kind":"HISTORY","record_digest":digest("budget-history",history),"provider":history["provider"],"source":history["source"]},
    ]}
    host=ReservationHost(configuration)
    reservation_v2._validate_admin(event,host_evidence,configuration)
    reservation_v2._validate_registration(event,host_evidence,host.export_state())
    result=host.step({"event":event,"host_evidence":host_evidence})
    return host,result,contention,{"registration":registration,"administration_bases":bases}


def rebind_deployment(request, definition, profile, role):
    request=copy.deepcopy(request);work_digest=digest("work-class-definition",definition)
    request.update({"profile":profile,"role":role,"definition":definition,"definition_digest":work_digest})
    authorization=request["deployment_authorization"];authorization["work_class_digest"]=work_digest;authorization["profile"]=profile;authorization["role"]=role
    subject=copy.deepcopy(authorization);subject.pop("authorization_evidence_digest")
    evidence=request["authorization_evidence"];evidence["subject_digest"]=digest("deployment-authorization-subject",subject);evidence["authorization_scope"]=sorted([PIN,work_digest,profile,role,request["instance_id"]],key=str.encode)
    authorization["authorization_evidence_digest"]=digest("evidence",evidence)
    return request


class FoundationTests(unittest.TestCase):
    def test_signed_decimal_accepts_negative_fraction_but_not_negative_zero(self):
        types = {"quantity": {"id":"quantity","kind":"DECIMAL","nonnegative":False,"unit":None}}
        self.assertTrue(work_class._typed({"type_ref":"quantity","value":"-0.1"}, types))
        self.assertFalse(work_class._typed({"type_ref":"quantity","value":"-0"}, types))
        self.assertFalse(work_class._typed({"type_ref":"quantity","value":"-0.0"}, types))

    def test_static_definition_rejects_semantic_cardinality_errors(self):
        definition=linear_deploy_request()["definition"]
        invalid=copy.deepcopy(definition);invalid["occurrence_limits"][0]["maximum"]="0"
        with self.assertRaises(lifecycle.Refusal) as root_limit: work_class.validate(invalid)
        self.assertEqual(root_limit.exception.code,"DEFINITION_INVALID")
        parallel=json.loads((ROOT.parent / "cases/parallel-entry/D2-051.json").read_text())["input"]["definition"]
        self.assertEqual(next(row["maximum"] for row in parallel["occurrence_limits"] if row["step_id"]=="branch-b"),"0")
        self.assertIsInstance(work_class.validate(parallel),str)
        loop=json.loads((ROOT.parent / "cases/bounded-loops/D2-048.json").read_text())["input"]["definition"]
        retry=copy.deepcopy(next(row for row in loop["steps"] if row["id"]=="issue"));retry["id"]="retry";retry["operation"]="retry-card"
        loop["steps"].append(retry);loop["steps"].sort(key=lambda row:row["id"].encode())
        next(row for row in loop["relationships"] if row["from"]=="issue" and row.get("label",{}).get("value")=="CONTINUE")["to"]="retry"
        loop["relationships"].extend([
            {"from":"retry","kind":"LABEL","label":{"type_ref":"STRING","value":"CONTINUE"},"to":"issue"},
            {"from":"retry","kind":"LABEL","label":{"type_ref":"STRING","value":"EXIT"},"to":"terminal"},
        ])
        retry_choice=copy.deepcopy(loop["choices"][0]);retry_choice["step_id"]="retry";loop["choices"].append(retry_choice);loop["choices"].sort(key=lambda row:row["step_id"].encode())
        loop["occurrence_limits"].append({"step_id":"retry","maximum":"0"});loop["occurrence_limits"].sort(key=lambda row:row["step_id"].encode())
        loop["loops"][0]["member_step_ids"]=["issue","retry"];loop["loops"][0]["back_edge_from_step_id"]="retry"
        with self.assertRaises(lifecycle.Refusal) as loop_limit: work_class.validate(loop)
        self.assertEqual(loop_limit.exception.code,"DEFINITION_INVALID")
        invalid=copy.deepcopy(definition);invalid["steps"][0]["completion"]["route_label_field"]="route";invalid["steps"][0]["completion"]["route_label_type_ref"]="status"
        with self.assertRaises(lifecycle.Refusal) as stray_choice: work_class.validate(invalid)
        self.assertEqual(stray_choice.exception.code,"DEFINITION_INVALID")
        invalid=copy.deepcopy(definition);invalid["profile"]="DEADLINES";invalid["deadlines"]=[{"id":"a","step_id":"operate","due":{"kind":"ELAPSED_DURATION","value":"1","unit":"SECOND"},"clock_source":"clock.1","boundary":"AT_OR_AFTER","expiry_target":None},{"id":"b","step_id":"operate","due":{"kind":"ELAPSED_DURATION","value":"2","unit":"SECOND"},"clock_source":"clock.1","boundary":"AT_OR_AFTER","expiry_target":None}]
        with self.assertRaises(lifecycle.Refusal) as duplicate_deadline: work_class.validate(invalid)
        self.assertEqual(duplicate_deadline.exception.code,"DEFINITION_INVALID")

    def test_observed_request_projects_changed_dispatch_arguments(self):
        request = {"definition":{"types":[
            {"id":"identity","kind":"IDENTITY","nonnegative":False,"unit":None},
            {"id":"status","kind":"STRING","nonnegative":False,"unit":None},
        ]}}
        step = {"completion":{
            "status_field":"status","status_type_ref":"status",
            "success_values":[{"type_ref":"status","value":"ok"}],"failure_values":[],
            "route_label_field":None,"route_label_type_ref":None,
            "evidence_bindings":[{"request_field":"subject","evidence_field":"subject"}],
        }}
        dispatch = {"native_request":{"interface":"service.1","operation":"operate.1","fields":[
            {"name":"subject","value":{"type_ref":"identity","value":"changed"}},
        ]}}
        attributed = {"work_class":"class.1","instance":"instance.1","occurrence":"occurrence.1","step":"operate","interface":"service.1","operation":"operate.1","fields":copy.deepcopy(dispatch["native_request"]["fields"])}
        evidence = {"status":"EFFECT_ESTABLISHED","attributed_request":attributed,"actual_fields":[
            {"name":"status","value":{"type_ref":"status","value":"ok"}},
            {"name":"subject","value":{"type_ref":"identity","value":"changed"}},
        ]}
        self.assertEqual(lifecycle._project_observed_request(request,dispatch,step,evidence),attributed)
        evidence["actual_fields"][1]["value"]["value"]="permitted"
        self.assertIsNone(lifecycle._project_observed_request(request,dispatch,step,evidence))

    def test_lifecycle_time_arithmetic_crosses_calendar_boundary(self):
        self.assertEqual(lifecycle._add_seconds("2026-12-31T23:59:59Z", 1), "2027-01-01T00:00:00Z")

    def test_prior_effect_basis_uses_recursive_completed_ancestor(self):
        source = lifecycle._occurrence(PIN, "sha256:" + "a" * 64, "instance.1", "source")
        middle = lifecycle._occurrence(PIN, "sha256:" + "a" * 64, "instance.1", "middle", predecessors=[source["occurrence_id"]])
        current = lifecycle._occurrence(PIN, "sha256:" + "a" * 64, "instance.1", "current", predecessors=[middle["occurrence_id"]])
        native_evidence = {
            "evidence_id":"evidence.1","native_operation_id":"native.1","provider":"provider.1","source":"source.1","record_type":"result.1","record_digest":"sha256:"+"b"*64,"evidence_ref":"ref.1",
            "attributed_request":{"work_class":"class.1","instance":"instance.1","occurrence":source["occurrence_id"],"step":"source","operation":"source.1","interface":"service.1","fields":[]},
            "native_request_digest":"sha256:"+"c"*64,"status":"EFFECT_ESTABLISHED","actual_fields":[{"name":"result-id","value":{"type_ref":"identity","value":"value.1"}}],"collections":[],"event_time":"2026-01-01T00:00:00Z","observed_at":"2026-01-01T00:00:00Z","rules_out_past_and_future_effects":False,
        }
        permit_id = "sha256:" + "d" * 64
        state = {
            "active":[{"occurrence":current}],
            "completed":[{"occurrence":source,"disposition":"SUCCEEDED","evidence_digest":digest("native-evidence",native_evidence)}, {"occurrence":middle,"disposition":"SUCCEEDED","evidence_digest":"sha256:"+"e"*64}],
            "outcomes":[{"kind":"GOVERNED","classification":"MATCHED","disputed":False,"permit_digest":permit_id,"native_evidence":native_evidence}],
            "permits":[{"permit_id":permit_id,"occurrence":source}],
        }
        step = {"prior_effect_bindings":[{"id":"binding.1","selection":"UNIQUE_COMPLETED_ANCESTOR","source_step_id":"source","source_evidence_field":"result-id","target_request_field":"input-id"}]}
        native = {"fields":[{"name":"input-id","value":{"type_ref":"identity","value":"value.1"}}]}
        bases = lifecycle._prior_effect_bases(state, step, current, native)
        self.assertEqual(bases[0]["source_occurrence_id"], source["occurrence_id"])
        changed = copy.deepcopy(native); changed["fields"][0]["value"]["value"] = "value.2"
        with self.assertRaises(lifecycle.Refusal) as raised:
            lifecycle._prior_effect_bases(state, step, current, changed)
        self.assertEqual(raised.exception.code, "BINDING_MISMATCH")

    def test_actor_separation_retains_complete_act_bases(self):
        prior_occurrence=lifecycle._occurrence(PIN,"sha256:"+"a"*64,"instance.1","confirm")
        current_occurrence=lifecycle._occurrence(PIN,"sha256:"+"a"*64,"instance.1","pay",predecessors=[prior_occurrence["occurrence_id"]])
        prior_act={"schema":IDENTITY+"/authority-act","id":"act.confirm","kind":"CONFIRM","actor":"actor.1","role":"confirmer","principal":"principal.1","basis":"basis.1","subject":"sha256:"+"b"*64,"occurred_at":"2026-09-11T01:00:00Z","disposition":"ACCEPT"}
        current_act=copy.deepcopy(prior_act);current_act.update({"id":"act.pay","kind":"RELEASE","role":"payer"})
        prior_basis={"act_digest":digest("authority-act",prior_act),"act":prior_act}
        permit_id="sha256:"+"c"*64
        evidence={"evidence_id":"effect.1","native_operation_id":"native.1","provider":"provider.1","source":"source.1","record_type":"result.1","record_digest":"sha256:"+"d"*64,"evidence_ref":"ref.1","attributed_request":{"work_class":"class.1","instance":"instance.1","occurrence":prior_occurrence["occurrence_id"],"step":"confirm","operation":"confirm.1","interface":"service.1","fields":[]},"native_request_digest":"sha256:"+"e"*64,"status":"EFFECT_ESTABLISHED","actual_fields":[],"collections":[],"event_time":"2026-09-11T01:00:00Z","observed_at":"2026-09-11T01:00:00Z","rules_out_past_and_future_effects":False}
        state={"active":[{"occurrence":current_occurrence}],"completed":[{"occurrence":prior_occurrence,"disposition":"SUCCEEDED","evidence_digest":digest("native-evidence",evidence)}],"permits":[{"permit_id":permit_id,"occurrence":prior_occurrence,"authority_act_bases":[prior_basis]}],"outcomes":[{"kind":"GOVERNED","classification":"MATCHED","disputed":False,"permit_digest":permit_id,"native_evidence":evidence}]}
        step={"prior_actor_separations":[{"id":"separation.1","prior_step_id":"confirm","prior_act_kind":"CONFIRM","current_act_kind":"RELEASE"}]}
        current_basis={"act_digest":digest("authority-act",current_act),"act":current_act}
        bases,failed=lifecycle._separation_bases(state,step,current_occurrence,[current_basis])
        self.assertEqual(failed,bases[0]);self.assertEqual(bases[0]["prior_act"],prior_basis);self.assertEqual(bases[0]["current_act"],current_basis)
        distinct=copy.deepcopy(current_basis);distinct["act"]["actor"]="actor.2";distinct["act_digest"]=digest("authority-act",distinct["act"])
        bases,failed=lifecycle._separation_bases(state,step,current_occurrence,[distinct])
        self.assertIsNone(failed);self.assertEqual(bases[0]["relation"],"DISTINCT_ACTOR")

    def test_no_effect_completion_authorization_is_fully_bound(self):
        request={"definition_digest":"sha256:"+"a"*64,"state":{"deployment_organization_id":"organization.1"},"event":{"instance_id":"instance.1","completion_authorization":None}}
        permit={"permit_id":"sha256:"+"b"*64,"occurrence":{"occurrence_id":"occurrence.1"}}
        dispatch={"dispatch_digest":"sha256:"+"c"*64}
        evidence={"evidence_id":"evidence.1","observed_at":"2026-09-11T02:00:00Z"}
        with self.assertRaises(lifecycle.Refusal) as missing:
            lifecycle._completion_authorization(request,permit,dispatch,evidence)
        self.assertEqual(missing.exception.code,"EVIDENCE_UNAVAILABLE")
        native_digest=digest("native-evidence",evidence)
        subject={"specification_pin":PIN,"work_class_digest":request["definition_digest"],"instance_id":"instance.1","occurrence_id":"occurrence.1","permit_id":permit["permit_id"],"dispatch_digest":dispatch["dispatch_digest"],"native_evidence_digest":native_digest}
        request["event"]["completion_authorization"]={"status":"ACCEPTED","expires_at":"2026-09-11T03:00:00Z","recorded_at":"2026-09-11T01:00:00Z","organization_id":"organization.1","subject_digest":digest("no-effect-completion",subject),"authorization_scope":sorted([PIN,request["definition_digest"],"instance.1","occurrence.1",permit["permit_id"],dispatch["dispatch_digest"],native_digest],key=str.encode)}
        lifecycle._completion_authorization(request,permit,dispatch,evidence)
        request["event"]["completion_authorization"]["organization_id"]="organization.2"
        with self.assertRaises(lifecycle.Refusal) as changed:
            lifecycle._completion_authorization(request,permit,dispatch,evidence)
        self.assertEqual(changed.exception.code,"BINDING_MISMATCH")

    def test_parallel_split_creates_complete_obligation_inventory(self):
        base=linear_deploy_request();definition=copy.deepcopy(base["definition"]);template=definition["steps"][0]
        def operation(step_id, operation):
            row=copy.deepcopy(template);row["id"]=step_id;row["operation"]=operation;return row
        structural=lambda step_id,kind:{"id":step_id,"kind":kind,"executor_role":None,"interface":None,"operation":None,"fields":[],"scope_fields":None,"required_credentials":[],"authority_requirements":[],"shared_budgets":[],"prior_effect_bindings":[],"prior_actor_separations":[],"permit_seconds":None,"failure_behavior":None,"completion":None}
        definition["profile"]="PARALLEL_FANOUT";definition["steps"]=[operation("branch-a","branch-a.1"),operation("branch-b","branch-b.1"),structural("join","PARALLEL_JOIN"),template,structural("split","PARALLEL_SPLIT"),structural("terminal","TERMINAL")]
        definition["steps"]=sorted(definition["steps"],key=lambda row:row["id"].encode())
        definition["relationships"]=[{"kind":"SEQUENCE","from":"operate","to":"split"},{"kind":"SEQUENCE","from":"branch-a","to":"join"},{"kind":"SEQUENCE","from":"branch-b","to":"join"},{"kind":"SEQUENCE","from":"join","to":"terminal"}]
        definition["parallel_blocks"]=[{"id":"parallel.1","split_step_id":"split","branches":[{"id":"a","head_step_id":"branch-a"},{"id":"b","head_step_id":"branch-b"}],"join_step_id":"join"}]
        definition["limits"]["maximum_active_obligations"]="2"
        invalid=copy.deepcopy(definition);next(row for row in invalid["relationships"] if row["from"]=="branch-a")["to"]="branch-b"
        with self.assertRaises(lifecycle.Refusal) as cross_boundary: work_class.validate(invalid)
        self.assertEqual(cross_boundary.exception.code,"DEFINITION_INVALID")
        deploy_request=rebind_deployment(base,definition,"PARALLEL_FANOUT","PARALLEL_FANOUT_RUNTIME");deployed=adapter._dispatch("deploy",deploy_request)
        self.assertEqual(deployed["status"],"DEPLOYED")
        state=copy.deepcopy(deployed["state"]);source=state["active"].pop()["occurrence"]
        event={"schema":IDENTITY+"/runtime-event","event_id":"effect.1","kind":"EFFECT_OBSERVED","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":deployed["state_digest"],"activation_clocks":[]}
        request={"definition":definition,"definition_digest":deploy_request["definition_digest"],"event":event}
        reasons,details,obligation_ids,constructs=lifecycle._enter_parallel(request,state,source,next(row for row in definition["steps"] if row["id"]=="split"),[source["occurrence_id"]])
        self.assertEqual((reasons,details,constructs),([],[],["parallel.1"]))
        self.assertEqual(len(obligation_ids),2);self.assertEqual(len(state["active"]),2);self.assertEqual(len(state["obligations"]),2)
        self.assertTrue(adapter.schema_valid(state,"lifecycle.schema.json","state"))
        first=next(row for row in state["active"] if row["occurrence"]["step_id"]=="branch-a")
        disposition,reasons,details=lifecycle._complete_simple_route(request,state,first,"MATCHED","sha256:"+"1"*64,None,"2026-09-11T02:00:00Z")
        self.assertEqual((disposition,reasons),("COMPLETED",[]));self.assertEqual(sum(row["status"]=="DISCHARGED" for row in state["obligations"]),1)
        second=next(row for row in state["active"] if row["occurrence"]["step_id"]=="branch-b")
        disposition,reasons,details=lifecycle._complete_simple_route(request,state,second,"MATCHED","sha256:"+"2"*64,None,"2026-09-11T02:00:00Z")
        self.assertEqual((disposition,reasons),("COMPLETED",[]));self.assertEqual(state["status"],"COMPLETE");self.assertTrue(all(row["status"]=="JOINED" for row in state["obligations"]))
        self.assertTrue(adapter.schema_valid(state,"lifecycle.schema.json","state"))

    def test_nested_child_pass_frontier_is_recursive(self):
        direct_a={"obligation_id":"a","status":"JOINED","completion_basis":{"kind":"DIRECT_EVENT","occurrence_id":"occurrence.a"}}
        direct_b={"obligation_id":"b","status":"JOINED","completion_basis":{"kind":"DIRECT_EVENT","occurrence_id":"occurrence.b"}}
        parent={"obligation_id":"parent","status":"DISCHARGED","completion_basis":{"kind":"CHILD_PASS","child_pass":{"kind":"PARALLEL","construct_id":"inner","pass":"1","outer_enclosing":[],"obligation_ids":["a","b"]}}}
        state={"obligations":[direct_a,direct_b,parent]}
        self.assertEqual(lifecycle._completion_frontier(state,parent),["occurrence.a","occurrence.b"])

        source=lifecycle._occurrence(PIN,"sha256:"+"a"*64,"instance.1","source")
        leaf=lifecycle._occurrence(PIN,"sha256:"+"a"*64,"instance.1","leaf",predecessors=[source["occurrence_id"]])
        child={"obligation_id":"child","status":"DISCHARGED","completion_basis":{"kind":"DIRECT_EVENT","occurrence_id":leaf["occurrence_id"]}}
        waiting={"obligation_id":"waiting","status":"WAITING","waiting_on":{"obligation_ids":["child"]}}
        disputed={"active":[],"completed":[{"occurrence":source},{"occurrence":leaf}],"obligations":[child,waiting]}
        lifecycle._block_dependents(disputed,source["occurrence_id"])
        self.assertEqual(child["status"],"DISPUTED");self.assertEqual(waiting["status"],"DISPUTED")

    def test_missing_choice_label_is_a_retained_policy_stop(self):
        base=linear_deploy_request();definition=copy.deepcopy(base["definition"]);step=definition["steps"][0]
        definition["profile"]="CHOICE_LOOPS";definition["types"].append({"id":"label","kind":"STRING","nonnegative":False,"unit":None});definition["types"].sort(key=lambda row:row["id"].encode())
        step["completion"]["route_label_field"]="route";step["completion"]["route_label_type_ref"]="label"
        labels=[{"type_ref":"label","value":"no"},{"type_ref":"label","value":"yes"}]
        definition["choices"]=[{"step_id":"operate","label_type_ref":"label","label_values":labels}]
        definition["relationships"]=[{"kind":"LABEL","from":"operate","to":"terminal","label":copy.deepcopy(value)} for value in labels]
        deploy_request=rebind_deployment(base,definition,"CHOICE_LOOPS","CHOICE_LOOP_RUNTIME");deployed=adapter._dispatch("deploy",deploy_request);self.assertEqual(deployed["status"],"DEPLOYED")
        active=deployed["state"]["active"][0];native={"operation":"operate.1","interface":"service.1","fields":[{"name":"subject","value":{"type_ref":"identity","value":"subject.1"}}]};permit={"native_request":native}
        evidence={"actual_fields":[{"name":"status","value":{"type_ref":"status","value":"ok"}},{"name":"subject","value":{"type_ref":"identity","value":"subject.1"}}],"collections":[]}
        classification,label,_=lifecycle._completion_fields(step,permit,evidence);self.assertEqual((classification,label),("MATCHED",None))
        event={"event_id":"effect.1"};state=copy.deepcopy(deployed["state"])
        disposition,reasons,details=lifecycle._complete_simple_route({"definition":definition,"definition_digest":deploy_request["definition_digest"],"event":event},state,state["active"][0],classification,"sha256:"+"1"*64,label,"2026-09-11T02:00:00Z")
        self.assertEqual((disposition,reasons),("STOPPED",["LABEL_INVALID"]));self.assertEqual(details,[{"kind":"LABEL","step_id":"operate","observed_value":None}])

    def test_fanout_freezes_source_order_and_object_bindings(self):
        base=linear_deploy_request();definition=copy.deepcopy(base["definition"]);expand=definition["steps"][0];expand["id"]="expand";expand["kind"]="FANOUT_EXPAND";expand["operation"]="list.1"
        head=copy.deepcopy(definition["steps"][0]);head["id"]="process";head["kind"]="OPERATION";head["operation"]="process.1";head["fields"]=[{"name":"object-id","type_ref":"identity"},{"name":"subject","type_ref":"identity"}];head["completion"]["evidence_bindings"]=[{"request_field":"object-id","evidence_field":"object-id"},{"request_field":"subject","evidence_field":"subject"}]
        structural=lambda step_id,kind:{"id":step_id,"kind":kind,"executor_role":None,"interface":None,"operation":None,"fields":[],"scope_fields":None,"required_credentials":[],"authority_requirements":[],"shared_budgets":[],"prior_effect_bindings":[],"prior_actor_separations":[],"permit_seconds":None,"failure_behavior":None,"completion":None}
        definition["profile"]="PARALLEL_FANOUT";definition["root"]="expand";definition["steps"]=sorted([expand,structural("join","FANOUT_JOIN"),head,structural("terminal","TERMINAL")],key=lambda row:row["id"].encode())
        definition["relationships"]=[{"kind":"SEQUENCE","from":"process","to":"join"},{"kind":"SEQUENCE","from":"join","to":"terminal"},{"kind":"EXPIRY","from":"process","to":"join","deadline_ref":"deadline.process"}]
        definition["occurrence_limits"]=[{"step_id":"expand","maximum":"1"}]
        definition["deadlines"]=[{"id":"deadline.process","step_id":"process","clock_source":"deadline-clock.1","due":{"kind":"ELAPSED_DURATION","value":"60","unit":"SECOND"},"boundary":"AT_OR_AFTER","expiry_target":"join"}]
        definition["fanouts"]=[{"id":"fanout.1","expand_step_id":"expand","region_head_step_id":"process","join_step_id":"join","object_field":"objects","object_request_field":"object-id","object_type_ref":"identity","empty_set_behavior":"ADVANCE_TO_JOIN"}]
        definition["limits"]["maximum_active_obligations"]="2";definition["limits"]["maximum_fanout_objects"]="2"
        deploy_request=rebind_deployment(base,definition,"PARALLEL_FANOUT","PARALLEL_FANOUT_RUNTIME");deployed=adapter._dispatch("deploy",deploy_request);self.assertEqual(deployed["status"],"DEPLOYED")
        state=copy.deepcopy(deployed["state"]);source=state["active"].pop()["occurrence"]
        activation_clock={"source":"deadline-clock.1","revision":"1","status":"AVAILABLE","observed_time":"2026-09-11T02:00:00Z","evidence_digest":"sha256:"+"f"*64};state["clocks"].append(activation_clock)
        evidence={"collections":[{"name":"objects","element_type_ref":"identity","values":[{"type_ref":"identity","value":"object-b"},{"type_ref":"identity","value":"object-a"}]}]}
        state["completed"].append({"occurrence":source,"disposition":"SUCCEEDED","evidence_digest":"sha256:"+"e"*64,"occurred_at":"2026-09-11T02:00:00Z","route_label":None,"selected_relationship_digest":None,"late":False})
        event={"schema":IDENTITY+"/runtime-event","event_id":"effect.1","kind":"EFFECT_OBSERVED","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":deployed["state_digest"],"activation_clocks":[activation_clock]}
        reasons,details,constructs=lifecycle._enter_fanout({"definition":definition,"definition_digest":deploy_request["definition_digest"],"event":event},state,source,evidence)
        self.assertEqual((reasons,details,constructs),([],[],["fanout.1"]))
        self.assertEqual(state["fanout_passes"][0]["object_keys"],evidence["collections"][0]["values"])
        self.assertEqual([row["occurrence"]["object_key"] for row in state["active"]],sorted(evidence["collections"][0]["values"],key=canonical))
        self.assertEqual([row["due"] for row in state["deadlines"]],["2026-09-11T02:01:00Z"]*2)
        self.assertTrue(adapter.schema_valid(state,"lifecycle.schema.json","state"))
        blocked=copy.deepcopy(state);blocked_active=blocked["active"][0];blocked_active["status"]="BLOCKED_DISPUTE";next(row for row in blocked["obligations"] if row["expected_occurrence_id"]==blocked_active["occurrence"]["occurrence_id"])["status"]="BLOCKED"
        clock={"schema":IDENTITY+"/runtime-event","event_id":"clock.mixed","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":lifecycle.state_digest(blocked),"clock":{"source":"deadline-clock.1","revision":"2","status":"AVAILABLE","observed_time":"2026-09-11T02:01:00Z","evidence_digest":"sha256:"+"9"*64},"activation_clocks":[]}
        mixed=lifecycle._clock_step({"profile":"PARALLEL_FANOUT","role":"PARALLEL_FANOUT_RUNTIME","definition":definition,"definition_digest":deploy_request["definition_digest"],"state":blocked,"state_digest":lifecycle.state_digest(blocked),"event":clock})
        self.assertEqual(mixed["decision"]["disposition"],"EXPIRED");self.assertTrue(all(row["status"]=="EXPIRED" for row in mixed["state"]["deadlines"]))
        self.assertEqual([row["status"] for row in mixed["state"]["obligations"]].count("BLOCKED"),1);self.assertEqual([row["status"] for row in mixed["state"]["obligations"]].count("DISCHARGED"),1)
        self.assertEqual(len(mixed["state"]["active"]),1);self.assertEqual(mixed["state"]["active"][0]["status"],"BLOCKED_DISPUTE")
        for active in list(state["active"]):
            disposition,reasons,details=lifecycle._complete_simple_route({"definition":definition,"definition_digest":deploy_request["definition_digest"],"event":event},state,active,"MATCHED","sha256:"+"d"*64,None,"2026-09-11T02:00:30Z")
            self.assertEqual((disposition,reasons),("COMPLETED",[]))
        self.assertTrue(state["fanout_passes"][0]["joined"]);self.assertTrue(all(row["status"]=="JOINED" for row in state["obligations"]));self.assertEqual(state["status"],"COMPLETE")
        self.assertTrue(adapter.schema_valid(state,"lifecycle.schema.json","state"))

    def test_due_set_stop_rolls_back_every_expiry_closure(self):
        base=linear_deploy_request();definition=copy.deepcopy(base["definition"]);template=definition["steps"][0]
        def operation(step_id, operation):
            row=copy.deepcopy(template);row["id"]=step_id;row["operation"]=operation;return row
        structural=lambda step_id,kind:{"id":step_id,"kind":kind,"executor_role":None,"interface":None,"operation":None,"fields":[],"scope_fields":None,"required_credentials":[],"authority_requirements":[],"shared_budgets":[],"prior_effect_bindings":[],"prior_actor_separations":[],"permit_seconds":None,"failure_behavior":None,"completion":None}
        definition["profile"]="PARALLEL_FANOUT"
        definition["steps"]=sorted([template,structural("split","PARALLEL_SPLIT"),operation("branch-a","branch-a.1"),operation("branch-b","branch-b.1"),structural("join","PARALLEL_JOIN"),structural("terminal","TERMINAL")],key=lambda row:row["id"].encode())
        definition["relationships"]=[{"kind":"SEQUENCE","from":"operate","to":"split"},{"kind":"SEQUENCE","from":"branch-a","to":"join"},{"kind":"SEQUENCE","from":"branch-b","to":"join"},{"kind":"EXPIRY","from":"branch-a","to":"join","deadline_ref":"deadline.a"},{"kind":"SEQUENCE","from":"join","to":"terminal"}]
        definition["parallel_blocks"]=[{"id":"parallel.1","split_step_id":"split","branches":[{"id":"a","head_step_id":"branch-a"},{"id":"b","head_step_id":"branch-b"}],"join_step_id":"join"}]
        definition["deadlines"]=[{"id":"deadline.a","step_id":"branch-a","clock_source":"deadline-clock.1","due":{"kind":"ELAPSED_DURATION","value":"60","unit":"SECOND"},"boundary":"AT_OR_AFTER","expiry_target":"join"},{"id":"deadline.b","step_id":"branch-b","clock_source":"deadline-clock.1","due":{"kind":"ELAPSED_DURATION","value":"61","unit":"SECOND"},"boundary":"AT_OR_AFTER","expiry_target":None}]
        definition["limits"]["maximum_active_obligations"]="2"
        deploy_request=rebind_deployment(base,definition,"PARALLEL_FANOUT","PARALLEL_FANOUT_RUNTIME");deployed=adapter._dispatch("deploy",deploy_request)
        self.assertEqual(deployed["status"],"DEPLOYED")
        state=copy.deepcopy(deployed["state"]);source=state["active"].pop()["occurrence"]
        activation_clock={"source":"deadline-clock.1","revision":"1","status":"AVAILABLE","observed_time":"2026-09-11T02:00:00Z","evidence_digest":"sha256:"+"f"*64};state["clocks"].append(activation_clock)
        state["completed"].append({"occurrence":source,"disposition":"SUCCEEDED","evidence_digest":"sha256:"+"e"*64,"occurred_at":"2026-09-11T02:00:00Z","route_label":None,"selected_relationship_digest":digest("relationship",definition["relationships"][0]),"late":False})
        activation_event={"schema":IDENTITY+"/runtime-event","event_id":"effect.enter","kind":"EFFECT_OBSERVED","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":deployed["state_digest"],"activation_clocks":[activation_clock]}
        reasons,details,obligation_ids,constructs=lifecycle._enter_parallel({"definition":definition,"definition_digest":deploy_request["definition_digest"],"event":activation_event},state,source,next(row for row in definition["steps"] if row["id"]=="split"),[source["occurrence_id"]])
        self.assertEqual((reasons,details,len(obligation_ids),constructs),([],[],2,["parallel.1"]))
        clock={"schema":IDENTITY+"/runtime-event","event_id":"clock.stop","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":lifecycle.state_digest(state),"clock":{"source":"deadline-clock.1","revision":"2","status":"AVAILABLE","observed_time":"2026-09-11T02:01:01Z","evidence_digest":"sha256:"+"9"*64},"activation_clocks":[]}
        stopped=lifecycle._clock_step({"profile":"PARALLEL_FANOUT","role":"PARALLEL_FANOUT_RUNTIME","definition":definition,"definition_digest":deploy_request["definition_digest"],"state":state,"state_digest":lifecycle.state_digest(state),"event":clock})
        self.assertEqual((stopped["decision"]["disposition"],stopped["decision"]["reason_codes"]),("STOPPED",["EXPIRY_STOP"]))
        self.assertEqual(stopped["state"]["active"],[])
        self.assertEqual([row["status"] for row in stopped["state"]["obligations"]],["DISCHARGED","DISCHARGED"])
        self.assertTrue(all(row["disposition"]=="EXPIRED" for row in stopped["state"]["completed"] if row["occurrence"]["step_id"].startswith("branch-")))
        self.assertEqual(len(stopped["state"]["completed"]),3)

    def test_linear_deployment_constructs_restartable_initial_state(self):
        request = linear_deploy_request()
        self.assertTrue(adapter.schema_valid(request, "lifecycle.schema.json", "deployInput"))
        result = adapter._dispatch("deploy", request)
        self.assertEqual(result["status"], "DEPLOYED")
        self.assertEqual(result["state"]["revision"], "0")
        self.assertEqual(result["state"]["active"][0]["occurrence"]["step_id"], "operate")
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], request["definition"]))
        self.assertTrue(adapter.schema_valid(result, "lifecycle.schema.json", "deployResult"))

    def test_deadline_clock_routes_at_exact_at_or_after_boundary(self):
        base=linear_deploy_request();definition=copy.deepcopy(base["definition"])
        definition["profile"]="DEADLINES"
        definition["relationships"].append({"kind":"EXPIRY","from":"operate","to":"terminal","deadline_ref":"deadline.1"})
        definition["deadlines"]=[{"id":"deadline.1","step_id":"operate","due":{"kind":"ELAPSED_DURATION","value":"60","unit":"SECOND"},"clock_source":"deadline-clock.1","boundary":"AT_OR_AFTER","expiry_target":"terminal"}]
        request=rebind_deployment(base,definition,"DEADLINES","DEADLINE_RUNTIME")
        request["initial_clocks"]=[{"source":"deadline-clock.1","revision":"7","status":"AVAILABLE","observed_time":"2026-09-11T01:00:00Z","evidence_digest":"sha256:"+"3"*64}]
        deployed=adapter._dispatch("deploy",request)
        before={"schema":IDENTITY+"/runtime-event","event_id":"clock.before","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":deployed["state_digest"],"clock":{"source":"deadline-clock.1","revision":"8","status":"AVAILABLE","observed_time":"2026-09-11T01:00:59Z","evidence_digest":"sha256:"+"4"*64},"activation_clocks":[]}
        step_base={"profile":"DEADLINES","role":"DEADLINE_RUNTIME","specification_pin":PIN,"definition":definition,"definition_digest":request["definition_digest"]}
        first=adapter._dispatch("step",{**step_base,"state":deployed["state"],"state_digest":deployed["state_digest"],"event":before})
        self.assertEqual(first["decision"]["disposition"],"CLOCK_RECORDED")
        at=copy.deepcopy(before);at["event_id"]="clock.at";at["expected_state_revision"]=first["state"]["revision"];at["expected_state_digest"]=first["state_digest"];at["clock"].update({"revision":"9","observed_time":"2026-09-11T01:01:00Z","evidence_digest":"sha256:"+"5"*64})
        expired=adapter._dispatch("step",{**step_base,"state":first["state"],"state_digest":first["state_digest"],"event":at})
        self.assertEqual(expired["decision"]["disposition"],"EXPIRED")
        self.assertEqual(expired["decision"]["reason_codes"],[])
        self.assertEqual(expired["state"]["status"],"COMPLETE")
        self.assertEqual(expired["state"]["completed"][0]["disposition"],"EXPIRED")
        self.assertEqual(expired["state"]["deadlines"][0]["status"],"EXPIRED")
        self.assertEqual([row["kind"] for row in expired["decision"]["details"]],["CLOCK","DEADLINE","ROUTE"])
        later=copy.deepcopy(at);later["event_id"]="clock.later";later["expected_state_revision"]=expired["state"]["revision"];later["expected_state_digest"]=expired["state_digest"];later["clock"].update({"revision":"10","observed_time":"2026-09-11T01:02:00Z","evidence_digest":"sha256:"+"6"*64})
        restarted=adapter._dispatch("step",{**step_base,"state":json.loads(canonical(expired["state"])),"state_digest":expired["state_digest"],"event":later})
        self.assertEqual(restarted["decision"]["disposition"],"CLOCK_RECORDED")

    def test_restart_rejects_rehashed_state_with_changed_deadline_binding(self):
        base=linear_deploy_request();definition=copy.deepcopy(base["definition"]);definition["profile"]="DEADLINES"
        definition["relationships"].append({"kind":"EXPIRY","from":"operate","to":"terminal","deadline_ref":"deadline.1"})
        definition["deadlines"]=[{"id":"deadline.1","step_id":"operate","due":{"kind":"ELAPSED_DURATION","value":"60","unit":"SECOND"},"clock_source":"deadline-clock.1","boundary":"AT_OR_AFTER","expiry_target":"terminal"}]
        deploy_request=rebind_deployment(base,definition,"DEADLINES","DEADLINE_RUNTIME")
        deploy_request["initial_clocks"]=[{"source":"deadline-clock.1","revision":"1","status":"AVAILABLE","observed_time":"2026-09-11T01:00:00Z","evidence_digest":"sha256:"+"3"*64}]
        deployed=adapter._dispatch("deploy",deploy_request);state=copy.deepcopy(deployed["state"])
        state["deadlines"][0]["activation_digest"]="sha256:"+"f"*64
        changed_digest=lifecycle.state_digest(state)
        event={"schema":IDENTITY+"/runtime-event","event_id":"clock.changed","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":changed_digest,"clock":{"source":"deadline-clock.1","revision":"2","status":"AVAILABLE","observed_time":"2026-09-11T01:00:30Z","evidence_digest":"sha256:"+"4"*64},"activation_clocks":[]}
        result=adapter._dispatch("step",{"profile":"DEADLINES","role":"DEADLINE_RUNTIME","specification_pin":PIN,"definition":definition,"definition_digest":deploy_request["definition_digest"],"state":state,"state_digest":changed_digest,"event":event})
        self.assertEqual((result["status"],result["code"]),("REFUSED","STATE_INVALID"))

    def test_restart_rejects_rebound_deployment_evidence(self):
        deploy_request=linear_deploy_request();deployed=adapter._dispatch("deploy",deploy_request);state=copy.deepcopy(deployed["state"])
        state["deployment_authorization_evidence"]["authorizer_id"]="attacker.1"
        evidence_digest=digest("evidence",state["deployment_authorization_evidence"])
        state["deployment_authorization_evidence_digest"]=evidence_digest
        state["deployment_authorization"]["authorization_evidence_digest"]=evidence_digest
        state["deployment_authorization_digest"]=digest("deployment-authorization",state["deployment_authorization"])
        changed_digest=lifecycle.state_digest(state)
        event={"schema":IDENTITY+"/runtime-event","event_id":"clock.rebound","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":changed_digest,"clock":{"source":"host-clock.1","revision":"1","status":"AVAILABLE","observed_time":"2026-09-11T02:00:00Z","evidence_digest":"sha256:"+"9"*64},"activation_clocks":[]}
        result=adapter._dispatch("step",{"profile":"LINEAR","role":"LINEAR_WORK_RUNTIME","specification_pin":PIN,"definition":deploy_request["definition"],"definition_digest":deploy_request["definition_digest"],"state":state,"state_digest":changed_digest,"event":event})
        self.assertEqual((result["status"],result["code"]),("REFUSED","STATE_INVALID"))

    def test_arbitrary_first_clock_source_is_retained_and_restartable(self):
        deploy_request = linear_deploy_request()
        deployed = adapter._dispatch("deploy", deploy_request)
        event = {
            "schema": IDENTITY + "/runtime-event", "event_id": "clock-event.1", "kind": "CLOCK",
            "instance_id": "instance.1", "expected_state_revision": "0", "expected_state_digest": deployed["state_digest"],
            "clock": {"source":"host-clock.1","revision":"9","status":"AVAILABLE","observed_time":"2026-09-11T02:00:00Z","evidence_digest":"sha256:"+"3"*64},
            "activation_clocks": [],
        }
        request = {"profile":"LINEAR","role":"LINEAR_WORK_RUNTIME","specification_pin":PIN,"definition":deploy_request["definition"],"definition_digest":deploy_request["definition_digest"],"state":deployed["state"],"state_digest":deployed["state_digest"],"event":event}
        result = adapter._dispatch("step", request)
        self.assertEqual(result["decision"]["disposition"], "CLOCK_RECORDED")
        self.assertEqual(result["state"]["clocks"][0]["revision"], "9")
        self.assertTrue(lifecycle._validate_state_integrity(result["state"], deploy_request["definition"]))
        next_clock=copy.deepcopy(event);next_clock["event_id"]="clock-event.next";next_clock["clock"]["revision"]="10";next_clock["clock"]["observed_time"]="2026-09-11T02:01:00Z"
        for mutate in ("status","disposition"):
            changed=copy.deepcopy(result["state"])
            receipt=changed["receipts"][-1]
            if mutate=="status":
                receipt["details"][0]["status"]="UNAVAILABLE"
                receipt["reason_codes"]=["CLOCK_UNAVAILABLE"]
            else:
                receipt["disposition"]="EXPIRED"
            changed_digest=rehash_last_lifecycle_decision(changed)
            next_clock["expected_state_revision"]=changed["revision"];next_clock["expected_state_digest"]=changed_digest
            refused=adapter._dispatch("step",{**request,"state":changed,"state_digest":changed_digest,"event":next_clock})
            self.assertEqual((refused["status"],refused["code"]),("REFUSED","STATE_INVALID"))

    def test_authority_only_linear_propose_dispatch_effect(self):
        deploy_request = linear_deploy_request(); deployed = adapter._dispatch("deploy", deploy_request)
        clock_event = {"schema":IDENTITY+"/runtime-event","event_id":"clock-event.2","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":deployed["state_digest"],"clock":{"source":"host-clock.1","revision":"9","status":"AVAILABLE","observed_time":"2026-09-11T02:00:00Z","evidence_digest":"sha256:"+"3"*64},"activation_clocks":[]}
        base = {"profile":"LINEAR","role":"LINEAR_WORK_RUNTIME","specification_pin":PIN,"definition":deploy_request["definition"],"definition_digest":deploy_request["definition_digest"]}
        clocked = adapter._dispatch("step", {**base,"state":deployed["state"],"state_digest":deployed["state_digest"],"event":clock_event})
        occurrence = clocked["state"]["active"][0]["occurrence"]
        native = {"operation":"operate.1","interface":"service.1","fields":[{"name":"subject","value":{"type_ref":"identity","value":"subject.1"}}]}
        authority_input = schema_valid_authority_input(deploy_request["definition"], occurrence, native)
        credential_ids = sorted([row["id"] for row in authority_input["credentials"]],key=str.encode)
        observations = sorted([digest("authority-observation",row) for row in authority_input["observations"]],key=str.encode)
        executor = {"participant_id":"participant.1","role":"operator","binding_digest":digest("executor-binding",authority_input["proposal"]["executor"])}
        propose = {"schema":IDENTITY+"/runtime-event","event_id":"proposal.1","kind":"PROPOSE","instance_id":"instance.1","expected_state_revision":clocked["state"]["revision"],"expected_state_digest":clocked["state_digest"],"occurrence":copy.deepcopy(occurrence),"native_request":native,"executor":executor,"credential_ids":credential_ids,"authority_input":authority_input,"budget_inputs":[],"clock_revision":"9","observation_digests":observations}
        act_digest = digest("authority-act", authority_input["acts"][0])
        ready = {"schema":IDENTITY+"/authority-result","specification_pin":PIN,"status":"READY_FOR_RESERVATION","source_digest":"sha256:"+"4"*64,"work_class_digest":digest("authority-work-class",authority_input["work_class"]),"envelope_digest":"sha256:"+"5"*64,"proposal_digest":"sha256:"+"6"*64,"operation_digest":"sha256:"+"7"*64,"scope":{"subjects":["subject.1"],"resources":["subject.1"]},"actual_scope":{"subjects":["subject.1"],"resources":["subject.1"]},"act_digests":[act_digest],"checks":[{"purpose":"SOURCE_BINDING","subject_digest":"sha256:"+"8"*64,"requirement_ref":"obligation.1","at":"2026-09-11T02:00:00Z"}],"required_budgets":[],"evidence_digest":"sha256:"+"9"*64}
        request = {**base,"state":clocked["state"],"state_digest":clocked["state_digest"],"event":propose}
        self.assertTrue(adapter.schema_valid(request,"lifecycle.schema.json","stepInput"))
        with mock.patch.object(lifecycle.authority,"evaluate_authority",return_value=ready):
            permitted = adapter._dispatch("step",request)
        self.assertEqual(permitted["decision"]["disposition"],"PERMITTED")
        changed=copy.deepcopy(permitted["state"]);false_proposal="sha256:"+"f"*64
        proposal=next(row for row in changed["proposals"] if row["event_id"]==propose["event_id"]);proposal["proposal_digest"]=false_proposal
        changed_permit=changed["permits"][0];changed_permit["proposal_digest"]=false_proposal
        permit_body=copy.deepcopy(changed_permit);permit_body.pop("permit_id");changed_permit["permit_id"]=digest("permit",permit_body)
        proposal["permit_digest"]=changed_permit["permit_id"]
        receipt=changed["receipts"][-1];receipt["permit_digest"]=changed_permit["permit_id"]
        replay=next(row for row in changed["replays"] if row["event_id"]==propose["event_id"]);replay["permit"]=copy.deepcopy(changed_permit)
        changed_digest=rehash_last_lifecycle_decision(changed)
        refused=adapter._dispatch("step",{**base,"state":changed,"state_digest":changed_digest,"event":propose})
        self.assertEqual((refused["status"],refused["code"]),("REFUSED","STATE_INVALID"))
        permit=permitted["permit"]
        connector={"id":"connector.1","version":"version.1","binding_digest":digest("connector-binding",{"id":"connector.1","version":"version.1"})}
        attempt={"attempt_id":"attempt.1","status":"SENT","request_digest":digest("dispatch-native-request",{"instance_id":"instance.1","occurrence_id":occurrence["occurrence_id"],"interface":native["interface"],"operation":native["operation"],"fields":native["fields"]}),"attempted_at":"2026-09-11T02:00:00Z"}
        dispatch_event={"schema":IDENTITY+"/runtime-event","event_id":"dispatch.1","kind":"DISPATCH_OBSERVED","instance_id":"instance.1","expected_state_revision":permitted["state"]["revision"],"expected_state_digest":permitted["state_digest"],"permit":permit,"native_request":native,"connector":connector,"attempt":attempt,"acknowledgement":{"status":"NONE","reference":None,"observed_at":None},"clock_revision":"9"}
        dispatched=adapter._dispatch("step",{**base,"state":permitted["state"],"state_digest":permitted["state_digest"],"event":dispatch_event})
        self.assertEqual(dispatched["decision"]["disposition"],"DISPATCH_RECORDED")
        dispatch=dispatched["state"]["dispatches"][0]
        corrupted=copy.deepcopy(dispatched["state"]);changed=corrupted["dispatches"][0];changed["dispatch_attempt_digest"]="sha256:"+"f"*64;body=copy.deepcopy(changed);body.pop("dispatch_digest");changed["dispatch_digest"]=digest("dispatch",body)
        self.assertFalse(lifecycle._validate_state_integrity(corrupted,deploy_request["definition"]))
        attributed={"work_class":"class.1","instance":"instance.1","occurrence":occurrence["occurrence_id"],"step":"operate","operation":"operate.1","interface":"service.1","fields":copy.deepcopy(native["fields"])}
        evidence={"evidence_id":"effect.1","native_operation_id":"native-operation.1","provider":"provider.1","source":"source.1","record_type":"result.1","record_digest":"sha256:"+"a"*64,"evidence_ref":"effect-ref.1","attributed_request":attributed,"native_request_digest":digest("native-request",attributed),"status":"EFFECT_ESTABLISHED","actual_fields":[{"name":"status","value":{"type_ref":"status","value":"ok"}},{"name":"subject","value":{"type_ref":"identity","value":"subject.1"}}],"collections":[],"event_time":"2026-09-11T02:00:00Z","observed_at":"2026-09-11T02:00:00Z","rules_out_past_and_future_effects":False}
        effect_event={"schema":IDENTITY+"/runtime-event","event_id":"effect-event.1","kind":"EFFECT_OBSERVED","instance_id":"instance.1","expected_state_revision":dispatched["state"]["revision"],"expected_state_digest":dispatched["state_digest"],"permit":permit,"dispatch_digest":dispatch["dispatch_digest"],"native_evidence":evidence,"completion_authorization":None,"budget_inputs":[],"clock_revision":None,"activation_clocks":[]}
        completed=adapter._dispatch("step",{**base,"state":dispatched["state"],"state_digest":dispatched["state_digest"],"event":effect_event})
        self.assertEqual(completed["decision"]["disposition"],"COMPLETED")
        self.assertEqual(completed["state"]["status"],"COMPLETE")
        self.assertEqual(completed["state"]["completed"][0]["disposition"],"SUCCEEDED")
        acknowledgement_update=copy.deepcopy(dispatch_event);acknowledgement_update["event_id"]="dispatch.2";acknowledgement_update["expected_state_revision"]=completed["state"]["revision"];acknowledgement_update["expected_state_digest"]=completed["state_digest"];acknowledgement_update["acknowledgement"]={"status":"ACCEPTED","reference":"ack.1","observed_at":"2026-09-11T02:00:00Z"}
        acknowledged=adapter._dispatch("step",{**base,"state":completed["state"],"state_digest":completed["state_digest"],"event":acknowledgement_update})
        self.assertEqual(acknowledged["decision"]["disposition"],"ACKNOWLEDGED")
        self.assertEqual(acknowledged["decision"]["reason_codes"],[])
        self.assertEqual(acknowledged["state"]["status"],"COMPLETE")
        duplicate_evidence=copy.deepcopy(evidence);duplicate_evidence["evidence_id"]="effect.2";duplicate_evidence["evidence_ref"]="effect-ref.2"
        duplicate_event=copy.deepcopy(effect_event);duplicate_event["event_id"]="effect-event.2";duplicate_event["expected_state_revision"]=acknowledged["state"]["revision"];duplicate_event["expected_state_digest"]=acknowledged["state_digest"];duplicate_event["native_evidence"]=duplicate_evidence
        duplicate=adapter._dispatch("step",{**base,"state":acknowledged["state"],"state_digest":acknowledged["state_digest"],"event":duplicate_event})
        self.assertEqual(duplicate["decision"]["disposition"],"OUTCOME_RETAINED")
        duplicate_outcome=next(row for row in duplicate["state"]["outcomes"] if row["native_evidence"]["evidence_id"]=="effect.2")
        self.assertEqual(duplicate_outcome["classification"],"DUPLICATE")
        conflict_evidence=copy.deepcopy(evidence);conflict_evidence["evidence_id"]="effect.3";conflict_evidence["evidence_ref"]="effect-ref.3";conflict_evidence["record_digest"]="sha256:"+"c"*64;conflict_evidence["actual_fields"][0]["value"]["value"]="other"
        conflict_event=copy.deepcopy(effect_event);conflict_event["event_id"]="effect-event.3";conflict_event["expected_state_revision"]=duplicate["state"]["revision"];conflict_event["expected_state_digest"]=duplicate["state_digest"];conflict_event["native_evidence"]=conflict_evidence
        conflict=adapter._dispatch("step",{**base,"state":duplicate["state"],"state_digest":duplicate["state_digest"],"event":conflict_event})
        self.assertEqual(conflict["decision"]["disposition"],"DISPUTED")
        self.assertEqual(next(row for row in conflict["state"]["outcomes"] if row["native_evidence"]["evidence_id"]=="effect.3")["classification"],"CONFLICTING")
        self.assertTrue(all(row["disputed"] for row in conflict["state"]["outcomes"]))
        disputed_duplicate_evidence=copy.deepcopy(evidence);disputed_duplicate_evidence["evidence_id"]="effect.4";disputed_duplicate_evidence["evidence_ref"]="effect-ref.4"
        disputed_duplicate_event=copy.deepcopy(effect_event);disputed_duplicate_event["event_id"]="effect-event.4";disputed_duplicate_event["expected_state_revision"]=conflict["state"]["revision"];disputed_duplicate_event["expected_state_digest"]=conflict["state_digest"];disputed_duplicate_event["native_evidence"]=disputed_duplicate_evidence
        disputed_duplicate=adapter._dispatch("step",{**base,"state":conflict["state"],"state_digest":conflict["state_digest"],"event":disputed_duplicate_event})
        self.assertEqual(disputed_duplicate["decision"]["disposition"],"OUTCOME_RETAINED")
        later=next(row for row in disputed_duplicate["state"]["outcomes"] if row["native_evidence"]["evidence_id"]=="effect.3")
        self.assertIn("effect.4",later["conflicts_with_evidence_ids"])
        restart_clock={"schema":IDENTITY+"/runtime-event","event_id":"clock-event.3","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":disputed_duplicate["state"]["revision"],"expected_state_digest":disputed_duplicate["state_digest"],"clock":{"source":"host-clock.1","revision":"10","status":"AVAILABLE","observed_time":"2026-09-11T03:00:00Z","evidence_digest":"sha256:"+"b"*64},"activation_clocks":[]}
        restarted=adapter._dispatch("step",{**base,"state":json.loads(canonical(disputed_duplicate["state"])),"state_digest":disputed_duplicate["state_digest"],"event":restart_clock})
        self.assertEqual(restarted["decision"]["disposition"],"CLOCK_RECORDED")

    def test_budget_backed_proposal_commits_reservation_atomically(self):
        base=linear_deploy_request();definition=copy.deepcopy(base["definition"])
        definition["id"]="card-issuance";definition["root"]="issue"
        definition["participants"]=[{"id":"participant.1","role":"card-issuer","kind":"SYSTEM"}]
        definition["types"]=[
            {"id":"IDENTITY","kind":"IDENTITY","nonnegative":False,"unit":None},
            {"id":"STRING","kind":"STRING","nonnegative":False,"unit":None},
            {"id":"amount","kind":"DECIMAL","nonnegative":True,"unit":"USD"},
        ]
        issue=definition["steps"][0];issue.update({"id":"issue","executor_role":"card-issuer","interface":"card-system","operation":"issue-card","fields":[{"name":"amount","type_ref":"amount"},{"name":"beneficiary","type_ref":"IDENTITY"},{"name":"card_id","type_ref":"IDENTITY"}],"scope_fields":{"subjects":["beneficiary"],"resources":["card_id"]},"required_credentials":["card-issuer-credential"],"shared_budgets":["license-spend"]})
        issue["completion"].update({"effect_provider":"native-provider","effect_source":"card-ledger","effect_record_type":"card-result","no_effect_provider":"native-provider","no_effect_source":"card-no-effect","no_effect_record_type":"card-no-effect","status_type_ref":"STRING","success_values":[{"type_ref":"STRING","value":"ok"}],"evidence_bindings":[{"request_field":"amount","evidence_field":"amount"},{"request_field":"beneficiary","evidence_field":"beneficiary"},{"request_field":"card_id","evidence_field":"card_id"}]})
        definition["steps"][1]["id"]="terminal"
        definition["relationships"]=[{"kind":"SEQUENCE","from":"issue","to":"terminal"}]
        definition["occurrence_limits"]=[{"step_id":"issue","maximum":"1"}]
        definition["shared_budgets"]=["license-spend"]
        definition["source"]={"id":"access-card-policy","revision":"r1","obligations":["issue-card"]}
        deploy_request=rebind_deployment(base,definition,"LINEAR","LINEAR_WORK_RUNTIME")
        authorization=deploy_request["deployment_authorization"];authorization["authorized_at"]="2026-09-09T00:00:00Z";authorization["expires_at"]="2026-10-01T00:00:00Z"
        deploy_request["authorization_clock"]["observed_time"]="2026-09-10T04:30:00Z"
        deploy_request["authorization_evidence"].update({"recorded_at":"2026-09-09T00:00:00Z","expires_at":"2026-10-01T00:00:00Z"})
        subject=copy.deepcopy(authorization);subject.pop("authorization_evidence_digest")
        deploy_request["authorization_evidence"]["subject_digest"]=digest("deployment-authorization-subject",subject)
        authorization["authorization_evidence_digest"]=digest("evidence",deploy_request["authorization_evidence"])
        deployed=adapter._dispatch("deploy",deploy_request)
        self.assertEqual(deployed.get("status"),"DEPLOYED",deployed)
        clock_event={"schema":IDENTITY+"/runtime-event","event_id":"clock.budget","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":deployed["state_digest"],"clock":{"source":"authority-clock","revision":"1","status":"AVAILABLE","observed_time":"2026-09-10T04:30:00Z","evidence_digest":"sha256:"+"6"*64},"activation_clocks":[]}
        lifecycle_base={"profile":"LINEAR","role":"LINEAR_WORK_RUNTIME","specification_pin":PIN,"definition":definition,"definition_digest":deploy_request["definition_digest"]}
        clocked=adapter._dispatch("step",{**lifecycle_base,"state":deployed["state"],"state_digest":deployed["state_digest"],"event":clock_event})
        occurrence=clocked["state"]["active"][0]["occurrence"]
        native={"operation":"issue-card","interface":"card-system","fields":[{"name":"amount","value":{"type_ref":"amount","value":"150"}},{"name":"beneficiary","value":{"type_ref":"IDENTITY","value":"employee-7"}},{"name":"card_id","value":{"type_ref":"IDENTITY","value":"card-802"}}]}
        authority_input=schema_valid_authority_input(definition,occurrence,native)
        authority_input["envelope"]["source_digest"]=digest("authority-source",authority_input["source"])
        authority_input["envelope"]["work_class_digest"]=digest("authority-work-class",authority_input["work_class"])
        authority_input["envelope"]["limits"]["shared_budgets"]=["license-spend"]
        authority_input["proposal"]["work_class_digest"]=digest("authority-work-class",authority_input["work_class"])
        authority_input["proposal"]["executor"].update({"actor":"participant.1","role":"card-issuer","principal":"access-card-owner","occupancy":"occ-card-machine"})
        authority_input["clock"]={"source":"authority-clock","status":"AVAILABLE","instant":"2026-09-10T04:30:00Z"}
        registry,registered,contention,registration_material=draft2_registry_registration(authority_input)
        self.assertEqual(registered["status"],"TRANSITION",registered)
        self.assertEqual(registered["receipt"]["decision"],"REGISTERED")
        registry_state=registry.export_state();registry_digest=digest("reservation-registry",contention["configuration"])
        reservation_event={"id":digest("lifecycle-reservation-event",{"instance_id":"instance.1","lifecycle_event_id":"proposal.budget","lifecycle_event_kind":"PROPOSE","reservation_event_kind":"RESERVE","registry_digest":registry_digest}),"expected_revision":registry_state["core"]["revision"],"kind":"RESERVE","clock":copy.deepcopy(contention["clock"]),"payload":{"authority":copy.deepcopy(authority_input),"histories":[copy.deepcopy(contention["history"])]},"administration":None}
        history=reservation_event["payload"]["histories"][0];history["budget_digest"]=registered["state"]["core"]["budgets"][0]["definition_digest"]
        registry_request={"schema":IDENTITY+"/reservation-input","specification_pin":PIN,"state":registry_state,"state_digest":reservation_v2._state_digest(registry_state),"event":reservation_event,"host_evidence":{"registry_digest":registry_digest,"selection_evidence":"selected-license-registry","administration_bases":[],"authenticated_records":[{"kind":"HISTORY","record_digest":digest("budget-history",history),"provider":history["provider"],"source":history["source"]}]}}
        self.assertTrue(adapter.schema_valid(authority_input,"authority.schema.json","input"),"authority input")
        self.assertTrue(adapter.schema_valid(registry_request,"reservation.schema.json","input"),"registry request")
        proposal={"schema":IDENTITY+"/runtime-event","event_id":"proposal.budget","kind":"PROPOSE","instance_id":"instance.1","expected_state_revision":clocked["state"]["revision"],"expected_state_digest":clocked["state_digest"],"occurrence":occurrence,"native_request":native,"executor":{"participant_id":"participant.1","role":"card-issuer","binding_digest":digest("executor-binding",authority_input["proposal"]["executor"])},"credential_ids":[row["id"] for row in authority_input["credentials"]],"observation_digests":sorted([digest("authority-observation",row) for row in authority_input["observations"]],key=str.encode),"authority_input":authority_input,"clock_revision":"1","budget_inputs":[{"registry_digest":registry_digest,"expected_revision":registry_state["core"]["revision"],"affected_anchors":["license-spend"],"request":registry_request}]}
        step_request={**lifecycle_base,"state":clocked["state"],"state_digest":clocked["state_digest"],"event":proposal}
        self.assertTrue(adapter.schema_valid(step_request,"lifecycle.schema.json","stepInput"))
        ready={"schema":IDENTITY+"/authority-result","specification_pin":PIN,"status":"READY_FOR_RESERVATION","source_digest":digest("authority-source",authority_input["source"]),"work_class_digest":digest("authority-work-class",authority_input["work_class"]),"envelope_digest":digest("authority-envelope",authority_input["envelope"]),"proposal_digest":digest("authority-proposal",authority_input["proposal"]),"operation_digest":"sha256:"+"7"*64,"scope":{"subjects":["employee-7"],"resources":["card-802"]},"actual_scope":{"subjects":["employee-7"],"resources":["card-802"]},"act_digests":[digest("authority-act",authority_input["acts"][0])],"checks":[{"purpose":"SOURCE_BINDING","subject_digest":"sha256:"+"8"*64,"requirement_ref":"issue-card","at":"2026-09-10T04:30:00Z"}],"required_budgets":["license-spend"],"evidence_digest":"sha256:"+"9"*64}
        with mock.patch.object(lifecycle.authority,"evaluate_authority",return_value=ready),mock.patch.object(reservation_v2,"_evaluate_authority",return_value=ready):
            permitted=adapter._dispatch("step",step_request)
        self.assertEqual(permitted.get("status"),"STEP",permitted)
        self.assertEqual(permitted["decision"]["disposition"],"PERMITTED")
        self.assertEqual(permitted["budget_results"][0]["result"]["receipt"]["decision"],"RESERVED")
        self.assertEqual(permitted["permit"]["budget_revisions"][0]["affected_anchors"],["license-spend"])
        self.assertEqual(permitted["state"]["total_actuations"],"1")
        permit=permitted["permit"];connector={"id":"card-connector","version":"v1","binding_digest":digest("connector-binding",{"id":"card-connector","version":"v1"})}
        attempt={"attempt_id":"card-attempt","status":"SENT","request_digest":digest("dispatch-native-request",{"instance_id":"instance.1","occurrence_id":occurrence["occurrence_id"],"interface":native["interface"],"operation":native["operation"],"fields":native["fields"]}),"attempted_at":"2026-09-10T04:30:00Z"}
        dispatch_event={"schema":IDENTITY+"/runtime-event","event_id":"dispatch.budget","kind":"DISPATCH_OBSERVED","instance_id":"instance.1","expected_state_revision":permitted["state"]["revision"],"expected_state_digest":permitted["state_digest"],"permit":permit,"native_request":native,"connector":connector,"attempt":attempt,"acknowledgement":{"status":"NONE","reference":None,"observed_at":None},"clock_revision":"1"}
        dispatched=adapter._dispatch("step",{**lifecycle_base,"state":permitted["state"],"state_digest":permitted["state_digest"],"event":dispatch_event});self.assertEqual(dispatched["decision"]["disposition"],"DISPATCH_RECORDED")
        dispatch=dispatched["state"]["dispatches"][0]
        clock_event={"schema":IDENTITY+"/runtime-event","event_id":"clock.budget.effect","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":dispatched["state"]["revision"],"expected_state_digest":dispatched["state_digest"],"clock":{"source":"authority-clock","revision":"2","status":"AVAILABLE","observed_time":"2026-09-10T04:31:00Z","evidence_digest":"sha256:"+"a"*64},"activation_clocks":[]}
        clocked_effect=adapter._dispatch("step",{**lifecycle_base,"state":dispatched["state"],"state_digest":dispatched["state_digest"],"event":clock_event});self.assertEqual(clocked_effect["decision"]["disposition"],"CLOCK_RECORDED")
        attributed={"work_class":"card-issuance","instance":"instance.1","occurrence":occurrence["occurrence_id"],"step":"issue","operation":"issue-card","interface":"card-system","fields":copy.deepcopy(native["fields"])}
        actual=[{"name":"amount","value":{"type_ref":"amount","value":"150"}},{"name":"beneficiary","value":{"type_ref":"IDENTITY","value":"employee-7"}},{"name":"card_id","value":{"type_ref":"IDENTITY","value":"card-802"}},{"name":"status","value":{"type_ref":"STRING","value":"ok"}}]
        evidence={"evidence_id":"effect.budget","native_operation_id":"native.card.1","provider":"native-provider","source":"card-ledger","record_type":"card-result","record_digest":"sha256:"+"b"*64,"evidence_ref":"effect-budget-ref","attributed_request":attributed,"native_request_digest":digest("native-request",attributed),"status":"EFFECT_ESTABLISHED","actual_fields":actual,"collections":[],"event_time":"2026-09-10T04:31:00Z","observed_at":"2026-09-10T04:31:00Z","rules_out_past_and_future_effects":False}
        reserved_state=permitted["budget_results"][0]["result"]["state"];reservation_id=permit["budget_revisions"][0]["reservation_id"]
        settled_history=copy.deepcopy(contention["history"]);settled_history["budget_digest"]=registered["state"]["core"]["budgets"][0]["definition_digest"];settled_history["revision"]="2";settled_history["as_of"]="2026-09-10T04:31:00Z"
        settled_history["journal"].append({"sequence":"2","event":{"id":digest("reservation-committed-event",{"budget_digest":settled_history["budget_digest"],"effect_id":"native.card.1","mapping":"pay"}),"state":"ACTIVE","occurred_at":"2026-09-10T04:31:00Z","fields":[{"name":"amount","value":{"type_ref":"amount","value":"150"}},{"name":"beneficiary","value":{"type_ref":"beneficiary","value":"employee-7"}}]}})
        reservation_native={"id":evidence["evidence_id"],"provider":evidence["provider"],"source":evidence["source"],"reservation":reservation_id,"outcome":"EFFECT","request":attributed,"effect_id":evidence["native_operation_id"],"occurred_at":evidence["event_time"],"rules_out_past_and_future_effects":False,"evidence_ref":evidence["evidence_ref"],"observed_request":attributed,"actual_fields":actual,"collections":[],"completion_mismatch":False,"mismatch_reason":None}
        registry_event={"id":digest("lifecycle-reservation-event",{"instance_id":"instance.1","lifecycle_event_id":"effect.budget","lifecycle_event_kind":"EFFECT_OBSERVED","reservation_event_kind":"SETTLE","registry_digest":registry_digest}),"expected_revision":reserved_state["core"]["revision"],"kind":"SETTLE","clock":{"source":"authority-clock","status":"AVAILABLE","instant":"2026-09-10T04:31:00Z"},"payload":{"native":reservation_native,"histories":[settled_history]},"administration":None}
        registry_effect_request={"schema":IDENTITY+"/reservation-input","specification_pin":PIN,"state":reserved_state,"state_digest":reservation_v2._state_digest(reserved_state),"event":registry_event,"host_evidence":{"registry_digest":registry_digest,"selection_evidence":"selected-license-registry","administration_bases":[],"authenticated_records":[{"kind":"HISTORY","record_digest":digest("budget-history",settled_history),"provider":settled_history["provider"],"source":settled_history["source"]},{"kind":"NATIVE_OUTCOME","record_digest":digest("reservation-native-outcome",reservation_native),"provider":reservation_native["provider"],"source":reservation_native["source"]}]}}
        effect_event={"schema":IDENTITY+"/runtime-event","event_id":"effect.budget","kind":"EFFECT_OBSERVED","instance_id":"instance.1","expected_state_revision":clocked_effect["state"]["revision"],"expected_state_digest":clocked_effect["state_digest"],"permit":permit,"dispatch_digest":dispatch["dispatch_digest"],"native_evidence":evidence,"completion_authorization":None,"budget_inputs":[{"registry_digest":registry_digest,"expected_revision":reserved_state["core"]["revision"],"affected_anchors":["license-spend"],"request":registry_effect_request}],"clock_revision":"2","activation_clocks":[]}
        with mock.patch.object(reservation_v2,"_evaluate_authority",return_value=ready):
            settled=adapter._dispatch("step",{**lifecycle_base,"state":clocked_effect["state"],"state_digest":clocked_effect["state_digest"],"event":effect_event})
        self.assertEqual(settled.get("status"),"STEP",settled);self.assertEqual(settled["budget_results"][0]["result"]["receipt"]["decision"],"SETTLED");self.assertEqual(settled["state"]["status"],"COMPLETE")

        no_effect=copy.deepcopy(evidence);no_effect.update({"evidence_id":"no-effect.budget","provider":"native-provider","source":"card-no-effect","record_type":"card-no-effect","record_digest":"sha256:"+"c"*64,"evidence_ref":"no-effect-budget-ref","status":"NO_EFFECT_ESTABLISHED","actual_fields":[],"collections":[],"event_time":None,"rules_out_past_and_future_effects":True})
        completion_subject={"specification_pin":PIN,"work_class_digest":deploy_request["definition_digest"],"instance_id":"instance.1","occurrence_id":occurrence["occurrence_id"],"permit_id":permit["permit_id"],"dispatch_digest":dispatch["dispatch_digest"],"native_evidence_digest":digest("native-evidence",no_effect)}
        completion_authorization={"schema":IDENTITY+"/evidence-record","evidence_id":"completion-authorization.1","kind":"ORGANIZATIONAL_AUTHORIZATION","status":"ACCEPTED","subject_digest":digest("no-effect-completion",completion_subject),"organization_id":"organization.1","authorizer_id":"release-authorizer.1","authorization_scope":sorted([PIN,deploy_request["definition_digest"],"instance.1",occurrence["occurrence_id"],permit["permit_id"],dispatch["dispatch_digest"],digest("native-evidence",no_effect)],key=str.encode),"recorded_at":"2026-09-10T04:30:00Z","expires_at":"2026-09-10T05:00:00Z","provenance_digest":"sha256:"+"d"*64}
        release_native={"id":no_effect["evidence_id"],"provider":no_effect["provider"],"source":no_effect["source"],"reservation":reservation_id,"outcome":"NO_EFFECT","request":attributed,"effect_id":None,"occurred_at":None,"rules_out_past_and_future_effects":True,"evidence_ref":no_effect["evidence_ref"],"observed_request":None,"actual_fields":[],"collections":[],"completion_mismatch":False,"mismatch_reason":None}
        release_event={"id":digest("lifecycle-reservation-event",{"instance_id":"instance.1","lifecycle_event_id":"no-effect.budget","lifecycle_event_kind":"EFFECT_OBSERVED","reservation_event_kind":"RELEASE","registry_digest":registry_digest}),"expected_revision":reserved_state["core"]["revision"],"kind":"RELEASE","clock":{"source":"authority-clock","status":"AVAILABLE","instant":"2026-09-10T04:31:00Z"},"payload":{"native":release_native},"administration":None}
        original_admin=registration_material["registration"]["event"]["administration"]
        release_act=copy.deepcopy(original_admin["act"]);release_act.update({"id":"admin-act-release","kind":"RELEASE","occurred_at":"2026-09-10T04:31:00Z","subject_digest":digest("reservation-administration-subject",reservation_v2._admin_subject(release_event,contention["configuration"]))})
        release_return=copy.deepcopy(original_admin["returned"]);release_return.update({"id":"admin-return-release","act_digest":digest("reservation-administration-act",release_act),"act_bytes_base64":base64.b64encode(reservation_v2.canon(release_act)).decode("ascii"),"returned_at":"2026-09-10T04:31:00Z"})
        release_event["administration"]={"act":release_act,"returned":release_return}
        release_bases=copy.deepcopy(registration_material["administration_bases"]);next(row for row in release_bases if row["id"]==release_act["basis"])["at"]="2026-09-10T04:31:00Z"
        release_request={"schema":IDENTITY+"/reservation-input","specification_pin":PIN,"state":reserved_state,"state_digest":reservation_v2._state_digest(reserved_state),"event":release_event,"host_evidence":{"registry_digest":registry_digest,"selection_evidence":"selected-license-registry","administration_bases":release_bases,"authenticated_records":[{"kind":"ADMIN_RETURN","record_digest":digest("reservation-administration-return",release_return),"provider":contention["configuration"]["administration_provider"],"source":contention["configuration"]["administration_source"]},{"kind":"NATIVE_OUTCOME","record_digest":digest("reservation-native-outcome",release_native),"provider":release_native["provider"],"source":release_native["source"]}]}}
        no_effect_event={"schema":IDENTITY+"/runtime-event","event_id":"no-effect.budget","kind":"EFFECT_OBSERVED","instance_id":"instance.1","expected_state_revision":clocked_effect["state"]["revision"],"expected_state_digest":clocked_effect["state_digest"],"permit":permit,"dispatch_digest":dispatch["dispatch_digest"],"native_evidence":no_effect,"completion_authorization":completion_authorization,"budget_inputs":[{"registry_digest":registry_digest,"expected_revision":reserved_state["core"]["revision"],"affected_anchors":["license-spend"],"request":release_request}],"clock_revision":"2","activation_clocks":[]}
        with mock.patch.object(reservation_v2,"_evaluate_authority",return_value=ready):
            released=adapter._dispatch("step",{**lifecycle_base,"state":clocked_effect["state"],"state_digest":clocked_effect["state_digest"],"event":no_effect_event})
        self.assertEqual(released.get("status"),"STEP",released);self.assertEqual(released["budget_results"][0]["result"]["receipt"]["decision"],"RELEASED");self.assertEqual(released["decision"]["disposition"],"STOPPED")

    def test_consumer_exposes_eight_operations(self):
        consumer = Consumer()
        self.assertEqual(tuple(sorted(adapter.ALL_OPERATIONS)), adapter.ALL_OPERATIONS)
        self.assertEqual(consumer.capabilities()["operations"], list(adapter.IMPLEMENTED_OPERATIONS))
        self.assertEqual(consumer.deploy({})["code"], "SCHEMA_INVALID")

    def test_capabilities_and_envelope(self):
        response = adapter.handle(envelope("capabilities", {}))
        self.assertEqual(response["request_id"], "request.1")
        self.assertEqual(response["result"]["specification_pin"], PIN)
        self.assertEqual(response["result"]["operations"], list(adapter.ALL_OPERATIONS))
        self.assertEqual(response["result"]["roles"], ["AGGREGATE_EVALUATOR","AUTHORITY_EVALUATOR","CHOICE_LOOP_RUNTIME","DEADLINE_RUNTIME","LINEAR_WORK_RUNTIME","PARALLEL_FANOUT_RUNTIME","REFERENCE_SINGLE_PROCESS_CONTENTION","REVIEW_EVIDENCE","SHARED_BUDGET_TRANSITIONS"])
        self.assertEqual(response["result"]["roles"], sorted(response["result"]["roles"], key=str.encode))

    def test_protocol_error_echoes_valid_identifiers(self):
        response = adapter.handle({"protocol": "wrong", "request_id": "request.2", "operation": "future", "input": {}})
        self.assertEqual(response["request_id"], "request.2")
        self.assertEqual(response["operation"], "future")
        self.assertEqual(response["result"]["code"], "PROTOCOL_INVALID")

    def test_number_is_transport_failure(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "adapter.py")],
            input=b'{"input":{"number":1},"operation":"capabilities","protocol":"' + PROTOCOL.encode() + b'","request_id":"r"}\n',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(process.stdout, b"")

    def test_unterminated_line_is_transport_failure(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "adapter.py")],
            input=canonical(envelope("capabilities", {})),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(process.stdout, b"")

    def test_lone_surrogate_is_transport_failure(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "adapter.py")],
            input=b'{"input":{"text":"\\ud800"},"operation":"capabilities","protocol":"' + PROTOCOL.encode() + b'","request_id":"r"}\n',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(process.stdout, b"")

    def test_boundary_validate_and_readback(self):
        artifact = {
            "schema": IDENTITY + "/boundary-record",
            "id": "boundary.clock",
            "candidate_identity": IDENTITY,
            "specification_pin": PIN,
            "paragraph_ids": ["WCS2-010"],
            "requirement_ids": ["PROT-001"],
            "external_fact_or_capability": "Clock truth",
            "responsible_party": {"kind": "CLOCK_PROVIDER", "party_id": "clock-provider"},
            "required_control_or_integration": "Authenticated clock record",
            "evidence_format": "Closed clock record",
            "failure_behavior": "Refuse or hold",
            "deployment_verification": "Exercise unavailable and stale records",
            "establishes": "Clock record binding",
            "does_not_establish": "External clock truth",
            "residual_limitation": "Provider assurance remains external",
        }
        encoded = base64.b64encode(canonical(artifact)).decode("ascii")
        value = {"kind": "BOUNDARY_RECORD", "specification_pin": PIN, "artifact_bytes_base64": encoded}
        accepted = adapter.handle(envelope("validate", value))["result"]
        readback = adapter.handle(envelope("readback", value))["result"]
        self.assertEqual(accepted, {"status": "ACCEPTED", "digest": digest("boundary", artifact)})
        self.assertEqual(readback["digest"], accepted["digest"])
        self.assertIn({"path": "/responsible_party/kind", "value": '"CLOCK_PROVIDER"'}, readback["lines"])

    def test_artifact_number_and_duplicate_classification(self):
        for raw, code in ((b'{"x":1}', "ARTIFACT_NONCANONICAL"), (b'{"x":"a","x":"b"}', "ARTIFACT_ENCODING_INVALID")):
            value = {
                "kind": "BOUNDARY_RECORD",
                "specification_pin": PIN,
                "artifact_bytes_base64": base64.b64encode(raw).decode("ascii"),
            }
            self.assertEqual(adapter.handle(envelope("validate", value))["result"]["code"], code)

    def test_basic_evidence(self):
        subject_digest = "sha256:" + "1" * 64
        record = {
            "schema": IDENTITY + "/evidence-record",
            "evidence_id": "evidence.1",
            "kind": "SOURCE_CONFIRMATION",
            "status": "ACCEPTED",
            "subject_digest": subject_digest,
            "actor_id": "actor.1",
            "scope_ids": ["scope.a", "scope.b"],
            "recorded_at": "2026-01-01T00:00:00Z",
            "provenance_digest": "sha256:" + "2" * 64,
        }
        request = {
            "profile": "LINEAR",
            "role": "REVIEW_EVIDENCE",
            "specification_pin": PIN,
            "subject": {
                "kind": "SOURCE",
                "subject_id": "source.1",
                "subject_digest": subject_digest,
                "candidate_identity": IDENTITY,
                "specification_pin": PIN,
            },
            "evidence": record,
        }
        result = adapter.handle(envelope("check-evidence", request))["result"]
        self.assertEqual(result["status"], "EVIDENCE_VALID")
        self.assertEqual(result["evidence_digest"], digest("evidence", record))
        invalid = copy.deepcopy(request)
        invalid["evidence"]["recorded_at"] = "2026-02-30T00:00:00Z"
        self.assertEqual(adapter.handle(envelope("check-evidence", invalid))["result"]["code"], "SCHEMA_INVALID")

    def test_per_action_count_aggregate(self):
        definition = {
            "schema": IDENTITY + "/aggregate-definition",
            "types": [
                {"id": "count", "kind": "INTEGER", "unit": None, "nonnegative": True},
                {"id": "region", "kind": "IDENTITY", "unit": None, "nonnegative": False},
            ],
            "aggregate": {
                "id": "count-by-region",
                "reducer": "COUNT",
                "result_type": "count",
                "element_type": None,
                "key_types": ["region"],
                "mappings": [{"id": "mapping.1", "step_ids": ["send"], "qualifier": {"kind": "BOOLEAN", "value": True}, "key_fields": ["region"], "contribution": {"kind": "COUNT"}}],
                "time": {"clock_source": "clock", "precision": "SECOND"},
                "window": {"kind": "PER_ACTION"},
                "committed_source": None,
                "pending_policy": "EXCLUDE_RESERVED",
                "operator": "LTE",
                "bound": {"type_ref": "count", "value": "1"},
            },
        }
        request = {
            "schema": IDENTITY + "/aggregate-input",
            "specification_pin": PIN,
            "definition": definition,
            "definition_digest": digest("aggregate-definition", definition),
            "operations": [{"occurrence": "occurrence.1", "step": "send", "fields": [{"name": "region", "value": {"type_ref": "region", "value": "north"}}]}],
            "pending": [],
            "clock": {"source": "clock", "status": "AVAILABLE", "instant": "2026-01-01T00:00:00Z"},
            "observations": [],
        }
        result = aggregate(request)
        self.assertEqual(result["status"], "SATISFIED")
        self.assertEqual(result["partitions"][0]["result"], "1")
        invalid = copy.deepcopy(request)
        invalid["definition"]["aggregate"]["pending_policy"] = "INCLUDE_ALL_RESERVED"
        invalid["definition_digest"] = digest("aggregate-definition", invalid["definition"])
        self.assertEqual(aggregate(invalid)["code"], "INPUT_INVALID")

    def test_reservation_host_initial_state_and_restart(self):
        configuration = {
            "schema": IDENTITY + "/reservation-registry",
            "id": "registry.1",
            "principal": "principal.1",
            "clock_source": "clock.1",
            "administration_provider": "provider.1",
            "administration_source": "source.1",
            "administration_role": "administrator",
            "slots": [{"anchor": "budget.1", "exposure_domain": "domain.1"}],
        }
        host = ReservationHost(configuration)
        state = host.export_state()
        self.assertEqual(state["specification_pin"],PIN)
        self.assertEqual(state["core"]["revision"], "0")
        self.assertEqual(state["receipts"], [])
        replacement = json.loads(canonical(state))
        host.restart(replacement)
        self.assertEqual(host.export_state(), state)

    def test_rolling_sum_with_committed_history(self):
        definition = {
            "schema": IDENTITY + "/aggregate-definition",
            "types": [
                {"id": "amount", "kind": "DECIMAL", "unit": "USD", "nonnegative": True},
                {"id": "region", "kind": "IDENTITY", "unit": None, "nonnegative": False},
            ],
            "aggregate": {
                "id": "spend-by-region",
                "reducer": "SUM",
                "result_type": "amount",
                "element_type": None,
                "key_types": ["region"],
                "mappings": [{"id": "mapping.1", "step_ids": ["pay"], "qualifier": {"kind": "BOOLEAN", "value": True}, "key_fields": ["region"], "contribution": {"kind": "SUM", "field": "amount"}}],
                "time": {"clock_source": "clock", "precision": "SECOND"},
                "window": {"kind": "ROLLING", "duration_seconds": "86400", "start_inclusive": False, "end_inclusive": True},
                "committed_source": {"provider": "ledger", "source": "payments", "freshness": {"kind": "MAX_AGE", "seconds": "60"}, "key_fields": ["region"], "qualifier": {"kind": "BOOLEAN", "value": True}, "contribution": {"kind": "SUM", "field": "amount"}},
                "pending_policy": "INCLUDE_ALL_RESERVED",
                "operator": "LTE",
                "bound": {"type_ref": "amount", "value": "1000"},
            },
        }
        definition_digest = digest("aggregate-definition", definition)
        key = [{"type_ref": "region", "value": "north"}]
        interval = {"start": "2025-12-31T00:00:00Z", "end": "2026-01-01T00:00:00Z", "start_inclusive": False, "end_inclusive": True}
        query_digest = digest("aggregate-query", {"definition_digest": definition_digest, "interval": interval, "keys": [key]})
        request = {
            "schema": IDENTITY + "/aggregate-input",
            "specification_pin": PIN,
            "definition": definition,
            "definition_digest": definition_digest,
            "operations": [{"occurrence": "occurrence.1", "step": "pay", "fields": [{"name": "amount", "value": {"type_ref": "amount", "value": "150"}}, {"name": "region", "value": key[0]}]}],
            "pending": [],
            "clock": {"source": "clock", "status": "AVAILABLE", "instant": "2026-01-01T00:00:00Z"},
            "observations": [{"provider": "ledger", "source": "payments", "request_digest": query_digest, "status": "AVAILABLE", "revision": "revision.1", "as_of": "2026-01-01T00:00:00Z", "coverage": interval, "kind": "EVENT_SNAPSHOT", "events": [{"id": "payment.1", "state": "ACTIVE", "occurred_at": "2025-12-31T23:00:00Z", "fields": [{"name": "amount", "value": {"type_ref": "amount", "value": "800"}}, {"name": "region", "value": key[0]}]}], "evidence_ref": "evidence.1"}],
        }
        result = aggregate(request)
        self.assertEqual(result["status"], "SATISFIED")
        self.assertEqual(result["partitions"][0]["result"], "950")

    def test_reservation_native_relationships(self):
        request = {
            "work_class": "class.1",
            "instance": "instance.1",
            "occurrence": "occurrence.1",
            "step": "step.1",
            "operation": "operation.1",
            "interface": "interface.1",
            "fields": [],
        }
        native = {
            "id": "evidence.1",
            "provider": "provider.1",
            "source": "source.1",
            "reservation": "reservation.1",
            "outcome": "UNKNOWN",
            "request": request,
            "effect_id": None,
            "occurred_at": None,
            "rules_out_past_and_future_effects": False,
            "evidence_ref": "evidence-ref.1",
            "observed_request": None,
            "actual_fields": [],
            "collections": [],
            "completion_mismatch": False,
            "mismatch_reason": None,
        }
        reservation_v2._validate_native(native)
        invalid = copy.deepcopy(native)
        invalid["actual_fields"] = [{"name": "amount", "value": {"type_ref": "amount", "value": "1"}}]
        with self.assertRaises(reservation_v2._AdmissionError) as raised:
            reservation_v2._validate_native(invalid)
        self.assertEqual(raised.exception.code, "INPUT_INVALID")
        mismatch = copy.deepcopy(native)
        mismatch["completion_mismatch"] = True
        mismatch["mismatch_reason"] = "NATIVE_REQUEST_MISMATCH"
        reservation_v2._validate_native(mismatch)

    def test_single_process_host_install_and_commit_are_atomic(self):
        old_state = {"instance_id": "instance.1", "value": "old"}
        new_state = {"instance_id": "instance.1", "value": "new"}
        old_digest = digest("work-state", old_state)
        new_digest = digest("work-state", new_state)
        transaction_digest = digest("lifecycle-transaction", {"event": "event.1"})

        class FakeConsumer:
            def deploy(self, request):
                state = old_state if request["definition_digest"].endswith("0") else new_state
                return {
                    "status": "DEPLOYED",
                    "state": copy.deepcopy(state),
                    "state_digest": digest("work-state", state),
                }

            def step(self, request):
                return {
                    "status": "STEP",
                    "state": copy.deepcopy(new_state),
                    "state_digest": new_digest,
                    "transaction_digest": transaction_digest,
                    "budget_results": [],
                    "replay": False,
                }

        host = SingleProcessReferenceHost(FakeConsumer())
        deploy_request = {
            "instance_id": "instance.1",
            "definition_digest": "sha256:" + "0" * 64,
            "deployment_authorization": {"organization_id": "organization.1"},
        }
        installed = host.install(deploy_request)
        self.assertEqual(installed["disposition"], "INSTALLED")
        self.assertFalse(installed["replay"])
        self.assertTrue(host.install(copy.deepcopy(deploy_request))["replay"])

        occupied_request = copy.deepcopy(deploy_request)
        occupied_request["definition_digest"] = "sha256:" + "1" * 64
        occupied = host.install(occupied_request)
        self.assertEqual(occupied["disposition"], "INSTANCE_OCCUPIED")
        self.assertEqual(occupied["authoritative_state_digest"], old_digest)

        step_request = {
            "profile": "LINEAR",
            "role": "LINEAR_WORK_RUNTIME",
            "state": copy.deepcopy(old_state),
            "state_digest": old_digest,
            "event": {"event_id": "event.1"},
        }
        failed = host.submit("organization.1", step_request, "failure.1")
        self.assertEqual(failed["host_commit"]["disposition"], "COMMIT_FAILED")
        self.assertEqual(host.snapshot("organization.1", "instance.1")["state_digest"], old_digest)

        committed = host.submit("organization.1", step_request)
        self.assertEqual(committed["host_commit"]["disposition"], "COMMITTED")
        self.assertEqual(host.snapshot("organization.1", "instance.1")["state_digest"], new_digest)

    def test_single_process_host_serializes_competing_lifecycle_events(self):
        deploy_request=linear_deploy_request();host=SingleProcessReferenceHost(Consumer())
        uninstalled=SingleProcessReferenceHost(Consumer())
        with self.assertRaisesRegex(ValueError,"instance is not installed"):
            uninstalled.submit("organization.1",{"state":{"instance_id":"instance.1"}})
        installed=host.install(deploy_request);self.assertEqual(installed["disposition"],"INSTALLED")
        snapshot=host.snapshot("organization.1","instance.1")
        base={"profile":"LINEAR","role":"LINEAR_WORK_RUNTIME","specification_pin":PIN,"definition":deploy_request["definition"],"definition_digest":deploy_request["definition_digest"],"state":snapshot["state"],"state_digest":snapshot["state_digest"]}
        barrier=threading.Barrier(3);results=[];lock=threading.Lock()
        def submit(index):
            event={"schema":IDENTITY+"/runtime-event","event_id":f"clock.concurrent.{index}","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":snapshot["state_digest"],"clock":{"source":"host-clock.1","revision":str(index),"status":"AVAILABLE","observed_time":f"2026-09-11T02:00:0{index}Z","evidence_digest":"sha256:"+str(index)*64},"activation_clocks":[]}
            barrier.wait();result=host.submit("organization.1",{**base,"event":event})
            with lock: results.append((event,result))
        threads=[threading.Thread(target=submit,args=(index,)) for index in (1,2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join()
        self.assertEqual(sum(result.get("host_commit",{}).get("disposition")=="COMMITTED" for _,result in results),1)
        self.assertEqual(sum(result.get("code")=="REVISION_CONFLICT" for _,result in results),1)
        current=host.snapshot("organization.1","instance.1")
        self.assertEqual(current["state"]["revision"],"1")
        winning_event=next(event for event,result in results if result.get("host_commit",{}).get("disposition")=="COMMITTED")
        replay=host.submit("organization.1",{**base,"state":current["state"],"state_digest":current["state_digest"],"event":winning_event})
        self.assertTrue(replay["transition"]["replay"])
        self.assertIsNone(replay["host_commit"])
        self.assertEqual(host.snapshot("organization.1","instance.1"),current)

    def test_single_process_host_commits_work_and_budget_roots_together(self):
        configuration={"schema":IDENTITY+"/reservation-registry","id":"registry.1","principal":"principal.1","clock_source":"clock.1","administration_provider":"provider.1","administration_source":"source.1","administration_role":"administrator","slots":[{"anchor":"budget.1","exposure_domain":"domain.1"}]}
        budget_state=ReservationHost(configuration).export_state();registry_digest=digest("reservation-registry",configuration)
        next_budget=copy.deepcopy(budget_state);next_budget["core"]["revision"]="1"
        lifecycle_deploy=linear_deploy_request();deployed=adapter._dispatch("deploy",lifecycle_deploy)
        clock={"schema":IDENTITY+"/runtime-event","event_id":"clock.host-budget","kind":"CLOCK","instance_id":"instance.1","expected_state_revision":"0","expected_state_digest":deployed["state_digest"],"clock":{"source":"host-clock.1","revision":"1","status":"AVAILABLE","observed_time":"2026-09-11T02:00:00Z","evidence_digest":"sha256:"+"7"*64},"activation_clocks":[]}
        transition=adapter._dispatch("step",{"profile":"LINEAR","role":"LINEAR_WORK_RUNTIME","specification_pin":PIN,"definition":lifecycle_deploy["definition"],"definition_digest":lifecycle_deploy["definition_digest"],"state":deployed["state"],"state_digest":deployed["state_digest"],"event":clock})
        class FakeConsumer:
            def deploy(self,request): return copy.deepcopy(deployed)
            def step(self,request):
                result=copy.deepcopy(transition)
                result["budget_results"]=[{"registry_digest":registry_digest,"affected_anchors":["budget.1"],"result":{"state":copy.deepcopy(next_budget)}}]
                if request["state_digest"]==transition["state_digest"]:
                    result["replay"]=True
                    result["state"]=copy.deepcopy(request["state"])
                    result["state_digest"]=request["state_digest"]
                return result
        host=SingleProcessReferenceHost(FakeConsumer())
        budget_roots=[{"registry_digest":registry_digest,"affected_anchors":["budget.1"],"state":budget_state,"state_digest":reservation_v2._state_digest(budget_state)}]
        installed=host.install(lifecycle_deploy,budget_roots);self.assertEqual(installed["disposition"],"INSTALLED")
        self.assertTrue(host.install(copy.deepcopy(lifecycle_deploy),copy.deepcopy(budget_roots))["replay"])
        self.assertEqual(host.install(copy.deepcopy(lifecycle_deploy),[])["disposition"],"INSTANCE_OCCUPIED")
        changed_roots=copy.deepcopy(budget_roots);changed_roots[0]["affected_anchors"]=[]
        self.assertEqual(host.install(copy.deepcopy(lifecycle_deploy),changed_roots)["disposition"],"INSTANCE_OCCUPIED")
        cross_pin=copy.deepcopy(budget_roots);cross_pin[0]["state"]["specification_pin"]="sha256:"+"f"*64;cross_pin[0]["state_digest"]=reservation_v2._state_digest(cross_pin[0]["state"])
        with self.assertRaises(ValueError): host.install(copy.deepcopy(lifecycle_deploy),cross_pin)
        snapshot=host.snapshot("organization.1","instance.1");base={"profile":"LINEAR","role":"LINEAR_WORK_RUNTIME","state":snapshot["state"],"state_digest":snapshot["state_digest"]}
        barrier=threading.Barrier(3);results=[];lock=threading.Lock()
        def submit(index):
            budget_input={"registry_digest":registry_digest,"affected_anchors":["budget.1"],"request":{"state":copy.deepcopy(budget_state),"state_digest":reservation_v2._state_digest(budget_state)}}
            event={"event_id":f"budget.concurrent.{index}","budget_inputs":[budget_input]}
            barrier.wait();result=host.submit("organization.1",{**base,"event":event})
            with lock: results.append((event,result))
        threads=[threading.Thread(target=submit,args=(index,)) for index in (1,2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join()
        self.assertEqual(sum(result.get("host_commit",{}).get("disposition")=="COMMITTED" for _,result in results),1)
        self.assertEqual(sum(result.get("code")=="REVISION_CONFLICT" for _,result in results),1)
        exported=host.snapshot("organization.1","instance.1")
        self.assertEqual(exported["state"],transition["state"]);self.assertEqual(exported["budget_states"][0]["state"],next_budget)
        original_event=next(event for event,result in results if result.get("host_commit",{}).get("disposition")=="COMMITTED")
        repeated={**base,"state":exported["state"],"state_digest":exported["state_digest"],"event":original_event}
        replayed=host.submit("organization.1",repeated)
        self.assertTrue(replayed["transition"]["replay"])
        self.assertIsNone(replayed["host_commit"])
        self.assertEqual(host.snapshot("organization.1","instance.1"),exported)


if __name__ == "__main__":
    unittest.main()
