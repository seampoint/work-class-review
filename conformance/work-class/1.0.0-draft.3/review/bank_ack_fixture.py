"""Synthetic native FinCEN response shapes and an explicit correlation adapter.

Authentication of the complete byte-bound correlation envelope is a trusted
host input. XML schema admission alone does not authenticate the association.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
import re
import xml.etree.ElementTree as ET

from bank_native_fixture import NS, package


def messages(*, status="ACCEPTED", warning=False, amended=False):
    root = ET.Element("BatchMessages")
    batch = ET.SubElement(root, "Batch", {"type": "SARXST", "trackingID": "SXST26-00000075" if amended else "SXST26-00000074", "status": status,
        "filingName": "MRB-SAR-074-amended.xml" if amended else "MRB-SAR-074.xml", "filingDate": "2026-10-06"})
    message = ET.SubElement(batch, "Message", {"level": "FATAL" if status == "REJECTED" else "WARN" if warning else "INFO",
        "code": "C21" if warning else "SYNTHETIC"})
    ET.SubElement(message, "Context").text = "EFilingBatchXML/Activity[1]"
    ET.SubElement(message, "Description").text = "Synthetic offline response. No report was submitted."
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def acknowledgement(*, amended=False, warnings=False, activity_sequence="1", bsa_id=None):
    def node(parent, name, attributes=None):
        return ET.SubElement(parent, "{" + NS + "}" + name, attributes or {})
    root = ET.Element("{" + NS + "}EFilingBatchXML", {"SeqNum": "1", "StatusCode": "A"})
    submission = node(root, "EFilingSubmissionXML", {"SeqNum": "1", "StatusCode": "A"})
    activity = node(submission, "EFilingActivityXML", {"SeqNum": activity_sequence})
    node(activity, "BSAID").text = bsa_id or ("31000000000002" if amended else "31000000000001")
    for sequence, code in enumerate(("C21", "C4") if warnings else (None,), 1):
        error = node(activity, "EFilingActivityErrorXML", {"SeqNum": str(sequence)})
        if code is not None:
            for name, value in (("ErrorContextText", "EFilingBatchXML/Activity[1]"), ("ErrorElementNameText", "PartyIdentificationNumberText" if code == "C21" else "RawIndividualFirstName"),
                ("ErrorLevelText", "WARN"), ("ErrorText", "Synthetic warning for correlation and complete-inventory tests."), ("ErrorTypeCode", code)):
                node(error, name).text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _parse(raw):
    if not isinstance(raw, bytes) or len(raw) > 1_048_576:
        raise ValueError("response byte limit")
    text = raw.decode("utf-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML declarations unavailable in response profile")
    return ET.fromstring(raw)


def correlate(message_bytes, ack_bytes, correlation, *, submitted_payload, validate_native, authenticate_correlation, ack_received_at, observation_id):
    """Require the authenticated exact envelope; preserve native inventories."""
    if not isinstance(ack_received_at, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", ack_received_at):
        raise ValueError("host observation time unavailable")
    datetime.strptime(ack_received_at, "%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(observation_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9._:/-]{0,127}", observation_id):
        raise ValueError("host observation identity unavailable")
    fields = {"tracking_id", "filing_name", "ack_file_submission_tracking_id", "activity_sequence",
        "native_payload_sha256", "prior_bsa_identifier", "message_sha256", "acknowledgement_sha256"}
    if not isinstance(correlation, dict) or set(correlation) != fields:
        raise ValueError("complete submission correlation envelope unavailable")
    if not isinstance(submitted_payload, bytes) or hashlib.sha256(submitted_payload).hexdigest() != correlation["native_payload_sha256"]:
        raise ValueError("submitted payload identity mismatch")
    if not isinstance(message_bytes, bytes) or hashlib.sha256(message_bytes).hexdigest() != correlation["message_sha256"]:
        raise ValueError("processing message identity mismatch")
    if ack_bytes is not None and not isinstance(ack_bytes, bytes):
        raise ValueError("acknowledgement byte identity unavailable")
    ack_sha256 = hashlib.sha256(ack_bytes).hexdigest() if ack_bytes is not None else None
    if ack_sha256 != correlation["acknowledgement_sha256"]:
        raise ValueError("acknowledgement byte identity mismatch")
    authenticated = authenticate_correlation(dict(correlation))
    if not isinstance(authenticated, dict) or authenticated != correlation:
        raise ValueError("complete submission correlation authentication unavailable")
    message_root = _parse(message_bytes)
    if validate_native("SUBMISSION", submitted_payload) is not True or validate_native("MESSAGES", message_bytes) is not True:
        raise ValueError("official native schema admission unavailable")
    submitted = _parse(submitted_payload)
    activities = submitted.findall("{" + NS + "}Activity")
    if len(activities) != 1 or activities[0].get("SeqNum") != correlation["activity_sequence"]:
        raise ValueError("submitted activity correlation mismatch")
    prior = activities[0].find("{" + NS + "}EFilingPriorDocumentNumber")
    if (prior.text if prior is not None else None) != correlation["prior_bsa_identifier"]:
        raise ValueError("prior filing correlation mismatch")
    if message_root.tag != "BatchMessages" or message_root.attrib or len(message_root) != 1:
        raise ValueError("unexpected message batch")
    batch = message_root[0]
    if batch.tag != "Batch" or set(batch.attrib) != {"type", "trackingID", "status", "filingName", "filingDate"}:
        raise ValueError("unexpected message identity")
    if batch.get("type") != "SARXST" or batch.get("status") not in {"ACCEPTED", "ACCEPTED-WITH-WARNINGS", "REJECTED"}:
        raise ValueError("unsupported message disposition")
    if batch.get("trackingID") != correlation["tracking_id"] or batch.get("filingName") != correlation["filing_name"]:
        raise ValueError("message correlation mismatch")
    processing = []
    for row in batch:
        if row.tag != "Message" or set(row.attrib) != {"level", "code"} or [child.tag for child in row] != ["Context", "Description"]:
            raise ValueError("incomplete message inventory")
        if row.get("level") not in {"INFO", "WARN", "FATAL"}:
            raise ValueError("unsupported message level")
        processing.append({"level": row.get("level"), "code": row.get("code"), "context": row[0].text or "", "description": row[1].text or ""})
    if not processing:
        raise ValueError("message inventory unavailable")
    result = {"tracking_id": batch.get("trackingID"), "filing_name": batch.get("filingName"),
        "provider_submission_date": batch.get("filingDate"), "processing_status": batch.get("status"), "processing_messages": processing,
        "message_sha256": hashlib.sha256(message_bytes).hexdigest(), "acknowledgement_sha256": None,
        "acknowledgement_received_at": ack_received_at, "host_observation_id": observation_id,
        "provider_event_time": None, "historical_filing_instant": None, "bsa_identifier": None,
        "acknowledgement_errors": [], "filing_established": False, "no_filing_established": False,
        "correction_required": False, "warning_review_required": False}
    if ack_bytes is None:
        # Even REJECTED does not authenticate absence for another route or attempt.
        return result
    if batch.get("status") == "REJECTED" or correlation["ack_file_submission_tracking_id"] != batch.get("trackingID"):
        raise ValueError("acknowledgement submission mismatch")
    root = _parse(ack_bytes)
    if validate_native("ACK", ack_bytes) is not True:
        raise ValueError("official acknowledgement schema admission unavailable")
    tag = lambda name: "{" + NS + "}" + name
    if root.tag != tag("EFilingBatchXML") or root.attrib != {"SeqNum": "1", "StatusCode": "A"} or len(root) != 1:
        raise ValueError("unexpected acknowledgement batch")
    submission = root[0]
    if submission.tag != tag("EFilingSubmissionXML") or submission.attrib != {"SeqNum": "1", "StatusCode": "A"} or len(submission) != 1:
        raise ValueError("unexpected acknowledgement submission")
    activity = submission[0]
    if activity.tag != tag("EFilingActivityXML") or activity.attrib != {"SeqNum": correlation["activity_sequence"]}:
        raise ValueError("activity correlation mismatch")
    if len(activity) < 2 or activity[0].tag != tag("BSAID") or not re.fullmatch(r"[0-9]{14}", activity[0].text or ""):
        raise ValueError("BSA identifier unavailable")
    bsa_id = activity[0].text
    if correlation["prior_bsa_identifier"] is not None and bsa_id == correlation["prior_bsa_identifier"]:
        raise ValueError("amendment reuses prior acknowledgement")
    error_names = ["ErrorContextText", "ErrorElementNameText", "ErrorLevelText", "ErrorText", "ErrorTypeCode"]
    errors = []
    seen = set()
    for row in activity[1:]:
        if row.tag != tag("EFilingActivityErrorXML") or set(row.attrib) != {"SeqNum"} or row.get("SeqNum") != str(len(errors) + 1) or row.get("SeqNum") in seen:
            raise ValueError("invalid error inventory identity")
        seen.add(row.get("SeqNum"))
        names = [child.tag.removeprefix("{" + NS + "}") for child in row]
        if names != [name for name in error_names if name in names] or len(names) != len(set(names)):
            raise ValueError("invalid error inventory fields")
        fields = {name: child.text or "" for name, child in zip(names, row)}
        errors.append({"sequence": row.get("SeqNum"), "fields": fields})
        if fields:
            result["warning_review_required"] = True
            # This bounded map is pinned to guide1.7 Attachment A, C21*.
            if fields.get("ErrorTypeCode") == "C21":
                result["correction_required"] = True
    result.update(acknowledgement_sha256=hashlib.sha256(ack_bytes).hexdigest(), bsa_identifier=bsa_id,
        acknowledgement_errors=errors, filing_established=True)
    return result


def selected_correlation(*, message_bytes, ack_bytes, amended=False):
    selected = package(amended=amended)
    document = ET.fromstring(selected["payload"])
    return {"tracking_id": "SXST26-00000075" if amended else "SXST26-00000074", "filing_name": "MRB-SAR-074-amended.xml" if amended else "MRB-SAR-074.xml",
        "ack_file_submission_tracking_id": "SXST26-00000075" if amended else "SXST26-00000074", "activity_sequence": document.find("{" + NS + "}Activity").get("SeqNum"),
        "native_payload_sha256": selected["payload_sha256"], "prior_bsa_identifier": "31000000000001" if amended else None,
        "message_sha256": hashlib.sha256(message_bytes).hexdigest(),
        "acknowledgement_sha256": hashlib.sha256(ack_bytes).hexdigest() if ack_bytes is not None else None}
