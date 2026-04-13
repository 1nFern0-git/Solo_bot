"""In-memory rate limit fallback для случаев когда Redis недоступен.

Используется только когда Redis не ответил — чтобы критичные auth-эндпоинты
не теряли защиту при кратковременных Redis-сбоях. Per-process, не шарится
между репликами — поэтому на нескольких инстансах лимит будет N*limit.
"""

import time
from collections import deque
from threading import Lock


_BUCKETS: dict[str, deque[float]] = {}
_LOCK = Lock()
_MAX_KEYS = 10000


def _prune(bucket: deque[float], window_sec: int) -> None:
    threshold = time.monotonic() - window_sec
    while bucket and bucket[0] < threshold:
        bucket.popleft()


def _evict_if_full() -> None:
    if len(_BUCKETS) < _MAX_KEYS:
        return
    now = time.monotonic()
    dead = [k for k, b in _BUCKETS.items() if not b or b[-1] < now - 3600]
    for k in dead:
        del _BUCKETS[k]
    if len(_BUCKETS) >= _MAX_KEYS:
        oldest = min(_BUCKETS.keys(), key=lambda k: _BUCKETS[k][0] if _BUCKETS[k] else 0)
        del _BUCKETS[oldest]


def check_and_increment(key: str, limit: int, window_sec: int) -> int:
    """Возвращает текущее значение счётчика после инкремента. Если >= limit — превышение."""
    with _LOCK:
        _evict_if_full()
        bucket = _BUCKETS.setdefault(key, deque())
        _prune(bucket, window_sec)
        bucket.append(time.monotonic())
        return len(bucket)
