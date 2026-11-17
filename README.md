# Module 7 Assignment: Time, Ordering & Coordination

CMPE-273 – A small order-processing simulation (Python, standard library only) that shows how a distributed system handles **event ordering, delayed messages, and stale workers**.

An order moves through versioned states:

```
CREATED (version 1) → PAID (version 2) → SHIPPED (version 3)
```

Every order update carries `order_id`, `version`, and `status`:

```
order_id=ORD-1001 version=2 status=PAID
```

Events may arrive **late, out of order, or more than once**, and the order must still end up correct.

## Architecture

```
 ┌──────────┐  events (late / reordered /   ┌─────────────────────────────────┐
 │ network  │  duplicated)                  │ OrderStore                      │
 │ (demo.py)│──────────────────────────────▶│  per order:                     │
 └──────────┘                               │   version  (last applied)       │
                                            │   pending  {version: event}     │
 ┌──────────┐ token=1 ┌──────────────┐      │   highest_token (fencing)       │
 │ worker-A │◀────────│ LockService  │      │                                 │
 └────┬─────┘         │ lease +      │      │  apply only version+1,          │
      │ write(token)  │ increasing   │      │  buffer later versions,         │
 ┌────┴─────┐ token=2 │ fencing token│      │  ignore duplicates,             │
 │ worker-B │◀────────└──────────────┘      │  reject old tokens              │
 └────┬─────┘                               └─────────────────────────────────┘
      └──────────── write(token) ──────────────────────▲
```

Key design choices:

| Concern | Choice |
|---|---|
| Ordering | An event is applied only if `version == last_applied_version + 1` |
| Late / out-of-order events | Later versions are **buffered as pending** until the gap is filled, then released in order |
| Duplicates | A version that is already applied or already buffered is ignored (idempotent) |
| Missing events | The gap between the applied version and the buffered versions is reported as `missing` |
| Stale workers | The lock service issues an **increasing fencing token** with each lease; the store rejects any write whose token is lower than the highest it has seen |
| Time | No wall-clock timestamps are used for ordering; lease expiry uses a simulated clock so the demo is deterministic |

## Running it

Requirements: Python 3.9+. No dependencies to install.

```bash
python3 demo.py        # run all three scenarios
python3 demo.py 1      # versioned event ordering (v2, v1, v2 again)
python3 demo.py 2      # missing event
python3 demo.py 3      # stale worker / fencing token
```

Run every scenario and save the output to `logs/`:

```bash
./scripts/run_demo.sh
```

Run the unit tests:

```bash
python3 -m unittest -v
```

## Evidence

Full terminal output is in [`logs/`](logs/). Excerpts below. (Timestamps are `HH:MM:SS.mmm` and are only there for the log; they are not used for ordering.)

### 1. Correct event ordering

Delivery order is **version 2, version 1, version 2 again**
([`logs/1_versioned_event_ordering.log`](logs/1_versioned_event_ordering.log)).

Version 2 arrives first. The store does not apply it; it waits for the missing version 1:

```
18:24:14.431 [network] delivering order_id=ORD-1001 version=2 status=PAID  (arrives FIRST, out of order)
18:24:14.431 [store] received  order_id=ORD-1001 version=2 status=PAID  (current version=0)
18:24:14.431 [store] BUFFERED  version 2 is PENDING, waiting for missing version(s) [1]
```

Version 1 arrives late. It is applied, and the buffered version 2 is released right after it, so the updates are applied in the correct order:

```
18:24:14.431 [network] delivering order_id=ORD-1001 version=1 status=CREATED  (arrives LATE)
18:24:14.431 [store] APPLIED   version 1: (none) -> CREATED
18:24:14.431 [store] gap filled -> releasing buffered version 2
18:24:14.431 [store] APPLIED   version 2: CREATED -> PAID
```

### 2. Duplicate handling

Same run: version 2 is delivered a second time and is ignored. The order stays at `PAID`, version 2, and the history shows each state exactly once:

```
18:24:14.431 [network] delivering order_id=ORD-1001 version=2 status=PAID  (DUPLICATE delivery)
18:24:14.431 [store] received  order_id=ORD-1001 version=2 status=PAID  (current version=2)
18:24:14.431 [store] DUPLICATE version 2 already applied -> ignored
18:24:14.431 [store] final: order_id=ORD-1001 status=PAID version=2 history=[CREATED -> PAID] pending=none missing=none
```

