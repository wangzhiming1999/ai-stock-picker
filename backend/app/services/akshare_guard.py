"""Serialize AkShare calls that share a process-level JavaScript runtime."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

_LOCK = threading.RLock()


def call(func: Callable[..., Any], *args, **kwargs):
    with _LOCK:
        return func(*args, **kwargs)
