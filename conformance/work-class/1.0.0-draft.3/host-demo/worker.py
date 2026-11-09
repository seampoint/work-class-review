#!/usr/bin/env python3
"""One independent client process for the bounded SQLite demonstration."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PYTHON = HERE.parent / "python"
sys.path[:0] = [str(PYTHON), str(PYTHON / "vendor")]

from consumer import Consumer
from implementation.common import Refusal
from sqlite_host import SQLiteReferenceHost, _encode
from connector_process import canonical


def main():
    request = json.loads(sys.stdin.buffer.read())
    host = SQLiteReferenceHost(request["database"], Consumer())

    def cut(stage):
        if request.get("kill_at") == stage:
            marker = Path(request["kill_marker"])
            with marker.open("w") as stream:
                stream.write(json.dumps({"pid": os.getpid(), "stage": stage, "signal": "SIGKILL"}))
                stream.flush()
                os.fsync(stream.fileno())
            os.kill(os.getpid(), signal.SIGKILL)

    try:
        if request["operation"] == "CALL":
            result = host.call(request["method"], *request["arguments"], fail_commit=request.get("fail_commit", False), cut=cut)
        elif request["operation"] == "INSPECT":
            result = host.inspect(request["method"], *request["arguments"])
        elif request["operation"] == "STATUS":
            result = host.database_status()
        elif request["operation"] == "DISPATCH":
            def invoke(payload):
                message = {"operation": "WRITE", "payload": payload}
                signature = hmac.new(Path(request["operator_key"]).read_bytes(), canonical(message), hashlib.sha256).hexdigest()
                command = [sys.executable, "-B", str(HERE / "connector_process.py"), "--database", request["resource_database"],
                    "--operator-key", request["operator_key"]]
                actual = subprocess.run(command, input=canonical({**message, "signature": signature}), capture_output=True, check=True)
                if json.loads(actual.stdout).get("status") != "EFFECT_RECORDED":
                    raise RuntimeError("resource refused authorized invocation")
                cut("AFTER_RESOURCE_EFFECT")
                # The simulator deliberately returns no admissible business receipt.
                # Its independently retained effect must be reconciled explicitly.
                return None
            connector = {**request["connector"], "invoke": invoke}
            result = host.dispatch(request["organization"], request["instance_id"], request["authorization_digest"],
                connector, request["event_id"], fail_commit=request.get("fail_commit", False), cut=cut)
        else:
            raise ValueError("unknown worker operation")
        response = {"status": "RESULT", "result": _encode(result)}
    except Refusal as error:
        response = {"status": "REFUSED", "code": error.code}
    except Exception as error:
        response = {"status": "ERROR", "type": type(error).__name__, "message": str(error)}
    sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
