"""Process-local dependency bulkhead and circuit breaker; no automatic retries.

Admission is non-blocking. Late calls cannot close a newer OPEN generation.
These limits are per API process, not a distributed deployment-wide quota.
"""
from contextlib import contextmanager
import math
import threading
import time


class DependencyRejected(RuntimeError):
    def __init__(self, reason: str, retry_after: int):
        super().__init__(reason)
        self.retry_after = retry_after


class DependencyGuard:
    def __init__(self, capacity=2, threshold=3, cooldown=30.0, clock=time.monotonic, count_failure=lambda _exc: True):
        if capacity < 1 or threshold < 1 or cooldown <= 0:
            raise ValueError("Dependency limits must be positive")
        self._permits = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._threshold = threshold
        self._cooldown = cooldown
        self._clock = clock
        self._count_failure = count_failure
        self._failures = 0
        self._open_until = 0.0
        self._probe = False
        self._generation = 0

    def _enter(self):
        if not self._permits.acquire(blocking=False):
            raise DependencyRejected("Analysis capacity is busy. Please retry shortly.", 1)
        try:
            with self._lock:
                if self._open_until:
                    remaining = self._open_until - self._clock()
                    if remaining > 0 or self._probe:
                        raise DependencyRejected("The analysis dependency is recovering. Please retry shortly.", max(1, math.ceil(remaining)))
                    self._probe = True
                return self._generation, self._probe
        except BaseException:
            self._permits.release()
            raise

    def _finish(self, generation, probe, failed):
        with self._lock:
            if generation != self._generation:
                return
            if failed:
                self._failures += 1
                if probe or self._failures >= self._threshold:
                    self._open_until = self._clock() + self._cooldown
                    self._probe = False
                    self._generation += 1
            else:
                self._failures = 0
                if probe:
                    self._open_until = 0.0
                    self._probe = False
                    self._generation += 1

    @contextmanager
    def call(self):
        generation, probe = self._enter()
        try:
            yield
        except BaseException as exc:
            self._finish(generation, probe, self._count_failure(exc))
            raise
        else:
            self._finish(generation, probe, False)
        finally:
            self._permits.release()
