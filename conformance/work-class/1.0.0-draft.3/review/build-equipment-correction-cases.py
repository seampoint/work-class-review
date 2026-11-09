#!/usr/bin/env python3
"""Author SOURCE_CORRECTION vectors from source and normative constructors."""

from __future__ import annotations

import copy

from corpus_common import CASES, canonical_bytes, digest, exact_case, write_canonical_json
from equipment_correction_fixture import (CORRECTION_AT, correction_fixture, correction_refusal,
    rebind_authority, seal_correction, seal_custodian_return)
from fixture_factory import typed


GROUP = CASES / "equipment-correction"


def native_digest(record):
    record["record_digest"] = digest("provider-native-record", {key: record[key] for key in (
        "provider", "source", "record_type", "provider_record_id", "provider_revision", "actual_fields", "event_time")})
    return record


def change(record, field, new_value):
    return {"field": field, "old_value": next((copy.deepcopy(row["value"]) for row in record["actual_fields"]
        if row["name"] == field), None), "new_value": new_value}


def field_value(fields, name):
    return next(row["value"] for row in fields if row["name"] == name)


def reseal_permit(supplied):
    permit = supplied["original_permit"]
    permit["permit_id"] = digest("permit", {key: value for key, value in permit.items() if key != "permit_id"})


def reseal_authority(supplied, member="correction_authority_input"):
    correction = supplied["correction"]
    correction[member], _ = rebind_authority(correction[member])
    if member == "correction_authority_input":
        decision = next(row for row in correction[member]["acts"] if row["kind"] == "INSTANCE_DECISION")
        correction["correction_authorization_digest"] = digest("authority-act", decision)
    seal_correction(correction)


