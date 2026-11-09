#!/usr/bin/env python3
"""Synthetic protected resource with an independently committed effect journal."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--operator-key", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(sys.stdin.buffer.read())
    with sqlite3.connect(args.database) as connection:
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("CREATE TABLE IF NOT EXISTS calls (sequence INTEGER PRIMARY KEY, accepted INTEGER NOT NULL, request TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS effects (sequence INTEGER PRIMARY KEY, intent TEXT NOT NULL, payload TEXT NOT NULL)")
        if request == {"operation": "READ"}:
            result = {"status": "READ", "calls": connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0],
                "accepted_calls": connection.execute("SELECT COUNT(*) FROM calls WHERE accepted=1").fetchone()[0],
                "effects": [{"sequence": row[0], "intent": row[1], "payload": json.loads(row[2])}
                    for row in connection.execute("SELECT sequence,intent,payload FROM effects ORDER BY sequence")]}
        else:
            valid = (isinstance(request, dict) and set(request) == {"operation", "payload", "signature"}
                and request["operation"] == "WRITE" and isinstance(request["signature"], str)
                and hmac.compare_digest(request["signature"], hmac.new(args.operator_key.read_bytes(),
                    canonical({"operation": "WRITE", "payload": request["payload"]}), hashlib.sha256).hexdigest()))
            connection.execute("INSERT INTO calls(accepted,request) VALUES (?,?)", (int(valid), canonical(request).decode()))
            if valid:
                payload = request["payload"]
                connection.execute("INSERT INTO effects(intent,payload) VALUES (?,?)", (payload["dispatch_intent_id"], canonical(payload).decode()))
                result = {"status": "EFFECT_RECORDED", "intent": payload["dispatch_intent_id"]}
            else:
                result = {"status": "REFUSED", "code": "RESOURCE_AUTHORITY_NOT_ESTABLISHED"}
    sys.stdout.buffer.write(canonical(result) + b"\n")


if __name__ == "__main__":
    main()
