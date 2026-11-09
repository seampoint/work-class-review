"""LIFE-013's dependency-affected set, shared by the builders that need it.

When a completed occurrence becomes disputed, the affected set is that occurrence and every
transitive active or completed descendant through the predecessor lists.
"""

from __future__ import annotations

import copy

from corpus_common import digest
from lifecycle_factory import admitted_transition, governed_outcome


def apply_dependency_block(state: dict, source_occurrence_id: str) -> None:
    """LIFE-013's dependency-affected set, applied in place.

    The set is the disputed occurrence and every transitive active or completed descendant
    through the predecessor lists. Active members other than the root become BLOCKED_DISPUTE,
    their owning OPEN obligations become BLOCKED, a DISCHARGED obligation whose completion
    frontier intersects the set becomes DISPUTED, and WAITING ancestors of a newly disputed
    obligation become DISPUTED, propagating outward.
    """
    affected = {source_occurrence_id}
    changed = True
    while changed:
        changed = False
        for row in state["active"] + state["completed"]:
            identifier = row["occurrence"]["occurrence_id"]
            if identifier in affected:
                continue
            if any(pred in affected for pred in row["occurrence"]["predecessor_occurrence_ids"]):
                affected.add(identifier)
                changed = True
    for active in state["active"]:
        if active["occurrence"]["occurrence_id"] != source_occurrence_id and active["occurrence"]["occurrence_id"] in affected:
            active["status"] = "BLOCKED_DISPUTE"
    for obligation in state["obligations"]:
        if obligation["status"] == "OPEN" and obligation.get("expected_occurrence_id") in affected:
            obligation["status"] = "BLOCKED"
        elif obligation["status"] == "DISCHARGED":
            basis = obligation.get("completion_basis") or {}
            # Only DIRECT_EVENT bases occur in these fixtures; a CHILD_PASS basis would need the
            # recursive frontier walk in LIFE-013.
            if basis.get("kind") == "DIRECT_EVENT" and basis.get("occurrence_id") in affected:
                obligation["status"] = "DISPUTED"
    changed = True
    while changed:
        changed = False
        disputed = {row["obligation_id"] for row in state["obligations"] if row["status"] == "DISPUTED"}
        for obligation in state["obligations"]:
            waiting = obligation.get("waiting_on") or {}
            if obligation["status"] == "WAITING" and any(
                identifier in disputed for identifier in waiting.get("obligation_ids", [])
            ):
                obligation["status"] = "DISPUTED"
                changed = True


def dependency_dispute_result(
    base: dict, carrier: dict, event: dict, *, conflicts: list[str], source_occurrence_id: str,
) -> dict:
    """A CONFLICTING record against a completed occurrence, with the LIFE-013 fan-out applied."""
    outcome = governed_outcome(event, carrier, classification="CONFLICTING", disputed=True, conflicts=conflicts)
    evidence_id = event["native_evidence"]["evidence_id"]

    def mutate(next_state: dict) -> None:
        for prior in next_state["outcomes"]:
            if prior["native_evidence"]["evidence_id"] not in conflicts:
                continue
            prior["disputed"] = True
            prior["conflicts_with_evidence_ids"] = sorted(
                set(prior["conflicts_with_evidence_ids"]) | {evidence_id},
                key=lambda value: value.encode("utf-8"),
            )
            prior["outcome_digest"] = digest(
                "outcome", {key: value for key, value in prior.items() if key != "outcome_digest"}
            )
        next_state["outcomes"].append(copy.deepcopy(outcome))
        next_state["outcomes"].sort(key=lambda row: row["outcome_digest"].encode("utf-8"))
        apply_dependency_block(next_state, source_occurrence_id)

    return admitted_transition(
        carrier["state"], event, disposition="DISPUTED", reason_codes=["CONFLICTING_EFFECT"],
        details=[{"kind": "EFFECT", "classification": "CONFLICTING", "evidence_id": evidence_id}],
        receipt_permit_digest=event["permit"]["permit_id"], mutate=mutate,
    )