### 3. Missing-event case

Version 1 is applied, then **only version 3** (`SHIPPED`) is sent; version 2 never arrives
([`logs/2_missing_event.log`](logs/2_missing_event.log)):

```
18:24:14.472 [store] APPLIED   version 1: (none) -> CREATED
18:24:14.472 [network] delivering order_id=ORD-2002 version=3 status=SHIPPED  (v2 never arrived)
18:24:14.472 [store] received  order_id=ORD-2002 version=3 status=SHIPPED  (current version=1)
18:24:14.472 [store] BUFFERED  version 3 is PENDING, waiting for missing version(s) [2]
18:24:14.472 [store] state: order_id=ORD-2002 status=CREATED version=1 history=[CREATED] pending=[3] missing=[2]
```

- The order does **not** jump ahead: it is still `CREATED` at version 1, not `SHIPPED`.
- Version 2 is detected as `missing`, and version 3 is recorded as `pending`.

As an extra step, the demo then delivers the missing version 2, and the buffered version 3 is applied after it:

```
18:24:14.472 [store] APPLIED   version 2: CREATED -> PAID
18:24:14.472 [store] gap filled -> releasing buffered version 3
18:24:14.472 [store] APPLIED   version 3: PAID -> SHIPPED
```

### 4. Stale-worker rejection

Two workers try to update the same order
([`logs/3_stale_worker_fencing.log`](logs/3_stale_worker_fencing.log)).
worker-A gets the lease with fencing token 1 and then pauses. Its lease expires, and worker-B gets the lease with the newer token 2:

```
18:24:14.503 [lock-service] lease on ORD-3003 granted to worker-A with fencing token=1 (expires t=5)
18:24:14.503 [worker-A] PAUSED (long GC pause / network stall) - it still believes it holds the lease
18:24:14.503 [lock-service] clock advanced to t=10
18:24:14.503 [lock-service] lease of worker-A (token=1) on ORD-3003 EXPIRED
18:24:14.503 [lock-service] lease on ORD-3003 granted to worker-B with fencing token=2 (expires t=15)
```

The worker with the newer token can update the order:

```
18:24:14.503 [store] write from worker-B token=2  order_id=ORD-3003 version=2 status=PAID  (highest token seen=0)
18:24:14.503 [store] ACCEPTED  token 2 is current
18:24:14.503 [store] APPLIED   version 2: CREATED -> PAID
```

worker-A wakes up, still believing it holds the lease, and writes with its old token. It is rejected:

```
18:24:14.503 [worker-A] RESUMED, unaware its lease expired; writing with old token=1
18:24:14.503 [store] write from worker-A token=1  order_id=ORD-3003 version=2 status=PAID  (highest token seen=2)
18:24:14.503 [store] REJECTED  worker-A is STALE: token 1 < 2 -> order left unchanged
18:24:14.503 [worker-A] write result: REJECTED_STALE_TOKEN
```

The check is done by the **store**, not by the worker. A paused worker cannot know its lease expired, so the resource it writes to has to be the one that refuses it.

### Unit tests

```
$ python3 -m unittest
.......
----------------------------------------------------------------------
Ran 7 tests in 0.004s

OK
```

One test delivers versions `1, 2, 3, 2, 1` in every possible order and checks that the order always ends as `CREATED -> PAID -> SHIPPED`.

## Reflection

**Why are timestamps alone not enough to guarantee correct event ordering in a distributed system?**

Each machine has its own physical clock, and those clocks drift, get adjusted by NTP, and can even jump backwards, so there is no single shared "now" to compare against. Two events on different machines can therefore carry timestamps that disagree with the order in which they actually happened, and a later update can end up with an earlier timestamp. A timestamp also says nothing about gaps: if an update is lost or delayed, the receiver cannot tell from the times alone that something is missing, the way it can with consecutive version numbers. The same problem applies to leases, since a worker that was paused can still believe its time-based lease is valid after it has expired. This is why this simulation orders updates with a per-order version number and protects writes with a fencing token, both of which are logical counters that do not depend on any clock being correct.

## Repository layout

```
common.py              OrderEvent (order_id, version, status) and logging helper
order_store.py         ordering, buffering, duplicate detection, fencing-token check
lock_service.py        leases with increasing fencing tokens (simulated clock)
demo.py                the three scenarios
test_order_store.py    unit tests
scripts/run_demo.sh    runs all scenarios and writes logs/
logs/                  captured evidence
```
