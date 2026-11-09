"""Closed offline validation of retained native bank XML and ACK shapes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin
import xml.etree.ElementTree as ET


PACKET = Path(__file__).resolve().parents[1] / "specimens/bank-sar-filing/native-format"


def validators():
    import xmlschema

    inventory = json.loads((PACKET / "schema-inventory.json").read_text())
    mapping = {}
    allowed = set()
    for row in inventory["files"]:
        path = (PACKET / row["path"]).resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("native schema identity mismatch: " + row["path"])
        allowed.add(path.as_uri())
        for uri in row["uris"]:
            mapping[uri] = path.as_uri()
    ism_uri = "https://www.fincen.gov/system/files/schema/base/Schema/ISM/IC-ISM.xsd"
    ism_path = PACKET / "schemas/IC-ISM.xsd"
    for row in ET.parse(ism_path).getroot():
        if row.tag == "{http://www.w3.org/2001/XMLSchema}import" and row.get("schemaLocation"):
            location = row.get("schemaLocation")
            selected = mapping[urljoin(ism_uri, location)]
            mapping[(ism_path.parent / location).resolve().as_uri()] = selected

    def local_uri(uri):
        if uri.startswith("/"):
            uri = Path(uri).resolve().as_uri()
        selected = mapping.get(uri, uri)
        if selected not in allowed:
            raise ValueError("undeclared native schema URI: " + uri)
        return selected

    result = {}
    for kind, name in (("SUBMISSION", "EFL_SARXBatchSchema.xsd"),
            ("MESSAGES", "MESSAGES.xsd"), ("ACK", "EFL_BatchAcknowledgementSchema.xsd")):
        result[kind] = xmlschema.XMLSchema11(PACKET / "schemas" / name,
            uri_mapper=local_uri, allow="local", defuse="always", use_fallback=False)
    return result


def validate_native(kind, raw, schemas):
    if kind not in schemas or not isinstance(raw, bytes) or len(raw) > 1_048_576:
        return False
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return False
    return schemas[kind].is_valid(raw)
