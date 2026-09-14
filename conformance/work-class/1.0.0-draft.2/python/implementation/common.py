"""Shared draft-2 transport, canonical JSON, digest, and schema functions."""

from __future__ import annotations

import base64
import datetime as datetime
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "input"
VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from jsonschema import Draft202012Validator, RefResolver  # noqa: E402


IDENTITY = "seampoint.work-class/1.0.0-draft.2"
PREFIX = IDENTITY + "/"
PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.2"
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9._:/-]{0,127}$")


class Refusal(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class NumberToken(ValueError):
    pass


class DuplicateKey(ValueError):
    pass


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise DuplicateKey(key)
        result[key] = value
    return result


def _number(value):
    raise NumberToken(value)


def parse_json(raw: bytes):
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_pairs,
        parse_int=_number,
        parse_float=_number,
        parse_constant=_number,
    )
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise UnicodeError("lone surrogate")
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return value


def parse_document(raw: bytes):
    """Parse trusted contract JSON while still rejecting duplicate keys."""
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)


def canonical(value) -> bytes:
    if value is None:
        return b"null"
    if type(value) is bool:
        return b"true" if value else b"false"
    if type(value) is str:
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise UnicodeError("lone surrogate")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if type(value) is list:
        return b"[" + b",".join(canonical(item) for item in value) + b"]"
    if type(value) is dict:
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        return b"{" + b",".join(canonical(key) + b":" + canonical(value[key]) for key in keys) + b"}"
    raise ValueError("JSON numbers are forbidden")


def digest(kind: str, value) -> str:
    subject = (PREFIX + kind + "\n").encode("utf-8") + canonical(value)
    return "sha256:" + hashlib.sha256(subject).hexdigest()


def manifest_pin() -> str:
    manifest_path = INPUT / "contract-manifest.json"
    raw = manifest_path.read_bytes()
    manifest = parse_document(raw)
    if manifest.get("identity") != IDENTITY:
        raise RuntimeError("wrong contract identity")
    if set(manifest) != {"claim_ceiling", "files", "identity", "status"}:
        raise RuntimeError("invalid contract manifest shape")
    entries = manifest.get("files", [])
    paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    if len(paths) != len(entries) or paths != sorted(paths, key=lambda value: value.encode("utf-8")):
        raise RuntimeError("manifest paths are not sorted")
    seen = set()
    for entry in entries:
        if set(entry) != {"path", "sha256"} or not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            raise RuntimeError("invalid manifest entry")
        relative = entry.get("path")
        if not isinstance(relative, str) or relative in seen or Path(relative).is_absolute():
            raise RuntimeError("invalid manifest path")
        if any(part in ("", ".", "..") for part in relative.split("/")):
            raise RuntimeError("invalid manifest path")
        seen.add(relative)
        file_path = INPUT / relative
        if not file_path.is_file() or file_path.is_symlink():
            raise RuntimeError(f"missing manifested file: {relative}")
        if hashlib.sha256(file_path.read_bytes()).hexdigest() != entry.get("sha256"):
            raise RuntimeError(f"manifest hash mismatch: {relative}")
    required = {
        "Specification.md", "PROTOCOL.md", "AGGREGATES.md", "AUTHORITY.md",
        "AUTHORITY-CHECKS.md", "RESERVATIONS.md", "RESERVATION-RECORDS.md",
        "LIFECYCLE.md", "COMPOSITION.md", "EXTERNAL-DEPENDENCIES.md",
        "SCOPE-AND-BOUNDARY.md", "README.md", "aggregate.schema.json", "authority.schema.json",
        "reservation.schema.json", "work-class.schema.json", "lifecycle.schema.json",
        "evidence.schema.json", "boundary.schema.json", "protocol.schema.json",
        "schema-bundle.json", "requirements.json",
    }
    if required != seen:
        raise RuntimeError("manifest file set differs from the candidate distribution")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


