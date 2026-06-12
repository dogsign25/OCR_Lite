from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.batch import load_reusable_manifest


class BatchManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.document_dir = Path(self.temporary_directory.name)
        self.output_file = self.document_dir / "json" / "result.json"
        self.output_file.parent.mkdir()
        self.output_file.write_text("{}\n", encoding="utf-8")
        self.searchable_pdf = self.document_dir / "result.searchable.pdf"
        self.searchable_pdf.write_bytes(b"%PDF-searchable")
        self.fingerprint = {
            "name": "source.pdf",
            "size": 123,
            "sha256": "abc",
        }
        self.settings = {
            "pipeline_version": "7",
            "ocr_language": "kor+eng",
            "filter_terms": [],
            "filter_match_mode": "any",
            "exclude_terms": [],
            "profiles": [],
        }
        self.manifest_path = self.document_dir / "manifest.json"
        self.result_zip = self.document_dir / "result.results.zip"
        with ZipFile(self.result_zip, "w", compression=ZIP_DEFLATED) as archive:
            archive.write(self.output_file, "json/result.json")
            archive.write(self.searchable_pdf, "pdf/result.searchable.pdf")
        self.manifest_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "source": self.fingerprint,
                    "settings": self.settings,
                    "result": {
                        "total_pages": 1,
                        "source_total_pages": 1,
                        "verified_json": "json/result.json",
                        "searchable_pdf": "result.searchable.pdf",
                        "result_zip": "result.results.zip",
                        "warning_count": 0,
                        "review_required_pages": 0,
                        "output_files": [
                            "json/result.json",
                            "result.searchable.pdf",
                            "result.results.zip",
                        ],
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_reuses_complete_matching_manifest(self) -> None:
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            self.settings,
        )
        self.assertIsNotNone(manifest)

    def test_reprocesses_when_source_changes(self) -> None:
        changed = {**self.fingerprint, "sha256": "changed"}
        manifest = load_reusable_manifest(
            self.manifest_path,
            changed,
            self.settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_output_is_missing(self) -> None:
        self.output_file.unlink()
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            self.settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_searchable_pdf_is_missing(self) -> None:
        self.searchable_pdf.unlink()
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            self.settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_result_zip_is_missing(self) -> None:
        self.result_zip.unlink()
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            self.settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_result_zip_is_corrupt(self) -> None:
        self.result_zip.write_bytes(b"not a zip")
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            self.settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_output_differs_from_result_zip(self) -> None:
        self.output_file.write_text('{"changed": true}\n', encoding="utf-8")
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            self.settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_manifest_is_incomplete(self) -> None:
        self.manifest_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "source": self.fingerprint,
                    "settings": self.settings,
                    "result": {"output_files": ["json/result.json"]},
                }
            ),
            encoding="utf-8",
        )
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            self.settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_filter_terms_change(self) -> None:
        changed_settings = {**self.settings, "filter_terms": ["invoice"]}
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            changed_settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_filter_mode_changes(self) -> None:
        changed_settings = {**self.settings, "filter_match_mode": "all"}
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            changed_settings,
        )
        self.assertIsNone(manifest)

    def test_reprocesses_when_exclude_terms_change(self) -> None:
        changed_settings = {**self.settings, "exclude_terms": ["draft"]}
        manifest = load_reusable_manifest(
            self.manifest_path,
            self.fingerprint,
            changed_settings,
        )
        self.assertIsNone(manifest)


if __name__ == "__main__":
    unittest.main()
