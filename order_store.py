"""OrderStore: the single place where order state lives.

It protects an order against three problems:

1. Out-of-order events  -> an event is applied only when its version is exactly
                           last_applied_version + 1. Later versions are buffered
                           as PENDING until the gap is filled.
2. Duplicate events     -> a version that was already applied (or is already
                           buffered) is ignored, so applying is idempotent.
3. Stale workers        -> every write from a worker carries a fencing token.
                           The store remembers the highest token it has seen for
                           the order and rejects anything older.
"""
from common import STATUS_BY_VERSION, OrderEvent, log

# Results returned by apply_event / write
APPLIED = "APPLIED"
BUFFERED = "BUFFERED"
DUPLICATE = "DUPLICATE"
INVALID = "INVALID"
REJECTED_STALE_TOKEN = "REJECTED_STALE_TOKEN"


class Order:
    def __init__(self, order_id):
        self.order_id = order_id
        self.version = 0            # last applied version (0 = nothing yet)
        self.status = None
        self.pending = {}           # version -> OrderEvent waiting for a gap
        self.history = []           # statuses in the order they were applied
        self.highest_token = 0      # highest fencing token seen for this order


class OrderStore:
    def __init__(self, name="store"):
        self.name = name
        self.orders = {}

    def _order(self, order_id):
        return self.orders.setdefault(order_id, Order(order_id))

    # ------------------------------------------------------------ ordering
    def apply_event(self, event: OrderEvent):
        """Handle one delivered event. Safe for late, reordered and repeated events."""
        order = self._order(event.order_id)
        log(self.name, f"received  {event}  (current version={order.version})")

        if STATUS_BY_VERSION.get(event.version) != event.status:
            log(self.name, f"INVALID   version {event.version} cannot carry status {event.status} -> dropped")
            return INVALID

        # Already applied, or already waiting in the buffer -> duplicate.
        if event.version <= order.version:
            log(self.name, f"DUPLICATE version {event.version} already applied -> ignored")
            return DUPLICATE
        if event.version in order.pending:
            log(self.name, f"DUPLICATE version {event.version} already buffered -> ignored")
            return DUPLICATE

        # A gap: an earlier version has not arrived yet. Do NOT jump ahead.
        if event.version > order.version + 1:
            order.pending[event.version] = event
            log(self.name, f"BUFFERED  version {event.version} is PENDING, "
                           f"waiting for missing version(s) {self.missing_versions(event.order_id)}")
            return BUFFERED

        # Exactly the next version: apply it, then drain whatever it unblocked.
        self._apply(order, event)
        while order.version + 1 in order.pending:
            nxt = order.pending.pop(order.version + 1)
            log(self.name, f"gap filled -> releasing buffered version {nxt.version}")
            self._apply(order, nxt)
        return APPLIED

    def _apply(self, order, event):
        previous = order.status or "(none)"
        order.version = event.version
        order.status = event.status
        order.history.append(event.status)
        log(self.name, f"APPLIED   version {event.version}: {previous} -> {event.status}")

    def missing_versions(self, order_id):
        """Versions we know are missing: gaps below the highest buffered version."""
        order = self._order(order_id)
        if not order.pending:
            return []
        return [v for v in range(order.version + 1, max(order.pending))
                if v not in order.pending]

    # ------------------------------------------------------------- fencing
    def write(self, worker, token, event: OrderEvent):
        """A worker's update. Checked against the fencing token before anything else."""
        order = self._order(event.order_id)
        log(self.name, f"write from {worker} token={token}  {event}  "
                       f"(highest token seen={order.highest_token})")
        if token < order.highest_token:
            log(self.name, f"REJECTED  {worker} is STALE: token {token} < {order.highest_token} "
                           f"-> order left unchanged")
            return REJECTED_STALE_TOKEN
        order.highest_token = token
        log(self.name, f"ACCEPTED  token {token} is current")
        return self.apply_event(event)

    # ------------------------------------------------------------- reading
    def describe(self, order_id):
        order = self._order(order_id)
        pending = sorted(order.pending) or "none"
        missing = self.missing_versions(order_id) or "none"
        history = " -> ".join(order.history) or "(empty)"
        return (f"order_id={order_id} status={order.status} version={order.version} "
                f"history=[{history}] pending={pending} missing={missing}")
