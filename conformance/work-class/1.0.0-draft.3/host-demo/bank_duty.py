"""Persistent scheduling evidence for the selected fictional bank procedure.

This host service creates no filing permission. Trusted callbacks authenticate
clock, monitor, delivery and filing records; supplied assertions are not proof
that a real clock, recipient or filing provider behaved as claimed.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _instant(value):
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ValueError("noncanonical clock")
    return parsed


def selected_duty(timezone_file):
    path = Path(timezone_file)
    with path.open("rb") as stream:
        zone = ZoneInfo.from_file(stream, key="America/New_York")
    operational = datetime(2026, 10, 13, 17, tzinfo=zone).astimezone(timezone.utc)
    due = operational.strftime("%Y-%m-%dT%H:%M:%SZ")
    if due != "2026-10-13T21:00:00Z":
        raise ValueError("timezone rules disagree with selected source")
    return {"id": "MRB-DUTY-074", "bank": "MRB-US-01", "case": "MRB-CASE-074",
        "detection_record": "MRB-DETECTION-074", "detection_revision": "1", "detection_date": "2026-09-14",
        "identified_suspect": True, "legal_due_date": (date(2026, 9, 14) + timedelta(days=30)).isoformat(),
        "operational_deadline": due, "timezone": "America/New_York", "timezone_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "recipients": ["bank-secrecy-act-officer", "reporting-records-custodian"], "channel": "protected-reporting",
        "reminders": [(operational - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ") for hours in (48, 24)],
        "status": "OPEN", "clock": None, "unresolved_at_operational_deadline": False, "filing": None,
        "intents": [], "faults": [], "events": []}


class BankDutyStore:
    def __init__(self, path, authenticate):
        self.path = Path(path)
        self.authenticate = authenticate
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS duties (id TEXT PRIMARY KEY, body TEXT NOT NULL)")

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level="IMMEDIATE")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def install(self, body):
        with self._connection() as connection:
            row = connection.execute("SELECT body FROM duties WHERE id=?", (body["id"],)).fetchone()
            if row is not None:
                if json.loads(row[0]) != body:
                    raise ValueError("duty already installed")
                return
            connection.execute("INSERT INTO duties VALUES (?,?)", (body["id"], _canonical(body)))

    def snapshot(self, duty_id="MRB-DUTY-074"):
        with self._connection() as connection:
            row = connection.execute("SELECT body FROM duties WHERE id=?", (duty_id,)).fetchone()
            if row is None:
                raise ValueError("duty unavailable")
            return json.loads(row[0])

    @staticmethod
    def _enqueue(body, identity, kind, due, observed_at):
        if any(row["id"] == identity for row in body["intents"]):
            return
        body["intents"].append({"id": identity, "kind": kind, "due": due, "created_at": observed_at,
            "recipients": copy.deepcopy(body["recipients"]), "channel": body["channel"], "attempts": [], "acknowledgement": None})

    def apply(self, record, *, fail_commit=False):
        if self.authenticate(copy.deepcopy(record)) is not True:
            raise ValueError("record authentication unavailable")
        if not isinstance(record.get("id"), str) or not record["id"]:
            raise ValueError("record identity unavailable")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored = connection.execute("SELECT body FROM duties WHERE id=?", (record["duty_id"],)).fetchone()
            if stored is None:
                raise ValueError("duty unavailable")
            body = json.loads(stored[0])
            previous = next((row for row in body["events"] if row["id"] == record["id"]), None)
            if previous is not None:
                if previous != record:
                    raise ValueError("event replay conflict")
                return body
            kind, at = record["kind"], record["observed_at"]
            _instant(at)
            if kind == "CLOCK":
                if record["source"] != "MRB-CLOCK" or record["status"] not in {"AVAILABLE", "UNAVAILABLE"}:
                    raise ValueError("clock source/status invalid")
                prior = body["clock"]
                if prior is not None and (int(record["revision"]) <= int(prior["revision"]) or at < prior["observed_at"]):
                    raise ValueError("clock rollback")
                body["clock"] = copy.deepcopy(record)
                if record["status"] == "UNAVAILABLE":
                    self._enqueue(body, "fault:" + record["id"], "CLOCK_UNAVAILABLE", at, at)
                elif body["status"] == "OPEN":
                    for due in body["reminders"]:
                        if at >= due:
                            self._enqueue(body, "reminder:" + due, "FILING_REMINDER", due, at)
                    if at >= body["operational_deadline"]:
                        body["unresolved_at_operational_deadline"] = True
                        self._enqueue(body, "operational-overdue", "UNRESOLVED_DEADLINE", body["operational_deadline"], at)
            elif kind == "FAULT":
                if record["component"] not in {"SCHEDULER", "STORAGE", "ACKNOWLEDGEMENT_SERVICE"}:
                    raise ValueError("unknown monitored component")
                body["faults"].append(copy.deepcopy(record))
                self._enqueue(body, "fault:" + record["id"], record["component"] + "_UNAVAILABLE", at, at)
            elif kind in {"DELIVERY_ATTEMPT", "DELIVERY_ACK"}:
                intent = next((row for row in body["intents"] if row["id"] == record["intent_id"]), None)
                if intent is None or record["channel"] != intent["channel"] or record["recipients"] != intent["recipients"]:
                    raise ValueError("delivery binding mismatch")
                if at < intent["created_at"]:
                    raise ValueError("delivery predates retained intent")
                if kind == "DELIVERY_ATTEMPT":
                    intent["attempts"].append(copy.deepcopy(record))
                else:
                    if not any(row["id"] == record["attempt_id"] for row in intent["attempts"]):
                        raise ValueError("acknowledgement has no retained attempt")
                    if intent["acknowledgement"] is not None:
                        raise ValueError("conflicting delivery acknowledgement")
                    intent["acknowledgement"] = copy.deepcopy(record)
            elif kind == "FILING_ACCEPTED":
                if body["filing"] is not None or record["bank"] != body["bank"] or record["case"] != body["case"] or not record["bsa_identifier"]:
                    raise ValueError("filing binding mismatch")
                filed_at, filed_date = record["filed_at"], date.fromisoformat(record["filing_date"])
                _instant(filed_at)
                if filed_at > at:
                    raise ValueError("filing postdates acknowledgement")
                body["filing"] = {**copy.deepcopy(record), "after_operational_deadline": filed_at > body["operational_deadline"],
                    "after_legal_due_date": filed_date > date.fromisoformat(body["legal_due_date"]),
                    "minimum_retention_date": (date(filed_date.year + 5, filed_date.month, 1) + timedelta(days=filed_date.day - 1)).isoformat()}
                body["status"] = "CLOSED"
            else:
                raise ValueError("unsupported duty event")
            body["events"].append(copy.deepcopy(record))
            connection.execute("UPDATE duties SET body=? WHERE id=?", (_canonical(body), body["id"]))
            if fail_commit:
                raise sqlite3.OperationalError("injected duty persistence failure")
            return body
