import threading
from contextlib import contextmanager

_registry_lock = threading.Lock()
_symbol_locks = {}


def _get_lock(symbol: str) -> threading.RLock:
    with _registry_lock:
        lock = _symbol_locks.get(symbol)
        if lock is None:
            lock = threading.RLock()
            _symbol_locks[symbol] = lock
        return lock


@contextmanager
def live_symbol_lock(symbol: str, blocking: bool = False):
    lock = _get_lock(symbol)
    acquired = lock.acquire(blocking=blocking)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()