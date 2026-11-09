"""Closed exact-content assessment bodies and human-context bindings."""
from __future__ import annotations

from holdings_schema_extensions import BASE, DIGEST, ID, INSTANT, arr, nullable, obj, ref


TEXT = {"type": "string", "minLength": 1, "maxLength": 8192}
FIELD = {"$ref": BASE + "aggregate.schema.json#/$defs/field"}


def extend_assessment_schemas(authority, evidence):
    evidence["$defs"]["refusal"]["properties"]["code"]["enum"].append("UNSUPPORTED_RELATION")
    a = authority["$defs"]
    a["assessmentCitation"] = {"oneOf": [
        obj({"kind": {"const": "PROPOSAL_FIELD"}, "field": ID}),
        obj({"kind": {"const": "CONTEXT_FIELD"}, "requirement_id": ID, "field": ID}),
    ]}
    a["assessmentEvaluator"] = obj({"provider": ID, "model": ID, "version": ID})
    a["assessmentRubric"] = obj({"id": ID, "revision": ID,
        "obligations": arr(obj({"id": ID, "text": TEXT}), 32, 1),
        "criteria": arr(obj({"id": ID, "obligation_ids": arr(ID, 32, 1),
            "citation_policy": {"enum": ["CONTEXT", "PROPOSAL", "ANY"]}}), 32, 1)})
    hash_source = obj({"requirement_id": ID, "digest_field": ID})
    a["assessmentRequirement"] = obj({"id": ID, "step": ID,
        "review_decision_requirement_id": ID, "rubric": ref("assessmentRubric"),
        "evaluator": ref("assessmentEvaluator"), "sources": obj({
            "content": ID, "context": arr(ID, 64),
            "context_selection": hash_source, "rubric": hash_source,
            "evaluator": obj({"requirement_id": ID, "provider_field": ID,
                "model_field": ID, "version_field": ID}),
            "assessment": hash_source,
            "selection": obj({"requirement_id": ID, "identity_field": ID, "digest_field": ID}),
            "effectiveness": obj({"requirement_id": ID, "identity_field": ID, "effective_field": ID}),
            "blockers": arr(ID, 64),
        })})
    a["assessmentSnapshot"] = obj({"requirement_id": ID, "provider_record_id": ID,
        "provider_revision": ID, "fields": arr(FIELD, 64)})
    a["contentAssessment"] = obj({"provider": ID, "source": ID, "record_type": ID,
        "id": ID, "revision": ID, "subject_digest": DIGEST, "context_digest": DIGEST,
        "rubric_digest": DIGEST, "evaluator": ref("assessmentEvaluator"), "assessed_at": INSTANT,
        "criteria": arr(obj({"id": ID, "verdict": {"enum": ["PASS", "FAIL", "UNCERTAIN"]},
            "explanation": TEXT, "escalation": obj({"required": {"type": "boolean"}, "reason": nullable(TEXT)}),
            "citations": arr(ref("assessmentCitation"), 32, 1)}), 32, 1)})
    a["assessmentReview"] = obj({"id": ID, "assessment_digest": DIGEST,
        "decision": {"enum": ["APPROVE", "REJECT"]},
        "criteria": arr(obj({"id": ID, "disposition": {"enum": ["SATISFIED", "NOT_SATISFIED", "UNRESOLVED"]},
            "reason": nullable(TEXT), "citations": arr(ref("assessmentCitation"), 32)}), 32, 1)})
    a["assessmentBasis"] = obj({"requirement_id": ID,
        "supporting_context": arr(ref("assessmentSnapshot"), 64),
        "assessment": ref("contentAssessment"), "review": ref("assessmentReview")})
    a["envelope"]["properties"]["assessment_requirements"] = arr(ref("assessmentRequirement"), 1)
    a["input"]["properties"]["assessment_bases"] = arr(ref("assessmentBasis"), 1)
    binding = a["humanDecisionRequirement"]["properties"]["context_bindings"]["items"]["properties"]["value"]["oneOf"]
    binding.append(obj({"kind": {"const": "ASSESSMENT"}, "requirement_id": ID,
        "member": {"enum": ["SUBJECT_DIGEST", "ASSESSMENT_DIGEST", "REVIEW_DIGEST", "REVIEW_IDENTITY"]},
        "type_ref": ID}))
    for name in ("check", "failedCheck"):
        a[name]["properties"]["purpose"]["enum"].append("ASSESSMENT")
    for name, prop in (("refusal", "reasons"), ("failedCheck", "reason")):
        target = a[name]["properties"][prop]
        if prop == "reasons":
            target = target["items"]
        target["enum"].extend(["ASSESSMENT_NOT_SATISFIED", "ASSESSMENT_DEPENDENCY_CHANGED"])
