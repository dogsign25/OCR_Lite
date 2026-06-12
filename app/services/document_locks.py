from __future__ import annotations

from contextlib import contextmanager
from threading import Lock, RLock
from typing import Iterator


class DocumentLockStore:
    def __init__(self) -> None:
        self._guard = Lock()
        self._locks: dict[str, tuple[RLock, int]] = {}

    @contextmanager
    def hold(self, document_id: str) -> Iterator[None]:
        with self._guard:
            lock, users = self._locks.get(document_id, (RLock(), 0))
            self._locks[document_id] = (lock, users + 1)

        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                current_lock, users = self._locks[document_id]
                if users == 1:
                    del self._locks[document_id]
                else:
                    self._locks[document_id] = (current_lock, users - 1)
