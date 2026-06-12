from __future__ import annotations

import unittest

from app.services.progress_tracker import ProgressStore


class ProgressStoreTests(unittest.TestCase):
    def test_tracks_monotonic_progress_and_terminal_state(self) -> None:
        store = ProgressStore()
        self.assertTrue(store.start("job"))
        store.update("job", 40, "Running OCR")
        store.update("job", 20, "Late update")

        progress = store.get("job")
        self.assertIsNotNone(progress)
        self.assertEqual(progress["percent"], 40.0)
        self.assertEqual(progress["message"], "Late update")
        self.assertIsNotNone(progress["eta_seconds"])

        store.finish("job")
        completed = store.get("job")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["percent"], 100.0)
        self.assertEqual(completed["eta_seconds"], 0)

    def test_rejects_duplicate_job_id(self) -> None:
        store = ProgressStore()
        self.assertTrue(store.start("same-job"))
        self.assertFalse(store.start("same-job"))
        self.assertEqual(store.get("same-job")["status"], "processing")


if __name__ == "__main__":
    unittest.main()
