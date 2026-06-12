from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import app.main as web_app


class WebOutputTests(unittest.TestCase):
    def test_bundle_and_cleanup_do_not_include_prefix_neighbor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_dir = root / "images"
            json_dir = root / "json"
            pdf_dir = root / "pdf"
            zip_dir = root / "zip"
            for path in (image_dir, json_dir, pdf_dir, zip_dir):
                path.mkdir()

            (json_dir / "report.verified.json").write_text(
                "{}",
                encoding="utf-8",
            )
            neighbor_json = json_dir / "report2.verified.json"
            neighbor_json.write_text("{}", encoding="utf-8")
            (pdf_dir / "report.searchable.pdf").write_bytes(b"%PDF")
            neighbor_pdf = pdf_dir / "report2.searchable.pdf"
            neighbor_pdf.write_bytes(b"%PDF")

            with (
                patch.object(web_app, "IMAGE_DIR", image_dir),
                patch.object(web_app, "JSON_DIR", json_dir),
                patch.object(web_app, "PDF_DIR", pdf_dir),
                patch.object(web_app, "ZIP_DIR", zip_dir),
            ):
                bundle = web_app.refresh_result_bundle("report")
                with ZipFile(bundle) as archive:
                    archive_names = sorted(archive.namelist())
                web_app.cleanup_web_outputs("report")

            self.assertEqual(
                archive_names,
                [
                    "json/report.verified.json",
                    "pdf/report.searchable.pdf",
                ],
            )
            self.assertFalse(bundle.exists())
            self.assertTrue(neighbor_json.is_file())
            self.assertTrue(neighbor_pdf.is_file())


if __name__ == "__main__":
    unittest.main()
