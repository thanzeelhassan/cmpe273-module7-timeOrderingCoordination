"""Order-processing simulation: event ordering, missing events and stale workers.

Usage:
  python3 demo.py            # run all three scenarios
  python3 demo.py 1          # versioned event ordering (v2, v1, v2 again)
  python3 demo.py 2          # missing event (only a later version arrives)
  python3 demo.py 3          # stale worker rejected by fencing token
"""
import sys

from common import STATUS_BY_VERSION, OrderEvent, log
from lock_service import LockService
from order_store import OrderStore


def event(order_id, version):
    return OrderEvent(order_id, version, STATUS_BY_VERSION[version])


def deliver(store, ev, note=""):
    """The 'network' delivering one event to the store."""
    log("network", f"delivering {ev}{'  ' + note if note else ''}")
    return store.apply_event(ev)


def banner(text):
    print(f"\n===== {text} =====", flush=True)


def scenario_1():
    banner("Scenario 1: versioned event ordering (delivery order: v2, v1, v2 again)")
    store, oid = OrderStore(), "ORD-1001"
    deliver(store, event(oid, 2), "(arrives FIRST, out of order)")
    log("store", f"state: {store.describe(oid)}")
    deliver(store, event(oid, 1), "(arrives LATE)")
    log("store", f"state: {store.describe(oid)}")
    deliver(store, event(oid, 2), "(DUPLICATE delivery)")
    log("store", f"final: {store.describe(oid)}")
    order = store.orders[oid]
    assert order.history == ["CREATED", "PAID"] and order.version == 2
    log("check", "PASS: applied in order CREATED -> PAID, duplicate ignored")


def scenario_2():
    banner("Scenario 2: missing event (v1 applied, then only v3 arrives; v2 is missing)")
    store, oid = OrderStore(), "ORD-2002"
    deliver(store, event(oid, 1))
    deliver(store, event(oid, 3), "(v2 never arrived)")
    log("store", f"state: {store.describe(oid)}")
    order = store.orders[oid]
    assert order.status == "CREATED" and store.missing_versions(oid) == [2]
    log("check", "PASS: order did NOT jump to SHIPPED; version 2 detected as missing, "
                 "version 3 recorded as pending")

    print("--- extra: the missing version finally shows up ---", flush=True)
    deliver(store, event(oid, 2), "(very late)")
    log("store", f"final: {store.describe(oid)}")
    assert order.history == ["CREATED", "PAID", "SHIPPED"]
    log("check", "PASS: gap filled, buffered version 3 applied in the correct order")


def scenario_3():
    banner("Scenario 3: stale worker (two workers, fencing tokens)")
    store, locks, oid = OrderStore(), LockService(lease_ticks=5), "ORD-3003"
    deliver(store, event(oid, 1))

    token_a = locks.acquire("worker-A", oid)
    log("worker-A", f"got token={token_a}, read order at version 1, about to mark it PAID ...")
    log("worker-A", "PAUSED (long GC pause / network stall) - it still believes it holds the lease")
    locks.advance(10)

    token_b = locks.acquire("worker-B", oid)
    log("worker-B", f"got token={token_b}, marking order PAID")
    result_b = store.write("worker-B", token_b, event(oid, 2))

    log("worker-A", f"RESUMED, unaware its lease expired; writing with old token={token_a}")
    result_a = store.write("worker-A", token_a, event(oid, 2))
    log("worker-A", f"write result: {result_a}")

    log("worker-B", "shipping the order")
    result_b2 = store.write("worker-B", token_b, event(oid, 3))
    log("store", f"final: {store.describe(oid)}")
    assert (result_b, result_a, result_b2) == ("APPLIED", "REJECTED_STALE_TOKEN", "APPLIED")
    log("check", f"PASS: newer token {token_b} accepted, older token {token_a} rejected")


SCENARIOS = {"1": scenario_1, "2": scenario_2, "3": scenario_3}

if __name__ == "__main__":
    chosen = sys.argv[1:] or ["1", "2", "3"]
    for key in chosen:
        if key not in SCENARIOS:
            sys.exit(f"unknown scenario {key!r}; choose from 1, 2, 3")
        SCENARIOS[key]()
