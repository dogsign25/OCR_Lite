from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.batch import load_reusable_manifest


class BatchManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.document_dir = Path(self.temporary_directory.name)
        self.output_file = self.document_dir / "json" / "result.json"
        self.output_file.parent.mkdir()
        self.output_file.write_text("{}\n", encoding="utf-8")
        self.fingerprint = {
            "name": "source.pdf",
            "size": 123,
            "sha256": "abc",
        }
        self.settings = {
            "pipeline_version": "3",
            "ocr_language": "kor+eng",
            "profiles": [],
        }
        self.manifest_path = self.document_dir / "manifest.json"
        self.manifest_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "source": self.fingerprint,
                    "settings": self.settings,
                    "result": {
                        "total_pages": 1,
                        "verified_json": "json/result.json",
                        "warning_count": 0,
                        "review_required_pages": 0,
                        "output_files": ["json/result.json"],
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


if __name__ == "__main__":
    unittest.main()
