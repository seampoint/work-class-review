"""Independent draft-2 shared-reservation reference.

The authority and aggregate evaluators are loaded from the independently
supplied Python baselines.  Transition semantics remain in this module.
"""
from __future__ import annotations

import base64
import copy
import datetime as _dt
import hashlib
import importlib.util
import json
import re
import sys
import threading
from decimal import Decimal
from pathlib import Path

from .common import PIN

try:
    from jsonschema import Draft202012Validator, RefResolver
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))
    from jsonschema import Draft202012Validator, RefResolver


ROOT = Path(__file__).resolve().parents[1]
PREFIX = "seampoint.work-class/1.0.0-draft.2/"
DEVELOPMENT_PIN = PIN

VENDOR = ROOT / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

RESERVATION_SCHEMA = json.loads(
    (ROOT / "input/reservation.schema.json").read_text()
)
AGGREGATE_SCHEMA = json.loads((ROOT / "input/aggregate.schema.json").read_text())
AUTHORITY_SCHEMA = json.loads((ROOT / "input/authority.schema.json").read_text())
SCHEMA_STORE = {
    RESERVATION_SCHEMA["$id"]: RESERVATION_SCHEMA,
    AGGREGATE_SCHEMA["$id"]: AGGREGATE_SCHEMA,
    AUTHORITY_SCHEMA["$id"]: AUTHORITY_SCHEMA,
}
RESOLVER = RefResolver(RESERVATION_SCHEMA["$id"], RESERVATION_SCHEMA, store=SCHEMA_STORE)

_AUTHORITY_ROOT = ROOT / "implementation"
if str(_AUTHORITY_ROOT) not in sys.path:
    sys.path.insert(0, str(_AUTHORITY_ROOT))
from authority import evaluate_authority as _evaluate_authority  # noqa: E402
from authority import _inside as _authority_inside  # noqa: E402
from authority import _instant as _authority_instant  # noqa: E402

_AGGREGATE_ROOT = ROOT / "implementation"
_aggregate_spec = importlib.util.spec_from_file_location(
    "reservation_v2_aggregate_dependency", _AGGREGATE_ROOT / "core.py"
)
if _aggregate_spec is None or _aggregate_spec.loader is None:
    raise ImportError("draft-2 aggregate dependency is unavailable")
_aggregate = importlib.util.module_from_spec(_aggregate_spec)
_aggregate_spec.loader.exec_module(_aggregate)
_AggregateEval = _aggregate.Eval
_aggregate_semantic_validate = _aggregate.semantic_validate
_aggregate_digest = _aggregate.digest
_aggregate_instant = _aggregate.instant
_aggregate_format = _aggregate.format_instant
_aggregate_refusal = _aggregate.Refusal


_STAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:\d{2}:\d{2}Z$")


class _AdmissionError(Exception):
    def __init__(self, code: str):
        self.code = code


