"""Commit fence installed only by admitted analysis callbacks."""

from contextlib import contextmanager
from contextvars import ContextVar

_guard = ContextVar("analysis_commit_guard", default=None)


def check_commit():
    guard = _guard.get()
    if guard is not None:
        guard()


@contextmanager
def commit_guard(check):
    token = _guard.set(check)
    try:
        yield
    finally:
        _guard.reset(token)
