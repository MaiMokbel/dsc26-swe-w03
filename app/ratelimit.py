"""Token bucket per customer."""
import math
import threading
from collections.abc import Callable


class TokenBucketLimiter:
    def __init__(self, capacity: int, refill_per_second: float, clock: Callable[[], float]):
        self.capacity = capacity
        self.rate = refill_per_second
        self.clock = clock                       ### settings.clock, mesh time.time abadan
        self._buckets: dict[str, tuple[float, float]] = {}             ### customer -> (tokens, last_time)
        self._lock = threading.Lock()

    def acquire(self, customer_id: str) -> int:
        """Return 0 if allowed, otherwise Retry-After in whole seconds (>= 1)."""
        with self._lock:
            now = self.clock()
            tokens, last = self._buckets.get(customer_id, (float(self.capacity), now))              ### bucket gedid bey-ebda2 malyan
            elapsed = max(0.0, now - last)
            tokens = min(float(self.capacity), tokens + elapsed * self.rate)            ### refill mesh a3la men el capacity
            if tokens >= 1.0 - 1e-9:
                self._buckets[customer_id] = (tokens - 1.0, now)
                return 0
            self._buckets[customer_id] = (tokens, now)
            wait = (1.0 - tokens) / self.rate if self.rate > 0 else 60.0
            return max(1, math.ceil(wait))              ### integer w >= 1