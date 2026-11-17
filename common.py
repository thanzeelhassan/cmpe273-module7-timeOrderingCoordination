"""Shared helpers: the order event shape and a timestamped logger."""
from dataclasses import dataclass
from datetime import datetime

# The order lifecycle. The version number IS the position in this lifecycle:
# version 1 = CREATED, version 2 = PAID, version 3 = SHIPPED.
STATUS_BY_VERSION = {1: "CREATED", 2: "PAID", 3: "SHIPPED"}


@dataclass(frozen=True)
class OrderEvent:
    """One order update. Every update carries order_id, version and status."""
    order_id: str
    version: int
    status: str

    def __str__(self):
        return f"order_id={self.order_id} version={self.version} status={self.status}"


def log(component, message):
    """Print 'HH:MM:SS.mmm [component] message'."""
    now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"{now} [{component}] {message}", flush=True)
