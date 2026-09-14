"""Draft-2 JSON-lines transport for trusted local conformance programs."""

from __future__ import annotations

import json
import os
import base64
import selectors
import signal
import subprocess
import time
from typing import Any


PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.2"
OPERATIONS = {
    "capabilities",
    "validate",
    "evaluate",
    "aggregate-step",
    "deploy",
    "step",
    "readback",
    "check-evidence",
}


def canonical(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + canonical(value[key])
            for key in sorted(value, key=lambda item: item.encode("utf-16-be", "surrogatepass"))
        ) + "}"
    if isinstance(value, list):
        return "[" + ",".join(canonical(member) for member in value) + "]"
    if value is None or isinstance(value, (str, bool)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise ValueError("JSON numbers and unsupported values are forbidden")


def read_json(data: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, member in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = member
        return value

    return json.loads(
        data,
        object_pairs_hook=pairs,
        parse_int=lambda value: (_ for _ in ()).throw(ValueError(f"JSON number {value}")),
        parse_float=lambda value: (_ for _ in ()).throw(ValueError(f"JSON number {value}")),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def invoke(
    command: list[str],
    request_id: str,
    operation: str,
    input_value: dict[str, Any],
    timeout: float,
    maximum: int,
    cwd: str,
) -> dict[str, Any]:
    request = {
        "protocol": PROTOCOL,
        "request_id": request_id,
        "operation": operation,
        "input": input_value,
    }
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    environment.update({"LANG": "C.UTF-8", "TZ": "UTC", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        cwd=cwd,
        start_new_session=True,
    )
    output = bytearray()
    errors = bytearray()
    started = time.monotonic()
    selector = selectors.DefaultSelector()
    try:
        payload = (canonical(request) + "\n").encode("utf-8")
        os.set_blocking(process.stdin.fileno(), False)
        selector.register(process.stdin, selectors.EVENT_WRITE, None)
        selector.register(process.stdout, selectors.EVENT_READ, output)
        selector.register(process.stderr, selectors.EVENT_READ, errors)
        written = 0
        while selector.get_map():
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise RuntimeError("TIMEOUT")
            for key, _ in selector.select(min(remaining, 0.1)):
                if key.fileobj is process.stdin:
                    count = os.write(process.stdin.fileno(), payload[written : written + 65536])
                    written += count
                    if written == len(payload):
                        selector.unregister(process.stdin)
                        process.stdin.close()
                    continue
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                key.data.extend(data)
                if len(key.data) > maximum:
                    raise RuntimeError("OUTPUT_LIMIT")
        process.wait(timeout=max(0.01, timeout - (time.monotonic() - started)))
        if process.returncode:
            raise RuntimeError(f"PROCESS_EXIT_{process.returncode}")
        lines = bytes(output).splitlines()
        if len(lines) != 1:
            raise RuntimeError("OUTPUT_LINE_COUNT")
        response = read_json(lines[0].decode("utf-8", errors="strict"))
        if bytes(output) != canonical(response).encode("utf-8") + b"\n":
            raise RuntimeError("NONCANONICAL_OUTPUT")
        if not isinstance(response, dict):
            raise RuntimeError("OUTPUT_NOT_OBJECT")
        expected_envelope = {
            "protocol": PROTOCOL,
            "request_id": request_id,
            "operation": operation,
        }
        for key, expected in expected_envelope.items():
            if response.get(key) != expected:
                raise RuntimeError(f"RESPONSE_{key.upper()}_MISMATCH")
        if set(response) != {"protocol", "request_id", "operation", "result"}:
            raise RuntimeError("RESPONSE_ENVELOPE_INVALID")
        if not isinstance(response["result"], dict):
            raise RuntimeError("RESULT_NOT_OBJECT")
        return response["result"]
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()
        process.stderr.close()
        selector.close()


def invoke_raw(
    command: list[str],
    bytes_base64: str,
    timeout: float,
    maximum: int,
    cwd: str,
) -> dict[str, Any]:
    """Send exact malformed transport bytes and require no adapter response."""
    payload = base64.b64decode(bytes_base64, validate=True)
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT") if key in os.environ}
    environment.update({"LANG": "C.UTF-8", "TZ": "UTC", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        output, errors = process.communicate(payload, timeout=timeout)
        if len(output) > maximum or len(errors) > maximum:
            raise RuntimeError("OUTPUT_LIMIT")
        if output:
            raise RuntimeError("UNEXPECTED_ADAPTER_RESPONSE")
        return {"adapter_response": None, "harness_observation": "TRANSPORT_ERROR"}
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("TIMEOUT") from error
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
