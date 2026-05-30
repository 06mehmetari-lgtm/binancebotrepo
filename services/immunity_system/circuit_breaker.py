import time

class CircuitBreaker:
    def __init__(self, max_failures: int = 5, reset_timeout: float = 300.0):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self._failures = 0
        self._open_since: float | None = None

    @property
    def is_open(self) -> bool:
        if self._open_since and (time.time() - self._open_since) > self.reset_timeout:
            self._failures = 0
            self._open_since = None
        return self._open_since is not None

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.max_failures:
            self._open_since = time.time()

    def record_success(self):
        self._failures = 0
        self._open_since = None
