"""
scanner/rate_limiter.py — Thread-safe token bucket rate limiter.

Used by Stage 2 to parallelize Schwab API calls while respecting 100 req/min limit.
"""
from __future__ import annotations
import threading
import time
import logging

logger = logging.getLogger(__name__)


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Allows `rate` operations per `per` seconds. Callers block in `acquire()`
    until a token is available.
    """

    def __init__(self, rate: float = 100, per: float = 60.0) -> None:
        self._rate = rate           # tokens per `per` seconds
        self._per = per             # time window in seconds
        self._tokens = rate         # start full
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> None:
        """Block until `tokens` are available, then consume them."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate wait time for next token
                tokens_needed = tokens - self._tokens
                wait = (tokens_needed / self._rate) * self._per
            time.sleep(min(wait, 0.1))  # sleep in small increments

    def _refill(self) -> None:
        """Refill tokens based on elapsed time. Must be called with lock held."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * (self._rate / self._per)
        self._tokens = min(self._tokens + new_tokens, self._rate)
        self._last_refill = now


# Module-level singleton for Schwab API (100 req/min)
_schwab_bucket: TokenBucket | None = None
_bucket_lock = threading.Lock()


def get_schwab_bucket() -> TokenBucket:
    """Return the module-level Schwab token bucket singleton (100 req/min)."""
    global _schwab_bucket
    if _schwab_bucket is None:
        with _bucket_lock:
            if _schwab_bucket is None:
                _schwab_bucket = TokenBucket(rate=100, per=60.0)
    return _schwab_bucket
