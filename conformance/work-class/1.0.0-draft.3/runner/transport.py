"""Draft-2 JSON-lines transport for trusted local conformance programs."""

from __future__ import annotations

import json
import hashlib
import os
import base64
import selectors
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


PROTOCOL = "seampoint.work-class.adapter/1.0.0-draft.3"
OPERATIONS = {
    "capabilities",
    "validate",
    "evaluate",
    "aggregate-step",
    "holdings-step",
    "flow-step",
    "deploy",
    "step",
    "readback",
    "check-evidence",
}


# Opt-in per-child capture. When this variable names an absolute directory, every
# child spawned through invoke, invoke_raw or run_captured leaves four files there:
# <stem>.json (argv, cwd, exit code, error, byte counts and SHA-256 of each stream)
# and the raw <stem>.stdin, <stem>.stdout and <stem>.stderr bytes. When the variable
# is unset or empty, nothing is recorded and every check below is unchanged.
CAPTURE_ENVIRONMENT = "WORK_CLASS_CHILD_CAPTURE_DIR"
_capture_lock = threading.Lock()
_capture_sequence = 0


def _capture_directory() -> Path | None:
    value = os.environ.get(CAPTURE_ENVIRONMENT, "")
    if not value:
        return None
    directory = Path(value)
    if not directory.is_absolute():
        raise RuntimeError(CAPTURE_ENVIRONMENT + " must be an absolute path")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _record_child(
    via: str,
    command: list[str],
    cwd: str | None,
    stdin: bytes,
    stdout: bytes,
    stderr: bytes,
    returncode: int | None,
    error: str | None,
) -> None:
    directory = _capture_directory()
    if directory is None:
        return
    global _capture_sequence
    with _capture_lock:
        _capture_sequence += 1
        sequence = _capture_sequence
    stem = f"{time.time_ns()}-{os.getpid()}-{sequence:06d}"
    streams = {"stdin": stdin, "stdout": stdout, "stderr": stderr}
    for name, data in streams.items():
        (directory / f"{stem}.{name}").write_bytes(data)
    metadata = {
        "via": via,
        "argv": [str(part) for part in command],
        "cwd": None if cwd is None else str(cwd),
        "exit_code": returncode,
        "error": error,
        "streams": {
            name: {
                "file": f"{stem}.{name}",
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in streams.items()
        },
    }
    (directory / f"{stem}.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n")


def run_captured(
    command: list[str],
    payload: bytes,
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    new_session: bool = False,
) -> subprocess.CompletedProcess:
    """Run one child with piped streams, as subprocess.run(capture_output=True) does.

    Returns a CompletedProcess whatever the exit code; the caller applies its own
    checks. On timeout the child (or its process group, with new_session) is killed
    and subprocess.TimeoutExpired is raised carrying the partial output. When capture
    is enabled, the child is recorded in both cases.
    """
    if env is None and _capture_directory() is not None:
        env = {key: value for key, value in os.environ.items() if key != CAPTURE_ENVIRONMENT}
    elif env is not None:
        env = {key: value for key, value in env.items() if key != CAPTURE_ENVIRONMENT}
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=new_session,
    )
    try:
        stdout, stderr = process.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        if new_session:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        stdout, stderr = process.communicate()
        _record_child("run_captured", command, None if cwd is None else str(cwd), payload, stdout, stderr, process.returncode, "TIMEOUT")
        raise subprocess.TimeoutExpired(command, timeout, output=stdout, stderr=stderr) from None
    except BaseException:
        process.kill()
        process.wait()
        raise
    _record_child("run_captured", command, None if cwd is None else str(cwd), payload, stdout, stderr, process.returncode, None)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


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
    payload = b""
    failure = None
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
    except BaseException as error:
        failure = str(error) or type(error).__name__
        raise
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
        _record_child("invoke", command, cwd, payload, bytes(output), bytes(errors), process.returncode, failure)


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
    output = errors = b""
    failure = None
    try:
        output, errors = process.communicate(payload, timeout=timeout)
        if len(output) > maximum or len(errors) > maximum:
            raise RuntimeError("OUTPUT_LIMIT")
        if output:
            raise RuntimeError("UNEXPECTED_ADAPTER_RESPONSE")
        return {"adapter_response": None, "harness_observation": "TRANSPORT_ERROR"}
    except subprocess.TimeoutExpired as error:
        failure = "TIMEOUT"
        raise RuntimeError("TIMEOUT") from error
    except BaseException as error:
        failure = str(error) or type(error).__name__
        raise
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        _record_child("invoke_raw", command, cwd, payload, output, errors, process.returncode, failure)
