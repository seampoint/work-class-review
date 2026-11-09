"""Conditional provider for the fictional CDMO specimen, with no external effects."""
from __future__ import annotations

import copy
import datetime
import threading


def instant(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


class ConditionalInventory:
    def __init__(self, authorization, request):
        self._lock = threading.RLock()
        self.authorization = copy.deepcopy(authorization)
        self.sources = copy.deepcopy(authorization["authorization_fence"]["sources"])
        self.coordinator = authorization["authorization_fence"]["provider_revision"]
        self.now = authorization["authorization_fence"]["checked_at"]
        self.inventory_revision = next(row["value"]["value"] for row in request["fields"] if row["name"] == "expected_inventory_revision")
        self.status = next(row["value"]["value"] for row in request["fields"] if row["name"] == "old_status")
        self.decision_effective = {"cedar": True, "alder": True}
        self.other_unresolved = False
        self.keys = set()
        self.events = []
        self.containment_intents = []
        self.candidate = next(row["value"]["value"] for row in request["fields"] if row["name"] == "request_id")
        self.attempts = {self.candidate: "REGISTERED"}
        self.executor_session_current = True

    def progress(self, request_id, status):
        with self._lock:
            self._progress(request_id, status)

    def _progress(self, request_id, status):
        self.attempts[request_id] = status
        if request_id != self.candidate:
            self.other_unresolved = status in {"REGISTERED", "POSSIBLY_SENT"}
            history = next(row for row in self.sources if row["requirement_id"] == "prior-attempt-history")
            history["provider_revision"] += ":other-attempt"
            self.coordinator += ":other-attempt"

    def commit(self, request, fail_commit=False):
        with self._lock:
            return self._commit(request, fail_commit)

    def _commit(self, request, fail_commit):
        authority = self.authorization
        fence = authority["authorization_fence"]
        values = {row["name"]: row["value"]["value"] for row in request["fields"]}
        key_values = [
            ("request", "cedar-vector-manufacturing", values["request_id"]),
            ("disposition", "cedar-inventory-ledger", values["batch_id"], values["site_id"], values["cedar_approval_identity"], "3"),
        ]
        valid = (
            request == authority["native_request"]
            and self.sources == fence["sources"]
            and self.coordinator == fence["provider_revision"]
            and instant(fence["checked_at"]) <= instant(self.now) < instant(authority["expires_at"])
            and all(self.decision_effective.values())
            and not self.other_unresolved
            and self.inventory_revision == values["expected_inventory_revision"]
            and self.status == values["old_status"]
            and not any(value in self.keys for value in key_values)
        )
        if not valid or fail_commit:
            return False
        event = {"request_id": values["request_id"], "committed_quality_revision": self.coordinator,
                 "new_status": values["new_status"], "inventory_revision": "12"}
        self.keys.update(key_values)
        self.status = values["new_status"]
        self.inventory_revision = "12"
        self.events.append(event)
        return True

    def hold_after_commit(self):
        with self._lock:
            self.coordinator += ":later-hold"
            self.containment_intents.append({"kind": "QUALITY_CONTAINMENT_REFERRAL"})

    def snapshot(self):
        with self._lock:
            return self._snapshot()

    def _snapshot(self):
        return {"sources": copy.deepcopy(self.sources), "coordinator": self.coordinator,
                "inventory_revision": self.inventory_revision, "status": self.status,
                "keys": [list(value) for value in sorted(self.keys)], "events": copy.deepcopy(self.events),
                "containment_intents": copy.deepcopy(self.containment_intents),
                "attempts": copy.deepcopy(self.attempts), "executor_session_current": self.executor_session_current}
