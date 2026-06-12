from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from app.services.page_filter import (
    PageFilterError,
    evaluate_page_filter,
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

    def test_any_mode_keeps_page_when_one_term_matches(self) -> None:
        decision = evaluate_page_filter(
            ["Invoice Number 42"],
            ["invoice", "approved"],
            match_mode="any",
        )

        self.assertTrue(decision.keep)
        self.assertEqual(decision.matched_terms, ("invoice",))

    def test_all_mode_combines_matches_from_different_candidates(self) -> None:
        decision = evaluate_page_filter(
            ["Invoice Number 42", "Approved by manager"],
            ["invoice", "approved"],
            match_mode="all",
        )

        self.assertTrue(decision.keep)
        self.assertEqual(decision.matched_terms, ("invoice", "approved"))

    def test_all_mode_rejects_page_with_missing_term(self) -> None:
        decision = evaluate_page_filter(
            ["Invoice Number 42"],
            ["invoice", "approved"],
            match_mode="all",
        )

        self.assertFalse(decision.keep)

    def test_exclude_term_overrides_include_match(self) -> None:
        decision = evaluate_page_filter(
            ["Approved invoice draft"],
            ["invoice"],
            exclude_terms=["draft"],
        )

        self.assertFalse(decision.keep)
        self.assertEqual(decision.excluded_terms, ("draft",))

    def test_exclude_only_filter_keeps_unmatched_page(self) -> None:
        decision = evaluate_page_filter(
            ["Final invoice"],
            exclude_terms=["draft"],
        )

        self.assertTrue(decision.keep)

    def test_rejects_invalid_match_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "any, all"):
            evaluate_page_filter(["text"], ["text"], match_mode="invalid")

    def test_matches_unicode_compatibility_forms(self) -> None:
        decision = evaluate_page_filter(
            ["ＡＰＰＲＯＶＥＤ 문서"],
            ["APPROVED"],
        )

        self.assertTrue(decision.keep)

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
        with self.assertRaisesRegex(PageFilterError, "No pages satisfied"):
            write_filtered_pdf(Path("source.pdf"), Path("filtered.pdf"), [])


if __name__ == "__main__":
    unittest.main()
