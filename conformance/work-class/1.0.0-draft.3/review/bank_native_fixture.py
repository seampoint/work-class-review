"""Exact synthetic SAR XML and source correspondence, without a consumer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


NS = "www.fincen.gov/base"
ET.register_namespace("fc2", NS)
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
SOURCE = "conformance/work-class/1.0.0-draft.3/review/fixtures/bank-native-serialization-revision1-source.md"
INSTITUTION = "MRB-INSTITUTION-01/revision-1"
CONTACT = "MRB-CONTACT-01/revision-1"
CUSTOMER = "MRB-CDD-074/revision-4"
DECISION = "MRB-DECISION-074/revision-1"
TRANSACTIONS = "MRB-TXN-081,MRB-TXN-082,MRB-TXN-083/revision-1"
SERIALIZER = "bank-sar-single-report-utf8/revision-1"


def package(*, amended=False):
    rows = []
    sequence = 0

    def node(parent, name, *, numbered=False):
        nonlocal sequence
        result = ET.Element("{" + NS + "}" + name) if parent is None else ET.SubElement(parent, "{" + NS + "}" + name)
        if numbered:
            sequence += 1
            result.set("SeqNum", str(sequence))
            rows.append({"sequence": str(sequence), "element": name, "source": SERIALIZER})
        return result

    def value(parent, name, text, source):
        child = node(parent, name)
        child.text = text
        rows.append({"parent_sequence": parent.get("SeqNum"), "element": name, "value": text, "source": source})
        return child

    def name(parent, text, source, *, entity=False):
        child = node(parent, "PartyName", numbered=True)
        value(child, "PartyNameTypeCode", "L", SERIALIZER)
        value(child, "RawEntityIndividualLastName" if entity else "RawPartyFullName", text, source)

    def address(parent, *, customer=False):
        child = node(parent, "Address", numbered=True)
        fields = [("RawCityText", "Chicago" if customer else "Boston"), ("RawCountryCodeText", "US"),
                  ("RawStateCodeText", "IL" if customer else "MA"),
                  ("RawStreetAddress1Text", "200 Example Avenue" if customer else "100 Example Plaza"),
                  ("RawZIPCode", "60601" if customer else "02110")]
        for field, text in fields:
            value(child, field, text, CUSTOMER if customer else INSTITUTION)

    def identification(parent, text, kind, source):
        child = node(parent, "PartyIdentification", numbered=True)
        value(child, "PartyIdentificationNumberText", text, source)
        value(child, "PartyIdentificationTypeCode", kind, SERIALIZER)

    def phone(parent):
        child = node(parent, "PhoneNumber", numbered=True)
        value(child, "PhoneNumberText", "2025550100", INSTITUTION)

    def party(parent, kind):
        child = node(parent, "Party", numbered=True)
        value(child, "ActivityPartyTypeCode", kind, SERIALIZER)
        return child

    def organization(parent):
        child = node(parent, "OrganizationClassificationTypeSubtype", numbered=True)
        value(child, "OrganizationTypeID", "2", INSTITUTION)

    root = node(None, "EFilingBatchXML")
    location = "www.fincen.gov/base https://www.fincen.gov/sites/default/files/schema/base/EFL_SARXBatchSchema.xsd"
    root.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation", location)
    rows.append({"attribute": "xsi:schemaLocation", "value": location, "source": SERIALIZER})
    value(root, "FormTypeCode", "SARX", SERIALIZER)
    activity = node(root, "Activity", numbered=True)
    if amended:
        value(activity, "EFilingPriorDocumentNumber", "31000000000001", "synthetic-prior-accepted-filing/revision-1")
    value(activity, "FilingDateText", "20261006", SERIALIZER)
    value(activity, "FilingInstitutionNotetoFinCEN", "TEST", INSTITUTION)
    association = node(activity, "ActivityAssociation", numbered=True)
    value(association, "CorrectsAmendsPriorReportIndicator" if amended else "InitialReportIndicator", "Y", SERIALIZER)

    transmitter = party(activity, "35")
    name(transmitter, "Maple Research Bank", INSTITUTION)
    address(transmitter)
    phone(transmitter)
    identification(transmitter, "123456789", "4", INSTITUTION)
    identification(transmitter, "TBSATEST", "28", INSTITUTION)
    contact = party(activity, "37")
    name(contact, "Example Filing Contact", CONTACT)
    filer = party(activity, "30")
    value(filer, "PrimaryRegulatorTypeCode", "2", INSTITUTION)
    name(filer, "Maple Research Bank", INSTITUTION)
    address(filer)
    identification(filer, "123456789", "2", INSTITUTION)
    identification(filer, "1234567", "14", INSTITUTION)
    organization(filer)
    office = party(activity, "8")
    name(office, "MRB Reporting Office", CONTACT)
    phone(office)
    institution = party(activity, "34")
    value(institution, "NoBranchActivityInvolvedIndicator", "Y", INSTITUTION)
    value(institution, "PrimaryRegulatorTypeCode", "2", INSTITUTION)
    name(institution, "Maple Research Bank", INSTITUTION)
    address(institution)
    identification(institution, "123456789", "2", INSTITUTION)
    identification(institution, "1234567", "14", INSTITUTION)
    organization(institution)

    subject = party(activity, "33")
    value(subject, "PartyAsEntityOrganizationIndicator", "Y", CUSTOMER)
    value(subject, "PurchaserSenderIndicator", "Y", TRANSACTIONS)
    name(subject, "Maple Example Trading LLC", CUSTOMER, entity=True)
    address(subject, customer=True)
    identification(subject, "987654321", "2", CUSTOMER)
    unknown = node(subject, "PartyIdentification", numbered=True)
    value(unknown, "IdentificationPresentUnknownIndicator", "Y", CUSTOMER)
    relation = node(subject, "PartyAssociation", numbered=True)
    value(relation, "CustomerIndicator", "Y", CUSTOMER)
    value(relation, "RelationshipContinuesIndicator", "Y", CUSTOMER)
    value(relation, "SubjectRelationshipFinancialInstitutionTINText", "123456789", INSTITUTION)
    account_association = node(subject, "PartyAccountAssociation", numbered=True)
    value(account_association, "PartyAccountAssociationTypeCode", "7", SERIALIZER)
    account_institution = party(account_association, "41")
    identification(account_institution, "123456789", "4", INSTITUTION)
    account = node(account_institution, "Account", numbered=True)
    value(account, "AccountNumberText", "account-074", CUSTOMER)
    account_link = node(account, "PartyAccountAssociation", numbered=True)
    value(account_link, "PartyAccountAssociationTypeCode", "5", SERIALIZER)

    suspicious = node(activity, "SuspiciousActivity", numbered=True)
    value(suspicious, "SuspiciousActivityFromDateText", "20260908", TRANSACTIONS)
    value(suspicious, "SuspiciousActivityToDateText", "20260912", TRANSACTIONS)
    value(suspicious, "TotalSuspiciousAmountText", "84000", TRANSACTIONS)
    classification = node(suspicious, "SuspiciousActivityClassification", numbered=True)
    value(classification, "OtherSuspiciousActivityTypeText", "Unresolved business purpose of outgoing transfers", DECISION)
    value(classification, "SuspiciousActivitySubtypeID", "9999", DECISION)
    value(classification, "SuspiciousActivityTypeID", "9", DECISION)
    for subtype, kind in [("46", "5"), ("33", "6")]:
        asset = node(activity, "Assets", numbered=True)
        value(asset, "AssetSubtypeID", subtype, SERIALIZER)
        value(asset, "AssetTypeID", kind, SERIALIZER)
    narrative = node(activity, "ActivityNarrativeInformation", numbered=True)
    value(narrative, "ActivityNarrativeSequenceNumber", "1", SERIALIZER)
    text = ("Maple Research Bank reports three completed outgoing USD transfers from account account-074 of "
            "Maple Example Trading LLC on September 8, 10 and 12, 2026, totaling USD 84,000.00. "
            "The attributed transaction records are MRB-TXN-081, MRB-TXN-082 and MRB-TXN-083, each revision 1. "
            "The business purpose remains unresolved in this fictional investigation. Individual transfer amounts and "
            "counterparty identities are not supplied in the retained fixture evidence. The Officer selected initial reporting "
            "in MRB-DECISION-074 revision 1; these observations establish no criminal guilt or intent. Initial detection "
            "was September 14, 2026. Supporting due diligence, investigation, detection and decision records remain "
            "with the bank and are available through its Reporting Office. No supporting documents are attached.")
    if amended:
        text += " This full corrected/amended package explicitly identifies prior filing 31000000000001 and clarifies that counterparty identities remain unresolved."
    value(narrative, "ActivityNarrativeText", text, "bank-case-source/revision-2;" + DECISION + ";" + TRANSACTIONS)
    counts = {"TotalAmount": "84000", "PartyCount": str(sum(p.find("{" + NS + "}ActivityPartyTypeCode").text == "33" for p in root.findall(".//{" + NS + "}Party"))),
              "ActivityCount": "1", "ActivityAttachmentCount": "0", "AttachmentCount": "0"}
    for key, text in counts.items():
        root.set(key, text)
        rows.append({"attribute": key, "value": text, "source": SERIALIZER})
    raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    conditional = json.loads((Path(__file__).parent / "fixtures/bank-native-conditional-correspondence-revision1.json").read_text())
    return {"kind": "CORRECT_AMEND" if amended else "INITIAL", "payload": raw.decode("utf-8"),
            "payload_sha256": hashlib.sha256(raw).hexdigest(), "field_correspondence": rows,
            "conditional_correspondence": conditional,
            "source": SOURCE, "serializer": SERIALIZER}
