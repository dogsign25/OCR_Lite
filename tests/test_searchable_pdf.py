from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from app.services.searchable_pdf import (
    SearchablePage,
    SearchablePdfError,
    write_searchable_pdf,
)


class SearchablePdfTests(unittest.TestCase):
    def test_writes_selected_pages_with_invisible_korean_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            output_pdf = root / "searchable.pdf"
            source = fitz.open()
            for _ in range(3):
                source.new_page()
            source.save(source_pdf)
            source.close()

            write_searchable_pdf(
                source_pdf,
                output_pdf,
                [
                    SearchablePage(2, "승인 완료 문서"),
                    SearchablePage(3, "Invoice number 42"),
                ],
            )

            searchable = fitz.open(output_pdf)
            self.assertEqual(searchable.page_count, 2)
            self.assertIn("승인 완료 문서", searchable[0].get_text())
            self.assertTrue(searchable[0].search_for("승인 완료"))
            self.assertIn("Invoice number 42", searchable[1].get_text())
            searchable.close()

    def test_rejects_empty_page_list(self) -> None:
        with self.assertRaisesRegex(SearchablePdfError, "at least one page"):
            write_searchable_pdf(
                Path("source.pdf"),
                Path("searchable.pdf"),
                [],
            )

    def test_preserves_long_text_on_a_short_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            output_pdf = root / "searchable.pdf"
            source = fitz.open()
            source.new_page(width=100, height=80)
            source.save(source_pdf)
            source.close()
            text = " ".join(f"word{index}" for index in range(500))
            text += " FINALMARKER"

            write_searchable_pdf(
                source_pdf,
                output_pdf,
                [SearchablePage(1, text)],
            )

            searchable = fitz.open(output_pdf)
            self.assertTrue(searchable[0].search_for("FINALMARKER"))
            searchable.close()

    def test_applies_page_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            output_pdf = root / "searchable.pdf"
            source = fitz.open()
            source.new_page()
            source.save(source_pdf)
            source.close()

            write_searchable_pdf(
                source_pdf,
                output_pdf,
                [SearchablePage(1, "rotated text", rotation=90)],
            )

            searchable = fitz.open(output_pdf)
            self.assertEqual(searchable[0].rotation, 90)
            self.assertTrue(searchable[0].search_for("rotated text"))
            searchable.close()


if __name__ == "__main__":
    unittest.main()
