from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from app.services.document_processor import process_document
from app.services.ocr_service import OcrResult


class DocumentProcessorFilterTests(unittest.TestCase):
    def test_keeps_only_pages_matching_any_ocr_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            image_dir = root / "images"
            json_dir = root / "json"
            filtered_pdf = root / "filtered.pdf"
            source = fitz.open()
            for page_number in range(1, 4):
                page = source.new_page()
                page.insert_text((72, 72), f"source page {page_number}")
            source.save(source_pdf)
            source.close()

            image_dir.mkdir()
            image_paths = [
                image_dir / f"source({page_number}).png"
                for page_number in range(1, 4)
            ]
            for image_path in image_paths:
                image_path.write_bytes(b"placeholder")

            def fake_ocr(
                image_path: Path,
                profile: object,
                **_: object,
            ) -> OcrResult:
                if (
                    image_path.name == "source(2).png"
                    and getattr(profile, "name") == "sparse-text"
                ):
                    return OcrResult("승인 완료 문서", 95.0)
                return OcrResult("일반 페이지", 90.0)

            with (
                patch(
                    "app.services.document_processor.validate_ocr_language"
                ),
                patch(
                    "app.services.document_processor.convert_pdf_to_png",
                    return_value=image_paths,
                ),
                patch(
                    "app.services.document_processor.extract_ocr_result",
                    side_effect=fake_ocr,
                ),
            ):
                result = process_document(
                    pdf_path=source_pdf,
                    image_dir=image_dir,
                    json_dir=json_dir,
                    base_name="source",
                    filter_terms=("승인 완료",),
                    filtered_pdf_path=filtered_pdf,
                )

            self.assertEqual(result.source_total_pages, 3)
            self.assertEqual(result.total_pages, 1)
            self.assertEqual([path.name for path in result.image_paths], ["source(2).png"])
            self.assertFalse(image_paths[0].exists())
            self.assertTrue(image_paths[1].exists())
            self.assertFalse(image_paths[2].exists())

            filtered = fitz.open(filtered_pdf)
            self.assertEqual(filtered.page_count, 1)
            self.assertIn("source page 2", filtered.load_page(0).get_text())
            filtered.close()

            payload = json.loads(result.verified_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["page_filter"]["retained_pages"], 1)
            self.assertEqual(payload["page_filter"]["discarded_pages"], 2)
            self.assertEqual(payload["pages"][0]["page_number"], 2)
            self.assertEqual(
                payload["pages"][0]["matched_filter_terms"],
                ["승인 완료"],
            )


if __name__ == "__main__":
    unittest.main()
