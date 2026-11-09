"""Derive recovery controller separation from the supplier source and REC-003."""
from __future__ import annotations

import copy
import datetime
import json

from corpus_common import CASES, CONFORMANCE, candidate_pin, digest, exact_case, write_canonical_json
from lifecycle_factory import stateful_refusal
from recovery_fixture import authorize, disposition_expected
from recovery_lifecycle_fixture import PBR, dispute_prerequisite, supplier_chain, work_dispose_expected, work_dispose_request
from reservation_fixture import refusal


GROUP = CASES / "recovery-authority"


def registry_cases():
    rows = []
    for result in ("ESTABLISH_NO_EFFECT", "ESTABLISH_EFFECT"):
        source = CONFORMANCE / "specimens/supplier-payment-recovery/recovery" / result.lower() / "requests.json"
        request = copy.deepcopy(json.loads(source.read_text())[1]["input"])
        assert request["specification_pin"] == candidate_pin(), "Regenerate the supplier recovery specimen before the corpus"
        authority = request["state"]["core"]["reservations"][0]["authority"]
        assert authority["envelope"]["gate"]["kind"] == "DECIDE" and not authority.get("decision_bases")
        actors = [
            ("independent", "independent-recovery-controller-human", False),
            ("executor", authority["proposal"]["executor"]["actor"], True),
            ("payment_releaser", next(row["actor"] for row in authority["acts"] if row["kind"] == "INSTANCE_DECISION"), True),
            ("grantor", next(row["actor"] for row in authority["acts"] if row["kind"] == "GRANT"), False),
            ("attester", next(row["actor"] for row in authority["acts"] if row["kind"] == "ORGANISATIONAL_ATTESTATION"), False),
        ]
        assert len({actor for _, actor, _ in actors}) == len(actors)
        for name, actor, forbidden in actors:
            supplied = copy.deepcopy(request)
            prefix = "recovery-controller-" if result == "ESTABLISH_NO_EFFECT" else "recovery-effect-controller-"
            supplied["event"]["id"] = prefix + name.replace("_", "-")
            supplied["host_evidence"]["recovery"]["authenticated_records"] = [row for row in supplied["host_evidence"]["recovery"]["authenticated_records"] if row["kind"] != "RECOVERY_RETURN"]
            facts = {"configuration": supplied["state"]["core"]["configuration"]}
            authorize(facts, supplied["event"], supplied["host_evidence"], operation=result,
                      scope_digest=digest("recovery-target", supplied["event"]["payload"]["target"]), actor=actor)
            expected = refusal(supplied["state"], "ADMINISTRATION_NOT_ESTABLISHED") if forbidden else disposition_expected(supplied)
            derivation = ("Supplier recovery source revision2 paragraph13 and REC-003 exclude the affected executor and exact selected payment releaser. The "
                          + name.replace("_", " ") + " identity has a separate current target-bound human recovery designation for " + result + ". "
                          + ("Its original executor or selected-gate identity still forbids adjudication." if forbidden else "A separate grantor or attester role creates no further exclusion.")
                          + (" No-effect authority also explicitly grants RELEASE_DISPUTED_EXPOSURE." if result == "ESTABLISH_NO_EFFECT" else " The complete payment journal corroborates the established authorized effect."))
            rows.append(exact_case("C3-RCTRL-" + str(len(rows) + 1).zfill(3), "aggregate-step", supplied, expected, ["REC-003"], derivation))
    return rows


def work_cases(start):
    chain = supplier_chain()
    _, disputed = dispute_prerequisite(chain)
    before = disputed["state"]
    authority = chain["change_authority"]["input"]
    assert authority["envelope"]["gate"]["kind"] == "VERIFY" and not authority.get("decision_bases")
    assert not any(permit["occurrence"]["step_id"] == "pay-invoice" for permit in before["permits"])
    step = next(row for row in chain["definition"]["steps"] if row["id"] == "change-supplier-destination")
    assert step["completion"]["effect_provider"] and step["completion"]["no_effect_provider"]
    actors = [
        ("independent", "independent-master-recovery-controller", False),
        ("executor", authority["proposal"]["executor"]["actor"], True),
        ("destination_confirmer", next(row["actor"] for row in authority["acts"] if row["kind"] == "VERIFY"), True),
        ("grantor", next(row["actor"] for row in authority["acts"] if row["kind"] == "GRANT"), False),
        ("attester", next(row["actor"] for row in authority["acts"] if row["kind"] == "ORGANISATIONAL_ATTESTATION"), False),
    ]
    assert len({actor for _, actor, _ in actors}) == len(actors)
    rows = []
    for result in ("ESTABLISH_EFFECT", "ESTABLISH_NO_EFFECT"):
        for name, actor, forbidden in actors:
            supplied = work_dispose_request(chain, before, result=result,
                event_id="master-controller-" + result.lower() + "-" + name.replace("_", "-"))
            host = supplied["recovery_host"]
            host["authenticated_records"] = [row for row in host["authenticated_records"] if row["kind"] != "RECOVERY_RETURN"]
            facts = {"configuration": {"principal": before["deployment_organization_id"], "recovery": chain["definition"]["recovery"]}, "clock": {"instant": PBR["NOW"]}}
            authorize(facts, supplied["event"], host, operation=result,
                scope_digest=digest("recovery-target", supplied["event"]["target"]), actor=actor)
            expected = stateful_refusal(before, "ADMINISTRATION_NOT_ESTABLISHED") if forbidden else work_dispose_expected(supplied)
            derivation = ("Supplier recovery source revision2 sections02 and 04 and REC-003 exclude the affected supplier-master executor and selected destination confirmer. The "
                + name.replace("_", " ") + " identity has separate current target-bound human recovery authority. No future payment releaser is selected. "
                + ("The same executor or confirmer identity still refuses with unchanged state." if forbidden else
                   "The local DISPOSE transaction applies the adjudication: " + ("restore the original prerequisite and unproposed payment eligibility." if result == "ESTABLISH_EFFECT" else "stop the ACTIVE instance while retaining historical completion and routes.")))
            rows.append(exact_case("C3-RCTRL-" + str(start + len(rows)).zfill(3), "step", supplied, expected, ["REC-003", "REC-012", "REC-013"], derivation))
    return rows


def build():
    rows = registry_cases()
    work = work_cases(len(rows) + 1)
    rows.extend(work)
    for original in work:
        event_id = original["input"]["event"]["event_id"]
        if not event_id.endswith(("-grantor", "-attester")):
            continue
        before = original["expected"]["state"]
        instant = (datetime.datetime.fromisoformat(PBR["NOW"].replace("Z", "+00:00")) + datetime.timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        event = PBR["clock_event"](before, event_id + "-restart-clock", source="governance-clock", revision="2", observed_time=instant)
        supplied = PBR["lifecycle_input"](original["input"]["definition"], original["input"]["definition_digest"], before, event)
        _, expected = PBR["accepted_clock"](before, event)
        rows.append(exact_case("C3-RCTRL-" + str(len(rows) + 1).zfill(3), "step", supplied, expected,
            ["REC-003", "REC-013", "REC-015"],
            "A fresh public CLOCK reconstructs the complete retained work-only disposition and application by the separately designated grantor or attester. It preserves the source-selected restoration or STOP and accepts no new operation."))
    return rows


def main():
    rows = build()
    for row in rows:
        write_canonical_json(GROUP / (row["id"] + ".json"), row)
    print(json.dumps({"cases": str(len(rows)), "group": str(GROUP.relative_to(CONFORMANCE))}))


if __name__ == "__main__":
    main()
