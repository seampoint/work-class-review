from __future__ import annotations

import base64
import copy
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor"), str(ROOT.parent / "review")]

from authority_fixture import authority_specimen
from consumer import Consumer
from implementation import authority, dispatch_gate, holdings
from implementation.common import PIN, PREFIX, Refusal, canonical, digest
from implementation.holdings_host import HoldingsReferenceHost


AT = "2026-10-08T12:00:00Z"


def configuration(principal="organization", clock_source="clock"):
    return {"schema": PREFIX + "holdings-configuration", "specification_pin": PIN, "id": "permission-registry",
        "principal": principal, "policy_revision": "policy-v1", "provider": "permission-provider", "source": "permission-source",
        "protected_channel": "permission-channel", "clock_source": clock_source, "administration_role": "permission-administrator",
        "actor_namespace": "organization-actors", "identity_provider": "identity-provider", "identity_revision": "identity-v1",
        "permissions": ["PREPARE", "REVIEW", "SUBMIT"], "conflicts": [{"left": "PREPARE", "right": "REVIEW"}]}


def request(config, state=None, kind="INITIALIZE", payload=None, event_id="event-initialize", at=AT):
    event = {"schema": PREFIX + "holdings-event", "id": event_id,
        "expected_revision": state["core"]["revision"] if state else "0",
        "expected_state_digest": holdings.state_digest(state) if state else None,
        "clock": {"source": config["clock_source"], "status": "AVAILABLE", "instant": at},
        "administration": None, "kind": kind, "payload": payload if payload is not None else {"grants": []}}
    basis = {"id": "administrator-designation", "configuration_digest": holdings.configuration_digest(config),
        "principal": config["principal"], "role": config["administration_role"], "actor": "administrator", "actor_kind": "HUMAN",
        "allowed_operations": ["GRANT", "INITIALIZE", "REVOKE"], "provider": config["provider"], "source": config["source"],
        "observed_at": at, "valid_from": "2026-01-01T00:00:00Z", "valid_until": None, "revoked_at": None, "evidence_ref": "designation-proof"}
    act = {"id": "act-" + event_id, "basis_id": basis["id"], "actor": basis["actor"], "principal": basis["principal"],
        "role": basis["role"], "kind": kind, "subject_digest": digest("holdings-administration-subject", {
            "configuration_digest": holdings.configuration_digest(config), "event": {key: value for key, value in event.items() if key != "administration"}}),
        "occurred_at": at, "status": "ACCEPTED"}
    returned = {"actor": basis["actor"], "provider": config["provider"], "source": config["source"], "channel": config["protected_channel"],
        "observed_at": at, "act_digest": digest("holdings-administration-act", act),
        "act_bytes_base64": base64.b64encode(canonical(act)).decode(), "evidence_ref": "return-proof", "provenance_digest": "sha256:" + "a" * 64}
    event["administration"] = {"basis": basis, "act": act, "return": returned}
    host = {"configuration_digest": holdings.configuration_digest(config), "selection_evidence": "selected-complete-registry",
        "authenticated_records": sorted([{"kind": kind, "record_digest": digest("holdings-administration-" + name, item),
            "provider": config["provider"], "source": config["source"], "channel": channel}
            for kind, name, item, channel in (("ADMIN_BASIS", "basis", basis, None), ("ADMIN_RETURN", "return", returned, config["protected_channel"]))], key=canonical),
        "seed_inventory": {"inventory_digest": digest("holdings-seed-inventory", event["payload"]["grants"]), "evidence_ref": "complete-inventory"} if kind == "INITIALIZE" else None}
    return {"schema": PREFIX + "holdings-input", "specification_pin": PIN, "configuration": config,
        "state": copy.deepcopy(state), "state_digest": holdings.state_digest(state) if state else None, "event": event, "host_evidence": host}


def basis(config, state, at):
    return {"configuration": config, "state": state, "state_digest": holdings.state_digest(state),
        "selection": {"configuration_digest": holdings.configuration_digest(config), "state_digest": holdings.state_digest(state),
            "revision": state["core"]["revision"], "provider": config["provider"], "source": config["source"], "channel": config["protected_channel"],
            "at": at, "status": "AVAILABLE", "selection_evidence": "host-owned-current-state"}}


