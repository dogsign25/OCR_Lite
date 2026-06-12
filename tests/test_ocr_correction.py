from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from app.services.ocr_correction import (
    OcrCorrectionError,
    PageCorrection,
    apply_ocr_corrections,
)


class OcrCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_pdf = self.root / "source.pdf"
        self.verified_json = self.root / "source.verified.json"
        self.searchable_pdf = self.root / "source.searchable.pdf"

        source = fitz.open()
        source.new_page()
        source.new_page()
        source.save(self.source_pdf)
        source.close()
        self.verified_json.write_text(
            json.dumps(
                {
                    "source_pdf": "source.pdf",
                    "total_pages": 2,
                    "verification": {"review_required_pages": 1},
                    "pages": [
                        {
                            "page_number": 1,
                            "text": "correct page",
                            "review_required": False,
                            "review_reasons": [],
                        },
                        {
                            "page_number": 2,
                            "text": "잘못 인식된 문장",
                            "review_required": True,
                            "review_reasons": ["low_ocr_confidence"],
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_updates_json_and_regenerates_searchable_pdf(self) -> None:
        payload = apply_ocr_corrections(
            self.verified_json,
            self.source_pdf,
            self.searchable_pdf,
            [PageCorrection(2, "수정된 승인 문장")],
        )

        corrected_page = payload["pages"][1]
        self.assertEqual(corrected_page["text"], "수정된 승인 문장")
        self.assertEqual(
            corrected_page["original_ocr_text"],
            "잘못 인식된 문장",
        )
        self.assertTrue(corrected_page["manually_corrected"])
        self.assertFalse(corrected_page["review_required"])
        self.assertEqual(
            payload["verification"]["review_required_pages"],
            0,
        )

        saved = json.loads(self.verified_json.read_text(encoding="utf-8"))
        self.assertEqual(saved["pages"][1]["text"], "수정된 승인 문장")
        searchable = fitz.open(self.searchable_pdf)
        self.assertEqual(searchable.page_count, 2)
        self.assertTrue(searchable[1].search_for("수정된 승인 문장"))
        searchable.close()

    def test_rejects_unknown_page_number(self) -> None:
        with self.assertRaisesRegex(OcrCorrectionError, "Unknown OCR page"):
            apply_ocr_corrections(
                self.verified_json,
                self.source_pdf,
                self.searchable_pdf,
                [PageCorrection(9, "invalid")],
            )

        self.assertFalse(self.searchable_pdf.exists())

    def test_keeps_unsubmitted_review_pages_pending(self) -> None:
        payload = json.loads(self.verified_json.read_text(encoding="utf-8"))
        payload["pages"][0]["review_required"] = True
        payload["pages"][0]["review_reasons"] = ["low_candidate_agreement"]
        payload["verification"]["review_required_pages"] = 2
        self.verified_json.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

        corrected = apply_ocr_corrections(
            self.verified_json,
            self.source_pdf,
            self.searchable_pdf,
            [PageCorrection(2, "수정된 문장")],
        )

        self.assertTrue(corrected["pages"][0]["review_required"])
        self.assertFalse(corrected["pages"][1]["review_required"])
        self.assertEqual(
            corrected["verification"]["review_required_pages"],
            1,
        )

    def test_generation_failure_preserves_existing_outputs(self) -> None:
        original_json = self.verified_json.read_bytes()
        self.searchable_pdf.write_bytes(b"existing searchable pdf")

        with patch(
            "app.services.ocr_correction.write_ocr_result",
            side_effect=OSError("disk full"),
        ):
            with self.assertRaisesRegex(
                OcrCorrectionError,
                "without changing existing outputs",
            ):
                apply_ocr_corrections(
                    self.verified_json,
                    self.source_pdf,
                    self.searchable_pdf,
                    [PageCorrection(2, "new text")],
                )

        self.assertEqual(self.verified_json.read_bytes(), original_json)
        self.assertEqual(
            self.searchable_pdf.read_bytes(),
            b"existing searchable pdf",
        )

    def test_rejects_duplicate_page_numbers_in_verified_json(self) -> None:
        payload = json.loads(self.verified_json.read_text(encoding="utf-8"))
        payload["pages"][1]["page_number"] = 1
        self.verified_json.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(OcrCorrectionError, "unique positive"):
            apply_ocr_corrections(
                self.verified_json,
                self.source_pdf,
                self.searchable_pdf,
                [PageCorrection(1, "new text")],
            )


if __name__ == "__main__":
    unittest.main()
