"""Derive measurement-age judgments without invoking a consumer."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

from authority_fixture import authority_refusal
from corpus_common import CASES, exact_case, write_canonical_json
from equipment_observation_fixture import observation, source_fixture, source_refusal


GROUP = CASES / "timing-observations"


def age_fixture(age=0, bound="900", *, mutate=None):
    def configure(request, _original):
        req = request["envelope"]["source_observation_requirements"][0]
        req["fields"] = [{"name": "measured_at", "type_ref": "INSTANT"}]
        req["relations"] = [{"id": "maximum-measurement-age", "kind": "ELAPSED_LTE",
            "left": "measured_at", "right": {"kind": "CLOCK", "type_ref": "INSTANT"},
            "maximum_seconds": bound}]
        now = datetime.strptime(request["clock"]["instant"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        measured = (now - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ")
        request["observations"] = [row for row in request["observations"] if row["query"]["purpose"] == "REVOCATION"]
        request["observations"].append(observation(req, request, values={"measured_at": measured}))
        if mutate is not None:
            mutate(request, req, request["observations"][-1])
    return source_fixture(mutator=configure)


def build():
    rows = []

    def add(request, expected, derivation):
        cid = "C3-TM-" + str(len(rows) + 1).zfill(3)
        rows.append(exact_case(cid, "evaluate", {"kind": "AUTHORITY", "request": request},
            expected, ["TIME-002", "AUTH-007"], derivation))

    for age, bound, passes in ((0, "900", True), (900, "900", True), (901, "900", False),
            (-1, "900", False), (0, "0", True), (1, "0", False),
            (1200, "900", False), (1200, "9" * 128, True)):
        request, ready = age_fixture(age, bound)
        expected = ready if passes else source_refusal(request, "current-session", "SOURCE_OBSERVATION_RELATIONS")
        add(request, expected, f"The source record was retrieved at the current query time. Its selected measurement difference is {age} seconds and its inclusive declared maximum is {bound}; the exact nonnegative elapsed predicate {'holds' if passes else 'fails'}. Retrieval time does not reset measurement time.")

    request, _ = age_fixture(bound="9" * 129)
    add(request, authority_refusal([], code="LIMIT_EXCEEDED"),
        "The canonical natural exceeds the inherited 128-digit numerical bound before any policy comparison.")

    def wrong_clock_type(request, req, row):
        req["relations"][0]["right"]["type_ref"] = "IDENTITY"
        row["query"]["relations"] = copy.deepcopy(req["relations"])
        row["relations"] = copy.deepcopy(req["relations"])
        from corpus_common import digest
        row["query_digest"] = digest("authority-query", row["query"])
    request, _ = age_fixture(mutate=wrong_clock_type)
    add(request, authority_refusal([], code="TYPE_INVALID"),
        "CLOCK must use an INSTANT type, and elapsed operands must have identical nominal types. IDENTITY cannot supply an instant.")

    def noninstant_operands(request, req, row):
        req["fields"][0]["type_ref"] = "IDENTITY"
        req["relations"][0]["right"] = {"kind": "PROPOSAL_FIELD", "field": "beneficiary"}
        row["fields"][0]["value"] = {"type_ref": "IDENTITY", "value": "employee-7"}
        row["query"]["fields"] = copy.deepcopy(req["fields"])
        row["query"]["relations"] = copy.deepcopy(req["relations"])
        row["relations"] = copy.deepcopy(req["relations"])
        from corpus_common import digest
        row["query_digest"] = digest("authority-query", row["query"])
    request, _ = age_fixture(mutate=noninstant_operands)
    add(request, authority_refusal([], code="TYPE_INVALID"),
        "Matching nominal identity operands still cannot establish an elapsed-time relation; both must have INSTANT kind.")

    for bound in ("01", "-1", "0.5"):
        request, _ = age_fixture(bound=bound)
        add(request, {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
            "The closed elapsed relation requires a canonical natural string; the malformed bound fails protocol input shape admission.")

    def missing_bound(request, req, row):
        req["relations"][0].pop("maximum_seconds")
    request, _ = age_fixture(mutate=missing_bound)
    add(request, {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
        "ELAPSED_LTE requires its bound. A four-member elapsed relation cannot select an implicit duration.")

    def inherited_extra(request, req, row):
        req["relations"][0]["kind"] = "AT_OR_BEFORE"
    request, _ = age_fixture(mutate=inherited_extra)
    add(request, {"status": "REFUSED", "code": "SCHEMA_INVALID", "path": ""},
        "An inherited ordering relation rejects maximum_seconds rather than silently ignoring it.")

    def copied_bound(request, req, row):
        row["relations"][0]["maximum_seconds"] = "901"
    request, _ = age_fixture(mutate=copied_bound)
    add(request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_RELATIONS"),
        "The provider's copied relation must equal the complete declaration, including the maximum. A substituted bound fails even when the actual measurement would pass.")

    def stale_response(request, req, row):
        row["as_of"] = "2026-09-10T04:29:59Z"
    request, _ = age_fixture(mutate=stale_response)
    add(request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_STALE"),
        "A current measurement does not cure a response older than the separately declared zero-second response allowance.")

    def missing_field(request, req, row):
        row["fields"] = []
    request, _ = age_fixture(mutate=missing_field)
    add(request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_FIELDS", "SOURCE_OBSERVATION_RELATIONS"),
        "Missing measurement evidence fails the field inventory and leaves its elapsed comparison unproven. Neither failure supplies permission.")

    def unavailable(request, req, row):
        row.clear()
        row.update(observation(req, request, status="UNAVAILABLE"))
    request, _ = age_fixture(mutate=unavailable)
    add(request, source_refusal(request, "current-session", "SOURCE_OBSERVATION_UNAVAILABLE"),
        "An unavailable record supplies no measurement and no default age. The existing availability failure withholds the dependent action.")
    return rows


if __name__ == "__main__":
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print(json.dumps({"measurement_age_cases": str(len(rows)), "implementation_or_output_consulted": False}))
