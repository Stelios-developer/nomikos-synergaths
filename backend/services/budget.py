"""Monotonic shared budget for a sequence of provider calls in one operation."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import time


class BudgetExpired(TimeoutError):
    pass


_deadline = ContextVar("dmc_operation_deadline", default=None)


def remaining():
    deadline = _deadline.get()
    value = 120.0 if deadline is None else deadline - time.monotonic()
    if value <= 0:
        raise BudgetExpired("The analysis time budget has expired.")
    return min(120.0, value)


@contextmanager
def operation_budget(seconds=180, *, expires_at=None):
    if expires_at is not None:
        seconds = min(
            seconds, (expires_at - datetime.now(timezone.utc)).total_seconds()
        )
    target = time.monotonic() + seconds
    parent = _deadline.get()
    token = _deadline.set(min(target, parent) if parent is not None else target)
    try:
        remaining()
        yield
    finally:
        _deadline.reset(token)
