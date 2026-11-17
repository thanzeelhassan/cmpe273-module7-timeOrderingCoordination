"""LockService: hands out a lease on an order together with a fencing token.

The token is a number that only ever increases. Each time the lease is granted
(to a new worker, or again after it expired) the token goes up by one, so a
worker that was paused and lost its lease is left holding an OLDER token.

Time here is a simulated clock (ticks) so the demo is deterministic.
"""
from common import log


class LockService:
    def __init__(self, lease_ticks=5):
        self.lease_ticks = lease_ticks
        self.now = 0
        self.next_token = 1
        self.leases = {}  # order_id -> (worker, token, expires_at)

    def advance(self, ticks):
        self.now += ticks
        log("lock-service", f"clock advanced to t={self.now}")

    def acquire(self, worker, order_id):
        """Return a fencing token, or None if another worker holds a live lease."""
        held = self.leases.get(order_id)
        if held and held[2] > self.now and held[0] != worker:
            log("lock-service", f"{worker} denied: {held[0]} holds the lease on {order_id} "
                                f"until t={held[2]}")
            return None
        if held and held[2] <= self.now:
            log("lock-service", f"lease of {held[0]} (token={held[1]}) on {order_id} EXPIRED")
        token = self.next_token
        self.next_token += 1
        self.leases[order_id] = (worker, token, self.now + self.lease_ticks)
        log("lock-service", f"lease on {order_id} granted to {worker} "
                            f"with fencing token={token} (expires t={self.now + self.lease_ticks})")
        return token
