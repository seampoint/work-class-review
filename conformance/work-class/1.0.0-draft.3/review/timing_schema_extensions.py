"""Closed event-time, deferred-deadline and measurement-age carriers."""

from __future__ import annotations

from copy import deepcopy

from equipment_schema_extensions import BASE, DIGEST, FIELD, ID, INSTANT, VALUE, arr, nullable, obj, optional


def extend_timing_schemas(work_schema, lifecycle_schema, authority_schema):
    authority = authority_schema["$defs"]
    inherited = deepcopy(authority["sourceObservationRelation"])
    if "oneOf" in inherited:
        inherited = inherited["oneOf"][0]
    elapsed = obj({"id": ID, "kind": {"const": "ELAPSED_LTE"},
        "left": {"$ref": "#/$defs/sourceObservationSelector"},
        "right": {"$ref": "#/$defs/sourceObservationSelector"},
        "maximum_seconds": {"type": "string", "pattern": r"^(0|[1-9][0-9]*)$"}})
    authority["sourceObservationRelation"] = {"oneOf": [inherited, elapsed]}

    work, life = work_schema["$defs"], lifecycle_schema["$defs"]
    local = lambda name: {"$ref": "#/$defs/" + name}
    life["decisionDetailLimit"]["properties"]["limit_kind"]["enum"].append("DEADLINE_RECORDS")
    optional(life["state"], "timing_clock_events", {"type": "array", "items": local("clockEvent")})
    natural = {"type": "string", "pattern": r"^(0|[1-9][0-9]*)$"}
    duration = {"value": {"type": "string", "pattern": r"^[1-9][0-9]*$"},
        "unit": {"enum": ["SECOND", "MINUTE", "HOUR", "DAY"]}}
    work["eventAnchor"] = obj({
        "id": ID, "provider": ID, "source": ID, "record_type": ID,
        "time": {"oneOf": [obj({"kind": {"const": "EVENT_TIME"}, "type_ref": ID}),
            obj({"kind": {"const": "FIELD"}, "field_ref": ID})]},
        "fields": arr(local("fieldDeclaration"), 64, 1),
        "subject_fields": arr(ID, 64, 1),
        "request_bindings": arr(obj({"step_id": ID, "subject_field": ID,
            "target_request_field": ID}), 64, 1),
    })
    optional(work["definition"], "event_anchors", arr(local("eventAnchor"), 64, 1))
    work["eventAnchorDue"] = obj({"kind": {"const": "ELAPSED_FROM_EVENT_ANCHOR"},
        "anchor_ref": ID, **deepcopy(duration)})
    source_reasons = ["SOURCE_OBSERVATION_BINDING", "SOURCE_OBSERVATION_TIME",
        "SOURCE_OBSERVATION_STALE", "SOURCE_OBSERVATION_FIELDS", "SOURCE_OBSERVATION_RELATIONS",
        "SOURCE_OBSERVATION_UNAVAILABLE", "SOURCE_OBSERVATION_INCOMPLETE",
        "SOURCE_OBSERVATION_CONFLICT", "SOURCE_OBSERVATION_ROLLED_BACK"]
    work["withheldDue"] = obj({"kind": {"const": "ELAPSED_FROM_FIRST_WITHHELD"},
        **deepcopy(duration), "failed_checks": arr(obj({"purpose": {"const": "SOURCE_OBSERVATION"},
            "requirement_ref": ID, "reason": {"enum": source_reasons}}), 64, 1)})
    work["dispatchDue"] = obj({"kind": {"const": "ELAPSED_FROM_FIRST_DISPATCH"}, **deepcopy(duration)})
    work["deadline"]["properties"]["due"]["oneOf"].extend(
        local(name) for name in ("eventAnchorDue", "withheldDue", "dispatchDue"))

    life["eventAnchorRecord"] = obj({"provider": ID, "source": ID, "record_type": ID,
        "provider_record_id": ID, "provider_revision": ID, "event_time": INSTANT,
        "observed_at": INSTANT, "fields": arr(FIELD, 64, 1), "evidence_ref": ID,
        "provenance_digest": DIGEST})
    life["initialEventAnchor"] = obj({"anchor_ref": ID, "specification_pin": DIGEST,
        "work_class_digest": DIGEST, "organization_id": ID, "instance_id": ID,
        "record": local("eventAnchorRecord"), "record_digest": DIGEST})
    anchor_digests = arr(obj({"anchor_ref": ID, "anchor_digest": DIGEST}), 64, 1)
    optional(life["deploymentAuthorization"], "event_anchor_digests", anchor_digests)
    optional(life["deployInput"], "event_anchors", arr(local("initialEventAnchor"), 64, 1))
    optional(life["state"], "initial_event_anchors", arr(local("initialEventAnchor"), 64, 1))
    life["deployInput"]["properties"]["initial_clocks"]["items"] = local("clock")

    life["eventDutyExpiry"] = {"oneOf": [
        obj({"kind": {"const": "DEPLOYMENT"}, "deployment_authorization_digest": DIGEST,
            "clock": local("clockAvailable")}),
        obj({"kind": {"const": "CLOCK"}, "event_digest": DIGEST, "clock": local("clockAvailable")}),
    ]}
    life["timingDischarge"] = obj({"kind": {"const": "COMPLETION"}, "event_digest": DIGEST,
        "occurrence_id": DIGEST, "evidence_digest": DIGEST})
    duty = {"deadline_id": ID, "target_step_id": ID, "source": ID,
        "boundary": {"enum": ["AT_OR_AFTER", "AFTER"]}, "anchor_ref": ID,
        "anchor_digest": DIGEST, "due": INSTANT, "creation_digest": DIGEST}
    duty_variants = []
    for status in ("PENDING", "EXPIRED"):
        for bound in (False, True):
            extra = {"status": {"const": status},
                "occurrence_id": DIGEST if bound else {"type": "null"},
                "binding_event_digest": DIGEST if bound else {"type": "null"}}
            if status == "EXPIRED":
                extra["expiry_basis"] = local("eventDutyExpiry")
            duty_variants.append(obj({**deepcopy(duty), **extra}))
    duty_variants.append(obj({**deepcopy(duty), "status": {"const": "DISCHARGED"},
        "occurrence_id": DIGEST, "binding_event_digest": DIGEST,
        "discharge_basis": local("timingDischarge")}))
    life["eventDuty"] = {"oneOf": duty_variants}
    optional(life["state"], "event_duties", arr(local("eventDuty"), 256, 1))

    life["timingTrigger"] = {"oneOf": [
        obj({"kind": {"const": "FIRST_WITHHELD"}, "evaluation_digest": DIGEST,
            "sequence": natural, "clock": local("clockAvailable")}),
        obj({"kind": {"const": "FIRST_DISPATCH"}, "event_digest": DIGEST, "sequence": natural,
            "dispatch_digest": DIGEST, "dispatch_attempt_digest": DIGEST,
            "clock": local("clockAvailable")}),
    ]}
    life["deferredExpiry"] = {"oneOf": [
        obj({"kind": {"const": "CLOCK"}, "event_digest": DIGEST, "clock": local("clockAvailable")}),
        obj({"kind": {"const": "DISPATCH"}, "event_digest": DIGEST, "clock": local("clockAvailable")}),
    ]}
    deferred = {"deadline_id": ID, "occurrence_id": DIGEST, "source": ID,
        "boundary": {"enum": ["AT_OR_AFTER", "AFTER"]}, "activation_event_digest": DIGEST,
        "creation_digest": DIGEST}
    alternatives = [obj({**deepcopy(deferred), "status": {"const": "WAITING"}})]
    for status in ("PENDING", "EXPIRED", "DISCHARGED"):
        extra = {"status": {"const": status}, "trigger": local("timingTrigger"), "due": INSTANT}
        if status == "EXPIRED":
            extra["expiry_basis"] = local("deferredExpiry")
        if status == "DISCHARGED":
            extra["discharge_basis"] = local("timingDischarge")
        alternatives.append(obj({**deepcopy(deferred), **extra}))
    alternatives.extend([
        obj({**deepcopy(deferred), "status": {"const": "DISCHARGED"},
            "discharge_basis": local("timingDischarge")}),
        obj({**deepcopy(deferred), "status": {"const": "TRIGGER_OVERFLOW"},
            "trigger": local("timingTrigger"), "reason": {"const": "DEADLINE_TIME_OVERFLOW"}}),
    ])
    life["deferredDeadline"] = {"oneOf": alternatives}
    optional(life["state"], "deferred_deadlines", arr(local("deferredDeadline"), 4096))
    for name in ("event_duties", "deferred_deadlines"):
        optional(life["recoveryProjection"], name, deepcopy(life["state"]["properties"][name]))