def canon(value):
    """Serialize the number-free RFC-8785 subset used by the contract."""
    if isinstance(value, dict):
        return b"{" + b",".join(
            canon(key) + b":" + canon(value[key])
            for key in sorted(value, key=lambda key: key.encode("utf-16-be"))
        ) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(canon(item) for item in value) + b"]"
    if value is None or type(value) is bool or type(value) is str:
        if isinstance(value, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("lone surrogate")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    raise ValueError("JSON numbers are not admitted")


def digest(kind, value):
    return "sha256:" + hashlib.sha256((PREFIX + kind + "\n").encode() + canon(value)).hexdigest()


def _valid(value, definition):
    try:
        validator = Draft202012Validator(
            {"$ref": f"{RESERVATION_SCHEMA['$id']}#/$defs/{definition}"},
            resolver=RESOLVER,
        )
        return not list(validator.iter_errors(value))
    except (TypeError, ValueError, KeyError):
        return False


def _authority_valid(value, definition):
    try:
        resolver = RefResolver(AUTHORITY_SCHEMA["$id"], AUTHORITY_SCHEMA, store=SCHEMA_STORE)
        return not list(
            Draft202012Validator(
                {"$ref": f"{AUTHORITY_SCHEMA['$id']}#/$defs/{definition}"},
                resolver=resolver,
            ).iter_errors(value)
        )
    except (TypeError, ValueError, KeyError):
        return False


def _aggregate_valid(value, definition):
    try:
        resolver = RefResolver(AGGREGATE_SCHEMA["$id"], AGGREGATE_SCHEMA, store=SCHEMA_STORE)
        return not list(
            Draft202012Validator(
                {"$ref": f"{AGGREGATE_SCHEMA['$id']}#/$defs/{definition}"},
                resolver=resolver,
            ).iter_errors(value)
        )
    except (TypeError, ValueError, KeyError):
        return False


def _state_digest(state):
    return digest("reservation-state", state)


def _core_digest(core):
    return digest("reservation-core", core)


def _event_digest(event):
    return digest("reservation-event", event)


def _receipt_digest(receipt):
    return digest("reservation-receipt", receipt)


def _zero_state(configuration, selected_pin):
    return {
        "schema": PREFIX + "reservation-state",
        "specification_pin": selected_pin,
        "core": {
            "configuration": copy.deepcopy(configuration),
            "revision": "0",
            "last_clock": None,
            "budgets": [],
            "reservations": [],
            "effects": [],
        },
        "receipts": [],
    }


def _configuration_valid(configuration):
    if not _valid(configuration, "configuration"):
        return False
    if configuration["schema"] != PREFIX + "reservation-registry":
        return False
    slots = configuration["slots"]
    if any(slots[i]["anchor"] >= slots[i + 1]["anchor"] for i in range(len(slots) - 1)):
        return False
    return len({slot["exposure_domain"] for slot in slots}) == len(slots)


def initial_state(configuration, selected_pin):
    if not isinstance(selected_pin, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", selected_pin):
        raise ValueError("invalid selected specification pin")
    if not _configuration_valid(configuration):
        raise ValueError("invalid registry configuration")
    return _zero_state(configuration, selected_pin)


def _parse_time(value):
    if not isinstance(value, str) or not _STAMP.fullmatch(value):
        raise ValueError("invalid UTC second")
    try:
        return _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid UTC second") from exc


def _format_time(value):
    return value.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _add_seconds(value, seconds):
    return _format_time(_parse_time(value) + _dt.timedelta(seconds=int(seconds)))


def _clock(event, configuration, last_clock):
    clock = event["clock"]
    if clock["source"] != configuration["clock_source"]:
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    if clock["status"] == "UNAVAILABLE":
        return None
    if last_clock is not None and clock["instant"] < last_clock:
        raise _AdmissionError("CLOCK_INVALID")
    _parse_time(clock["instant"])
    return clock["instant"]


def _refusal(code, state, state_digest):
    return {
        "status": "REFUSED",
        "code": code,
        "path": "",
        "state": copy.deepcopy(state),
        "state_digest": state_digest,
    }


def _records(rows):
    return {row["id"]: row for row in rows}


def _definition_types(definition):
    return {row["id"]: row for row in definition["aggregate"]["types"]}


def _value_matches(value, type_ref, types):
    if not isinstance(value, dict) or set(value) != {"type_ref", "value"} or value["type_ref"] != type_ref:
        return False
    type_def = types.get(type_ref)
    if type_def is None:
        return False
    raw = value["value"]
    kind = type_def["kind"]
    if kind in ("STRING", "IDENTITY"):
        return isinstance(raw, str) and (kind != "IDENTITY" or raw != "")
    if kind == "BOOLEAN":
        return type(raw) is bool
    if kind == "INTEGER":
        return isinstance(raw, str) and re.fullmatch(r"0|[1-9][0-9]*", raw) is not None
    if kind == "DECIMAL":
        if not isinstance(raw, str) or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?", raw) is None:
            return False
        return not type_def["nonnegative"] or not raw.startswith("-")
    return False


def _aggregate_mapping_fields(definition):
    aggregate = definition["aggregate"]["aggregate"]
    fields = {}
    for mapping in aggregate["mappings"]:
        for field in mapping["key_fields"]:
            fields[field] = next(
                type_ref for type_ref, name in zip(aggregate["key_types"], mapping["key_fields"]) if name == field
            )
        contribution = mapping["contribution"]
        if contribution["kind"] != "COUNT":
            fields[contribution["field"]] = aggregate["result_type"] if contribution["kind"] == "SUM" else aggregate["element_type"]
    return fields


def _projection_for(authorizations, authority, budget):
    proposal = authority["proposal"]
    candidates = [
        row
        for row in authorizations
        if row["work_class"] == proposal["work_class"]
        and row["step"] == proposal["step"]
        and row["work_class_digest"] == digest("authority-work-class", authority["work_class"])
        and row["envelope_digest"] == digest("authority-envelope", authority["envelope"])
        and row["principal"] == budget["definition"]["principal"]
    ]
    if len(candidates) != 1:
        raise _AdmissionError("REFERENCE_INVALID")
    authorization = candidates[0]
    if not _authority_valid(authorization["authority_definition"], "definition"):
        raise _AdmissionError("REFERENCE_INVALID")
    work_class = authorization["authority_definition"]["work_class"]
    steps = _records(work_class["steps"])
    step = steps.get(proposal["step"])
    if step is None:
        raise _AdmissionError("REFERENCE_INVALID")
    native_fields = {row["name"]: row for row in step["fields"]}
    budget_types = _definition_types(budget["definition"])
    budget_fields = _aggregate_mapping_fields(budget["definition"])
    projection = authorization["projection"]
    if len({row["native_field"] for row in projection}) != len(projection):
        raise _AdmissionError("REFERENCE_INVALID")
    if any(projection[i]["budget_field"] >= projection[i + 1]["budget_field"] for i in range(len(projection) - 1)):
        raise _AdmissionError("REFERENCE_INVALID")
    projected = {}
    for row in projection:
        native = native_fields.get(row["native_field"])
        budget_type = budget_types.get(row["budget_type"])
        native_types = _records(work_class["types"])
        native_type = native_types.get(row["native_type"])
        if native is None or native["type_ref"] != row["native_type"] or native_type is None:
            raise _AdmissionError("REFERENCE_INVALID")
        if row["budget_field"] not in budget_fields or budget_type is None:
            raise _AdmissionError("REFERENCE_INVALID")
        if (native_type["kind"], native_type.get("unit"), native_type["nonnegative"]) != (
            budget_type["kind"], budget_type.get("unit"), budget_type["nonnegative"]
        ):
            raise _AdmissionError("TYPE_INVALID")
        source = next((field for field in proposal["fields"] if field["name"] == row["native_field"]), None)
        if source is None or source["value"]["type_ref"] != row["native_type"]:
            raise _AdmissionError("INPUT_INVALID")
        projected[row["budget_field"]] = {
            "type_ref": row["budget_type"],
            "value": source["value"]["value"],
        }
    for field, type_ref in budget_fields.items():
        if field not in projected:
            raise _AdmissionError("INPUT_INVALID")
        if not _value_matches(projected[field], type_ref, budget_types):
            raise _AdmissionError("TYPE_INVALID")
    return authorization, projected


def _validate_history(history, budget, clock, previous_history=None):
    definition = budget["definition"]
    aggregate = definition["aggregate"]["aggregate"]
    if not _valid(history, "history"):
        raise _AdmissionError("SCHEMA_INVALID")
    if history["budget_digest"] != budget["definition_digest"]:
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    source = aggregate["committed_source"]
    if history["provider"] != source["provider"] or history["source"] != source["source"]:
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    if previous_history is not None:
        if history["status"] == "AVAILABLE" and previous_history["status"] == "AVAILABLE":
            old = previous_history["journal"]
            if len(history["journal"]) < len(old) or history["journal"][: len(old)] != old:
                raise _AdmissionError("INPUT_INVALID")
    if history["status"] != "AVAILABLE":
        return
    if history["revision"] != str(len(history["journal"])):
        raise _AdmissionError("INPUT_INVALID")
    if [row["sequence"] for row in history["journal"]] != [str(i) for i in range(1, len(history["journal"]) + 1)]:
        raise _AdmissionError("INPUT_INVALID")
    now = _parse_time(clock)
    types = _definition_types(definition)
    source_fields = set(source["key_fields"])
    if source["contribution"]["kind"] != "COUNT":
        source_fields.add(source["contribution"]["field"])
    source_types = {name: type_ref for name, type_ref in zip(aggregate["key_fields"], aggregate["key_types"])} if "key_fields" in aggregate else {}
    # The source key fields use the aggregate mapping's declared key types.
    for mapping in aggregate["mappings"]:
        for name, type_ref in zip(mapping["key_fields"], aggregate["key_types"]):
            source_types[name] = type_ref
        if mapping["contribution"]["kind"] != "COUNT":
            source_types[mapping["contribution"]["field"]] = aggregate["result_type"] if mapping["contribution"]["kind"] == "SUM" else aggregate["element_type"]
    for row in history["journal"]:
        event = row["event"]
        if event["state"] == "RETRACTED":
            continue
        occurred = _parse_time(event["occurred_at"])
        if occurred > _parse_time(history["as_of"]) or _parse_time(history["as_of"]) > now:
            raise _AdmissionError("INPUT_INVALID")
        names = [field["name"] for field in event["fields"]]
        if names != sorted(names) or len(names) != len(set(names)):
            raise _AdmissionError("INPUT_INVALID")
        if set(names) != source_fields:
            raise _AdmissionError("INPUT_INVALID")
        for field in event["fields"]:
            if field["name"] not in source_types or not _value_matches(field["value"], source_types[field["name"]], types):
                raise _AdmissionError("TYPE_INVALID")


def _history_is_fresh(history, budget, clock):
    if history["status"] != "AVAILABLE":
        return False
    freshness = budget["definition"]["aggregate"]["aggregate"]["committed_source"]["freshness"]
    if freshness["kind"] == "NONE":
        return True
    if freshness["kind"] == "EXACT_REVISION":
        return history["revision"] == freshness["revision"]
    age = Decimal((_parse_time(clock) - _parse_time(history["as_of"])).total_seconds())
    return age <= Decimal(freshness["seconds"])


def _admin_subject(event, configuration):
    registry_digest = digest("reservation-registry", configuration)
    return {
        "registry_digest": registry_digest,
        "event_id": event["id"],
        "expected_revision": event["expected_revision"],
        "kind": event["kind"],
        "clock": event["clock"],
        "payload": event["payload"],
    }


def _authenticated(host, expected):
    actual = {
        (row["kind"], row["record_digest"], row["provider"], row["source"])
        for row in host["authenticated_records"]
    }
    return actual == expected


def _validate_native_host(host, configuration, native):
    if not _valid(host,"host"):
        raise _AdmissionError("SCHEMA_INVALID")
    if host["registry_digest"]!=digest("reservation-registry",configuration):
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    expected={("NATIVE_OUTCOME",digest("reservation-native-outcome",native),native["provider"],native["source"])}
    if not _authenticated(host,expected):
        actual={(row["kind"],row["record_digest"],row["provider"],row["source"]) for row in host["authenticated_records"]}
        raise _AdmissionError("EVIDENCE_UNAVAILABLE" if len(actual)<len(expected) else "DEPENDENCY_MISMATCH")


def _native_fact(native):
    value=copy.deepcopy(native)
    value.pop("id",None);value.pop("evidence_ref",None)
    return canon(value)


def _validate_admin(event, host, configuration, extra_records=()):
    if not _valid(host, "host"):
        raise _AdmissionError("SCHEMA_INVALID")
    if host["registry_digest"] != digest("reservation-registry", configuration):
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    act = event["administration"]["act"]
    returned = event["administration"]["returned"]
    bases = [row for row in host["administration_bases"] if row["id"] == act["basis"]]
    if len(bases) != 1:
        raise _AdmissionError("EVIDENCE_UNAVAILABLE")
    basis = bases[0]
    basis_binding = (
        basis["registry_digest"] == digest("reservation-registry", configuration)
        and basis["principal"] == configuration["principal"]
        and basis["role"] == configuration["administration_role"]
        and basis["provider"] == configuration["administration_provider"]
        and basis["source"] == configuration["administration_source"]
        and basis["at"] == event["clock"]["instant"]
        and event["kind"] in basis["operations"]
    )
    if not basis_binding:
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    if basis["kind"] != "HUMAN" or basis["revoked"] or not _authority_inside(basis["validity"], _authority_instant(event["clock"]["instant"])):
        raise _AdmissionError("ADMINISTRATION_NOT_ESTABLISHED")
    if act["disposition"] != "ACCEPT":
        raise _AdmissionError("ADMINISTRATION_NOT_ESTABLISHED")
    if (
        act["actor"] != basis["actor"]
        or act["principal"] != configuration["principal"]
        or act["role"] != configuration["administration_role"]
        or act["kind"] != event["kind"]
        or act["occurred_at"] != event["clock"]["instant"]
        or act["subject_digest"] != digest("reservation-administration-subject", _admin_subject(event, configuration))
    ):
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    try:
        raw = base64.b64decode(returned["act_bytes_base64"], validate=True)
    except (ValueError, TypeError):
        raise _AdmissionError("INPUT_INVALID")
    if (
        raw != canon(act)
        or returned["act_digest"] != digest("reservation-administration-act", act)
        or returned["actor"] != act["actor"]
        or returned["provider"] != configuration["administration_provider"]
        or returned["source"] != configuration["administration_source"]
        or returned["returned_at"] != event["clock"]["instant"]
    ):
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    expected = {
        (
            "ADMIN_RETURN",
            digest("reservation-administration-return", returned),
            configuration["administration_provider"],
            configuration["administration_source"],
        ),
    }
    if event["kind"] == "REGISTER":
        history = event["payload"]["history"]
        expected.add(("HISTORY", digest("budget-history", history), history["provider"], history["source"]))
    expected.update(extra_records)
    if not _authenticated(host, expected):
        supplied = {(kind, row["record_digest"], row["provider"], row["source"]) for kind, row in []}
        if len(host["authenticated_records"]) < len(expected):
            raise _AdmissionError("EVIDENCE_UNAVAILABLE")
        raise _AdmissionError("DEPENDENCY_MISMATCH")


def _validate_registration(event, host, state):
    configuration = state["core"]["configuration"]
    _validate_admin(event, host, configuration)
    payload = event["payload"]
    definition = payload["definition"]
    if definition["schema"] != PREFIX + "budget-definition":
        raise _AdmissionError("VERSION_UNSUPPORTED")
    definition_digest = digest("budget-definition", definition)
    slot = next((row for row in configuration["slots"] if row["anchor"] == definition["anchor"]), None)
    if slot is None:
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    if slot["exposure_domain"] != definition["exposure_domain"] or definition["principal"] != configuration["principal"]:
        raise _AdmissionError("REFERENCE_INVALID")
    if not _aggregate_valid(definition["aggregate"], "definition"):
        raise _AdmissionError("SCHEMA_INVALID")
    aggregate = definition["aggregate"]["aggregate"]
    if aggregate["reducer"] not in {"COUNT", "SUM", "CARDINALITY"} or aggregate["operator"] not in {"LT", "LTE"}:
        raise _AdmissionError("UNSUPPORTED_RELATION")
    if aggregate["pending_policy"] != "INCLUDE_ALL_RESERVED" or aggregate["time"]["precision"] != "SECOND" or aggregate["window"]["kind"] not in {"ROLLING", "CALENDAR"}:
        raise _AdmissionError("UNSUPPORTED_RELATION")
    policy = definition["reservation_policy"]
    if not policy["pending_across_windows"] or policy["unexpected_effect"] != "BLOCK_AFFECTED_PARTITIONS" or policy["unprojectable_effect"] != "BLOCK_ANCHOR":
        raise _AdmissionError("UNSUPPORTED_RELATION")
    if int(policy["permit_seconds"]) <= 0:
        raise _AdmissionError("INPUT_INVALID")
    if any(b["definition"]["anchor"] == definition["anchor"] for b in state["core"]["budgets"]):
        raise _AdmissionError("DEFINITION_CONFLICT")
    _validate_history(payload["history"], {"definition": definition, "definition_digest": definition_digest}, event["clock"]["instant"])
    if payload["history"]["budget_digest"] != definition_digest:
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    auths = payload["authorizations"]
    if any(auths[i]["id"] >= auths[i + 1]["id"] for i in range(len(auths) - 1)):
        raise _AdmissionError("REFERENCE_INVALID")
    classes = set(definition["contributor_classes"])
    for authorization in auths:
        if not _valid(authorization, "authorization"):
            raise _AdmissionError("SCHEMA_INVALID")
        authority_definition = authorization["authority_definition"]
        if (
            authorization["budget_digest"] != definition_digest
            or authorization["principal"] != definition["principal"]
            or authorization["work_class"] not in classes
            or authority_definition["work_class"]["id"] != authorization["work_class"]
            or authorization["work_class_digest"] != digest("authority-work-class", authority_definition["work_class"])
            or authorization["envelope_digest"] != digest("authority-envelope", authority_definition["envelope"])
            or authority_definition["schema"] != PREFIX + "authority-definition"
            or authority_definition["envelope"]["principal"] != definition["principal"]
            or authorization["step"] not in {step["id"] for step in authority_definition["work_class"]["steps"]}
        ):
            raise _AdmissionError("DEPENDENCY_MISMATCH")
        baseline = _validate_authority_definition(authority_definition)
        if baseline is not None:
            raise _AdmissionError(baseline)
        _validate_registered_projection(authorization, definition)
    return definition_digest


def _validate_registered_projection(authorization, definition):
    work_class = authorization["authority_definition"]["work_class"]
    steps = _records(work_class["steps"])
    step = steps.get(authorization["step"])
    if step is None:
        raise _AdmissionError("REFERENCE_INVALID")
    native_fields = {row["name"]: row for row in step["fields"]}
    native_types = _records(work_class["types"])
    budget_types = _definition_types(definition)
    budget_fields = _aggregate_mapping_fields(definition)
    projection = authorization["projection"]
    if any(projection[i]["budget_field"] >= projection[i + 1]["budget_field"] for i in range(len(projection) - 1)):
        raise _AdmissionError("REFERENCE_INVALID")
    if len({row["native_field"] for row in projection}) != len(projection):
        raise _AdmissionError("REFERENCE_INVALID")
    seen_budget = set()
    for row in projection:
        native = native_fields.get(row["native_field"])
        native_type = native_types.get(row["native_type"])
        budget_type = budget_types.get(row["budget_type"])
        if native is None or native["type_ref"] != row["native_type"] or native_type is None:
            raise _AdmissionError("REFERENCE_INVALID")
        if row["budget_field"] not in budget_fields or budget_type is None or row["budget_field"] in seen_budget:
            raise _AdmissionError("REFERENCE_INVALID")
        if (native_type["kind"], native_type.get("unit"), native_type["nonnegative"]) != (
            budget_type["kind"], budget_type.get("unit"), budget_type["nonnegative"]
        ):
            raise _AdmissionError("TYPE_INVALID")
        seen_budget.add(row["budget_field"])
    if seen_budget != set(budget_fields):
        raise _AdmissionError("REFERENCE_INVALID")


def _validate_authority_definition(authority_definition):
    if not _authority_valid(authority_definition, "definition"):
        return "SCHEMA_INVALID"
    source = authority_definition["source"]
    work_class = authority_definition["work_class"]
    envelope = authority_definition["envelope"]
    if (
        envelope["source_digest"] != digest("authority-source", source)
        or envelope["work_class_digest"] != digest("authority-work-class", work_class)
        or not set(envelope["source_obligations"]).issubset({row["id"] for row in source["obligations"]})
    ):
        return "DEPENDENCY_MISMATCH"
    return None


def _history_events(history):
    latest = {}
    for row in history["journal"]:
        latest[row["event"]["id"]] = copy.deepcopy(row["event"])
    return list(latest.values())


def _global_occurrence(authority):
    proposal = authority["proposal"]
    return digest(
        "reservation-occurrence",
        {"work_class": proposal["work_class"], "instance": proposal["instance"], "occurrence": proposal["occurrence"]},
    )


def _contributions(budget, authorization, projected, authority):
    aggregate = budget["definition"]["aggregate"]["aggregate"]
    types = _definition_types(budget["definition"])
    occurrence = _global_occurrence(authority)
    rows = []
    for mapping in aggregate["mappings"]:
        if authority["proposal"]["step"] not in mapping["step_ids"]:
            continue
        if not _predicate(mapping["qualifier"], projected):
            continue
        key = [projected[field] for field in mapping["key_fields"]]
        contribution = mapping["contribution"]
        if contribution["kind"] == "COUNT":
            value = {"type_ref": aggregate["result_type"], "value": "1"}
        else:
            value = projected[contribution["field"]]
        if not _value_matches(value, aggregate["result_type"] if contribution["kind"] != "CARDINALITY" else aggregate["element_type"], types):
            raise _AdmissionError("TYPE_INVALID")
        rows.append({"anchor": budget["definition"]["anchor"], "mapping": mapping["id"], "occurrence": occurrence, "key": key, "value": value})
    rows.sort(key=lambda row: canon([row["anchor"], row["mapping"], row["occurrence"], row["key"]]))
    if not rows:
        raise _AdmissionError("REFERENCE_INVALID")
    return rows


def _predicate(predicate, fields):
    kind = predicate["kind"]
    if kind == "BOOLEAN":
        return predicate["value"]
    if kind == "ALL":
        return all(_predicate(child, fields) for child in predicate["operands"])
    if kind == "ANY":
        return any(_predicate(child, fields) for child in predicate["operands"])
    if kind == "NOT":
        return not _predicate(predicate["operand"], fields)

    def operand(row):
        return fields[row["name"]] if row["kind"] == "FIELD" else row["value"]

    left = operand(predicate.get("left", predicate.get("value")))
    if kind == "MEMBER":
        return any(canon(left) == canon(member) for member in predicate["members"])
    right = operand(predicate["right"])
    if kind == "EQUAL":
        return left["type_ref"] == right["type_ref"] and left["value"] == right["value"]
    left_value, right_value = left["value"], right["value"]
    if isinstance(left_value, str) and isinstance(right_value, str):
        try:
            left_value, right_value = Decimal(left_value), Decimal(right_value)
        except ArithmeticError:
            pass
    return {
        "LT": left_value < right_value,
        "LTE": left_value <= right_value,
        "GT": left_value > right_value,
        "GTE": left_value >= right_value,
    }[predicate["operator"]]


def _aggregate_request(
    budget,
    authority,
    projected,
    contributions,
    history,
    clock,
    pending,
    selected_pin,
    operations_override=None,
    keys_override=None,
):
    definition = budget["definition"]["aggregate"]
    if operations_override is None:
        operations = [{
            "occurrence": _global_occurrence(authority),
            "step": authority["proposal"]["step"],
            "fields": [{"name": name, "value": projected[name]} for name in sorted(projected)],
        }]
    else:
        operations = copy.deepcopy(operations_override)
    if keys_override is None:
        keys = []
        for mapping in definition["aggregate"]["mappings"]:
            if authority["proposal"]["step"] in mapping["step_ids"]:
                key = [projected[field] for field in mapping["key_fields"]]
                if canon(key) not in {canon(old) for old in keys}:
                    keys.append(key)
        keys.sort(key=canon)
    else:
        keys = []
        for key in keys_override:
            if canon(key) not in {canon(old) for old in keys}:
                keys.append(copy.deepcopy(key))
        keys.sort(key=canon)
    now = _aggregate_instant(clock["instant"])
    window = definition["aggregate"]["window"]
    if window["kind"] == "ROLLING":
        start = now - int(Decimal(window["duration_seconds"]) * 1_000_000_000)
        precision = 0
    else:
        start, _ = _aggregate.calendar_interval(now, window, definition["aggregate"]["time"]["precision"])
        precision = 0
    interval = {
        "start": _aggregate_format(start, precision),
        "end": _aggregate_format(now, precision),
        "start_inclusive": window.get("start_inclusive", True),
        "end_inclusive": window.get("end_inclusive", True),
    }
    query = {"definition_digest": _aggregate_digest("aggregate-definition", definition), "interval": interval, "keys": keys}
    query_digest = _aggregate_digest("aggregate-query", query)
    if history["status"] == "AVAILABLE":
        observation = {
            "provider": definition["aggregate"]["committed_source"]["provider"],
            "source": definition["aggregate"]["committed_source"]["source"],
            "request_digest": query_digest,
            "status": "AVAILABLE",
            "revision": history["revision"],
            "as_of": history["as_of"],
            "coverage": interval,
            "kind": "EVENT_SNAPSHOT",
            "events": _history_events(history),
            "evidence_ref": history["evidence_ref"],
        }
    else:
        observation = {
            "provider": definition["aggregate"]["committed_source"]["provider"],
            "source": definition["aggregate"]["committed_source"]["source"],
            "request_digest": query_digest,
            "status": "UNAVAILABLE" if history["status"] == "UNAVAILABLE" else "INCOMPLETE",
            "evidence_ref": history["evidence_ref"],
        }
    return {
        "schema": PREFIX + "aggregate-input",
        "specification_pin": selected_pin,
        "definition": definition,
        "definition_digest": _aggregate_digest("aggregate-definition", definition),
        "operations": operations,
        "pending": [
            {"reservation": row["reservation"], "mapping": row["mapping"], "occurrence": row["occurrence"], "key": row["key"], "contribution": row["value"]}
            for row in pending
        ],
        "clock": clock,
        "observations": [observation],
    }


def _evaluate_aggregate(request, selected_pin):
    try:
        _aggregate_semantic_validate(request)
        result = _AggregateEval(request).evaluate()
    except (_aggregate_refusal, KeyError, TypeError, ValueError, ArithmeticError):
        raise _AdmissionError("INPUT_INVALID")
    result["specification_pin"] = selected_pin
    if not _aggregate_valid(result, "result"):
        raise _AdmissionError("INPUT_INVALID")
    return result


def _required_histories(payload_histories, budgets, authority_result):
    required = authority_result.get("required_budgets", [])
    supplied = {history["budget_digest"]: history for history in payload_histories}
    if set(supplied) != {budget["definition_digest"] for budget in budgets if budget["definition"]["anchor"] in required}:
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    return {
        budget["definition"]["anchor"]: supplied[budget["definition_digest"]]
        for budget in budgets
        if budget["definition"]["anchor"] in required
    }


def _validate_history_authentication(host, histories, configuration):
    if not _valid(host, "host") or host["registry_digest"] != digest("reservation-registry", configuration):
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    expected = {
        ("HISTORY", digest("budget-history", history), history["provider"], history["source"])
        for history in histories
    }
    actual = {
        (row["kind"], row["record_digest"], row["provider"], row["source"])
        for row in host["authenticated_records"]
    }
    if actual != expected:
        raise _AdmissionError("EVIDENCE_UNAVAILABLE" if len(actual) < len(expected) else "DEPENDENCY_MISMATCH")


def _validate_native(native):
    if not _valid(native, "native"):
        raise _AdmissionError("SCHEMA_INVALID")
    for request in (native["request"], native["observed_request"]):
        if request is None:
            continue
        names = [row["name"] for row in request["fields"]]
        if names != sorted(names, key=lambda value: value.encode("utf-8")) or len(names) != len(set(names)):
            raise _AdmissionError("INPUT_INVALID")
    field_names = [row["name"] for row in native["actual_fields"]]
    collection_names = [row["name"] for row in native["collections"]]
    if (
        field_names != sorted(field_names, key=lambda value: value.encode("utf-8"))
        or len(field_names) != len(set(field_names))
        or collection_names != sorted(collection_names, key=lambda value: value.encode("utf-8"))
        or len(collection_names) != len(set(collection_names))
        or set(field_names) & set(collection_names)
    ):
        raise _AdmissionError("INPUT_INVALID")
    for collection in native["collections"]:
        values = collection["values"]
        encoded = [canon(value) for value in values]
        if encoded != sorted(encoded) or len(encoded) != len(set(encoded)):
            raise _AdmissionError("INPUT_INVALID")
        if any(value["type_ref"] != collection["element_type_ref"] for value in values):
            raise _AdmissionError("TYPE_INVALID")
    if native["completion_mismatch"] != (native["mismatch_reason"] is not None):
        raise _AdmissionError("INPUT_INVALID")
    if native["outcome"] == "EFFECT":
        if native["effect_id"] is None or native["occurred_at"] is None or native["rules_out_past_and_future_effects"]:
            raise _AdmissionError("INPUT_INVALID")
        if native["observed_request"] is None and not native["completion_mismatch"]:
            raise _AdmissionError("INPUT_INVALID")
        _parse_time(native["occurred_at"])
    elif native["outcome"] == "UNKNOWN":
        if (
            native["effect_id"] is not None
            or native["occurred_at"] is not None
            or native["observed_request"] is not None
            or native["actual_fields"]
            or native["collections"]
            or native["rules_out_past_and_future_effects"]
        ):
            raise _AdmissionError("INPUT_INVALID")
    elif native["outcome"] == "NO_EFFECT":
        if (
            native["effect_id"] is not None
            or native["occurred_at"] is not None
            or native["observed_request"] is not None
            or native["actual_fields"]
            or native["collections"]
            or not native["rules_out_past_and_future_effects"]
        ):
            raise _AdmissionError("INPUT_INVALID")


def _validate_retained_native_id(state, event):
    if event["kind"] not in {"SETTLE", "RELEASE"}:
        return
    native = event["payload"]["native"]
    native_digest = digest("reservation-native-outcome", native)
    for record in state["receipts"]:
        prior_event = record["event"]
        prior_payload = prior_event.get("payload")
        if not isinstance(prior_payload, dict):
            continue
        prior_native = prior_payload.get("native")
        if prior_native is not None and prior_native["id"] == native["id"]:
            if digest("reservation-native-outcome", prior_native) != native_digest:
                raise _AdmissionError("INPUT_INVALID")


def _validate_native_authentication(host, native, configuration):
    if not _valid(host, "host") or host["registry_digest"] != digest("reservation-registry", configuration):
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    expected = {
        (
            "NATIVE_OUTCOME",
            digest("reservation-native-outcome", native),
            native["provider"],
            native["source"],
        )
    }
    actual = {
        (row["kind"], row["record_digest"], row["provider"], row["source"])
        for row in host["authenticated_records"]
    }
    if actual != expected:
        raise _AdmissionError("EVIDENCE_UNAVAILABLE" if len(actual) < len(expected) else "DEPENDENCY_MISMATCH")


def _validate_settle_authentication(host, native, histories, configuration):
    if not _valid(host, "host") or host["registry_digest"] != digest("reservation-registry", configuration):
        raise _AdmissionError("DEPENDENCY_MISMATCH")
    expected = {
        (
            "NATIVE_OUTCOME",
            digest("reservation-native-outcome", native),
            native["provider"],
            native["source"],
        )
    }
    expected.update(
        ("HISTORY", digest("budget-history", history), history["provider"], history["source"])
        for history in histories
    )
    actual = {
        (row["kind"], row["record_digest"], row["provider"], row["source"])
        for row in host["authenticated_records"]
    }
    if actual != expected:
        raise _AdmissionError("EVIDENCE_UNAVAILABLE" if len(actual) < len(expected) else "DEPENDENCY_MISMATCH")


def _native_request(reservation, budget):
    authority = reservation["authority"]
    authorization, _ = _projection_for(budget["authorizations"], authority, budget)
    proposal = authority["proposal"]
    return {
        "work_class": proposal["work_class"],
        "instance": proposal["instance"],
        "occurrence": proposal["occurrence"],
        "step": proposal["step"],
        "operation": proposal["operation"],
        "interface": proposal["interface"],
        "fields": copy.deepcopy(proposal["fields"]),
    }, authorization


def _native_projection(budget, native_request):
    candidates = []
    for authorization in budget["authorizations"]:
        definition = authorization["authority_definition"]
        if authorization["work_class"] != native_request["work_class"] or authorization["step"] != native_request["step"]:
            continue
        step = next((row for row in definition["work_class"]["steps"] if row["id"] == native_request["step"]), None)
        if step is not None and (step["operation"], step["interface"]) == (native_request["operation"], native_request["interface"]):
            candidates.append(authorization)
    if len(candidates) != 1:
        return None, None
    authorization = candidates[0]
    definition = authorization["authority_definition"]
    step = next(row for row in definition["work_class"]["steps"] if row["id"] == native_request["step"])
    declared = {row["name"]: row for row in step["fields"]}
    supplied = {row["name"]: row for row in native_request["fields"]}
    if set(supplied) != set(declared) or [row["name"] for row in native_request["fields"]] != sorted(supplied):
        return None, None
    native_types = _records(definition["work_class"]["types"])
    for name, field in supplied.items():
        declared_type = native_types.get(declared[name]["type_ref"])
        if declared_type is None or field["value"]["type_ref"] != declared[name]["type_ref"]:
            return None, None
        if not _value_matches(field["value"], declared[name]["type_ref"], native_types):
            return None, None
    budget_types = _definition_types(budget["definition"])
    budget_fields = _aggregate_mapping_fields(budget["definition"])
    projected = {}
    for row in authorization["projection"]:
        if row["native_field"] not in supplied or row["budget_field"] not in budget_fields:
            return None, None
        native_type = native_types.get(row["native_type"])
        budget_type = budget_types.get(row["budget_type"])
        if native_type is None or budget_type is None:
            return None, None
        if (native_type["kind"], native_type.get("unit"), native_type["nonnegative"]) != (
            budget_type["kind"], budget_type.get("unit"), budget_type["nonnegative"]
        ):
            return None, None
        source = supplied[row["native_field"]]
        projected[row["budget_field"]] = {"type_ref": row["budget_type"], "value": source["value"]["value"]}
    if set(projected) != set(budget_fields) or any(
        not _value_matches(projected[field], budget_fields[field], budget_types) for field in projected
    ):
        return None, None
    return authorization, projected


def _native_contributions(budget, native_request):
    authorization, projected = _native_projection(budget, native_request)
    if authorization is None:
        return None
    authority = {"proposal": copy.deepcopy(native_request)}
    return _contributions(budget, authorization, projected, authority)


def _prescribed_event(budget, contribution, effect_id, occurred_at):
    aggregate = budget["definition"]["aggregate"]["aggregate"]
    mapping = next(row for row in aggregate["mappings"] if row["id"] == contribution["mapping"])
    fields = {name: value for name, value in zip(mapping["key_fields"], contribution["key"])}
    if mapping["contribution"]["kind"] != "COUNT":
        fields[mapping["contribution"]["field"]] = contribution["value"]
    return {
        "id": digest(
            "reservation-committed-event",
            {"budget_digest": budget["definition_digest"], "effect_id": effect_id, "mapping": contribution["mapping"]},
        ),
        "state": "ACTIVE",
        "occurred_at": occurred_at,
        "fields": [{"name": name, "value": fields[name]} for name in sorted(fields)],
    }


def _history_has_prescribed(history, expected):
    if history["status"] != "AVAILABLE":
        return False
    actual = {row["event"]["id"]: row["event"] for row in history["journal"]}
    return actual.get(expected["id"]) is not None and canon(actual[expected["id"]]) == canon(expected)


def _mark_retracted_matches(core, budget, history):
    previous = budget["history"]
    if canon(previous) == canon(history) or history["status"] != "AVAILABLE":
        return
    anchor = budget["definition"]["anchor"]
    for effect in core["effects"]:
        if effect["disposition"] != "MATCHED" or anchor not in effect["affected_anchors"]:
            continue
        target = next((row for row in core["reservations"] if row["id"] == effect["reservation"]), None)
        if target is None or target["status"] != "SETTLED":
            continue
        for contribution in target["contributions"]:
            if contribution["anchor"] != anchor:
                continue
            expected = _prescribed_event(budget, contribution, effect["native"]["effect_id"], effect["native"]["occurred_at"])
            if _history_has_prescribed(previous, expected) and not _history_has_prescribed(history, expected):
                target["status"] = "DISPUTED"
                break


def _blocked(core, anchor, key):
    for reservation in core["reservations"]:
        if reservation["status"] != "DISPUTED":
            continue
        if any(
            contribution["anchor"] == anchor and canon(contribution["key"]) == canon(key)
            for contribution in reservation["contributions"]
        ):
            return True
    for effect in core["effects"]:
        if anchor not in effect["affected_anchors"]:
            continue
        for partition in effect["blocked_partitions"]:
            if partition["anchor"] != anchor:
                continue
            if partition["key"] is None or canon(partition["key"]) == canon(key):
                return True
    return False


def _aggregate_reconciliation_request(budget, history, clock, pending, keys, selected_pin):
    aggregate = budget["definition"]["aggregate"]["aggregate"]
    mapping = aggregate["mappings"][0]
    type_by_field = _aggregate_mapping_fields(budget["definition"])
    operations = []
    for index, key in enumerate(keys):
        fields = {name: value for name, value in zip(mapping["key_fields"], key)}
        contribution = mapping["contribution"]
        if contribution["kind"] != "COUNT":
            value_type = type_by_field[contribution["field"]]
            if contribution["kind"] == "SUM":
                fields[contribution["field"]] = {"type_ref": value_type, "value": "0"}
            else:
                fields[contribution["field"]] = {"type_ref": value_type, "value": "reconciliation"}
        operations.append({
            "occurrence": digest("reservation-reconciliation-operation", {"anchor": budget["definition"]["anchor"], "index": str(index)}),
            "step": mapping["step_ids"][0],
            "fields": [{"name": name, "value": fields[name]} for name in sorted(fields)],
        })
    return _aggregate_request(
        budget,
        {"proposal": {"work_class": "reconciliation", "instance": "reconciliation", "occurrence": "reconciliation", "step": "reconciliation"}},
        {},
        [],
        history,
        clock,
        pending,
        selected_pin,
        operations_override=operations,
        keys_override=keys,
    )


def _effect_record(native, reservation, disposition, affected_anchors, blocked_partitions, reason):
    return {
        "id": native["id"],
        "native": copy.deepcopy(native),
        "native_digest": digest("reservation-native-outcome", native),
        "reservation": reservation,
        "disposition": disposition,
        "affected_anchors": sorted(set(affected_anchors)),
        "blocked_partitions": sorted(
            copy.deepcopy(blocked_partitions), key=lambda row: canon([row["anchor"], row["key"]])
        ),
        "reason": reason,
    }


def _history_keys(budget, history):
    keys = []
    if history["status"] == "AVAILABLE":
        aggregate = budget["definition"]["aggregate"]["aggregate"]
        key_names = set()
        for mapping in aggregate["mappings"]:
            key_names.update(mapping["key_fields"])
        for event in _history_events(history):
            if event["state"] != "ACTIVE":
                continue
            fields = {row["name"]: row["value"] for row in event["fields"]}
            key = [fields[name] for name in sorted(key_names) if name in fields]
            if len(key) == len(key_names) and canon(key) not in {canon(old) for old in keys}:
                keys.append(key)
    return keys


def _reconciliation_budgets(core, selected, event, selected_pin, exclude_reservation=None):
    results = []
    for budget, history, keys in selected:
        if not keys:
            keys = _history_keys(budget, history)
        pending = _pending_for(core, budget["definition"]["anchor"], keys, exclude_reservation)
        request = _aggregate_reconciliation_request(budget, history, event["clock"], pending, keys, selected_pin)
        result = _evaluate_aggregate(request, selected_pin)
        results.append({"anchor": budget["definition"]["anchor"], "result": result})
    return sorted(results, key=lambda row: row["anchor"])


def _effect_result(effect):
    if effect["disposition"] == "MATCHED":
        return "SETTLED", []
    if effect["disposition"] == "UNKNOWN":
        return "UNKNOWN", []
    if effect["disposition"] == "RELEASED":
        return "RELEASED", []
    return "EFFECT_DISPUTED", [effect["reason"]]


def _apply_settle(core, event, host, selected_pin):
    native = event["payload"]["native"]
    _validate_native(native)
    if native["outcome"] == "NO_EFFECT":
        raise _AdmissionError("INPUT_INVALID")
    target = next((row for row in core["reservations"] if row["id"] == native["reservation"]), None)
    budgets_by_digest = {row["definition_digest"]: row for row in core["budgets"]}
    histories = event["payload"]["histories"]
    if [row["budget_digest"] for row in histories] != sorted({row["budget_digest"] for row in histories}):
        raise _AdmissionError("INPUT_INVALID")
    if target is not None:
        required_anchors = {row["anchor"] for row in target["contributions"]}
        selected_budgets = [
            row for row in core["budgets"] if row["definition"]["anchor"] in required_anchors
        ]
        if {row["budget_digest"] for row in histories} != {row["definition_digest"] for row in selected_budgets}:
            raise _AdmissionError("DEPENDENCY_MISMATCH")
    else:
        if not histories:
            raise _AdmissionError("DEPENDENCY_MISMATCH")
        selected_budgets = [budgets_by_digest.get(row["budget_digest"]) for row in histories]
        if any(row is None for row in selected_budgets):
            raise _AdmissionError("DEPENDENCY_MISMATCH")
    _validate_settle_authentication(host, native, histories, core["configuration"])
    history_by_digest = {row["budget_digest"]: row for row in histories}
    selected = []
    for budget in selected_budgets:
        history = history_by_digest[budget["definition_digest"]]
        policy = budget["definition"]["reservation_policy"]["settlement"]
        if (native["provider"], native["source"]) != (policy["provider"], policy["source"]):
            raise _AdmissionError("DEPENDENCY_MISMATCH")
        _validate_history(history, budget, event["clock"]["instant"], budget["history"])
        selected.append((budget, history))

    existing = next((row for row in core["effects"] if row["id"] == native["id"]), None)
    native_digest = digest("reservation-native-outcome", native)
    if existing is not None and existing["native_digest"] != native_digest:
        raise _AdmissionError("INPUT_INVALID")
    same_effect = next((row for row in core["effects"] if row["reservation"]==native["reservation"] and _native_fact(row["native"])==_native_fact(native)),None)
    # A duplicate returns the established disposition and "does not repeat an effect record or charge";
    # it is recognized by its native fact, whatever history accompanies the retry, and stores none of it.
    if existing is None and same_effect is not None:
        decision, reasons = _effect_result(same_effect)
        selected_results = [
            (budget, budget["history"], [row["key"] for row in (target or {}).get("contributions", []) if row["anchor"] == budget["definition"]["anchor"]])
            for budget, _ in selected
        ]
        return decision, same_effect["reservation"], [], None, reasons
    if existing is not None:
        decision, reasons = _effect_result(existing)
        selected_results = [
            (budget, budget["history"], [row["key"] for row in (target or {}).get("contributions", []) if row["anchor"] == budget["definition"]["anchor"]])
            for budget, _ in selected
        ]
        return decision, existing["reservation"], [], None, reasons

    for budget, history in selected:
        if history["status"] == "AVAILABLE":
            budget["history"] = copy.deepcopy(history)

    original = {}
    if target is not None:
        for contribution in target["contributions"]:
            original.setdefault(contribution["anchor"], []).append(contribution)
    actual = {}
    exact_request = target is not None
    observed_differs = False
    history_corroborated = True
    native_occurrence = native["occurred_at"]
    for budget, history in selected:
        anchor = budget["definition"]["anchor"]
        if target is not None:
            expected_request, _ = _native_request(target, budget)
            exact_request = exact_request and canon(expected_request) == canon(native["request"])
            observed_differs = observed_differs or (
                native["observed_request"] is not None and canon(expected_request) != canon(native["observed_request"])
            )
        # An unknown reservation or absent mismatched observation has no
        # projectable affected key and therefore blocks the whole anchor.
        observed_request = native["observed_request"]
        if target is None or (observed_request is None and native["completion_mismatch"]):
            contributions = None
        elif observed_request is None:
            contributions = []
        else:
            contributions = _native_contributions(budget, observed_request)
        actual[anchor] = contributions
        if native["outcome"] == "EFFECT" and contributions is not None:
            if target is not None and exact_request:
                for contribution in original.get(anchor, []):
                    expected = _prescribed_event(budget, contribution, native["effect_id"], native_occurrence)
                    if not _history_has_prescribed(history, expected):
                        history_corroborated = False
            else:
                history_corroborated = False
        elif native["outcome"] == "EFFECT":
            history_corroborated = False

    effect_ids = {
        row["native"].get("effect_id")
        for row in core["effects"]
        if row["reservation"] == native["reservation"] and row["native"].get("effect_id") is not None
    }
    # A non-duplicate record reaching here under a retained effect identifier has a changed conclusive fact.
    distinct_effect = native["outcome"] == "EFFECT" and any(effect_id != native["effect_id"] for effect_id in effect_ids)
    changed_fact = native["outcome"] == "EFFECT" and native["effect_id"] in effect_ids

    # RES-WIRE-003: "DISPUTED; any new attributable fact -> EFFECT_DISPUTED; remain DISPUTED;
    # ... perform no automatic resolution." A DISPUTED reservation cannot be resolved by a
    # matching record of any outcome kind, so neither branch below may set `matching` true for it.
    matching = (
        target is not None
        and target["status"] not in {"RELEASED", "DISPUTED"}
        and native["outcome"] == "EFFECT"
        and not native["completion_mismatch"]
        and exact_request
        and history_corroborated
        and not distinct_effect
        and not changed_fact
        and not observed_differs
    )
    if native["outcome"] == "UNKNOWN" and not native["completion_mismatch"] and target is not None and target["status"] not in {"SETTLED", "RELEASED", "DISPUTED"}:
        expected_request, _ = _native_request(target, selected_budgets[0])
        matching = canon(expected_request) == canon(native["request"])

    affected_anchors = [budget["definition"]["anchor"] for budget, _ in selected]
    blocked = []
    for budget, _ in selected:
        anchor = budget["definition"]["anchor"]
        for contribution in original.get(anchor, []):
            blocked.append({"anchor": anchor, "key": copy.deepcopy(contribution["key"])})
        if actual.get(anchor) is None:
            blocked.append({"anchor": anchor, "key": None})
        else:
            blocked.extend({"anchor": anchor, "key": copy.deepcopy(row["key"])} for row in actual[anchor])

    if native["outcome"]=="UNKNOWN" and target is not None and target["status"] in {"SETTLED","RELEASED"} and not native["completion_mismatch"] and exact_request:
        disposition,reason,decision="UNKNOWN","UNKNOWN_OUTCOME","UNKNOWN"
        blocked=[]
    elif matching and native["outcome"] == "EFFECT":
        target["status"] = "SETTLED"
        target["matched_effect"] = native["effect_id"]
        disposition, reason, decision = "MATCHED", "MATCHED_EFFECT", "SETTLED"
        blocked = []
    elif matching and native["outcome"] == "UNKNOWN":
        target["status"] = "UNKNOWN"
        disposition, reason, decision = "UNKNOWN", "UNKNOWN_OUTCOME", "UNKNOWN"
        blocked = []
    elif target is None:
        disposition, reason, decision = "DISPUTED", "UNKNOWN_RESERVATION", "EFFECT_DISPUTED"
    elif target["status"] == "RELEASED" and native["outcome"] == "EFFECT":
        target["status"] = "DISPUTED"
        disposition, reason, decision = "DISPUTED", "LATE_EFFECT_AFTER_RELEASE", "EFFECT_DISPUTED"
    elif native["completion_mismatch"] or not exact_request:
        target["status"] = "DISPUTED"
        disposition, reason, decision = (
            "DISPUTED",
            native["mismatch_reason"] or "UNEXPECTED_EFFECT",
            "EFFECT_DISPUTED",
        )
    # RES-WIRE-004: whatever the prior status, an identity conflict precedes missing corroboration,
    # which precedes the outcome's own reason.
    elif distinct_effect or changed_fact or observed_differs:
        target["status"] = "DISPUTED"
        disposition, reason, decision = "DISPUTED", "UNEXPECTED_EFFECT", "EFFECT_DISPUTED"
    elif native["outcome"] == "EFFECT" and exact_request and not history_corroborated:
        target["status"] = "DISPUTED"
        disposition, reason, decision = "DISPUTED", "HISTORY_UNCORROBORATED", "EFFECT_DISPUTED"
    elif target["status"] == "DISPUTED":
        disposition, reason, decision = "DISPUTED", "MATCHED_EFFECT" if native["outcome"] == "EFFECT" else "UNKNOWN_OUTCOME", "EFFECT_DISPUTED"
    else:
        target["status"] = "DISPUTED"
        disposition, reason, decision = (
            "DISPUTED",
            native["mismatch_reason"] or "UNEXPECTED_EFFECT",
            "EFFECT_DISPUTED",
        )

    unique_blocked = {}
    for partition in blocked:
        unique_blocked[canon([partition["anchor"], partition["key"]])] = partition
    wholly_blocked = {partition["anchor"] for partition in unique_blocked.values() if partition["key"] is None}
    effective_blocked = [
        partition for partition in unique_blocked.values()
        if partition["key"] is None or partition["anchor"] not in wholly_blocked
    ]
    effect = _effect_record(
        native,
        native["reservation"],
        disposition,
        affected_anchors,
        effective_blocked,
        reason,
    )
    if existing is None:
        core["effects"].append(effect)
    else:
        index = core["effects"].index(existing)
        core["effects"][index] = effect
    core["effects"].sort(key=lambda row: row["id"])
    selected_results = []
    for budget, history in selected:
        anchor = budget["definition"]["anchor"]
        keys = [row["key"] for row in original.get(anchor, [])]
        keys.extend(row["key"] for row in actual.get(anchor, []) or [])
        selected_results.append((budget, budget["history"], keys))
    # Correction-3 makes native settlement a state/evidence transition only.
    # It must not emit a new aggregate judgment or authority result.
    return decision, target["id"] if target is not None else native["reservation"], [], None, [] if decision in {"SETTLED", "UNKNOWN"} else [reason]


def _apply_release(core, event, host, selected_pin):
    native = event["payload"]["native"]
    _validate_native(native)
    if native["outcome"] != "NO_EFFECT":
        raise _AdmissionError("INPUT_INVALID")
    target = next((row for row in core["reservations"] if row["id"] == native["reservation"]), None)
    if target is None:
        raise _AdmissionError("RESERVATION_NOT_FOUND")
    exact_request = True
    for budget in core["budgets"]:
        if any(row["anchor"] == budget["definition"]["anchor"] for row in target["contributions"]):
            policy = budget["definition"]["reservation_policy"]["no_effect"]
            if (native["provider"], native["source"]) != (policy["provider"], policy["source"]):
                raise _AdmissionError("DEPENDENCY_MISMATCH")
            expected, _ = _native_request(target, budget)
            exact_request = exact_request and canon(expected) == canon(native["request"])
    existing = next((row for row in core["effects"] if row["id"] == native["id"]), None)
    native_digest = digest("reservation-native-outcome", native)
    if existing is not None and existing["native_digest"] != native_digest:
        raise _AdmissionError("INPUT_INVALID")
    affected = sorted({row["anchor"] for row in target["contributions"]})
    same_fact=next((row for row in core["effects"] if row["reservation"]==native["reservation"] and _native_fact(row["native"])==_native_fact(native)),None)
    duplicate=existing or same_fact
    newly_releases=target["status"] in {"OPEN","UNKNOWN"} and not native["completion_mismatch"] and exact_request and duplicate is None
    if newly_releases:
        _validate_admin(event,host,core["configuration"],[('NATIVE_OUTCOME',native_digest,native["provider"],native["source"])])
    else:
        if event["administration"] is not None: raise _AdmissionError("DEPENDENCY_MISMATCH")
        _validate_native_host(host,core["configuration"],native)
    if duplicate is not None:
        decision,reasons=_effect_result(duplicate)
        return decision,target["id"],[],None,reasons
    if native["completion_mismatch"]:
        target["status"]="DISPUTED";disposition="DISPUTED";reason=native["mismatch_reason"]
        blocked=[{"anchor":anchor,"key":None} for anchor in affected]
        decision="EFFECT_DISPUTED";reasons=[reason]
    # RES-WIRE-004: a clean record whose attributed request differs is retained as unexpected for RELEASE as for SETTLE.
    elif not exact_request or target["status"] in {"SETTLED","RELEASED","DISPUTED"}:
        reason="AFFIRMATIVE_NO_EFFECT" if exact_request and target["status"]=="DISPUTED" and target["matched_effect"] is None else "UNEXPECTED_EFFECT";target["status"]="DISPUTED";disposition="DISPUTED"
        blocked=[{"anchor":row["anchor"],"key":copy.deepcopy(row["key"])} for row in target["contributions"]]
        decision="EFFECT_DISPUTED";reasons=[reason]
    else:
        target["status"]="RELEASED";disposition="RELEASED";reason="AFFIRMATIVE_NO_EFFECT";blocked=[]
        decision="RELEASED";reasons=[]
    effect = _effect_record(native, target["id"], disposition, affected, blocked, reason)
    core["effects"].append(effect)
    core["effects"].sort(key=lambda row: row["id"])
    return decision,target["id"],[],None,reasons


def _pending_for(core, anchor, keys, exclude_id=None):
    result = []
    key_bytes = {canon(key) for key in keys}
    for reservation in core["reservations"]:
        if reservation["id"] == exclude_id or reservation["status"] not in {"OPEN", "UNKNOWN", "DISPUTED"}:
            continue
        for contribution in reservation["contributions"]:
            if contribution["anchor"] == anchor and canon(contribution["key"]) in key_bytes:
                result.append({"reservation": reservation["id"], **copy.deepcopy(contribution)})
    result.sort(key=lambda row: canon([row["reservation"], row["mapping"], row["occurrence"], row["key"]]))
    return result


def _make_receipt(event, prior, core, decision, reservation, budgets, authority_result, reasons):
    return {
        "event_digest": _event_digest(event),
        "prior_state_digest": _state_digest(prior),
        "revision": core["revision"],
        "next_core_digest": _core_digest(core),
        "decision": decision,
        "reservation": reservation,
        "budgets": sorted(budgets, key=lambda row: row["anchor"]),
        "authority_result": authority_result,
        "reasons": sorted(set(reasons)),
    }


def _apply_event(state, event, host, selected_pin):
    prior = copy.deepcopy(state)
    core = copy.deepcopy(state["core"])
    clock = _clock(event, core["configuration"], core["last_clock"])
    _validate_retained_native_id(state, event)
    authority_result = None
    if event["kind"] == "REGISTER":
        definition_digest = _validate_registration(event, host, state)
        payload = event["payload"]
        budget = {
            "definition": copy.deepcopy(payload["definition"]),
            "definition_digest": definition_digest,
            "authorizations": copy.deepcopy(payload["authorizations"]),
            "history": copy.deepcopy(payload["history"]),
        }
        core["budgets"].append(budget)
        core["budgets"].sort(key=lambda row: row["definition"]["anchor"])
        decision, reservation, budgets, authority_result, reasons = "REGISTERED", None, [], None, []
    elif event["kind"] in {"RESERVE", "RENEW"}:
        payload = event["payload"]
        reservation = None
        budgets = []
        decision = "WITHHELD"
        target = None
        if event["kind"] == "RENEW":
            target = next((row for row in core["reservations"] if row["id"] == payload["reservation"]), None)
            if target is None:
                raise _AdmissionError("RESERVATION_NOT_FOUND")
            # RES-WIRE-004: "An already DISPUTED reservation cannot be renewed or released; WITHHELD with
            # EXPOSURE_DISPUTED retains it."
            if target["status"] not in {"OPEN", "UNKNOWN", "DISPUTED"}:
                raise _AdmissionError("INPUT_INVALID")
        authority = payload["authority"]
        if target is not None and (
            target["proposal_digest"] != digest("authority-proposal", authority["proposal"])
            or target["envelope_digest"] != digest("authority-envelope", authority["envelope"])
        ):
            raise _AdmissionError("OCCURRENCE_CONFLICT")
        authority_result = _evaluate_authority(copy.deepcopy(authority), selected_pin)
        if authority_result.get("status") != "READY_FOR_RESERVATION":
            new_state = copy.deepcopy(state)
            core["revision"] = str(int(core["revision"]) + 1)
            core["last_clock"] = clock if clock is not None else core["last_clock"]
            reasons = ["AUTHORITY_WITHHELD"]
            receipt = _make_receipt(event, prior, core, "WITHHELD", target["id"] if target else None, [], authority_result, reasons)
            new_state["core"] = core
            new_state["receipts"].append({"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(host), "receipt": receipt})
            return new_state, receipt
        budgets_by_anchor = {budget["definition"]["anchor"]: budget for budget in core["budgets"]}
        occurrence_key = _global_occurrence(authority)
        if event["kind"] == "RESERVE" and any(row["occurrence_key"] == occurrence_key for row in core["reservations"]):
            raise _AdmissionError("OCCURRENCE_CONFLICT")
        required = authority_result["required_budgets"]
        if set(required) != {anchor for anchor in required if anchor in budgets_by_anchor}:
            raise _AdmissionError("REFERENCE_INVALID")
        selected_policies=[budgets_by_anchor[anchor]["definition"]["reservation_policy"] for anchor in required]
        if len({(row["settlement"]["provider"],row["settlement"]["source"]) for row in selected_policies})>1 or len({(row["no_effect"]["provider"],row["no_effect"]["source"]) for row in selected_policies})>1:
            raise _AdmissionError("UNSUPPORTED_RELATION")
        histories = _required_histories(payload["histories"], list(budgets_by_anchor.values()), authority_result)
        _validate_history_authentication(host, payload["histories"], core["configuration"])
        selected = []
        for anchor in required:
            budget = budgets_by_anchor[anchor]
            history = histories[anchor]
            _validate_history(history, budget, event["clock"]["instant"], budget["history"])
            history_fresh = _history_is_fresh(history, budget, event["clock"]["instant"])
            if history_fresh:
                _mark_retracted_matches(core, budget, history)
            authorization, projected = _projection_for(budget["authorizations"], authority, budget)
            contributions = _contributions(budget, authorization, projected, authority)
            if event["kind"] == "RENEW":
                old = [row for row in target["contributions"] if row["anchor"] == anchor]
                if old != contributions:
                    raise _AdmissionError("OCCURRENCE_CONFLICT")
            keys = [row["key"] for row in contributions]
            pending = _pending_for(core, anchor, keys, target["id"] if target else None)
            request = _aggregate_request(budget, authority, projected, contributions, history, event["clock"], pending, selected_pin)
            aggregate_result = _evaluate_aggregate(request, selected_pin)
            selected.append((budget, history, contributions, aggregate_result))
        budgets_result = [{"anchor": budget["definition"]["anchor"], "result": aggregate_result} for budget, _, _, aggregate_result in selected]
        budgets = budgets_result
        reasons = []
        for budget, history, contributions, aggregate_result in selected:
            if history["status"] != "AVAILABLE":
                reasons.append({"UNAVAILABLE": "HISTORY_UNAVAILABLE", "INCOMPLETE": "HISTORY_INCOMPLETE", "CONFLICT": "HISTORY_CONFLICT"}[history["status"]])
            if history["status"] == "AVAILABLE":
                for reason in aggregate_result["reasons"]:
                    reasons.append({
                        "BOUND_VIOLATED": "BOUND_VIOLATED",
                        "OBSERVATION_UNAVAILABLE": "HISTORY_UNAVAILABLE",
                        "OBSERVATION_INCOMPLETE": "HISTORY_INCOMPLETE",
                        "OBSERVATION_STALE": "HISTORY_STALE",
                        "OBSERVATION_MISSING": "HISTORY_UNAVAILABLE",
                        "OBSERVATION_CONFLICT": "HISTORY_CONFLICT",
                    }.get(reason, reason))
            if aggregate_result["status"] != "SATISFIED":
                if aggregate_result["status"] == "VIOLATED":
                    reasons.append("BOUND_VIOLATED")
                elif not reasons:
                    reasons.append("HISTORY_UNAVAILABLE")
            if any(_blocked(core, budget["definition"]["anchor"], contribution["key"]) for contribution in contributions):
                reasons.append("EXPOSURE_DISPUTED")
        blocked = (target is not None and target["status"] == "DISPUTED") or any(
            _blocked(core, budget["definition"]["anchor"], contribution["key"])
            for budget, _, contributions, _ in selected
            for contribution in contributions
        )
        if blocked:
            budgets = []
            reasons = ["EXPOSURE_DISPUTED"]
            decision = "WITHHELD"
            reservation_id = target["id"] if target else None
            reservation = reservation_id
        elif reasons:
            decision = "WITHHELD"
            reservation_id = target["id"] if target else None
            reservation = reservation_id
        else:
            permit_seconds = min(int(budget["definition"]["reservation_policy"]["permit_seconds"]) for budget, _, _, _ in selected)
            permit_until = _add_seconds(event["clock"]["instant"], permit_seconds)
            all_contributions = [row for _, _, contributions, _ in selected for row in contributions]
            all_contributions.sort(key=lambda row: canon([row["anchor"], row["mapping"], row["occurrence"], row["key"]]))
            proposal = authority["proposal"]
            reservation_id = target["id"] if target else event["id"]
            reservation = reservation_id
            if target is None:
                core["reservations"].append({
                    "id": reservation_id,
                    "occurrence_key": occurrence_key,
                    "proposal_digest": digest("authority-proposal", proposal),
                    "envelope_digest": digest("authority-envelope", authority["envelope"]),
                    "authority": copy.deepcopy(authority),
                    "authority_result": copy.deepcopy(authority_result),
                    "contributions": all_contributions,
                    "created_at": event["clock"]["instant"],
                    "permit_until": permit_until,
                    "status": "OPEN",
                    "matched_effect": None,
                })
                decision = "RESERVED"
            else:
                target["authority"] = copy.deepcopy(authority)
                target["authority_result"] = copy.deepcopy(authority_result)
                target["permit_until"] = permit_until
                decision = "RENEWED"
        if "HISTORY_STALE" in reasons:
            budgets = []
        for budget, history, _, _ in selected:
            if _history_is_fresh(history, budget, event["clock"]["instant"]):
                budget["history"] = copy.deepcopy(history)
        core["reservations"].sort(key=lambda row: row["id"])
    elif event["kind"] == "SETTLE":
        decision, reservation, budgets, authority_result, reasons = _apply_settle(core, event, host, selected_pin)
    elif event["kind"] == "RELEASE":
        decision, reservation, budgets, authority_result, reasons = _apply_release(core, event, host, selected_pin)
    else:
        raise _AdmissionError("UNSUPPORTED_RELATION")
    core["revision"] = str(int(core["revision"]) + 1)
    if clock is not None:
        core["last_clock"] = clock
    receipt = _make_receipt(event, prior, core, decision, reservation, budgets, authority_result, reasons)
    new_state = copy.deepcopy(state)
    new_state["core"] = core
    new_state["receipts"].append({"event": copy.deepcopy(event), "host_evidence": copy.deepcopy(host), "receipt": receipt})
    return new_state, receipt


def _replay_state(state, selected_pin):
    if not _valid(state, "state") or state["specification_pin"] != selected_pin or not _configuration_valid(state["core"]["configuration"]):
        return False
    rebuilt = _zero_state(state["core"]["configuration"], selected_pin)
    records = sorted(state["receipts"], key=lambda row: int(row["receipt"]["revision"]))
    if len(records) != int(state["core"]["revision"]) or len(records) != len(state["receipts"]):
        return False
    for index, record in enumerate(records, 1):
        if not _valid(record, "record") or record["receipt"]["revision"] != str(index):
            return False
        event = record["event"]
        if event["expected_revision"] != str(index - 1):
            return False
        if record["receipt"]["prior_state_digest"] != _state_digest(rebuilt):
            return False
        if record["receipt"]["event_digest"] != _event_digest(event):
            return False
        try:
            rebuilt, receipt = _apply_event(rebuilt, event, record["host_evidence"], selected_pin)
        except (KeyError, TypeError, ValueError, _AdmissionError):
            return False
        if receipt != record["receipt"]:
            return False
    return rebuilt["core"] == state["core"] and rebuilt["receipts"] == state["receipts"]


def aggregate_step(request, selected_pin, _checking_replay=False):
    if not isinstance(request, dict) or not _valid(request, "input"):
        return {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""}
    state = request["state"]
    supplied_state_digest = request["state_digest"]
    if request["specification_pin"] != selected_pin:
        return _refusal("DEPENDENCY_MISMATCH", state, supplied_state_digest)
    if not _replay_state(state, selected_pin) or _state_digest(state) != supplied_state_digest:
        return _refusal("STATE_INVALID", state, supplied_state_digest)
    event = request["event"]
    event_id = event["id"]
    prior_records = [record for record in state["receipts"] if record["event"]["id"] == event_id]
    event_digest = _event_digest(event)
    if prior_records:
        if prior_records[-1]["receipt"]["event_digest"] != event_digest:
            return _refusal("REPLAY_CONFLICT", state, supplied_state_digest)
        old_receipt = prior_records[-1]["receipt"]
        return {
            "status": "TRANSITION",
            "receipt": copy.deepcopy(old_receipt),
            "receipt_digest": _receipt_digest(old_receipt),
            "state": copy.deepcopy(state),
            "state_digest": _state_digest(state),
            "replay": True,
        }
    if event["expected_revision"] != state["core"]["revision"]:
        return _refusal("REVISION_CONFLICT", state, supplied_state_digest)
    try:
        next_state, receipt = _apply_event(state, event, request["host_evidence"], selected_pin)
    except _AdmissionError as exc:
        return _refusal(exc.code, state, supplied_state_digest)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return _refusal("INPUT_INVALID", state, supplied_state_digest)
    result = {
        "status": "TRANSITION",
        "receipt": receipt,
        "receipt_digest": _receipt_digest(receipt),
        "state": next_state,
        "state_digest": _state_digest(next_state),
        "replay": False,
    }
    if not _valid(result, "result"):
        return _refusal("INPUT_INVALID", state, supplied_state_digest)
    return result


class ReferenceHost:
    """Serialized host that owns its state and ignores caller-supplied state."""

    def __init__(self, configuration, selected_pin=PIN):
        self.pin = selected_pin
        self.state = initial_state(configuration, selected_pin)
        self.lock = threading.Lock()

    def step(self, request):
        with self.lock:
            owned_request = {
                "schema": PREFIX + "reservation-input",
                "specification_pin": self.pin,
                "state": copy.deepcopy(self.state),
                "state_digest": _state_digest(self.state),
                "event": copy.deepcopy(request["event"]),
                "host_evidence": copy.deepcopy(request["host_evidence"]),
            }
            result = aggregate_step(owned_request, self.pin)
            if result.get("status") == "TRANSITION":
                self.state = result["state"]
            return result

    def export_state(self):
        with self.lock:
            return copy.deepcopy(self.state)

    def restart(self, state):
        with self.lock:
            if not _replay_state(state, self.pin):
                raise ValueError("invalid restart state")
            self.state = copy.deepcopy(state)


REGISTER = "REGISTER"
RESERVE = "RESERVE"
RENEW = "RENEW"
