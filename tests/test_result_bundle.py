from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from app.services.result_bundle import (
    BundleFile,
    ResultBundleError,
    write_result_bundle,
)


class ResultBundleTests(unittest.TestCase):
    def test_writes_outputs_into_named_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_file = root / "result.json"
            pdf_file = root / "result.pdf"
            json_file.write_text('{"status": "ok"}', encoding="utf-8")
            pdf_file.write_bytes(b"%PDF")
            output_zip = root / "result.zip"

            write_result_bundle(
                output_zip,
                [
                    BundleFile(json_file, "json"),
                    BundleFile(pdf_file, "pdf"),
                ],
            )

            with ZipFile(output_zip) as archive:
                self.assertEqual(
                    sorted(archive.namelist()),
                    ["json/result.json", "pdf/result.pdf"],
                )
                self.assertEqual(
                    archive.read("json/result.json"),
                    b'{"status": "ok"}',
                )

    def test_rejects_empty_bundle(self) -> None:
        with self.assertRaisesRegex(ResultBundleError, "at least one"):
            write_result_bundle(Path("result.zip"), [])

    def test_rejects_unsafe_archive_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "result.json"
            source.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ResultBundleError, "unsafe"):
                write_result_bundle(
                    root / "result.zip",
                    [BundleFile(source, "../outside")],
                )


if __name__ == "__main__":
    unittest.main()
