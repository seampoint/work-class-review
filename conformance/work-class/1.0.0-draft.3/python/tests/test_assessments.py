from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from implementation import assessments, authority, common, dispatch_gate, human_decisions, lifecycle, source_corrections, source_observations
from implementation.common import Refusal


AT = "2026-10-08T12:00:00Z"
PREFIX = "seampoint.work-class/1.0.0-draft.3/"


def encoded(value):
    # These test vectors use ASCII keys; JSON key sorting equals the contract order.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def hashed(kind, value):
    return "sha256:" + hashlib.sha256((PREFIX + kind + "\n").encode() + encoded(value)).hexdigest()


def typed(value, ref="TEXT"):
    return {"type_ref": ref, "value": value}


def field(name, value, ref="TEXT"):
    return {"name": name, "value": typed(value, ref)}


def computed(request):
    declaration, basis = request["envelope"]["assessment_requirements"][0], request["assessment_bases"][0]
    sources = {row["id"]: row for row in request["envelope"]["source_observation_requirements"]}
    records = [{"requirement_id": row["requirement_id"],
        **{key: sources[row["requirement_id"]][key] for key in ("provider", "source", "record_type")},
        **{key: row[key] for key in ("provider_record_id", "provider_revision", "fields")}} for row in basis["supporting_context"]]
    context_digest = hashed("content-assessment-context", {"types": request["work_class"]["types"], "records": records})
    rubric_digest = hashed("content-assessment-rubric", declaration["rubric"])
    subject = {key: request["proposal"][key] for key in ("work_class_digest", "instance", "occurrence", "step", "interface", "operation", "fields")}
    subject.update(principal=request["proposal"]["executor"]["principal"], context_digest=context_digest,
                   rubric_digest=rubric_digest, evaluator=declaration["evaluator"])
    return {"context_digest": context_digest, "rubric_digest": rubric_digest,
        "SUBJECT_DIGEST": hashed("content-assessment-subject", subject),
        "ASSESSMENT_DIGEST": hashed("content-assessment", basis["assessment"]),
        "REVIEW_DIGEST": hashed("content-assessment-review", basis["review"]),
        "REVIEW_IDENTITY": encoded({"provider": "provider", "source": "source", "record_type": "approval", "provider_record_id": basis["review"]["id"]}).decode()}


