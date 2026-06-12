from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from app.services.page_filter import (
    PageFilterError,
    find_matching_terms,
    normalize_filter_terms,
    parse_filter_terms,
    write_filtered_pdf,
)


class PageFilterTests(unittest.TestCase):
    def test_normalizes_and_deduplicates_terms(self) -> None:
        self.assertEqual(
            normalize_filter_terms([" Invoice ", "invoice", "승인   완료", ""]),
            ("Invoice", "승인 완료"),
        )

    def test_parses_comma_and_newline_separated_terms(self) -> None:
        self.assertEqual(
            parse_filter_terms("invoice, approved\n결재"),
            ("invoice", "approved", "결재"),
        )

    def test_matches_any_candidate_case_insensitively(self) -> None:
        matches = find_matching_terms(
            ["No useful text", "Invoice Number 42"],
            ["invoice", "approved"],
        )

        self.assertEqual(matches, ["invoice"])

    def test_writes_only_selected_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.pdf"
            output_path = root / "filtered.pdf"
            source = fitz.open()
            for page_number in range(1, 4):
                page = source.new_page()
                page.insert_text((72, 72), f"page {page_number}")
            source.save(source_path)
            source.close()

            write_filtered_pdf(source_path, output_path, [2, 3])

            filtered = fitz.open(output_path)
            self.assertEqual(filtered.page_count, 2)
            self.assertIn("page 2", filtered.load_page(0).get_text())
            self.assertIn("page 3", filtered.load_page(1).get_text())
            filtered.close()

    def test_rejects_empty_page_selection(self) -> None:
        with self.assertRaisesRegex(PageFilterError, "No pages matched"):
            write_filtered_pdf(Path("source.pdf"), Path("filtered.pdf"), [])


if __name__ == "__main__":
    unittest.main()
