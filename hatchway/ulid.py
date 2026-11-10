"""Minimal monotonic ULID generator: 48-bit millisecond timestamp + 80 random bits, Crockford
base32. Within one process, IDs strictly increase, even within the same millisecond."""

from __future__ import annotations

import os
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_RANDOM_BITS = 80

_lock = threading.Lock()
_last = 0


def new_ulid() -> str:
    """Return a 26-character ULID that sorts after every ULID this process made before it."""
    global _last
    with _lock:
        value = (time.time_ns() // 1_000_000) << _RANDOM_BITS | int.from_bytes(
            os.urandom(10), "big"
        )
        if value <= _last:
            # Same millisecond (or clock stepped back): keep order by incrementing.
            value = _last + 1
        _last = value
    chars = []
    for _ in range(26):
        value, index = divmod(value, 32)
        chars.append(_ALPHABET[index])
    return "".join(reversed(chars))
