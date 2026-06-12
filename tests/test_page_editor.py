from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from app.services.page_editor import (
    PageEdit,
    PageEditError,
    apply_page_edits,
)


class PageEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_pdf = self.root / "source.pdf"
        source = fitz.open()
        for number in range(1, 4):
            page = source.new_page()
            page.insert_text((72, 72), f"source page {number}")
        source.save(self.source_pdf)
        source.close()

        pages = [
            {
                "page_number": number,
                "text": f"OCR page {number}",
                "review_required": False,
            }
            for number in range(1, 4)
        ]
        self.verified_json = self.root / "source.verified.json"
        self.candidate_json = self.root / "source.candidate-1.json"
        for path in (self.verified_json, self.candidate_json):
            path.write_text(
                json.dumps({"pages": pages}),
                encoding="utf-8",
            )
        self.edited_pdf = self.root / "source.edited.pdf"
        self.searchable_pdf = self.root / "source.searchable.pdf"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_reorders_rotates_and_updates_json_outputs(self) -> None:
        payload = apply_page_edits(
            self.source_pdf,
            self.verified_json,
            [self.candidate_json],
            self.edited_pdf,
            self.searchable_pdf,
            [PageEdit(3, 90), PageEdit(1, 0), PageEdit(2, 180)],
        )

        self.assertEqual(
            [page["page_number"] for page in payload["pages"]],
            [3, 1, 2],
        )
        self.assertEqual(
            [page["output_page_number"] for page in payload["pages"]],
            [1, 2, 3],
        )
        self.assertEqual(
            [page["rotation"] for page in payload["pages"]],
            [90, 0, 180],
        )

        edited = fitz.open(self.edited_pdf)
        self.assertIn("source page 3", edited[0].get_text())
        self.assertEqual(edited[0].rotation, 90)
        self.assertEqual(edited[2].rotation, 180)
        edited.close()

        searchable = fitz.open(self.searchable_pdf)
        self.assertTrue(searchable[0].search_for("OCR page 3"))
        self.assertEqual(searchable[0].rotation, 90)
        searchable.close()

        candidate = json.loads(self.candidate_json.read_text(encoding="utf-8"))
        self.assertEqual(
            [page["page_number"] for page in candidate["pages"]],
            [3, 1, 2],
        )

    def test_requires_every_page_once(self) -> None:
        with self.assertRaisesRegex(PageEditError, "every retained page"):
            apply_page_edits(
                self.source_pdf,
                self.verified_json,
                [self.candidate_json],
                self.edited_pdf,
                self.searchable_pdf,
                [PageEdit(1)],
            )

    def test_generation_failure_preserves_existing_outputs(self) -> None:
        original_verified = self.verified_json.read_bytes()
        original_candidate = self.candidate_json.read_bytes()
        self.edited_pdf.write_bytes(b"existing edited")
        self.searchable_pdf.write_bytes(b"existing searchable")

        with patch(
            "app.services.page_editor.write_searchable_pdf",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(
                PageEditError,
                "without changing existing outputs",
            ):
                apply_page_edits(
                    self.source_pdf,
                    self.verified_json,
                    [self.candidate_json],
                    self.edited_pdf,
                    self.searchable_pdf,
                    [PageEdit(1), PageEdit(2), PageEdit(3)],
                )

        self.assertEqual(self.verified_json.read_bytes(), original_verified)
        self.assertEqual(self.candidate_json.read_bytes(), original_candidate)
        self.assertEqual(self.edited_pdf.read_bytes(), b"existing edited")
        self.assertEqual(
            self.searchable_pdf.read_bytes(),
            b"existing searchable",
        )

    def test_rejects_partial_candidate_set(self) -> None:
        payload = json.loads(self.verified_json.read_text(encoding="utf-8"))
        payload["verification"] = {"candidate_count": 2}
        self.verified_json.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(PageEditError, "All candidate"):
            apply_page_edits(
                self.source_pdf,
                self.verified_json,
                [self.candidate_json],
                self.edited_pdf,
                self.searchable_pdf,
                [PageEdit(1), PageEdit(2), PageEdit(3)],
            )


if __name__ == "__main__":
    unittest.main()
