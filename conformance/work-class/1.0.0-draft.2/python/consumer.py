"""In-process interface to the independent draft-2 consumer."""

from __future__ import annotations

import copy

import adapter


class Consumer:
    """Expose the eight protocol operations without JSON-lines transport."""

    def call(self, operation: str, value):
        if operation not in adapter.ALL_OPERATIONS:
            raise ValueError(f"unsupported operation: {operation}")
        return copy.deepcopy(adapter._dispatch(operation, copy.deepcopy(value)))

    def capabilities(self):
        return self.call("capabilities", {})

    def validate(self, value):
        return self.call("validate", value)

    def evaluate(self, value):
        return self.call("evaluate", value)

    def aggregate_step(self, value):
        return self.call("aggregate-step", value)

    def deploy(self, value):
        return self.call("deploy", value)

    def step(self, value):
        return self.call("step", value)

    def readback(self, value):
        return self.call("readback", value)

    def check_evidence(self, value):
        return self.call("check-evidence", value)