def main():
    cases = []
    administrative, admitted = correction_fixture()
    original = administrative["original_record"]

    def emit(supplied, expected, derivation):
        number = len(cases) + 1
        cases.append(exact_case("C3-ER-" + str(number).zfill(3), "check-evidence", supplied, expected,
            ["LIFE-020A", "LIFE-008", "LIFE-010", "AUTH-001", "AUTH-004", "AUTH-005", "AUTH-006"], derivation))

    def reject(name, mutate, code="BINDING_MISMATCH", *, source=None, rebind=None, custodian_return=False):
        supplied = copy.deepcopy(administrative if source is None else source)
        mutate(supplied)
        if rebind:
            reseal_authority(supplied, rebind)
        if custodian_return:
            seal_custodian_return(supplied["correction"]["custodian_return"])
        seal_correction(supplied["correction"])
        emit(supplied, correction_refusal(code), name)

    emit(administrative, admitted,
        "The Maintenance Records Custodian changes reason under a complete independently evaluated Reliability Supervisor Correction Authorization. The seven-argument original request and eleven-field original provider event stay immutable; no business-result field changes and both new-approval result members are null.")

    positives = []
    for name, value in (("performer_role", typed("ROLE_ID", "maintenance-records-custodian")),
            ("event_id", typed("EVENT_ID", "RTS-EVT-901-CORRECTED")),
            ("event_timestamp", typed("INSTANT", "2026-09-12T14:31:00Z"))):
        supplied, expected = correction_fixture(changes=[change(original, name, value)])
        emit(supplied, expected,
            "The source explicitly permits correction of " + name + " through the custodian's linked event. The original top-level provider identity and event_time remain unchanged; this administrative field does not require a new approval.")
    for name, value in (("asset", typed("ASSET_ID", "EQ-205")),
            ("work_order", typed("WORK_ORDER_ID", "WO-7305")),
            ("inspection", typed("INSPECTION_ID", "IN-553")),
            ("effective_time", typed("INSTANT", "2026-09-12T14:31:00Z")),
            ("resulting_status", typed("STATUS", "Rejected"))):
        supplied, expected = correction_fixture(changes=[change(original, name, value)])
        positives.append(supplied)
        emit(supplied, expected,
            "Changing source-declared business-result field " + name + " requires a complete fresh AP-092 approval basis. Its current authority and corrected-result digest are independently derived; the original permit and event are retained.")
    new_link = canonical_bytes({"provider": "maintenance-register", "source": "approval-register",
        "record_type": "approval", "provider_record_id": "AP-092"}).decode("utf-8")
    business, business_result = correction_fixture(changes=[change(original, "approval", typed("APPROVAL_ID", "AP-092")),
        change(original, "approval_register_link", typed("PROVIDER_LINK", new_link))])
    positives.append(business)
    emit(business, business_result,
        "Approval AP-092 and its fully qualified approval-register link change together. A distinct independently admitted new grant commits the entire corrected inventory; correcting the link alone cannot authorize a business-result change.")

    damaged = copy.deepcopy(original)
    field_value(damaged["actual_fields"], "approval_register_link").update(value="AP-091")
    native_digest(damaged)
    supplied, expected = correction_fixture(original_record=damaged, changes=[change(damaged,
        "approval_register_link", copy.deepcopy(field_value(original["actual_fields"], "approval_register_link")))])
    emit(supplied, expected,
        "A retained unqualified original approval link may be corrected to the full declared approval-register tuple. Approval itself stays AP-091, so this link-only repair requires correction authority and no new business-result approval.")

    damaged = copy.deepcopy(original)
    damaged["actual_fields"] = [row for row in damaged["actual_fields"] if row["name"] != "reason"]
    native_digest(damaged)
    supplied, expected = correction_fixture(original_record=damaged,
        changes=[change(damaged, "reason", typed("REASON", "RTS-AUTH-INSPECTED"))])
    emit(supplied, expected,
        "An attributed existing native record may be missing a declared field. Null old_value exactly denotes absence and the authorized addition reconstructs the full eleven-field inventory.")
    for name, value, restored in (("event_id", typed("EVENT_ID", "WRONG-EVENT-ID"), typed("EVENT_ID", "RTS-EVT-901")),
            ("asset", typed("ASSET_ID", "WRONG-ASSET"), typed("ASSET_ID", "EQ-204"))):
        damaged = copy.deepcopy(original)
        field_value(damaged["actual_fields"], name).update(value)
        native_digest(damaged)
        supplied, expected = correction_fixture(original_record=damaged, changes=[change(damaged, name, restored)])
        emit(supplied, expected,
            "The original " + name + " actual field mismatches its source request while immutable provider metadata and request attribution identify the record. Exact old bytes may be corrected; business-result membership still determines whether fresh approval is required.")
    damaged = copy.deepcopy(original)
    damaged["actual_fields"].append({"name": "undeclared_extra", "value": typed("REASON", "unexpected-original-value")})
    damaged["actual_fields"].sort(key=lambda row: row["name"].encode())
    native_digest(damaged)
    supplied, expected = correction_fixture(original_record=damaged, changes=[change(damaged, "undeclared_extra", None)])
    emit(supplied, expected,
        "The custodian may remove an undeclared original extra by naming its exact retained old bytes and null new_value. The corrected body contains precisely the eleven declared fields; no undeclared addition is authorized.")

    reject("A changed outer definition digest cannot identify the immutable original definition.",
        lambda x: x.update(definition_digest=digest("wrong-definition", {})), "DEPENDENCY_MISMATCH")
    reject("A changed original permit id fails its complete canonical body commitment.",
        lambda x: x["original_permit"].update(permit_id=digest("wrong-permit", {})), "DEPENDENCY_MISMATCH")
    reject("A changed retained original authority result digest fails before correction authority admission.",
        lambda x: x["original_permit"].update(authority_result_digest=digest("wrong-result", {})), "DEPENDENCY_MISMATCH")
    reject("A rehashed original permit and authority receipt cannot hide an omitted original satisfied check. Original authority is independently reconstructed from its retained complete basis.",
        lambda x: (x["original_permit"]["authority_result"]["checks"].pop(),
            x["original_permit"].update(authority_result_digest=digest("authority-result", x["original_permit"]["authority_result"])),
            reseal_permit(x)), "DEPENDENCY_MISMATCH")
    reject("A changed original native request attribution digest cannot establish which retained request produced the event.",
        lambda x: x["original_record"].update(native_request_digest=digest("wrong-request", {})))
    reject("An original provider fact with a forged full native-record digest cannot be corrected from a caller hash.",
        lambda x: x["original_record"].update(record_digest=digest("wrong-native-record", {})))
    for member in ("provider_record_id", "provider_revision"):
        reject("A source correction requires nonnull original " + member + "; absent provider metadata cannot be reconstructed from actual field values.",
            lambda x, member=member: x["original_record"].update({member: None}))
    reject("Original provider coordinates must equal the admitted completion carrier, even when every correction hash is internally consistent.",
        lambda x: x["original_record"].update(provider="another-register"))
    reject("Original evidence must establish an existing provider effect; OUTCOME_UNKNOWN is not an event to correct.",
        lambda x: x["original_record"].update(status="OUTCOME_UNKNOWN"))
    for member, value in (("original_provider_record_id", "another-original-record"),
            ("original_record_digest", digest("another-original-record", {})), ("expected_revision", "another-revision"),
            ("provider", "another-provider"), ("source", "another-source"), ("record_type", "another-correction-type")):
        reject("The linked correction's " + member + " must equal the selected original fact or source-declared correction coordinates.",
            lambda x, member=member, value=value: x["correction"].update({member: value}))
    reject("A correction cannot precede the original provider event.",
        lambda x: x["correction"].update(event_time="2026-09-12T14:29:00Z"))
    reject("Correction observed_at cannot precede correction event_time.",
        lambda x: x["correction"].update(observed_at="2026-09-12T14:59:00Z"))

    reject("An old_value with different original bytes refuses rather than overwriting an unselected revision.",
        lambda x: x["correction"]["changes"][0]["old_value"].update(value="WRONG-OLD-REASON"))
    reject("Null old_value cannot claim absence of the retained reason field.",
        lambda x: x["correction"]["changes"][0].update(old_value=None))
    reject("A replacement equal to its exact original value is a no-op and does not define a correction.",
        lambda x: x["correction"]["changes"][0].update(new_value=copy.deepcopy(x["correction"]["changes"][0]["old_value"])))
    reject("Duplicate change names are ambiguous even when the change bodies are identical.",
        lambda x: x["correction"]["changes"].append(copy.deepcopy(x["correction"]["changes"][0])))
    reject("Removing a declared field cannot produce the complete required inventory.",
        lambda x: x["correction"]["changes"][0].update(new_value=None))
    reject("Undeclared fields cannot be added by a correction authorization.",
        lambda x: x["correction"]["changes"].append({"field": "undeclared_extra", "old_value": None, "new_value": typed("REASON", "extra")}))
    reject("Corrected fields must be derived from all changes, rather than a second independent caller-selected inventory.",
        lambda x: field_value(x["correction"]["corrected_fields"], "reason").update(value="ANOTHER-CORRECTED-REASON"))
    reject("An omitted corrected field cannot satisfy the eleven-field completion inventory.",
        lambda x: x["correction"].update(corrected_fields=[row for row in x["correction"]["corrected_fields"] if row["name"] != "asset"]))
    reject("Corrected field names are unique; duplicate values cannot hide ambiguity.",
        lambda x: x["correction"]["corrected_fields"].append(copy.deepcopy(x["correction"]["corrected_fields"][0])))
    for type_ref in ("IDENTITY", "UNKNOWN_TYPE"):
        reject("The new reason scalar under nominal type " + type_ref + " does not satisfy its declared REASON type.",
            lambda x, type_ref=type_ref: x["correction"]["changes"][0]["new_value"].update(type_ref=type_ref), "TYPE_INVALID")
    supplied, _ = correction_fixture(changes=[change(original, "event_timestamp", typed("INSTANT", "2026-02-30T14:30:00Z"))])
    emit(supplied, correction_refusal("TYPE_INVALID"),
        "An impossible calendar instant in a new declared INSTANT field refuses TYPE_INVALID after SOURCE_CORRECTION admission.")
    damaged = copy.deepcopy(original)
    damaged["actual_fields"].append(copy.deepcopy(damaged["actual_fields"][0]))
    native_digest(damaged)
    supplied, _ = correction_fixture(original_record=damaged)
    emit(supplied, correction_refusal("BINDING_MISMATCH"),
        "Two original fields with one name refuse instead of letting a map construction choose which old value to overwrite.")

    for link in ("AP-091", canonical_bytes({"provider": "another-provider", "source": "approval-register",
            "record_type": "approval", "provider_record_id": "AP-091"}).decode(),
            canonical_bytes({"provider": "maintenance-register", "source": "approval-register",
            "record_type": "approval", "provider_record_id": "AP-999"}).decode()):
        supplied, _ = correction_fixture(changes=[change(original, "approval_register_link", typed("PROVIDER_LINK", link))])
        emit(supplied, correction_refusal("BINDING_MISMATCH"),
            "A nominally valid corrected link must identify the corrected approval using the exact provider/source/register/id tuple. An unqualified id, another provider or another approval does not establish that link.")
    supplied, _ = correction_fixture(changes=[change(original, "approval", typed("APPROVAL_ID", "AP-092"))])
    emit(supplied, correction_refusal("BINDING_MISMATCH"),
        "Fresh approval authority does not make an unchanged AP-091 link identify corrected approval AP-092. The full linked field inventory must be consistent.")

    for member, value in (("actor", "another-custodian"), ("role", "maintenance-records-clerk"),
            ("principal", "another-principal"), ("occupancy", "another-occupancy")):
        reject("The correction custodian's " + member + " must exactly identify the independently occupied executor.",
            lambda x, member=member, value=value: x["correction"]["custodian"].update({member: value}))
    for member, value in (("provider", "another-identity-provider"), ("source", "another-role-source"),
            ("occupancy_digest", digest("another-occupancy", {})), ("actor", "another-custodian"),
            ("role", "another-role"), ("at", "2026-09-12T14:59:00Z")):
        reject("A fully rehashed custodian return with wrong " + member + " cannot establish the selected current custodian occupancy.",
            lambda x, member=member, value=value: x["correction"]["custodian_return"].update({member: value}), custodian_return=True)
    reject("The custodian return's provenance commits its complete bound body.",
        lambda x: x["correction"]["custodian_return"].update(provenance_digest=digest("wrong-custodian-provenance", {})))

    for name, value in (("original_record_identity", "RTS-EVT-901"), ("original_record_digest", digest("wrong-old-digest", {})),
            ("original_revision", "wrong-revision"), ("changes_digest", digest("wrong-changes", {}))):
        reject("An independently rebound correction authority proposal with wrong " + name + " cannot authorize these selected original bytes and exact changes.",
            lambda x, name=name, value=value: field_value(x["correction"]["correction_authority_input"]["proposal"]["fields"], name).update(value=value),
            rebind="correction_authority_input")
    reject("A caller-selected decision hash must identify the exact positive independently admitted INSTANCE_DECISION.",
        lambda x: x["correction"].update(correction_authorization_digest=digest("wrong-decision", {})))
    reject("Unavailable correction authority clock cannot establish current correction permission.",
        lambda x: x["correction"]["correction_authority_input"]["clock"].update(status="UNAVAILABLE", instant=None), "EVIDENCE_UNAVAILABLE")
    reject("A correction authority clock at another valid instant cannot establish authority at this linked correction event.",
        lambda x: x["correction"]["correction_authority_input"]["clock"].update(instant="2026-09-12T14:59:00Z"), "EVIDENCE_UNAVAILABLE")
    reject("Missing current revocation responses withhold correction authority.",
        lambda x: x["correction"]["correction_authority_input"].update(observations=[]), "EVIDENCE_UNAVAILABLE")
    reject("Missing returned correction authority acts withhold authority despite retained act bytes.",
        lambda x: x["correction"]["correction_authority_input"].update(returns=[]), "EVIDENCE_UNAVAILABLE")
    reject("An expired correction envelope with independently rebound hashes cannot establish current authority.",
        lambda x: x["correction"]["correction_authority_input"]["envelope"]["temporal_validity"].update(valid_until=CORRECTION_AT),
        "EVIDENCE_UNAVAILABLE", rebind="correction_authority_input")
    reject("An explicit current envelope revocation withholds correction authority.",
        lambda x: next(row for row in x["correction"]["correction_authority_input"]["observations"]
            if row["query"]["subject_digest"] == digest("authority-envelope", x["correction"]["correction_authority_input"]["envelope"])
            and row["query"]["at"] == CORRECTION_AT).update(revoked=True), "EVIDENCE_UNAVAILABLE")
    reject("Correction authority scope must include the full original identity resource, even if another declared field makes a standard authority proposal internally valid.",
        lambda x: x["correction"]["correction_authority_input"]["work_class"]["steps"][0]["scope_fields"].update(resources=["original_revision"]),
        "EVIDENCE_UNAVAILABLE", rebind="correction_authority_input")
    reject("An INSTANCE_DECISION issued under another role is not the source-required Reliability Supervisor authorization.",
        lambda x: next(row for row in x["correction"]["correction_authority_input"]["acts"] if row["kind"] == "INSTANCE_DECISION").update(role="maintenance-records-clerk"),
        "EVIDENCE_UNAVAILABLE", rebind="correction_authority_input")
    reject("A pending correction decision cannot grant Correction Authorization despite complete returned bytes and matching digests.",
        lambda x: next(row for row in x["correction"]["correction_authority_input"]["acts"] if row["kind"] == "INSTANCE_DECISION").update(disposition="PENDING"),
        "EVIDENCE_UNAVAILABLE", rebind="correction_authority_input")

    for supplied in positives:
        name = next(row["field"] for row in supplied["correction"]["changes"] if row["field"] != "approval_register_link")
        reject("Changing " + name + " cannot reuse correction authority without the independently evaluated fresh approval basis.",
            lambda x: x["correction"].update(new_approval_basis=None), source=supplied)
    reject("An administrative-only correction must not carry an unrelated fresh approval basis.",
        lambda x: x["correction"].update(new_approval_basis=copy.deepcopy(business["correction"]["new_approval_basis"])))
    reject("A new approval proposal must commit the complete corrected field body, rather than another result digest.",
        lambda x: field_value(x["correction"]["new_approval_basis"]["proposal"]["fields"], "corrected_result_digest").update(value=digest("wrong-corrected-result", {})),
        source=business, rebind="new_approval_basis")
    reject("Missing current fresh-approval revocation evidence withholds authority despite a previously valid original grant.",
        lambda x: x["correction"]["new_approval_basis"].update(observations=[]), "EVIDENCE_UNAVAILABLE", source=business)
    reject("A fresh approval clock must be current at the correction instant.",
        lambda x: x["correction"]["new_approval_basis"]["clock"].update(instant="2026-09-12T14:59:00Z"), "EVIDENCE_UNAVAILABLE", source=business)
    reject("An expired independently rebound new approval cannot authorize a business-result change.",
        lambda x: x["correction"]["new_approval_basis"]["envelope"]["temporal_validity"].update(valid_until=CORRECTION_AT),
        "EVIDENCE_UNAVAILABLE", source=business, rebind="new_approval_basis")
    reject("A new business-result grant under another issuer role is not the source-required Reliability Supervisor approval.",
        lambda x: next(row for row in x["correction"]["new_approval_basis"]["acts"] if row["kind"] == "GRANT").update(role="maintenance-records-clerk"),
        "EVIDENCE_UNAVAILABLE", source=business, rebind="new_approval_basis")
    reject("A standard valid grant with the original approval id cannot be the distinct new business-result approval.",
        lambda x: (x["correction"]["new_approval_basis"]["envelope"].update(grant_ref="AP-091"),
            next(row for row in x["correction"]["new_approval_basis"]["acts"] if row["kind"] == "GRANT").update(id="AP-091")),
        source=business, rebind="new_approval_basis")
    reject("New approval scope must include the same original identity resource and original principal.",
        lambda x: field_value(x["correction"]["new_approval_basis"]["proposal"]["fields"], "principal").update(value="another-principal"),
        "EVIDENCE_UNAVAILABLE", source=business, rebind="new_approval_basis")

    supplied = copy.deepcopy(administrative)
    supplied["correction"]["provenance_digest"] = digest("wrong-correction-provenance", {})
    emit(supplied, correction_refusal("BINDING_MISMATCH"),
        "The correction provenance is the complete supplied record omitting only itself; a caller digest cannot replace that commitment.")
    reject("The native evidence carrier permits omission for older branches, but SOURCE_CORRECTION cannot select history without an original provider record id.",
        lambda x: x["original_record"].pop("provider_record_id"))
    for derivation, mutate, code in (
            ("An extra correction record member cannot become an undeclared source-correction channel.", lambda x: x["correction"].update(extra_member="extra"), "SCHEMA_INVALID"),
            ("A caller READY receipt cannot replace the complete independent correction authority input.", lambda x: x["correction"].update(correction_authority_input={"status": "READY_FOR_RESERVATION"}), "SCHEMA_INVALID"),
            ("Candidate selection precedes correction admission; another top-level specification pin refuses generically.", lambda x: x.update(specification_pin=digest("another-candidate", {})), "VERSION_UNSUPPORTED")):
        supplied = copy.deepcopy(administrative)
        mutate(supplied)
        emit(supplied, {"status": "REFUSED", "code": code, "path": ""}, derivation)

    for case in cases:
        write_canonical_json(GROUP / (case["id"] + ".json"), case)
    print({"group": str(GROUP), "cases": len(cases),
        "derivation": "source facts and normative constructors only; consumers not consulted"})


if __name__ == "__main__":
    main()
