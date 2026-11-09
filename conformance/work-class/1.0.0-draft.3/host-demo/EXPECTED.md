# Bounded durable-host expectations

These expectations come from the approved host demonstration and existing consumer rules. They do not depend on observed implementation results. The demonstration uses synthetic authority, one operator-owned SQLite database, a serialized file lock for every participating writer, independent client processes and a separate connector process and database. It establishes no isolation against arbitrary code running as the operator, distributed coordination or production provider behavior.

| Exercise | Required observation |
|---|---|
| Install and restart | A new process reconstructs the same authoritative state and canonical history. |
| Occupied instance | A changed deployment cannot replace an installed root. |
| Wrong candidate | A process refuses a stored root pinned to another candidate. |
| Failed state and event-log commit | The complete prior root survives and no connector call occurs. |
| Kill before commit | SQLite rolls back the uncommitted state and event log together. |
| Two clients share the last budget allocation | Exactly one allocation commits. The stale loser cannot overwrite the current shared root. |
| Failed intent commit | No connector call occurs and no pending claim survives. |
| Kill after intent commit | The pending claim survives restart, no effect has occurred, and replay does not invoke the connector. Absence of an effect in this simulator is not general provider absence evidence. |
| Kill after resource effect | The independent resource journal records one effect. Restart preserves the pending claim and replay does not repeat it. |
| Explicit reconciliation | Evidence concerning the retained invocation updates the work without another connector call or duplicate accounting. |
| Disposition followed by restart and conflict | The original disposition survives; new contradictory evidence reinstates the required blocks. |
| Alternate resource clients | Unsigned direct writes are refused and create no effects. The declared read operation remains available. Credential custody and all-writer participation are deployment premises. |

The connector deliberately has no deduplication behavior. A repeated authorized invocation would create a second independently visible effect. A valid host run must prevent that invocation.
