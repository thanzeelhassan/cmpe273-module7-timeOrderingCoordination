"""Unit tests. Run with: python3 -m unittest -v"""
import contextlib
import io
import itertools
import unittest

from common import STATUS_BY_VERSION, OrderEvent
from lock_service import LockService
from order_store import (APPLIED, BUFFERED, DUPLICATE, INVALID,
                         REJECTED_STALE_TOKEN, OrderStore)


def ev(version, order_id="ORD-1"):
    return OrderEvent(order_id, version, STATUS_BY_VERSION[version])


class OrderStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = OrderStore()
        self._quiet = contextlib.redirect_stdout(io.StringIO())
        self._quiet.__enter__()
        self.addCleanup(self._quiet.__exit__, None, None, None)

    def test_v2_v1_v2_again(self):
        results = [self.store.apply_event(ev(v)) for v in (2, 1, 2)]
        self.assertEqual(results, [BUFFERED, APPLIED, DUPLICATE])
        self.assertEqual(self.store.orders["ORD-1"].history, ["CREATED", "PAID"])

    def test_missing_version_does_not_jump_ahead(self):
        self.store.apply_event(ev(1))
        self.assertEqual(self.store.apply_event(ev(3)), BUFFERED)
        order = self.store.orders["ORD-1"]
        self.assertEqual((order.status, order.version), ("CREATED", 1))
        self.assertEqual(self.store.missing_versions("ORD-1"), [2])
        self.assertEqual(sorted(order.pending), [3])

    def test_any_delivery_order_with_duplicates_converges(self):
        for perm in itertools.permutations([1, 2, 3, 2, 1]):
            store = OrderStore()
            for v in perm:
                store.apply_event(ev(v))
            self.assertEqual(store.orders["ORD-1"].history, ["CREATED", "PAID", "SHIPPED"])

    def test_duplicate_of_buffered_event(self):
        self.store.apply_event(ev(3))
        self.assertEqual(self.store.apply_event(ev(3)), DUPLICATE)

    def test_orders_are_independent(self):
        self.store.apply_event(ev(1, "A"))
        self.assertEqual(self.store.apply_event(ev(2, "B")), BUFFERED)
        self.assertEqual(self.store.orders["A"].status, "CREATED")

    def test_wrong_status_for_version_is_dropped(self):
        self.assertEqual(self.store.apply_event(OrderEvent("ORD-1", 1, "SHIPPED")), INVALID)

    def test_stale_token_rejected(self):
        locks = LockService(lease_ticks=5)
        self.store.apply_event(ev(1))
        old = locks.acquire("A", "ORD-1")
        self.assertIsNone(locks.acquire("B", "ORD-1"))   # lease still live
        locks.advance(10)
        new = locks.acquire("B", "ORD-1")
        self.assertGreater(new, old)
        self.assertEqual(self.store.write("B", new, ev(2)), APPLIED)
        self.assertEqual(self.store.write("A", old, ev(3)), REJECTED_STALE_TOKEN)
        self.assertEqual(self.store.orders["ORD-1"].status, "PAID")
        self.assertEqual(self.store.write("B", new, ev(3)), APPLIED)


if __name__ == "__main__":
    unittest.main()