def profile():
    """Construct helper inputs under admitted ordinary authority/source premises."""
    types = [{"id": name, "kind": kind, "unit": None, "nonnegative": False}
             for name, kind in (("BOOLEAN", "BOOLEAN"), ("INSTANT", "INSTANT"), ("TEXT", "STRING"))]
    roles = {"content": "content", "context": ["context"], "blockers": [],
        "context_selection": {"requirement_id": "context-selection", "digest_field": "digest"},
        "rubric": {"requirement_id": "rubric", "digest_field": "digest"},
        "evaluator": {"requirement_id": "evaluator", "provider_field": "provider", "model_field": "model", "version_field": "version"},
        "assessment": {"requirement_id": "assessment", "digest_field": "digest"},
        "selection": {"requirement_id": "selection", "identity_field": "identity", "digest_field": "digest"},
        "effectiveness": {"requirement_id": "effectiveness", "identity_field": "identity", "effective_field": "effective"}}
    declaration = {"id": "assess-message", "step": "send", "review_decision_requirement_id": "human-review",
        "rubric": {"id": "message-rubric", "revision": "revision-1", "obligations": [{"id": "accurate", "text": "Use supported facts."}],
            "criteria": [{"id": "supported", "obligation_ids": ["accurate"], "citation_policy": "CONTEXT"}]},
        "evaluator": {"provider": "model-provider", "model": "model", "version": "version-1"}, "sources": roles}
    native = [{"name": "body", "type_ref": "TEXT"}, {"name": "recipient", "type_ref": "TEXT"}]
    inventories = {"content": copy.deepcopy(native), "context": [{"name": "claim", "type_ref": "TEXT"}],
        "evaluator": [{"name": name, "type_ref": "TEXT"} for name in ("model", "provider", "version")],
        "effectiveness": [{"name": "effective", "type_ref": "BOOLEAN"}, {"name": "identity", "type_ref": "TEXT"}],
        "selection": [{"name": "digest", "type_ref": "TEXT"}, {"name": "identity", "type_ref": "TEXT"}],
        "approval": [{"name": "identity", "type_ref": "TEXT"}]}
    for name in ("assessment", "context-selection", "rubric"):
        inventories[name] = [{"name": "digest", "type_ref": "TEXT"}]
    sources = []
    for name in sorted(inventories):
        relations = []
        if name == "content":
            relations = [{"id": item["name"], "kind": "EQUALS", "left": {"kind": "OBSERVATION_FIELD", "requirement_id": name, "field": item["name"]},
                "right": {"kind": "PROPOSAL_FIELD", "field": item["name"]}} for item in native]
        elif name in {"assessment", "selection"}:
            relations = [{"id": "digest-binding", "kind": "EQUALS", "left": {"kind": "OBSERVATION_FIELD", "requirement_id": name, "field": "digest"},
                "right": {"kind": "DECISION_FIELD", "requirement_id": "human-review", "field": "assessment_digest"}}]
        sources.append({"id": name, "step": "send", "at": "CLOCK", "provider": "provider", "source": "source", "record_type": name,
            "subject": {"kind": "PROPOSAL_FIELD", "field": "recipient"}, "record_id": None if name == "approval" else name + "-record",
            "purpose": "AUTHORITY", "freshness_seconds": "0", "expected_status": "AVAILABLE", "fields": inventories[name],
            "relations": relations, "evaluation_point": "PROPOSE_AND_DISPATCH"})
    bindings = [{"field": member.lower(), "value": {"kind": "ASSESSMENT", "requirement_id": declaration["id"], "member": member, "type_ref": "TEXT"}}
                for member in sorted(assessments.MEMBERS)]
    human = {"id": "human-review", "step": "send", "record_requirement_id": "approval", "context_bindings": bindings,
        "identity_field": "review_identity", "distinct_from": []}
    request = {"source": {"obligations": copy.deepcopy(declaration["rubric"]["obligations"])},
        "work_class": {"types": types, "steps": [{"id": "send", "fields": native,
            "dispatch_gate": {"kind": "SOURCE_REQUIREMENTS", "requirements": sorted(inventories), "validity_requirements": []}}]},
        "envelope": {"operations": [{"step": "send"}], "gate": {"kind": "DECIDE", "decision_requirement": "human-review"},
            "assessment_requirements": [declaration], "decision_requirements": [human], "source_observation_requirements": sources},
        "proposal": {"step": "send", "instance": "case", "occurrence": "send-1", "work_class_digest": "sha256:" + "1" * 64,
            "interface": "mail", "operation": "send", "executor": {"principal": "bank"},
            "fields": [field("body", "Approved fact: caf\u00e9."), field("recipient", "recipient")]},
        "clock": {"instant": AT}, "assessment_bases": [{"requirement_id": declaration["id"],
            "supporting_context": [{"requirement_id": "context", "provider_record_id": "context-record", "provider_revision": "revision-1", "fields": [field("claim", "Approved fact: caf\u00e9.")]}],
            "assessment": {"provider": "provider", "source": "source", "record_type": "assessment", "id": "assessment-record", "revision": "revision-1",
                "subject_digest": "", "context_digest": "", "rubric_digest": "", "evaluator": declaration["evaluator"], "assessed_at": AT,
                "criteria": [{"id": "supported", "verdict": "PASS", "explanation": "The message cites the supplied fact.",
                    "escalation": {"required": False, "reason": None}, "citations": [{"kind": "CONTEXT_FIELD", "requirement_id": "context", "field": "claim"}]}]},
            "review": {"id": "review-record", "assessment_digest": "", "decision": "APPROVE", "criteria": [{"id": "supported", "disposition": "SATISFIED", "reason": None, "citations": []}]}}]}
    seal(request)
    return request


