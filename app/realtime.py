"""In-memory realtime event buffer for WebSocket delivery.

Sync code anywhere calls ``publish(...)``; WebSocket handlers poll
``events_since(...)`` to stream new events to admins and chat widgets.
A thread lock keeps it safe across the request threadpool.
"""
import threading
import time

_lock = threading.Lock()
_events: list[dict] = []
_seq = 0
_MAX = 600


def publish(event: dict) -> None:
    """Append a realtime event (gets a monotonic ``seq`` and timestamp)."""
    global _seq
    with _lock:
        _seq += 1
        _events.append({**event, "seq": _seq, "ts": time.time()})
        if len(_events) > _MAX:
            del _events[: len(_events) - _MAX]


def events_since(last_seq: int) -> tuple[list[dict], int]:
    """Return events newer than ``last_seq`` and the current head sequence."""
    with _lock:
        return [e for e in _events if e["seq"] > last_seq], _seq


def head() -> int:
    with _lock:
        return _seq