class HoldingsTests(unittest.TestCase):
    def initialize(self, config=None, grants=None):
        config = config or configuration()
        supplied = request(config, payload={"grants": grants or []})
        result = Consumer().holdings_step(supplied)
        self.assertEqual(result["receipt"]["decision"], "INITIALIZED")
        self.assertEqual(result["state"]["core"]["revision"], "1")
        return config, result["state"]

    def test_excluded_permissions_span_events_and_duplicate_grant_cannot_extend(self):
        config, state = self.initialize()
        grant = request(config, state, "GRANT", {"grant_id": "grant-first", "actor": "person", "permission": "PREPARE", "valid_until": "2026-10-09T00:00:00Z"}, "grant-first")
        first = holdings.transition(grant)
        self.assertEqual(first["receipt"]["decision"], "GRANTED")
        duplicate = holdings.transition(request(config, first["state"], "GRANT", {"grant_id": "grant-duplicate", "actor": "person", "permission": "PREPARE", "valid_until": None}, "grant-duplicate"))
        self.assertEqual(duplicate["receipt"]["reasons"], ["ALREADY_HELD"])
        self.assertEqual(duplicate["state"]["core"]["grants"], first["state"]["core"]["grants"])
        conflict = holdings.transition(request(config, duplicate["state"], "GRANT", {"grant_id": "grant-conflict", "actor": "person", "permission": "REVIEW", "valid_until": None}, "grant-conflict"))
        self.assertEqual(conflict["receipt"]["decision"], "WITHHELD")
        self.assertEqual(conflict["receipt"]["reasons"], ["CONFLICTING_HOLDING"])
        self.assertEqual(conflict["state"]["core"]["revision"], "4")

    def test_exact_old_replay_returns_current_state_and_changed_event_refuses(self):
        config, state = self.initialize()
        initial = request(config)
        next_result = holdings.transition(request(config, state, "GRANT", {"grant_id": "grant", "actor": "person", "permission": "SUBMIT", "valid_until": None}, "grant"))
        initial.update(state=next_result["state"], state_digest=next_result["state_digest"])
        replay = holdings.transition(initial)
        self.assertTrue(replay["replay"])
        self.assertEqual(replay["receipt"]["revision"], "1")
        self.assertEqual(replay["state"]["core"]["revision"], "2")
        initial["host_evidence"]["selection_evidence"] = "changed-selection"
        self.assertEqual(holdings.transition(initial)["code"], "REPLAY_CONFLICT")

    def test_rehashed_history_does_not_admit_changed_grant(self):
        config, state = self.initialize(grants=[{"id": "seed", "actor": "person", "permission": "PREPARE", "valid_from": AT, "valid_until": None}])
        state["core"]["grants"][0]["permission"] = "REVIEW"
        supplied = request(config, state, "REVOKE", {"grant_id": "seed", "actor": "person", "permission": "REVIEW"}, "revoke")
        result = holdings.transition(supplied)
        self.assertEqual(result["code"], "STATE_INVALID")
        self.assertEqual(result["state"], supplied["state"])

    def test_revoke_names_original_grant_and_old_id_cannot_be_reused(self):
        config, state = self.initialize(grants=[{"id": "old", "actor": "person", "permission": "SUBMIT", "valid_from": AT, "valid_until": None}])
        revoked = holdings.transition(request(config, state, "REVOKE", {"grant_id": "old", "actor": "person", "permission": "SUBMIT"}, "revoke"))
        self.assertEqual(revoked["receipt"]["decision"], "REVOKED")
        fresh = holdings.transition(request(config, revoked["state"], "GRANT", {"grant_id": "new", "actor": "person", "permission": "SUBMIT", "valid_until": None}, "regrant"))
        old_revoke = holdings.transition(request(config, fresh["state"], "REVOKE", {"grant_id": "old", "actor": "person", "permission": "SUBMIT"}, "old-revoke"))
        self.assertEqual(old_revoke["receipt"]["reasons"], ["NOT_ACTIVE"])
        self.assertTrue(holdings.active(next(row for row in old_revoke["state"]["core"]["grants"] if row["id"] == "new"), AT))
        reuse = holdings.transition(request(config, fresh["state"], "GRANT", {"grant_id": "old", "actor": "other", "permission": "SUBMIT", "valid_until": None}, "reuse"))
        self.assertEqual(reuse["code"], "DEPENDENCY_MISMATCH")

    def test_admin_return_binding_and_authentication_precede_accepted_status(self):
        config = configuration()
        supplied = request(config)
        supplied["event"]["administration"]["act"]["status"] = "REJECTED"
        self.assertEqual(holdings.transition(supplied)["code"], "DEPENDENCY_MISMATCH")
        supplied = request(config)
        supplied["host_evidence"]["authenticated_records"] = []
        self.assertEqual(holdings.transition(supplied)["code"], "EVIDENCE_UNAVAILABLE")

    def test_initialization_requires_completeness_and_rejects_imported_conflicts(self):
        supplied = request(configuration())
        supplied["host_evidence"]["seed_inventory"] = None
        self.assertEqual(holdings.transition(supplied)["code"], "EVIDENCE_UNAVAILABLE")
        supplied = request(configuration(), payload={"grants": [{"id": "first", "actor": "person", "permission": "PREPARE", "valid_from": AT, "valid_until": None},
            {"id": "second", "actor": "person", "permission": "REVIEW", "valid_from": AT, "valid_until": None}]})
        self.assertEqual(holdings.transition(supplied)["code"], "STATE_INVALID")

    def test_grant_capacity_allows_noop_but_not_new_grant(self):
        grants = [{"id": "grant-%03d" % index, "actor": "actor-%03d" % index, "permission": "SUBMIT", "valid_from": AT, "valid_until": None} for index in range(256)]
        config, state = self.initialize(grants=grants)
        noop = holdings.transition(request(config, state, "GRANT", {"grant_id": "noop", "actor": "actor-000", "permission": "SUBMIT", "valid_until": None}, "noop"))
        self.assertEqual(noop["receipt"]["reasons"], ["ALREADY_HELD"])
        overflow = holdings.transition(request(config, state, "GRANT", {"grant_id": "new", "actor": "new-person", "permission": "SUBMIT", "valid_until": None}, "new"))
        self.assertEqual(overflow["code"], "LIMIT_EXCEEDED")
        self.assertEqual(overflow["state"], state)

    def test_current_policy_uses_query_time_and_exclusive_expiry(self):
        config, state = self.initialize(grants=[{"id": "seed", "actor": "person", "permission": "SUBMIT", "valid_from": AT, "valid_until": "2026-10-08T13:00:00Z"}])
        req = {"id": "submit-permission", "step": "submit", "configuration_digest": holdings.configuration_digest(config), "permission": "SUBMIT", "actor": "EXECUTOR"}
        current = {"proposal": {"step": "submit", "executor": {"actor": "person"}}, "envelope": {"holdings_requirements": [req]}, "clock": {"instant": AT}, "holdings_bases": [basis(config, state, AT)]}
        self.assertEqual(holdings.policy(current, [])["reasons"], set())
        current["clock"]["instant"] = "2026-10-08T13:00:00Z"
        self.assertEqual(holdings.policy(current, [])["reasons"], {"HOLDINGS_STALE"})
        current["holdings_bases"][0]["selection"]["at"] = current["clock"]["instant"]
        self.assertEqual(holdings.policy(current, [])["reasons"], {"CURRENT_HOLDING_REQUIRED"})

    def test_exact_gate_actor_does_not_use_other_successful_leaf(self):
        current = {"proposal": {"executor": {"actor": "executor"}}, "envelope": {"gate": {"kind": "DECIDE", "role": "reviewer", "decision_requirement": "selected"}}}
        req = {"actor": "GATE_ACTOR"}
        contexts = {"selected": {"decision": {"actor": "reviewer"}}, "other": {"decision": {"actor": "unselected-reviewer"}}}
        self.assertEqual(holdings.actor_for(current, req, [], contexts), "reviewer")
        with self.assertRaises(Refusal):
            holdings.actor_for(current, req, [], {"other": contexts["other"]})

    def test_combined_dispatch_projection_accepts_64_and_refuses_65(self):
        step = {"id": "submit", "dispatch_gate": {"kind": "SOURCE_REQUIREMENTS", "requirements": ["source-%02d" % index for index in range(63)]}}
        envelope = {"gate": {"kind": "DECIDE"}, "holdings_requirements": [{"id": "permission", "step": "submit", "configuration_digest": "sha256:" + "a" * 64,
            "permission": "SUBMIT", "actor": "EXECUTOR"}]}
        self.assertIsNone(holdings.declaration_error({"steps": [step]}, envelope))
        step["dispatch_gate"]["requirements"].append("source-63")
        self.assertEqual(holdings.declaration_error({"steps": [step]}, envelope), "LIMIT_EXCEEDED")

    def test_phase_two_collects_basis_failures_in_global_priority(self):
        config, state = self.initialize()
        first = basis(config, state, "2026-02-30T00:00:00Z")
        second = basis(config, state, AT)
        second["state"] = copy.deepcopy(second["state"])
        second["state"]["core"]["configuration_digest"] = "sha256:" + "b" * 64
        second["state_digest"] = holdings.state_digest(second["state"])
        supplied = {"proposal": {"step": "submit"}, "envelope": {"principal": config["principal"], "clock_source": config["clock_source"], "holdings_requirements": []},
            "holdings_bases": [first, second]}
        with self.assertRaises(Refusal) as error:
            holdings.phase_two(supplied)
        self.assertEqual(error.exception.code, "DEPENDENCY_MISMATCH")
        second["state"]["specification_pin"] = "sha256:" + "b" * 64
        with self.assertRaises(Refusal) as error:
            holdings.phase_two(supplied)
        self.assertEqual(error.exception.code, "VERSION_UNSUPPORTED")

    def test_extra_basis_binding_precedes_selected_provider_dependency(self):
        config, state = self.initialize()
        item = basis(config, state, AT)
        item["selection"]["provider"] = "wrong-provider"
        supplied = {"proposal": {"step": "submit"}, "envelope": {"principal": config["principal"], "clock_source": config["clock_source"], "holdings_requirements": []},
            "holdings_bases": [item]}
        self.assertEqual(holdings.phase_three(supplied), "BINDING_MISMATCH")

    def test_selected_holdings_pin_precedes_wrong_envelope_digest(self):
        supplied, _ = authority_specimen(shared_budget=False)
        config = configuration(supplied["envelope"]["principal"], supplied["envelope"]["clock_source"])
        at = supplied["clock"]["instant"]
        state = holdings.transition(request(config, at=at))["state"]
        item = basis(config, state, at)
        item["state"]["specification_pin"] = "sha256:" + "b" * 64
        supplied["holdings_bases"] = [item]
        supplied["envelope"]["source_digest"] = "sha256:" + "c" * 64
        self.assertEqual(Consumer().evaluate({"kind": "AUTHORITY", "request": supplied})["code"], "VERSION_UNSUPPORTED")

    def test_unavailable_selection_still_requires_a_calendar_instant(self):
        config, state = self.initialize()
        item = basis(config, state, "2026-02-30T00:00:00Z")
        item["selection"]["status"] = "UNAVAILABLE"
        with self.assertRaises(Refusal) as error:
            holdings.phase_two({"holdings_bases": [item]})
        self.assertEqual(error.exception.code, "CLOCK_INVALID")

    def test_optional_empty_bases_have_distinct_evidence_digest(self):
        supplied, _ = authority_specimen(shared_budget=False)
        absent = authority.evaluate_authority(supplied, PIN)
        supplied["holdings_bases"] = []
        present = authority.evaluate_authority(supplied, PIN)
        self.assertEqual(present["status"], "READY_FOR_RESERVATION")
        self.assertNotEqual(absent["evidence_digest"], present["evidence_digest"])
        supplied["envelope"]["holdings_requirements"] = []
        self.assertFalse(dispatch_gate.immutable_binding(supplied, {**supplied, "envelope": {key: value for key, value in supplied["envelope"].items() if key != "holdings_requirements"}}))

    def test_full_authority_requires_current_membership_and_admits_state_before_policy(self):
        def add_requirement(supplied, original):
            config = configuration(supplied["envelope"]["principal"], supplied["envelope"]["clock_source"])
            at = supplied["clock"]["instant"]
            initialized = holdings.transition(request(config, payload={"grants": [{"id": "executor-grant", "actor": supplied["proposal"]["executor"]["actor"],
                "permission": "SUBMIT", "valid_from": at, "valid_until": None}]}, at=at))
            supplied["envelope"]["holdings_requirements"] = [{"id": "current-submit", "step": supplied["proposal"]["step"],
                "configuration_digest": holdings.configuration_digest(config), "permission": "SUBMIT", "actor": "EXECUTOR"}]
            supplied["holdings_bases"] = [basis(config, initialized["state"], at)]
        supplied, _ = authority_specimen(shared_budget=False, mutator=add_requirement)
        admitted = Consumer().evaluate({"kind": "AUTHORITY", "request": supplied})
        self.assertEqual(admitted["status"], "READY_FOR_RESERVATION")
        requirement = supplied["envelope"]["holdings_requirements"][0]
        self.assertIn({"purpose": "HOLDINGS", "subject_digest": digest("holdings-query", {"requirement": requirement,
            "actor": supplied["proposal"]["executor"]["actor"], "at": supplied["clock"]["instant"]}), "requirement_ref": "current-submit", "at": supplied["clock"]["instant"]}, admitted["checks"])
        missing = copy.deepcopy(supplied)
        missing["holdings_bases"] = []
        self.assertEqual(Consumer().evaluate({"kind": "AUTHORITY", "request": missing})["reasons"], ["HOLDINGS_UNAVAILABLE"])
        stale = copy.deepcopy(supplied)
        stale["holdings_bases"][0]["selection"]["at"] = "2026-01-01T00:00:00Z"
        self.assertEqual(authority.evaluate_authority(stale, PIN)["reasons"], ["HOLDINGS_STALE"])
        corrupted = copy.deepcopy(supplied)
        item = corrupted["holdings_bases"][0]
        item["state"]["core"]["grants"][0]["actor"] = "other-person"
        item["state_digest"] = holdings.state_digest(item["state"])
        item["selection"]["state_digest"] = item["state_digest"]
        self.assertEqual(Consumer().evaluate({"kind": "AUTHORITY", "request": corrupted})["code"], "STATE_INVALID")

    def test_exhausted_history_replays_but_refuses_fresh_changes_and_eligibility(self):
        config = configuration()
        state = None
        for index in range(64):
            supplied = request(config, state, "INITIALIZE" if index == 0 else "GRANT",
                {"grants": [{"id": "seed", "actor": "person", "permission": "SUBMIT", "valid_from": AT, "valid_until": None}]} if index == 0
                else {"grant_id": "noop-%02d" % index, "actor": "person", "permission": "SUBMIT", "valid_until": None}, "event-%02d" % index)
            state = holdings._apply(config, state, supplied["event"], supplied["host_evidence"])["state"]
        supplied = request(config, state, "REVOKE", {"grant_id": "unknown", "actor": "person", "permission": "SUBMIT"}, "fresh")
        self.assertEqual(holdings.transition(supplied)["code"], "LIMIT_EXCEEDED")
        supplied["event"]["expected_revision"] = "63"
        self.assertEqual(holdings.transition(supplied)["code"], "REVISION_CONFLICT")
        original = state["records"][0]
        replay = {**request(config, state), "event": original["event"], "host_evidence": original["host_evidence"]}
        self.assertTrue(holdings.transition(replay)["replay"])
        current = {"proposal": {"step": "submit", "executor": {"actor": "person"}}, "envelope": {"holdings_requirements": [{"id": "submit", "step": "submit",
            "configuration_digest": holdings.configuration_digest(config), "permission": "SUBMIT", "actor": "EXECUTOR"}]}, "clock": {"instant": AT}, "holdings_bases": [basis(config, state, AT)]}
        self.assertEqual(holdings.policy(current, [])["reasons"], {"HOLDINGS_CAPACITY_EXHAUSTED"})

    def test_host_serializes_conflicting_writers(self):
        config, state = self.initialize()
        host = HoldingsReferenceHost(Consumer())
        host.install_holdings("organization", config, state, holdings.state_digest(state))
        requests = [request(config, state, "GRANT", {"grant_id": permission, "actor": "person", "permission": permission, "valid_until": None}, permission) for permission in ("PREPARE", "REVIEW")]
        results = []
        threads = [threading.Thread(target=lambda supplied=supplied: results.append(host.submit_holdings("organization", supplied))) for supplied in requests]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sorted(row.get("code", row.get("receipt", {}).get("decision")) for row in results), ["GRANTED", "REVISION_CONFLICT"])
        restored = HoldingsReferenceHost.from_checkpoint(Consumer(), host.export_checkpoint())
        self.assertEqual(restored.holdings_snapshot("organization", holdings.configuration_digest(config)), host.holdings_snapshot("organization", holdings.configuration_digest(config)))

    def test_public_failure_has_no_protected_detail(self):
        self.assertEqual(HoldingsReferenceHost.public_failure(), {"status": "REFUSED", "code": "OPERATION_NOT_ALLOWED"})


if __name__ == "__main__":
    unittest.main()
