"""Recommit a changed checkpoint's last receipt and replay, for single-fault refusal vectors."""

from __future__ import annotations

import copy

from corpus_common import digest
from lifecycle_factory import state_core


def reseal_last_transition(state: dict) -> None:
    """Recommit the last receipt and its replay to the state as it now stands.

    A refusal vector changes one fact in an admitted checkpoint. LIFECYCLE.md:315 binds the last
    receipt's state_after_core_digest, decision identifier and transaction digest to that state, so a
    checkpoint left with stale commitments is refused for them before the rule under test is reached.
    """
    receipt = state["receipts"][-1]
    core_digest = digest("work-state-core", state_core(state))
    body = {key: value for key, value in receipt.items() if key != "decision_id"}
    body["state_after_core_digest"] = core_digest
    decision_id = digest("decision-receipt", body)
    state["receipts"][-1] = {"decision_id": decision_id, **body}
    replay = next(row for row in state["replays"] if row["event_id"] == receipt["event_id"])
    replay["decision"] = copy.deepcopy(state["receipts"][-1])
    replay["decision_receipt_digest"] = decision_id
    replay["transition_state_digest"] = core_digest
    replay["transaction_digest"] = digest("lifecycle-transaction", {
        "state_before_digest": body["state_before_digest"], "event_digest": body["event_digest"],
        "decision_receipt_digest": decision_id, "state_after_core_digest": core_digest,
        "budget_results": copy.deepcopy(replay["budget_results"]),
    })
