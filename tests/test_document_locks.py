from __future__ import annotations

import threading
import time
import unittest

from app.services.document_locks import DocumentLockStore


class DocumentLockStoreTests(unittest.TestCase):
    def test_serializes_mutations_for_same_document(self) -> None:
        store = DocumentLockStore()
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()

        def first() -> None:
            with store.hold("document"):
                first_entered.set()
                release_first.wait(timeout=2)

        def second() -> None:
            first_entered.wait(timeout=2)
            with store.hold("document"):
                second_entered.set()

        first_thread = threading.Thread(target=first)
        second_thread = threading.Thread(target=second)
        first_thread.start()
        second_thread.start()
        self.assertTrue(first_entered.wait(timeout=1))
        time.sleep(0.05)
        self.assertFalse(second_entered.is_set())
        release_first.set()
        first_thread.join(timeout=2)
        second_thread.join(timeout=2)
        self.assertTrue(second_entered.is_set())


if __name__ == "__main__":
    unittest.main()
