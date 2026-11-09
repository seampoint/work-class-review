# Local durable host demonstration

The host retains work state, reservation state, complete event results and pending dispatch claims in an operator-owned SQLite database. It reloads and validates the complete checkpoint for each operation. SQLite WAL mode and FULL synchronous commits persist the checkpoint and operation record together. A process lock serializes every participating writer through the first synchronous connector effect. This is a bounded local coordination design; a long connector call also holds that lock.

Before invoking the connector, the host commits a pending dispatch claim. A crash after that commit consumes the attempt even if the connector was never reached. Recovery retains uncertainty and requires separately authorized reconciliation. It does not automatically resend. The synthetic resource runs in a separate process and maintains its own effect journal. It verifies an HMAC before writing and deliberately supplies no duplicate suppression, so the host's ordering is responsible for preventing a second call.

The demonstration uses independent client processes, actual SIGKILL points, two database journals and competing instances sharing the final available reservation. It exercises restart, occupied instance refusal, candidate mismatch, failed commit rollback, pre-effect claim persistence, uncertainty, reconciliation without a second resource call, and refusal of an unsigned direct resource write. A separate recovery exercise retains a disposition across restart, adds a conflicting later fact and blocks fresh reliance without deleting the earlier disposition.

The bank duty store persists reminders, delivery evidence, clock failure, overdue status and the actual filing date independently of work permission. A delayed acknowledgement does not establish a late filing. Its selected timezone bytes and calendar policy are retained. Fault-report fixtures exercise escalation records; they do not demonstrate an independent production scheduler detecting silence or surviving a physical storage outage. The duty store grants no filing permission.

## Run the demonstrations

Use fresh output directories under the repository's SSD-backed runs root:

```sh
python -B conformance/work-class/1.0.0-draft.3/host-demo/run_demo.py --output runs/<fresh-run>/durable
python -B conformance/work-class/1.0.0-draft.3/host-demo/recovery_demo.py --output runs/<fresh-run>/recovery
python -B conformance/work-class/1.0.0-draft.3/host-demo/run_duty_demo.py --output runs/<fresh-run>/duty
```

Each command retains exact requests, responses and before/after source hashes. Previous output directories are refused. Failed and superseded runs remain evidence at their original paths.

The operator must own the database, process lock, connector credentials and every participating writer. This demonstration does not exclude malicious code running under the operator's identity, qualify distributed coordination or real provider behavior, or demonstrate durable protected information-flow enforcement. The durable wrapper uses HoldingsReferenceHost; the separate in-memory FlowReferenceHost retains its own verification record. A production integration must establish current identity and authority, protected readback, source authenticity, complete route mediation and operational monitoring for its actual deployment.