def seal(request):
    basis = request["assessment_bases"][0]
    values = computed(request)
    basis["assessment"].update(subject_digest=values["SUBJECT_DIGEST"], context_digest=values["context_digest"], rubric_digest=values["rubric_digest"])
    basis["review"]["assessment_digest"] = computed(request)["ASSESSMENT_DIGEST"]


def current_rows(request):
    basis, values = request["assessment_bases"][0], computed(request)
    identity = encoded({"provider": "provider", "source": "source", "record_type": "assessment", "provider_record_id": "assessment-record"}).decode()
    contents = {"content": request["proposal"]["fields"], "context": basis["supporting_context"][0]["fields"],
        "context-selection": [field("digest", values["context_digest"])], "rubric": [field("digest", values["rubric_digest"])],
        "assessment": [field("digest", values["ASSESSMENT_DIGEST"])],
        "evaluator": [field(key, value) for key, value in sorted(request["envelope"]["assessment_requirements"][0]["evaluator"].items())],
        "selection": [field("digest", values["ASSESSMENT_DIGEST"]), field("identity", identity)],
        "effectiveness": [field("effective", True, "BOOLEAN"), field("identity", identity)]}
    return {name: {"provider_record_id": name + "-record", "revision": "revision-1", "fields": copy.deepcopy(fields)} for name, fields in contents.items()}


