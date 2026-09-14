"""Revocation-observation inventory, freshness, and current-validity phase."""
from __future__ import annotations

import json

try:
    from .authority import _inside, _instant, _records, canonical, digest, _refusal
except ImportError:
    from authority import _inside, _instant, _records, canonical, digest, _refusal


def _query(subject, at, declaration):
    return {"purpose": "REVOCATION", "subject_digest": subject, "at": at, "provider": declaration["provider"], "source": declaration["source"]}


def observe_revocation(request, selected_acts, root, capacities, credentials, envelope=None, operation_digest=None):
    envelope = envelope or request["envelope"]
    clock = request["clock"]
    now = None
    if clock["status"] == "AVAILABLE":
        try:
            now = _instant(clock["instant"])
        except (TypeError, ValueError):
            return _refusal("INPUT_INVALID")
    capacities = _records(capacities) if not isinstance(capacities, dict) else capacities
    root_digest = digest("authority-root", root)
    declarations = {root_digest: root["revocation"]}
    queries = {}
    for act in selected_acts:
        capacity = capacities[act["capacity"]]
        capacity_digest = digest("authority-capacity", capacity)
        declarations[capacity_digest] = capacity["revocation"]
        for at in (act["occurred_at"], clock["instant"] if now is not None else None):
            if at is not None:
                queries[canonical(_query(root_digest, at, root["revocation"]))] = _query(root_digest, at, root["revocation"])
                queries[canonical(_query(capacity_digest, at, capacity["revocation"]))] = _query(capacity_digest, at, capacity["revocation"])
    envelope_digest = digest("authority-envelope", envelope)
    declarations[envelope_digest] = envelope["revocation"]
    if now is not None:
        queries[canonical(_query(envelope_digest, clock["instant"], envelope["revocation"]))] = _query(envelope_digest, clock["instant"], envelope["revocation"])
        for credential in credentials:
            credential_digest = digest("authority-credential", credential)
            declarations[credential_digest] = credential["revocation"]
            queries[canonical(_query(credential_digest, clock["instant"], credential["revocation"]))] = _query(credential_digest, clock["instant"], credential["revocation"])

    expected = {digest("authority-query", query): query for query in queries.values()}
    by_query = {}
    for observation in request["observations"]:
        query = observation["query"]
        query_digest = observation["query_digest"]
        if query_digest != digest("authority-query", query):
            return _refusal("DEPENDENCY_MISMATCH")
        if query["provider"] not in root["providers"]:
            return _refusal("DEPENDENCY_MISMATCH")
        if now is not None and query_digest not in expected:
            return _refusal("DEPENDENCY_MISMATCH")
        by_query.setdefault(canonical(query), set()).add(canonical(observation))
    if now is None:
        return {"status": "OBSERVATIONS_DERIVED", "queries": [], "reasons": {"CLOCK_UNAVAILABLE"}, "failed": []}
    expected_query_keys = {canonical(query) for query in expected.values()}
    if set(by_query) - expected_query_keys:
        return _refusal("DEPENDENCY_MISMATCH")
    if expected_query_keys - set(by_query):
        return _refusal("EVIDENCE_UNAVAILABLE")

    reasons = set()
    failed = []

    def fail(reason, purpose, subject, reference, at):
        # AUTHORITY-CHECKS: one failed_checks row per failed check and the reason it contributed.
        reasons.add(reason)
        failed.append({"purpose": purpose, "subject_digest": subject, "requirement_ref": reference, "at": at, "reason": reason})

    now_stamp = clock["instant"]
    for query_digest, query in expected.items():
        rows = by_query[canonical(query)]
        if len(rows) > 1:
            fail("OBSERVATION_CONFLICT", "REVOCATION", query["subject_digest"], query_digest, query["at"])
            continue
        observation = json.loads(next(iter(rows)))
        if observation["status"] != "AVAILABLE":
            fail({"UNAVAILABLE": "OBSERVATION_UNAVAILABLE", "INCOMPLETE": "OBSERVATION_INCOMPLETE", "CONFLICT": "OBSERVATION_CONFLICT"}[observation["status"]], "REVOCATION", query["subject_digest"], query_digest, query["at"])
            continue
        try:
            query_at = _instant(query["at"])
            as_of = _instant(observation["as_of"])
            age = int((query_at - as_of).total_seconds())
            maximum = int(declarations[query["subject_digest"]]["max_age_seconds"])
            if age > maximum:
                fail("OBSERVATION_STALE", "REVOCATION", query["subject_digest"], query_digest, query["at"])
        except (KeyError, TypeError, ValueError):
            fail("OBSERVATION_STALE", "REVOCATION", query["subject_digest"], query_digest, query["at"])
        if observation["revoked"]:
            fail("REVOKED", "REVOCATION", query["subject_digest"], query_digest, query["at"])

    if not _inside(envelope["temporal_validity"], now):
        fail("ENVELOPE_EXPIRED", "ENVELOPE_VALIDITY", envelope_digest, envelope["id"], now_stamp)
    if not _inside(root["validity"], now) and not root["prior_acts_survive_expiry"]:
        fail("ROOT_EXPIRED", "ROOT_BINDING", envelope_digest, root["id"], now_stamp)
    for credential in credentials:
        if not _inside(credential["validity"], now):
            fail("CREDENTIAL_EXPIRED", "CREDENTIAL", operation_digest, credential["id"], now_stamp)
    for act in selected_acts:
        act_digest = digest("authority-act", act)
        capacity = capacities[act["capacity"]]
        if not _inside(capacity["validity"], now):
            reliance = capacity["reliance"]
            if reliance["kind"] != "SURVIVE_EXPIRY" or not _inside(reliance["validity"], now):
                fail("RELIANCE_EXPIRED", "ACT_RELIANCE", act_digest, act["capacity"], now_stamp)
    executor = request["proposal"]["executor"]
    occupancy = _records(request["occupancies"])[executor["occupancy"]]
    if not _inside(occupancy["validity"], now):
        fail("ACT_EXPIRED", "EXECUTOR_OCCUPANCY", operation_digest, executor["occupancy"], now_stamp)
    return {"status": "OBSERVATIONS_DERIVED", "queries": list(expected.values()), "reasons": reasons, "failed": failed}


def derive_revocation_observations(*args, **kwargs):
    return observe_revocation(*args, **kwargs)
