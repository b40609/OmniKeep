import asyncio
from weakref import WeakValueDictionary

_locks = WeakValueDictionary()


def target_lock(key):
    identity = (asyncio.get_running_loop(), key)
    lock = _locks.get(identity)
    if lock is None:
        lock = asyncio.Lock()
        _locks[identity] = lock
    return lock
