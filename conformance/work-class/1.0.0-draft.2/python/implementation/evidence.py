"""Draft-2 evidence and correspondence checks."""

from __future__ import annotations

from .common import PIN, digest, readback_lines, schema_valid, utf8_sorted_unique, valid_instant


def _invalid(request, code):
    return {
        "status": "EVIDENCE_INVALID",
        "profile": request["profile"],
        "role": request["role"],
        "code": code,
        "path": "",
        "specification_pin": PIN,
    }


def _valid(request):
    return {
        "status": "EVIDENCE_VALID",
        "profile": request["profile"],
        "role": request["role"],
        "subject_digest": request["subject"]["subject_digest"],
        "evidence_digest": digest("evidence", request["evidence"]),
        "specification_pin": PIN,
    }


def _basic(request):
    subject = request["subject"]
    evidence = request["evidence"]
    if request["specification_pin"] != PIN or subject["specification_pin"] != PIN:
        return _invalid(request, "BINDING_MISMATCH")
    if subject["candidate_identity"] != "seampoint.work-class/1.0.0-draft.2":
        return _invalid(request, "BINDING_MISMATCH")
    if evidence["subject_digest"] != subject["subject_digest"]:
        return _invalid(request, "BINDING_MISMATCH")
    if not valid_instant(evidence["recorded_at"]) or (evidence.get("expires_at") is not None and not valid_instant(evidence["expires_at"])):
        return _invalid(request, "SCHEMA_INVALID")
    if evidence["status"] != "ACCEPTED":
        return _invalid(request, "EVIDENCE_NOT_ACCEPTED")
    for key in ("scope_ids", "decision_ids", "authorization_scope", "paragraph_ids", "case_ids", "finding_ids"):
        if key in evidence and not utf8_sorted_unique(evidence[key]):
            return _invalid(request, "BINDING_MISMATCH")
    return _valid(request)


def _correspondence(request):
    subject = request["subject"]
    work_class = request["work_class"]
    correspondence = request["evidence"]
    if not valid_instant(correspondence["recorded_at"]) or not valid_instant(correspondence["review"]["recorded_at"]):
        return _invalid(request, "SCHEMA_INVALID")
    work_digest = digest("work-class-definition", work_class)
    if request["specification_pin"] != PIN or subject["specification_pin"] != PIN:
        return _invalid(request, "BINDING_MISMATCH")
    if work_class["specification_pin"] != PIN or request["profile"] != work_class["profile"]:
        return _invalid(request, "BINDING_MISMATCH")
    if subject["kind"] != "WORK_CLASS" or subject["subject_id"] != work_class["id"]:
        return _invalid(request, "BINDING_MISMATCH")
    if any(value != work_digest for value in (
        request["work_class_digest"], subject["subject_digest"],
        correspondence["subject_digest"], correspondence["work_class_digest"],
    )):
        return _invalid(request, "BINDING_MISMATCH")
    if correspondence["source_id"] != work_class["source"]["id"] or correspondence["source_revision"] != work_class["source"]["revision"]:
        return _invalid(request, "BINDING_MISMATCH")

    obligations = work_class["source"]["obligations"]
    mappings = correspondence["mappings"]
    uncovered = correspondence["uncovered_source_obligation_ids"]
    unsupported = correspondence["unsupported_provision_paths"]
    paths = [row["path"] for row in readback_lines(work_class)]
    mapping_ids = [row["source_obligation_id"] for row in mappings]
    mapped_paths = [item for row in mappings for item in row["provision_paths"]]
    if not utf8_sorted_unique(mapping_ids) or any(not utf8_sorted_unique(row["provision_paths"]) for row in mappings):
        return _invalid(request, "BINDING_MISMATCH")
    if not utf8_sorted_unique(uncovered) or sorted(mapping_ids + uncovered, key=lambda value: value.encode("utf-8")) != obligations:
        return _invalid(request, "BINDING_MISMATCH")
    if not utf8_sorted_unique(unsupported) or set(mapped_paths) & set(unsupported):
        return _invalid(request, "BINDING_MISMATCH")
    if set(mapped_paths) | set(unsupported) != set(paths):
        return _invalid(request, "BINDING_MISMATCH")
    if len([(row["source_obligation_id"], path) for row in mappings for path in row["provision_paths"]]) != len(set((row["source_obligation_id"], path) for row in mappings for path in row["provision_paths"])):
        return _invalid(request, "BINDING_MISMATCH")

    residues = correspondence["residue"]
    expected_residues = {("SOURCE_OBLIGATION", item) for item in uncovered} | {("ARTIFACT_PROVISION", item) for item in unsupported}
    actual_residues = [(row["kind"], row["subject"]) for row in residues]
    if len(actual_residues) != len(set(actual_residues)) or set(actual_residues) != expected_residues:
        return _invalid(request, "BINDING_MISMATCH")
    if actual_residues != sorted(actual_residues, key=lambda row: (row[0].encode("utf-8"), row[1].encode("utf-8"))):
        return _invalid(request, "BINDING_MISMATCH")

    if correspondence["status"] != "ACCEPTED":
        return _invalid(request, "EVIDENCE_NOT_ACCEPTED")
    review = correspondence["review"]
    subject_body = dict(correspondence)
    del subject_body["review"]
    if review["subject_digest"] != digest("correspondence-subject", subject_body):
        return _invalid(request, "BINDING_MISMATCH")
    if review["status"] != "ACCEPTED":
        return _invalid(request, "EVIDENCE_NOT_ACCEPTED")
    return _valid(request)


def check(request):
    if not schema_valid(request, "evidence.schema.json", "input"):
        profile = request.get("profile") if isinstance(request, dict) else None
        role = request.get("role") if isinstance(request, dict) else None
        if "specification_pin" in request and profile in {"LINEAR", "CHOICE_LOOPS", "DEADLINES", "PARALLEL_FANOUT"} and role == "REVIEW_EVIDENCE":
            return _invalid(request, "SCHEMA_INVALID")
        return {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""}
    if request["specification_pin"] != PIN:
        return {"status":"REFUSED","code":"VERSION_UNSUPPORTED","path":""}
    if "work_class" in request:
        return _correspondence(request)
    return _basic(request)
