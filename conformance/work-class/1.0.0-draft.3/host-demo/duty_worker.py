#!/usr/bin/env python3
"""Trusted fixture client for the separate persistent bank duty service."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

from bank_duty import BankDutyStore, selected_duty


def main():
    request = json.loads(sys.stdin.buffer.read())
    admitted = json.loads(Path(request["authenticated_records"]).read_bytes())
    def authenticate(record):
        return record in admitted
    service = BankDutyStore(request["database"], authenticate)
    try:
        operation = request["operation"]
        if operation == "INSTALL":
            service.install(selected_duty(request["timezone_file"]))
            result = service.snapshot()
        elif operation == "APPLY":
            result = service.apply(request["record"], fail_commit=request.get("fail_commit", False))
            if request.get("kill_after_commit"):
                Path(request["kill_marker"]).write_text(json.dumps({"pid": os.getpid(), "signal": "SIGKILL", "stage": "AFTER_DUTY_COMMIT"}))
                os.kill(os.getpid(), signal.SIGKILL)
        elif operation == "SNAPSHOT":
            result = service.snapshot()
        else:
            raise ValueError("unsupported duty operation")
        response = {"status": "RESULT", "result": result}
    except Exception as error:
        response = {"status": "REFUSED", "type": type(error).__name__, "reason": str(error)}
    print(json.dumps(response, sort_keys=True))


if __name__ == "__main__":
    main()
