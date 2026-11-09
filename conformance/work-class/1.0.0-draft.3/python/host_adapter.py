#!/usr/bin/env python3
"""Runner-only JSON-lines interface for the single-process host contract."""

from __future__ import annotations

import copy
import sys
from pathlib import Path


ROOT=Path(__file__).resolve().parent
for dependency in (ROOT,ROOT/"vendor"):
    if str(dependency) not in sys.path:
        sys.path.insert(0,str(dependency))

from implementation.common import IDENTIFIER_PATTERN,PROTOCOL,canonical,parse_json,schema_valid  # noqa: E402


def _commit(value):
    if value["inject_failure"]:
        result={
            "status":"HOST_COMMIT","disposition":"COMMIT_FAILED","transaction_digest":value["transaction_digest"],
            "state_before_digest":value["authoritative_state_digest"],"authoritative_state_digest":value["authoritative_state_digest"],
            "budget_before":copy.deepcopy(value["authoritative_budgets"]),"authoritative_budgets":copy.deepcopy(value["authoritative_budgets"]),
            "failure_reference":value["failure_reference"],"dispatch_performed":False,
        }
    else:
        result={
            "status":"HOST_COMMIT","disposition":"COMMITTED","transaction_digest":value["transaction_digest"],
            "state_before_digest":value["authoritative_state_digest"],"state_after_digest":value["calculated_state_digest"],
            "budget_before":copy.deepcopy(value["authoritative_budgets"]),"budget_after":copy.deepcopy(value["calculated_budgets"]),
            "dispatch_performed":False,
        }
    if not schema_valid(result,"lifecycle.schema.json","hostCommitResult"):
        raise ValueError("invalid host commit input")
    return result


def _install(value):
    replay=canonical(value["request"])==canonical(value["authoritative_request"]) and canonical(value["calculated"])==canonical(value["authoritative_result"])
    if replay:
        result={
            "status":"HOST_DEPLOY","disposition":"INSTALLED","organization":value["organization"],"instance_id":value["instance_id"],
            "state_digest":value["authoritative_result"]["state_digest"],"replay":True,"dispatch_performed":False,
        }
    else:
        result={
            "status":"HOST_DEPLOY","disposition":"INSTANCE_OCCUPIED","organization":value["organization"],"instance_id":value["instance_id"],
            "authoritative_state_digest":value["authoritative_result"]["state_digest"],"proposed_state_digest":value["calculated"]["state_digest"],
            "replay":False,"dispatch_performed":False,
        }
    if not schema_valid(result,"lifecycle.schema.json","hostDeploymentResult"):
        raise ValueError("invalid host installation input")
    return result


def handle(request):
    if (
        not isinstance(request,dict) or set(request)!={"protocol","request_id","operation","input"}
        or request.get("protocol")!=PROTOCOL or request.get("operation")!="host-harness"
        or not isinstance(request.get("request_id"),str) or not IDENTIFIER_PATTERN.fullmatch(request["request_id"])
        or not isinstance(request.get("input"),dict)
    ):
        raise ValueError("invalid host harness envelope")
    value=request["input"]
    if value.get("kind")=="COMMIT":
        result=_commit(value)
    elif value.get("kind")=="INSTALL":
        result=_install(value)
    else:
        raise ValueError("unsupported host harness input")
    return {"protocol":PROTOCOL,"request_id":request["request_id"],"operation":"host-harness","result":result}


def main():
    if sys.argv[1:]:
        raise SystemExit("usage: host_adapter.py")
    for raw in sys.stdin.buffer:
        if not raw.endswith(b"\n"):
            raise SystemExit("unterminated request")
        response=handle(parse_json(raw[:-1]))
        sys.stdout.buffer.write(canonical(response)+b"\n")
        sys.stdout.buffer.flush()


if __name__=="__main__":
    main()