PIN = manifest_pin()
SCHEMA_FILES = (
    "aggregate.schema.json", "authority.schema.json", "boundary.schema.json",
    "evidence.schema.json", "lifecycle.schema.json", "protocol.schema.json",
    "reservation.schema.json", "work-class.schema.json",
)
SCHEMAS = {name: parse_document((INPUT / name).read_bytes()) for name in SCHEMA_FILES}
BUNDLE = parse_document((INPUT / "schema-bundle.json").read_bytes())
if set(BUNDLE) != {"identity", "status", "resolution", "schemas"}:
    raise RuntimeError("invalid schema bundle shape")
bundle_rows = BUNDLE["schemas"]
if [row["path"] for row in bundle_rows] != sorted(SCHEMA_FILES, key=lambda value: value.encode("utf-8")):
    raise RuntimeError("schema bundle file set or order is invalid")
for row in bundle_rows:
    if set(row) != {"uri", "path", "sha256"}:
        raise RuntimeError("invalid schema bundle entry")
    raw = (INPUT / row["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row["sha256"] or SCHEMAS[row["path"]].get("$id") != row["uri"]:
        raise RuntimeError("schema bundle binding mismatch")
SCHEMA_STORE = {row["uri"]: SCHEMAS[row["path"]] for row in bundle_rows}


def schema_valid(value, filename: str, definition: str | None = None) -> bool:
    schema = SCHEMAS[filename]
    target = schema if definition is None else {"$ref": f"{schema['$id']}#/$defs/{definition}"}
    try:
        resolver = RefResolver(schema["$id"], schema, store=SCHEMA_STORE)
        return not list(Draft202012Validator(target, resolver=resolver).iter_errors(value))
    except (KeyError, TypeError, ValueError):
        return False


def artifact_bytes(encoded: str):
    if not isinstance(encoded, str):
        raise Refusal("ARTIFACT_ENCODING_INVALID")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise Refusal("ARTIFACT_ENCODING_INVALID") from None
    if base64.b64encode(raw).decode("ascii") != encoded:
        raise Refusal("ARTIFACT_ENCODING_INVALID")
    try:
        value = parse_json(raw)
    except NumberToken:
        raise Refusal("ARTIFACT_NONCANONICAL") from None
    except (DuplicateKey, ValueError, UnicodeError):
        raise Refusal("ARTIFACT_ENCODING_INVALID") from None
    try:
        encoded_canonical = canonical(value)
    except (ValueError, UnicodeError):
        raise Refusal("ARTIFACT_ENCODING_INVALID") from None
    if raw != encoded_canonical:
        raise Refusal("ARTIFACT_NONCANONICAL")
    return value


def utf8_sorted_unique(values) -> bool:
    return len(values) == len(set(values)) and values == sorted(values, key=lambda value: value.encode("utf-8"))


def valid_instant(value: str, nanoseconds: bool = False) -> bool:
    fraction = r"(?:\.[0-9]{9})?" if nanoseconds else ""
    if not isinstance(value, str) or re.fullmatch(
        rf"[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}{fraction}Z",
        value,
    ) is None:
        return False
    try:
        datetime.datetime.fromisoformat(value[:-1] + "+00:00")
        return not value.startswith("0000-")
    except ValueError:
        return False


def readback_lines(value):
    def walk(node, pointer=""):
        if type(node) is dict:
            if not node:
                yield pointer, "{}"
            for key in sorted(node, key=lambda item: item.encode("utf-8")):
                token = key.replace("~", "~0").replace("/", "~1")
                yield from walk(node[key], pointer + "/" + token)
        elif type(node) is list:
            if not node:
                yield pointer, "[]"
            for index, item in enumerate(node):
                yield from walk(item, pointer + "/" + str(index))
        else:
            yield pointer, canonical(node).decode("utf-8")

    return [
        {"path": pointer, "value": value_text}
        for pointer, value_text in sorted(walk(value), key=lambda row: row[0].encode("utf-8"))
    ]
