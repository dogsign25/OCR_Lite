from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from app.services.pdf_converter import PdfConversionError, convert_pdf_to_png


class PdfConverterLimitTests(unittest.TestCase):
    def test_rejects_pdf_over_page_limit_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            document = fitz.open()
            document.new_page()
            document.new_page()
            document.save(source_pdf)
            document.close()

            with self.assertRaisesRegex(PdfConversionError, "limit is 1"):
                convert_pdf_to_png(
                    source_pdf,
                    root / "images",
                    "source",
                    max_pages=1,
                )
            self.assertEqual(list((root / "images").glob("*.png")), [])

    def test_rejects_page_over_pixel_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            document = fitz.open()
            document.new_page(width=1000, height=1000)
            document.save(source_pdf)
            document.close()

            with self.assertRaisesRegex(PdfConversionError, "too large"):
                convert_pdf_to_png(
                    source_pdf,
                    root / "images",
                    "source",
                    max_render_pixels=100,
                )
            self.assertEqual(list((root / "images").glob("*.png")), [])


if __name__ == "__main__":
    unittest.main()
