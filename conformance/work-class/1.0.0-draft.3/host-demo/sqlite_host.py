"""Bounded local durability around the Python reference host.

The operator owns this database and lock. Every participating writer uses this
wrapper. The file lock remains held during the synchronous connector call; the
connector effect is outside every host database transaction.
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from implementation.common import PIN, Refusal
from implementation.holdings_host import HoldingsReferenceHost


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _encode(value):
    if isinstance(value, bytes):
        return {"type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, tuple):
        return {"type": "tuple", "value": [_encode(item) for item in value]}
    if isinstance(value, dict):
        pairs = [[_encode(key), _encode(item)] for key, item in value.items()]
        pairs.sort(key=lambda pair: _json(pair[0]))
        return {"type": "dict", "value": pairs}
    if isinstance(value, list):
        return {"type": "list", "value": [_encode(item) for item in value]}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise TypeError("unsupported checkpoint value")


def _decode(value):
    if not isinstance(value, dict):
        if value is None or isinstance(value, (str, bool, int)):
            return value
        raise ValueError("invalid checkpoint scalar")
    if set(value) != {"type", "value"}:
        raise ValueError("invalid checkpoint tag")
    kind, body = value["type"], value["value"]
    if kind == "bytes" and isinstance(body, str):
        return base64.b64decode(body, validate=True)
    if kind in {"dict", "tuple", "list"} and isinstance(body, list):
        if kind == "dict":
            pairs = [(_decode(pair[0]), _decode(pair[1])) for pair in body if isinstance(pair, list) and len(pair) == 2]
            result = dict(pairs)
            if len(pairs) != len(body) or len(result) != len(pairs):
                raise ValueError("invalid checkpoint map")
            return result
        items = [_decode(item) for item in body]
        return tuple(items) if kind == "tuple" else items
    raise ValueError("invalid checkpoint type")


class SQLiteReferenceHost:
    """One operator-owned SQLite store, serialized across local processes."""

    def __init__(self, path, consumer):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.consumer = consumer
        with self._locked(), self._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS checkpoints (id INTEGER PRIMARY KEY, pin TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS operations (sequence INTEGER PRIMARY KEY, method TEXT NOT NULL, request TEXT NOT NULL, response TEXT NOT NULL, checkpoint_digest TEXT NOT NULL)")
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def _locked(self):
        descriptor = os.open(str(self.path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @contextlib.contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            yield connection
        finally:
            connection.close()

    def _load(self, connection):
        row = connection.execute("SELECT pin, body, digest FROM checkpoints WHERE id=1").fetchone()
        if row is None:
            return HoldingsReferenceHost(self.consumer)
        pin, body, stored_digest = row
        if pin != PIN:
            raise Refusal("PIN_MISMATCH")
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != stored_digest:
            raise Refusal("STATE_INVALID")
        return HoldingsReferenceHost.from_checkpoint(self.consumer, _decode(json.loads(body)))

    def _persist(self, connection, host, method, request, response, fail_commit=False, cut=None):
        body = _json(_encode(host.export_checkpoint()))
        checksum = hashlib.sha256(body.encode("utf-8")).hexdigest()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("INSERT INTO checkpoints VALUES (1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET pin=excluded.pin, body=excluded.body, digest=excluded.digest", (PIN, body, checksum))
            connection.execute("INSERT INTO operations(method,request,response,checkpoint_digest) VALUES (?,?,?,?)", (method, _json(_encode(request)), _json(_encode(response)), checksum))
            if fail_commit:
                raise sqlite3.OperationalError("injected event-log commit failure")
            if cut:
                cut("BEFORE_COMMIT")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    def call(self, method, *args, fail_commit=False, cut=None):
        if method not in {"install", "submit", "submit_registry", "install_holdings", "submit_holdings", "recover_dispatch"}:
            raise ValueError("unsupported durable host method")
        with self._locked(), self._connection() as connection:
            host = self._load(connection)
            result = getattr(host, method)(*args)
            self._persist(connection, host, method, args, result, fail_commit, cut)
            return result

    def inspect(self, method, *args):
        if method not in {"snapshot", "holdings_snapshot", "dispatch_claims", "pending_evidence", "export_checkpoint"}:
            raise ValueError("unsupported inspection method")
        with self._locked(), self._connection() as connection:
            return getattr(self._load(connection), method)(*args)

    def dispatch(self, organization, instance_id, authorization_digest, connector, event_id, *, fail_commit=False, cut=None):
        """Retain the complete pending claim before the first connector call."""
        with self._locked(), self._connection() as connection:
            host = self._load(connection)
            precommit_failed = False
            retained_request = {"organization": organization, "instance_id": instance_id,
                "authorization_digest": authorization_digest, "event_id": event_id,
                "connector": {key: value for key, value in connector.items() if key != "invoke"}}

            def invoke(payload):
                nonlocal precommit_failed
                try:
                    self._persist(connection, host, "DISPATCH_INTENT", {**retained_request, "payload": payload},
                        {"status": "PENDING"}, fail_commit)
                except Exception:
                    precommit_failed = True
                    raise
                if cut:
                    cut("AFTER_INTENT_COMMIT")
                result = connector["invoke"](payload)
                if cut:
                    cut("AFTER_CONNECTOR_RESULT")
                return result

            result = host.dispatch(organization, instance_id, authorization_digest, {**connector, "invoke": invoke}, event_id)
            if precommit_failed:
                return {"status": "HOST_COMMIT", "disposition": "COMMIT_FAILED", "dispatch_performed": False}
            self._persist(connection, host, "DISPATCH_RESULT", retained_request, result)
            return result

    def database_status(self):
        with self._locked(), self._connection() as connection:
            return {"sqlite_version": sqlite3.sqlite_version,
                "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
                "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
                "operations": connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]}
