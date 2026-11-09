#!/usr/bin/env python3
"""Construct independent generated completion cases without a consumer."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import runpy
from pathlib import Path

from corpus_common import CASES, CONFORMANCE, ROOT, candidate_pin, canonical_bytes, digest, exact_case, write_canonical_json
from equipment_completion_fixture import completion_authority_mutator, completion_definition_mutator, completion_native, terminal_effect_result
from equipment_dispatch_fixture import authorization_event, authorization_result, retained
from fixture_factory import deployment, typed
from lifecycle_factory import base_lifecycle, dispatch_event, dispatch_result, governed_effect_event, permitted_proposal, step_input

HERE = Path(__file__).resolve().parent
GROUP = CASES / "generated-completion"
SPECIMEN = CONFORMANCE / "specimens/generated-completion"
SOURCE = HERE / "fixtures/generic-generated-completion-revision1-source.md"
GENERATION_ROOT = Path(os.environ.get("WORK_CLASS_GENERATION_ROOT", str(ROOT / "runs/2026-10-08-overnight"))).resolve()
RUN = GENERATION_ROOT / "flow-source/bank-review"
GENERATED = [{"name":"processing_timestamp","type_ref":"INSTANT"},{"name":"provider_reference","type_ref":"IDENTITY"},{"name":"warning_error_inventory","type_ref":"STRING"}]


def constructor(*, generated=GENERATED):
    def mutate_authority(supplied, original):
        completion_authority_mutator(supplied, original)
        supplied["source"] = {"schema":supplied["source"]["schema"],"id":"generic-generated-completion-source","revision":"revision-1","obligations":[{"id":"EXACT-PROVIDER-GENERATED","text":SOURCE.read_text()}]}
        supplied["envelope"]["source_obligations"]=["EXACT-PROVIDER-GENERATED"]
        step=next(row for row in supplied["work_class"]["steps"] if row["id"]==supplied["proposal"]["step"])
        if generated is not None:step["completion"]["generated_fields"]=copy.deepcopy(generated)
    def mutate_definition(definition):
        completion_definition_mutator(definition)
        for step in definition["steps"]:
            if step["kind"]=="OPERATION" and generated is not None:step["completion"]["generated_fields"]=copy.deepcopy(generated)
    base=base_lifecycle(authority_mutator=mutate_authority,definition_mutator=mutate_definition,instance_id="generic-generated-instance")
    for check in base["authority_result"]["checks"]:
        if check["purpose"]=="SOURCE_BINDING":check["requirement_ref"]=base["authority_input"]["source"]["id"]
    base["authority_result"]["checks"].sort(key=canonical_bytes)
    return base


def native(base, prior):
    value=completion_native(base,prior)
    value["actual_fields"] += [{"name":"processing_timestamp","value":typed("INSTANT","2026-09-10T04:30:00Z")},{"name":"provider_reference","value":typed("IDENTITY","provider-generated-reference-01")},{"name":"warning_error_inventory","value":typed("STRING",canonical_bytes([{"code":"SYNTHETIC-WARNING-1","detail":"Declared unresolved item."}]).decode())}]
    value["actual_fields"].sort(key=lambda row:row["name"])
    value["record_digest"]=digest("provider-native-record",{key:value[key] for key in ("provider","source","record_type","provider_record_id","provider_revision","native_operation_id","actual_fields","collections","event_time","status")})
    return value


def public(value):
    value=copy.deepcopy(value)
    if value.get("status")=="STEP" and value["decision"]["event_kind"]!="PROPOSE":value["permit"]=None
    return value


def validation(definition):
    return {"kind":"WORK_CLASS","specification_pin":candidate_pin(),"artifact_bytes_base64":base64.b64encode(canonical_bytes(definition)).decode()}


def main():
    rows=[];labels={}
    def emit(operation,supplied,expected,label,text,refs=("LIFE-009","LIFE-010","LIFE-007")):
        case_id=f"C3-GEN-{len(rows)+1:03}";row=exact_case(case_id,operation,supplied,expected,list(refs),text+" Independent judgment from the separate generic source and frozen generated-field rules; no consumer output was consulted.")
        rows.append(row);labels[label]=case_id;return row
    base=constructor();permit=permitted_proposal(base);auth_event=authorization_event(base,permit);auth=retained(authorization_result(base,permit,auth_event),permit["permit"])
    send=dispatch_event(base,auth,event_id="generated-dispatch",authorization_digest=auth["state"]["authorizations"][0]["authorization_digest"])
    dispatched=retained(dispatch_result(auth,send,disposition="DISPATCH_RECORDED",reasons=[],occurrence_status="DISPATCHED"),permit["permit"])
    emit("deploy",base["deploy_input"],base["deploy_result"],"deploy","The complete selected definition declares three generated fields and their nominal types.")
    emit("step",step_input(base,base["deploy_result"]["state"],base["clock_event"]),public(base["clock_result"]),"clock","The source retains its attributable current clock.")
    emit("step",step_input(base,base["clock_result"]["state"],base["proposal_event"]),public(permit),"permit","The permit retains complete original generated completion declarations and exact authority projection.")
    emit("step",step_input(base,permit["state"],auth_event),public(auth),"authorization","Fresh authorization preserves the generated completion contract.")
    emit("step",step_input(base,auth["state"],send),public(dispatched),"dispatch","One attempted transmission establishes no generated result or accepted effect.")
    evidence=native(base,dispatched);event=governed_effect_event(dispatched,dispatched,evidence,event_id="generated-match")
    success=terminal_effect_result(base,dispatched,event,classification="MATCHED",disposition="COMPLETED",reason_codes=[],occurrence_status=None,disputed=False,complete_disposition="SUCCEEDED",route=True)
    emit("step",step_input(base,dispatched["state"],event),public(success),"complete","Exact provider-generated reference, processing time and warning inventory are required and retained without a preknown equality target.")
    variants=[("missing",lambda x:x["actual_fields"].__setitem__(slice(None),[r for r in x["actual_fields"] if r["name"]!="provider_reference"])),("wrong-nominal",lambda x:next(r for r in x["actual_fields"] if r["name"]=="provider_reference")["value"].update(type_ref="STRING")),("bad-scalar",lambda x:next(r for r in x["actual_fields"] if r["name"]=="processing_timestamp")["value"].update(value="2026-02-30T04:30:00Z")),("duplicate",lambda x:x["actual_fields"].append(copy.deepcopy(next(r for r in x["actual_fields"] if r["name"]=="provider_reference")))),("extra",lambda x:x["actual_fields"].append({"name":"undeclared_generated","value":typed("STRING","extra")}))]
    for label,mutate in variants:
        value=copy.deepcopy(evidence);mutate(value);value["actual_fields"].sort(key=lambda row:row["name"]);value["record_digest"]=digest("synthetic-provider-fault",{"kind":label})
        event=governed_effect_event(dispatched,dispatched,value,event_id="generated-"+label)
        expected=terminal_effect_result(base,dispatched,event,classification="UNEXPECTED",disposition="DISPUTED",reason_codes=["UNEXPECTED_EFFECT"],occurrence_status="BLOCKED_DISPUTE",disputed=True)
        emit("step",step_input(base,dispatched["state"],event),public(expected),label,"The "+label+" generated-field fault retains complete supplied evidence, blocks dispute, stops the instance and creates no matching effect or retry.")
    value=copy.deepcopy(evidence);next(r for r in value["actual_fields"] if r["name"]=="provider_reference")["value"]["value"]="another-valid-generated-reference"
    next(r for r in value["actual_fields"] if r["name"]=="warning_error_inventory")["value"]["value"]="[]";value["record_digest"]=digest("independent-provider-result",value)
    event=governed_effect_event(dispatched,dispatched,value,event_id="generated-another-value")
    expected=terminal_effect_result(base,dispatched,event,classification="MATCHED",disposition="COMPLETED",reason_codes=[],occurrence_status=None,disputed=False,complete_disposition="SUCCEEDED",route=True)
    emit("step",step_input(base,dispatched["state"],event),public(expected),"variable-values","From the same pre-completion controlled state, a different valid generated value can match. This is an alternative trace, not a changed fact after established effect.")
    empty=constructor(generated=[]);empty_permit=permitted_proposal(empty)
    emit("deploy",empty["deploy_input"],empty["deploy_result"],"empty-deploy","Explicit generated_fields:[] remains present in definition and projection.")
    emit("step",step_input(empty,empty["clock_result"]["state"],empty["proposal_event"]),public(empty_permit),"empty-permit","The complete original authority basis in the permit retains explicit empty generated_fields.")
    omitted=constructor(generated=None)
    emit("deploy",omitted["deploy_input"],omitted["deploy_result"],"omitted-deploy","Omitted generated_fields is preserved, retaining inherited behavior.")
    for label,generated,code in [("collision",[{"name":"card_id","type_ref":"IDENTITY"}],"DEFINITION_INVALID"),("unknown-type",[{"name":"new_result","type_ref":"NO_SUCH_TYPE"}],"REFERENCE_INVALID"),("inventory-limit",[{"name":f"field_{i:02}","type_ref":"STRING"} for i in range(56)],"LIMIT_EXCEEDED")]:
        definition=copy.deepcopy(base["definition"]);step=next(s for s in definition["steps"] if s["kind"]=="OPERATION");step["completion"]["generated_fields"]=generated
        emit("validate",validation(definition),{"status":"REFUSED","code":code,"path":""},label,"The "+label+" declaration refuses before deployment; no field may be dropped or guessed.")
    legacy=copy.deepcopy(base["definition"]);carrier=next(s for s in legacy["steps"] if s["kind"]=="OPERATION")["completion"];carrier["terminal_policy"]="LEGACY_NONTERMINAL"
    for key in ["provider_record_identity","event_time_identity","additional_fields","lookup"]:carrier.pop(key)
    emit("validate",validation(legacy),{"status":"REFUSED","code":"SCHEMA_INVALID","path":""},"legacy-generated","The legacy closed completion carrier has no generated_fields member.")
    pb=runpy.run_path(str(HERE/"build-prior-binding-static-cases.py"));definition=pb["definition"]();source=next(s for s in definition["steps"] if s["id"]=="confirm-destination");target=next(s for s in definition["steps"] if s["id"]=="pay-invoice")
    source["completion"].update(terminal_policy="STOP_RETAIN",provider_record_identity={"field":"provider_event","type_ref":"identity"},event_time_identity={"field":"event_time","type_ref":"instant"},additional_fields=[],generated_fields=[{"name":"generated-destination","type_ref":"identity"}],lookup={"provider":"payment-provider","source":"payment-system","record_type":"operation-result","namespace":"synthetic-generated","key_projection":[{"field":"supplier-id","type_ref":"identity"}]})
    definition["types"].append({"id":"instant","kind":"INSTANT","nonnegative":False,"unit":None});definition["types"].sort(key=lambda r:r["id"]);target["prior_effect_bindings"][0]["source_evidence_field"]="generated-destination"
    definition["source"]={"id":"generic-generated-completion-source","revision":"revision-1","obligations":["EXACT-PROVIDER-GENERATED"]}
    supplied,expected=deployment(definition,instance_id="generic-generated-prior",authorization_time="2026-09-10T04:00:00Z",evidence_expires_at="2026-09-12T00:00:00Z")
    emit("deploy",supplied,expected,"generated-prior-static","A STOP_RETAIN generated source field is a legal exact prior-effect source coordinate with the matching target nominal type; ancestor eligibility is still required at proposal.")
    wrong=copy.deepcopy(definition);next(s for s in wrong["steps"] if s["id"]=="confirm-destination")["completion"]["generated_fields"][0]["type_ref"]="status"
    emit("validate",validation(wrong),{"status":"REFUSED","code":"DEFINITION_INVALID","path":""},"generated-prior-type","A generated source coordinate with another nominal type cannot bind the target request.")
    malformed=copy.deepcopy(base["deploy_input"])
    malformed["definition"]["source"]["revision"]="1"
    emit("deploy",malformed,{"status":"REFUSED","code":"SCHEMA_INVALID","path":""},"malformed-source-revision-deploy","A definition source revision violating the initial-letter identifier grammar fails closed schema admission before any runtime state exists. The generic admission refusal contains no selected lifecycle state, profile or role.")
    for row in rows:write_canonical_json(GROUP/(row["id"]+".json"),row)
    SPECIMEN.mkdir(parents=True,exist_ok=True);(SPECIMEN/SOURCE.name).write_bytes(SOURCE.read_bytes())
    write_canonical_json(SPECIMEN/"definition.json",base["definition"]);write_canonical_json(SPECIMEN/"complete-native-evidence.json",evidence)
    freeze={"candidate_pin":candidate_pin(),"status":"INDEPENDENT_EXPECTATIONS_BEFORE_RUNTIME_COMPARISON","source_raw_sha256":"sha256:"+hashlib.sha256(SOURCE.read_bytes()).hexdigest(),"builder_raw_sha256":"sha256:"+hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"cases":[{"id":r["id"],"raw_sha256":"sha256:"+hashlib.sha256((GROUP/(r["id"]+".json")).read_bytes()).hexdigest()} for r in rows],"labels":labels,"limits":["Prior-field probe establishes static selection only; full exact ancestor runtime cases remain independently declared source expectations.","No real ACK/provider authentication or business adequacy is proved."]}
    path=RUN/"GENERATED-CASE-FREEZE-03.json"
    if not path.exists():write_canonical_json(path,freeze)
    print(json.dumps({"cases":len(rows),"candidate_pin":candidate_pin(),"labels":labels},indent=2))

if __name__=="__main__":main()
