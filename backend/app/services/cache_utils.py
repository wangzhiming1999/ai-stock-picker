from __future__ import annotations

from typing import MutableMapping, TypeVar

K = TypeVar("K")
V = TypeVar("V")


def put_bounded(cache: MutableMapping[K, V], key: K, value: V, *, max_entries: int) -> None:
    """Store a value and evict oldest inserted entries beyond the limit."""
    cache[key] = value
    overflow = len(cache) - max(1, max_entries)
    if overflow <= 0:
        return
    for old_key in list(cache.keys())[:overflow]:
        if old_key != key:
            cache.pop(old_key, None)

