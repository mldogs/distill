"""Distributed locking utilities for jobs (best-effort)."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def redis_lock(
    key: str,
    *,
    ttl_seconds: int = 600,
    blocking: bool = False,
    blocking_timeout_seconds: int = 0,
) -> Iterator[bool]:
    """
    Best-effort Redis lock.

    Returns:
        Iterator yielding `True` if acquired, `False` otherwise.

    Notes:
        - If Redis is not configured or the `redis` package is missing, this becomes a no-op lock (acquired=True).
        - This is intended for operational protection (overlap prevention), not as a strict correctness primitive.
    """
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        yield True
        return

    try:
        import redis  # type: ignore
    except Exception:
        yield True
        return

    client = redis.Redis.from_url(redis_url)
    lock = client.lock(
        name=key,
        timeout=ttl_seconds,
        blocking_timeout=blocking_timeout_seconds,
    )

    acquired = False
    try:
        acquired = lock.acquire(blocking=blocking)
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except Exception:
                # Lock TTL will expire eventually.
                pass

