"""Artifact admission and deterministic readback for draft 2."""

from __future__ import annotations

from . import aggregate_contract, authority, work_class
from .common import IDENTITY, PIN, Refusal, digest, readback_lines, schema_valid, utf8_sorted_unique


SCHEMAS = {
    "AGGREGATE_DEFINITION": ("aggregate.schema.json", "definition", "aggregate-definition"),
    "AUTHORITY_DEFINITION": ("authority.schema.json", "definition", "authority-definition"),
    "WORK_CLASS": ("work-class.schema.json", "definition", "work-class-definition"),
    "BOUNDARY_RECORD": ("boundary.schema.json", "record", "boundary"),
    "EVIDENCE_RECORD": ("evidence.schema.json", "record", "evidence"),
}


def _schema_token(kind: str) -> str:
    return {
        "AGGREGATE_DEFINITION": "aggregate-definition",
        "AUTHORITY_DEFINITION": "authority-definition",
        "WORK_CLASS": "work-class-definition",
        "BOUNDARY_RECORD": "boundary-record",
        "EVIDENCE_RECORD": "evidence-record",
    }[kind]


def _aggregate_static(value):
    aggregate_contract.definition(value)


def _authority_static(value):
    result = authority.validate_definition(value)
    if result.get("status") != "ACCEPTED":
        raise Refusal(result.get("code", "INPUT_INVALID"))


def _boundary_static(value):
    if value["candidate_identity"] != IDENTITY or value["specification_pin"] != PIN:
        raise Refusal("BINDING_MISMATCH")
    for name in ("paragraph_ids", "requirement_ids"):
        if not utf8_sorted_unique(value[name]):
            raise Refusal("REFERENCE_INVALID")


def _evidence_static(value):
    for name in ("scope_ids", "decision_ids", "authorization_scope", "paragraph_ids", "case_ids", "finding_ids"):
        if name in value and not utf8_sorted_unique(value[name]):
            raise Refusal("REFERENCE_INVALID")
    if value["kind"] == "CORRESPONDENCE":
        mappings = value["mappings"]
        if not utf8_sorted_unique([row["source_obligation_id"] for row in mappings]):
            raise Refusal("REFERENCE_INVALID")
        if any(not utf8_sorted_unique(row["provision_paths"]) for row in mappings):
            raise Refusal("REFERENCE_INVALID")
        for name in ("uncovered_source_obligation_ids", "unsupported_provision_paths"):
            if not utf8_sorted_unique(value[name]):
                raise Refusal("REFERENCE_INVALID")
        residue_keys = [(row["kind"], row["subject"]) for row in value["residue"]]
        if len(residue_keys) != len(set(residue_keys)) or residue_keys != sorted(
            residue_keys, key=lambda row: (row[0].encode("utf-8"), row[1].encode("utf-8"))
        ):
            raise Refusal("REFERENCE_INVALID")


def admit(kind: str, value):
    if kind not in SCHEMAS or type(value) is not dict:
        raise Refusal("SCHEMA_INVALID")
    filename, definition, digest_kind = SCHEMAS[kind]
    expected_schema = f"{IDENTITY}/{_schema_token(kind)}"
    if value.get("schema") != expected_schema:
        raise Refusal("VERSION_UNSUPPORTED")
    if not schema_valid(value, filename, definition):
        raise Refusal("SCHEMA_INVALID")
    if kind == "WORK_CLASS" and value["specification_pin"] != PIN:
        raise Refusal("BINDING_MISMATCH")
    if kind == "WORK_CLASS":
        work_class.validate(value)
    elif kind == "AGGREGATE_DEFINITION":
        _aggregate_static(value)
    elif kind == "AUTHORITY_DEFINITION":
        _authority_static(value)
    elif kind == "BOUNDARY_RECORD":
        _boundary_static(value)
    elif kind == "EVIDENCE_RECORD":
        _evidence_static(value)
    return digest(digest_kind, value)


def readback(kind: str, value):
    return {"status": "READBACK", "digest": admit(kind, value), "lines": readback_lines(value)}