class AssessmentTests(unittest.TestCase):
    def test_independent_frozen_digest_known_answers(self):
        path = ROOT.parent / "specimens/factual-customer-message-review/digest-known-answers.json"
        answers = json.loads(path.read_bytes())
        self.assertEqual(answers["candidate_pin"], common.PIN)
        self.assertEqual(len(answers["vectors"]), 30)
        self.assertEqual({row["domain"] for row in answers["vectors"]}, {
            "content-assessment-context", "content-assessment-rubric", "content-assessment-subject", "content-assessment", "content-assessment-review"})
        for row in answers["vectors"]:
            body = row["body"]
            reordered = dict(reversed(list(body.items())))
            for consumer in (authority, common):
                with self.subTest(vector=row["id"], consumer=consumer.__name__):
                    self.assertEqual(consumer.canonical(body), bytes.fromhex(row["canonical_utf8_hex"]))
                    self.assertEqual(consumer.digest(row["domain"], body), row["expected_digest"])
                    self.assertEqual(consumer.canonical(reordered), bytes.fromhex(row["canonical_utf8_hex"]))
                    self.assertEqual(consumer.digest(row["domain"], reordered), row["expected_digest"])

    def test_complete_digest_domains_and_exact_text(self):
        request = profile()
        declaration, basis = request["envelope"]["assessment_requirements"][0], request["assessment_bases"][0]
        self.assertEqual(assessments.values(request, declaration, basis), computed(request))
        before = computed(request)
        request["proposal"]["fields"][0]["value"]["value"] = "Approved fact: cafe\u0301."
        self.assertNotEqual(assessments.values(request, declaration, basis)["SUBJECT_DIGEST"], before["SUBJECT_DIGEST"])
        self.assertEqual(assessments.phase_three(request), "BINDING_MISMATCH")

    def test_subject_binds_recipient_occurrence_context_revision_and_evaluator(self):
        original = profile()
        before = computed(original)["SUBJECT_DIGEST"]
        for mutate in (lambda row: row["proposal"]["fields"][1]["value"].update(value="other-recipient"),
                       lambda row: row["proposal"].update(occurrence="send-2"),
                       lambda row: row["assessment_bases"][0]["supporting_context"][0].update(provider_revision="revision-2"),
                       lambda row: row["envelope"]["assessment_requirements"][0]["evaluator"].update(version="version-2")):
            changed = copy.deepcopy(original)
            mutate(changed)
            self.assertNotEqual(computed(changed)["SUBJECT_DIGEST"], before)

    def test_static_role_partition_and_complete_native_inventory(self):
        request = profile()
        self.assertEqual(assessments.declaration_errors(request["work_class"], request["envelope"], request["source"]), set())
        request["envelope"]["assessment_requirements"][0]["sources"]["blockers"] = ["content"]
        self.assertIn("UNSUPPORTED_RELATION", assessments.declaration_errors(request["work_class"], request["envelope"], request["source"]))
        request = profile()
        next(row for row in request["envelope"]["source_observation_requirements"] if row["id"] == "content")["fields"].pop()
        self.assertIn("REFERENCE_INVALID", assessments.declaration_errors(request["work_class"], request["envelope"], request["source"]))

    def test_rubric_text_and_coverage_have_distinct_admission_codes(self):
        request = profile()
        rubric = request["envelope"]["assessment_requirements"][0]["rubric"]
        rubric["obligations"][0]["text"] = "Changed obligation."
        self.assertIn("DEPENDENCY_MISMATCH", assessments.phase_two(request))
        rubric["criteria"][0]["obligation_ids"] = ["unknown"]
        self.assertIn("REFERENCE_INVALID", assessments.phase_two(request))

    def test_unknown_derived_target_defers_only_null_record_exception(self):
        request = profile()
        human = request["envelope"]["decision_requirements"][0]
        del request["envelope"]["assessment_requirements"]
        errors = human_decisions.declaration_errors(request["work_class"], request["envelope"])
        self.assertEqual(errors, {"REFERENCE_INVALID"})
        human["context_bindings"] = []
        self.assertIn("UNSUPPORTED_RELATION", human_decisions.declaration_errors(request["work_class"], request["envelope"]))

    def test_selection_map_fields_must_differ(self):
        request = profile()
        request["envelope"]["assessment_requirements"][0]["sources"]["selection"]["identity_field"] = "digest"
        self.assertIn("UNSUPPORTED_RELATION", assessments.phase_two(request))

    def test_unknown_review_human_defers_computed_sibling_comparison(self):
        request = profile()
        request["envelope"]["assessment_requirements"][0]["review_decision_requirement_id"] = "missing-review-human"
        self.assertNotIn("UNSUPPORTED_RELATION", human_decisions.declaration_errors(request["work_class"], request["envelope"]))
        self.assertEqual(assessments.phase_two(request), {"REFERENCE_INVALID"})
        sibling = copy.deepcopy(request["envelope"]["decision_requirements"][0])
        sibling["id"] = "missing-review-human"
        request["envelope"]["decision_requirements"].append(sibling)
        self.assertIn("UNSUPPORTED_RELATION", human_decisions.declaration_errors(request["work_class"], request["envelope"]))

    def test_raw_calendar_escalation_and_snapshot_nominal_admission(self):
        request = profile()
        request["assessment_bases"][0]["assessment"]["assessed_at"] = "2026-02-30T00:00:00Z"
        self.assertIn("INPUT_INVALID", assessments.phase_one(request))
        request = profile()
        request["assessment_bases"][0]["assessment"]["criteria"][0]["escalation"]["reason"] = "Requires review."
        self.assertIn("INPUT_INVALID", assessments.phase_one(request))
        request = profile()
        request["assessment_bases"][0]["supporting_context"][0]["fields"][0]["value"] = typed(True, "BOOLEAN")
        self.assertIn("TYPE_INVALID", assessments.phase_one(request))
        request["assessment_bases"][0]["supporting_context"][0]["fields"][0]["value"] = typed("value", "UNKNOWN")
        self.assertNotIn("TYPE_INVALID", assessments.phase_one(request))
        self.assertIn("REFERENCE_INVALID", assessments.phase_two(request))

    def test_missing_body_and_criterion_refs_are_admitted_before_computation(self):
        request = profile()
        request["assessment_bases"] = []
        self.assertIn("EVIDENCE_UNAVAILABLE", assessments.phase_two(request))
        request = profile()
        request["assessment_bases"][0]["review"]["criteria"][0]["id"] = "unknown"
        self.assertTrue({"EVIDENCE_UNAVAILABLE", "REFERENCE_INVALID"} <= assessments.phase_two(request))

    def test_extra_snapshot_and_extra_field_have_distinct_admission_codes(self):
        request = profile()
        snapshot = copy.deepcopy(request["assessment_bases"][0]["supporting_context"][0])
        snapshot["requirement_id"] = "unrequested"
        request["assessment_bases"][0]["supporting_context"].append(snapshot)
        self.assertEqual(assessments.phase_two(request), {"DEPENDENCY_MISMATCH"})
        request = profile()
        request["assessment_bases"][0]["supporting_context"][0]["fields"].append(field("extra", "value"))
        self.assertEqual(assessments.phase_two(request), {"REFERENCE_INVALID"})

    def test_outer_canonical_byte_ceiling_accepts_exact_limit_and_rejects_next_byte(self):
        request = profile()
        content = request["proposal"]["fields"][0]["value"]
        content["value"] = ""
        content["value"] = "x" * (1048576 - len(encoded(request)))
        self.assertEqual(len(encoded(request)), 1048576)
        self.assertNotIn("LIMIT_EXCEEDED", assessments.phase_two(request))
        content["value"] += "x"
        self.assertEqual(len(encoded(request)), 1048577)
        self.assertIn("LIMIT_EXCEEDED", assessments.phase_two(request))

    def test_model_failure_requires_reason_but_satisfied_human_may_resolve_it(self):
        request = profile()
        basis = request["assessment_bases"][0]
        basis["assessment"]["criteria"][0]["verdict"] = "FAIL"
        seal(request)
        self.assertEqual(assessments.phase_three(request), "BINDING_MISMATCH")
        basis["review"]["criteria"][0]["reason"] = "The supplied statement resolves the model's false positive."
        self.assertIsNone(assessments.phase_three(request))
        result = assessments.policy(request, current_rows(request))
        self.assertEqual(result["reasons"], set())
        self.assertEqual(result["checks"], [{"purpose": "ASSESSMENT", "subject_digest": computed(request)["ASSESSMENT_DIGEST"], "requirement_ref": "assess-message", "at": AT}])

    def test_wrong_known_model_citation_policy_is_binding_failure(self):
        request = profile()
        request["assessment_bases"][0]["assessment"]["criteria"][0]["citations"] = [{"kind": "PROPOSAL_FIELD", "field": "body"}]
        seal(request)
        self.assertEqual(assessments.phase_three(request), "BINDING_MISMATCH")

    def test_chronology_uses_authenticated_selected_human_time_without_clock(self):
        request = profile()
        request["clock"] = {"status": "UNAVAILABLE", "instant": None}
        contexts = {"human-review": {"decision": {"occurred_at": "2026-10-08T11:59:59Z"}}}
        self.assertEqual(assessments.chronology_error(request, contexts), "BINDING_MISMATCH")
        contexts["human-review"]["decision"]["occurred_at"] = AT
        self.assertIsNone(assessments.chronology_error(request, contexts))

    def test_current_maps_union_human_failure_and_skip_unusable_values(self):
        request = profile()
        rows = current_rows(request)
        rows["selection"]["fields"][0]["value"]["value"] = "old-digest"
        request["assessment_bases"][0]["review"]["decision"] = "REJECT"
        result = assessments.policy(request, rows)
        self.assertEqual(result["reasons"], {"ASSESSMENT_DEPENDENCY_CHANGED", "ASSESSMENT_NOT_SATISFIED"})
        self.assertEqual({row["reason"] for row in result["failed"]}, result["reasons"])
        request["assessment_bases"][0]["review"]["decision"] = "APPROVE"
        self.assertEqual(assessments.policy(request, {})["reasons"], set())

    def test_current_complete_fields_compare_by_name_and_nominal_value(self):
        request = profile()
        rows = current_rows(request)
        rows["content"]["fields"].reverse()
        self.assertEqual(assessments.policy(request, rows)["reasons"], set())
        rows["context"]["revision"] = "revision-2"
        self.assertEqual(assessments.policy(request, rows)["reasons"], {"ASSESSMENT_DEPENDENCY_CHANGED"})

    def test_false_relation_keeps_map_value_but_expired_source_does_not(self):
        request = profile()
        observation_request = copy.deepcopy(request)
        content = next(row for row in observation_request["envelope"]["source_observation_requirements"] if row["id"] == "content")
        observation_request["envelope"]["source_observation_requirements"] = [content]
        query = {**copy.deepcopy(content), "requirement_id": content["id"], "at": AT, "subject": "recipient"}
        del query["id"]
        observation = {"query": query, "query_digest": hashed("authority-query", query), "status": "AVAILABLE", "as_of": AT,
            "provider_record_id": "content-record", "revision": "revision-1", "fields": [field("body", "Changed content."), field("recipient", "recipient")],
            "relations": copy.deepcopy(content["relations"])}
        observation_request["observations"] = [observation]
        result = source_observations.observe_source(observation_request, observation_request["envelope"], [])
        self.assertEqual(result["reasons"], {"SOURCE_OBSERVATION_RELATIONS"})
        self.assertIn("content", result["assessment_values"])
        self.assertEqual(assessments.policy(request, result["assessment_values"])["reasons"], {"ASSESSMENT_DEPENDENCY_CHANGED"})
        step = observation_request["work_class"]["steps"][0]
        step["dispatch_gate"]["validity_requirements"] = [{"requirement_id": "content", "not_before_field": "begin", "not_after_field": "end"}]
        content["fields"].extend([{"name": "begin", "type_ref": "INSTANT"}, {"name": "end", "type_ref": "INSTANT"}])
        content["fields"].sort(key=lambda row: row["name"])
        query["fields"] = copy.deepcopy(content["fields"])
        observation["fields"].extend([field("begin", "2026-01-01T00:00:00Z", "INSTANT"), field("end", AT, "INSTANT")])
        observation["query_digest"] = hashed("authority-query", query)
        result = source_observations.observe_source(observation_request, observation_request["envelope"], [])
        self.assertIn("SOURCE_OBSERVATION_TIME", result["reasons"])
        self.assertNotIn("content", result["assessment_values"])
        self.assertEqual(assessments.policy(request, result["assessment_values"])["reasons"], set())

    def test_refresh_retains_complete_body_and_optional_presence(self):
        request = profile()
        fresh = copy.deepcopy(request)
        fresh["clock"]["instant"] = "2026-10-08T12:00:01Z"
        self.assertTrue(dispatch_gate.immutable_binding(request, fresh))
        fresh["assessment_bases"][0]["review"]["criteria"][0]["reason"] = "Changed review."
        self.assertFalse(dispatch_gate.immutable_binding(request, fresh))
        self.assertFalse(dispatch_gate.immutable_binding({"assessment_bases": []}, {}))

    def test_authority_evidence_preserves_optional_empty_collection(self):
        request = {"source": {"id": "source"}, "work_class": {"types": []},
            "envelope": {"id": "envelope", "conditions": [], "gate": {"criteria": []},
                "limits": {"per_action": [], "shared_budgets": []}, "scope": {"id": "scope"}},
            "proposal": {"step": "send", "executor": {"occupancy": "executor"}}, "clock": {"instant": AT},
            "host_selection": {}, "occupancies": [], "capacities": [], "credentials": [], "acts": [], "returns": [], "observations": []}
        dependencies = {"root": {"id": "root"}, "capacities": {}, "credentials": []}
        application = {"fields": {}, "scope": {}, "actual_scope": {}, "step": {}}
        observations = {"reasons": set(), "failed": [], "checks": [], "queries": []}
        # Act and query admission are premises here; this isolates the evidence preimage.
        with mock.patch("implementation.authority_observations.observe_revocation", return_value=observations), mock.patch("implementation.source_observations.observe_source", return_value=observations):
            omitted = authority._policy_result(request, "pin", dependencies, application, {"selected": [], "returns": {}})
            evidence = {key: request[key] for key in ("host_selection", "occupancies", "capacities", "credentials", "acts", "returns", "observations", "clock")}
            self.assertEqual(omitted["evidence_digest"], hashed("authority-evidence", evidence))
            request["assessment_bases"] = []
            explicit = authority._policy_result(request, "pin", dependencies, application, {"selected": [], "returns": {}})
            self.assertEqual(explicit["evidence_digest"], hashed("authority-evidence", {**evidence, "assessment_bases": []}))
            self.assertNotEqual(explicit["evidence_digest"], omitted["evidence_digest"])

    def test_retained_separation_reconstructs_explicit_empty_assessment_basis(self):
        act = {"id": "current-decision", "kind": "INSTANCE_DECISION", "actor": "reviewer"}
        selected = {"act": act, "act_digest": hashed("authority-act", act)}
        result = {"status": "READY_FOR_RESERVATION", "act_digests": [selected["act_digest"]]}
        occurrence = {"step_id": "send", "occurrence_id": "current"}
        requirement = {"id": "prior-reviewer", "relation": "DISTINCT_ACTOR", "current_act_kind": "INSTANCE_DECISION",
            "prior_act_kind": "INSTANCE_DECISION", "prior_step_id": "prior"}
        source = {"id": "source", "revision": "revision-1", "obligations": [{"id": "obligation"}]}
        projection = {"admitted": "authority-work-class"}
        basis = {"assessment_bases": [], "acts": [act], "source": source, "work_class": projection,
            "proposal": {"work_class": "work", "instance": "case", "occurrence": "current", "step": "send", "operation": "send", "interface": "mail",
                "executor": {"actor": "executor", "role": "operator"}},
            "envelope": {"id": "envelope", "limits": {"shared_budgets": []}, "gate": {"kind": "DECIDE"}},
            "clock": {"source": "clock", "status": "AVAILABLE", "instant": AT}}
        definition = {"id": "work", "source": {**source, "obligations": ["obligation"]},
            "participants": [{"id": "executor", "role": "operator"}],
            "steps": [{"id": "send", "operation": "send", "interface": "mail", "authority_requirements": ["envelope"], "shared_budgets": [],
                "prior_actor_separations": [requirement]}]}
        state = {"instance_id": "case", "active": [{"occurrence": occurrence}], "completed": [{"occurrence": {"step_id": "prior", "occurrence_id": "prior"}}],
            "clocks": [{"source": "clock", "status": "AVAILABLE", "revision": "1", "observed_time": AT}],
            "receipts": [{"sequence": "1", "details": [{"kind": "CLOCK", "source": "clock", "revision": "1"}]}]}
        detail = {"authority_result": result, "authority_basis": basis,
            "basis": {"current_act": selected, "prior_act": selected, "requirement_id": requirement["id"], "relation": requirement["relation"], "prior_occurrence_id": "prior"}}
        receipt = {"sequence": "2", "authority_result_digest": hashed("authority-result", result)}
        # Ordinary authority admission is supplied; this checks the retention carrier and exact reconstruction path.
        with mock.patch.object(lifecycle, "_authority_projection", return_value=projection), mock.patch.object(authority, "evaluate_authority", return_value=result) as evaluate:
            self.assertTrue(lifecycle._separation_current_integrity(receipt, detail, occurrence, state, definition))
            evaluate.assert_called_once_with(basis, lifecycle.PIN)
            receipt["authority_result_digest"] = "sha256:" + "0" * 64
            self.assertFalse(lifecycle._separation_current_integrity(receipt, detail, occurrence, state, definition))
        del basis["assessment_bases"]
        self.assertFalse(lifecycle._separation_current_integrity(receipt, detail, occurrence, state, definition))

    def test_unsupported_correction_profile_does_not_infer_authority(self):
        request = {"original_record": {}, "correction": {"correction_authority_input": {"assessment_bases": [{}], "envelope": {}}}}
        with self.assertRaises(Refusal) as error:
            source_corrections.check(request)
        self.assertEqual(error.exception.code, "UNSUPPORTED_RELATION")
        current = request["correction"]["correction_authority_input"]
        current["assessment_bases"] = []
        current["envelope"]["assessment_requirements"] = []
        current["envelope"]["decision_requirements"] = [{"context_bindings": [{"value": {"kind": "ASSESSMENT"}}]}]
        with self.assertRaises(Refusal) as error:
            source_corrections.check(request)
        self.assertEqual(error.exception.code, "UNSUPPORTED_RELATION")


if __name__ == "__main__":
    unittest.main()
