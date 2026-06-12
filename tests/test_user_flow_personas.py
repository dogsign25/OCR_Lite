from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from fastapi import HTTPException

import app.main as web_app
from app.batch import process_batch_item, write_summary
from app.services.document_processor import JsonOutput, ProcessedDocument, process_document
from app.services.ocr_service import OcrResult
from app.services.page_filter import PageFilterError


class AsyncUpload:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content
        self._offset = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._content) - self._offset
        chunk = self._content[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


def create_pdf(path: Path, page_texts: list[str]) -> None:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def create_image_placeholders(
    image_dir: Path,
    base_name: str,
    page_count: int,
) -> list[Path]:
    image_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        image_dir / f"{base_name}({page_number}).png"
        for page_number in range(1, page_count + 1)
    ]
    for path in paths:
        path.write_bytes(b"image")
    return paths


class BatchOperatorPersonaTests(unittest.TestCase):
    """P-01: A bulk operator needs one bad PDF not to block the others."""

    def test_batch_records_success_and_failure_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            good_pdf = input_dir / "good.pdf"
            bad_pdf = input_dir / "bad.pdf"
            good_pdf.write_bytes(b"good")
            bad_pdf.write_bytes(b"bad")

            def fake_process_document(**kwargs: object) -> ProcessedDocument:
                pdf_path = Path(kwargs["pdf_path"])
                if pdf_path.name == "bad.pdf":
                    image_dir = Path(kwargs["image_dir"])
                    json_dir = Path(kwargs["json_dir"])
                    create_image_placeholders(image_dir, "bad", 1)
                    json_dir.mkdir(parents=True, exist_ok=True)
                    (json_dir / "bad.partial.json").write_text(
                        "{}\n",
                        encoding="utf-8",
                    )
                    raise RuntimeError("simulated OCR failure")

                image_dir = Path(kwargs["image_dir"])
                json_dir = Path(kwargs["json_dir"])
                base_name = str(kwargs["base_name"])
                image_path = create_image_placeholders(image_dir, base_name, 1)[0]
                json_dir.mkdir(parents=True, exist_ok=True)
                verified_path = json_dir / f"{base_name}.verified.json"
                verified_path.write_text("{}\n", encoding="utf-8")
                searchable_pdf = Path(kwargs["searchable_pdf_path"])
                searchable_pdf.write_bytes(b"%PDF-searchable")
                return ProcessedDocument(
                    source_pdf=pdf_path.name,
                    image_paths=[image_path],
                    json_outputs=[
                        JsonOutput("verified", "Verified result", verified_path)
                    ],
                    warnings=[],
                    review_required_pages=0,
                    source_total_pages=1,
                    searchable_pdf=searchable_pdf,
                )

            with patch(
                "app.batch.process_document",
                side_effect=fake_process_document,
            ):
                items = [
                    process_batch_item(
                        good_pdf,
                        output_dir,
                        "good",
                        "kor+eng",
                        False,
                    ),
                    process_batch_item(
                        bad_pdf,
                        output_dir,
                        "bad",
                        "kor+eng",
                        False,
                    ),
                ]

            summary_path = write_summary(output_dir, items)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

            self.assertEqual(items[0].status, "completed")
            self.assertEqual(items[1].status, "failed")
            self.assertIn("simulated OCR failure", items[1].error)
            self.assertEqual(summary["counts"], {
                "completed": 1,
                "skipped": 0,
                "failed": 1,
            })
            self.assertTrue((output_dir / "good" / "manifest.json").is_file())
            self.assertFalse((output_dir / "bad" / "manifest.json").exists())
            self.assertEqual(list((output_dir / "bad" / "images").iterdir()), [])
            self.assertEqual(list((output_dir / "bad" / "json").iterdir()), [])

    def test_failed_reprocessing_preserves_last_successful_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            source_pdf.write_bytes(b"new source")
            document_dir = root / "output" / "source"
            image_dir = document_dir / "images"
            json_dir = document_dir / "json"
            image_dir.mkdir(parents=True)
            json_dir.mkdir()
            old_image = image_dir / "source(1).png"
            old_json = json_dir / "source.verified.json"
            old_pdf = document_dir / "source.searchable.pdf"
            old_zip = document_dir / "source.results.zip"
            old_manifest = document_dir / "manifest.json"
            old_image.write_bytes(b"old image")
            old_json.write_bytes(b"old json")
            old_pdf.write_bytes(b"old pdf")
            old_zip.write_bytes(b"old zip")
            old_manifest.write_bytes(b"old manifest")

            def fail_after_partial_outputs(**_: object) -> ProcessedDocument:
                old_image.write_bytes(b"partial image")
                old_json.write_bytes(b"partial json")
                raise RuntimeError("simulated reprocessing failure")

            with patch(
                "app.batch.process_document",
                side_effect=fail_after_partial_outputs,
            ):
                item = process_batch_item(
                    source_pdf,
                    root / "output",
                    "source",
                    "kor+eng",
                    True,
                )

            self.assertEqual(item.status, "failed")
            self.assertEqual(old_image.read_bytes(), b"old image")
            self.assertEqual(old_json.read_bytes(), b"old json")
            self.assertEqual(old_pdf.read_bytes(), b"old pdf")
            self.assertEqual(old_zip.read_bytes(), b"old zip")
            self.assertEqual(old_manifest.read_bytes(), b"old manifest")


class OcrFailurePersonaTests(unittest.TestCase):
    """P-03/P-04: OCR failures must be visible and reviewable."""

    def test_one_failed_profile_becomes_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            create_pdf(source_pdf, ["review me"])
            image_paths = create_image_placeholders(root / "images", "source", 1)

            def fake_ocr(
                image_path: Path,
                profile: object,
                **_: object,
            ) -> OcrResult:
                if getattr(profile, "name") == "uniform-block":
                    raise RuntimeError("profile timeout")
                return OcrResult("review me", 45.0)

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
                    image_dir=root / "images",
                    json_dir=root / "json",
                    base_name="source",
                )

            payload = json.loads(result.verified_json.read_text(encoding="utf-8"))
            self.assertEqual(len(result.warnings), 1)
            self.assertIn("profile timeout", result.warnings[0])
            self.assertEqual(result.review_required_pages, 1)
            self.assertIn(
                "low_ocr_confidence",
                payload["pages"][0]["review_reasons"],
            )

    def test_all_failed_profiles_do_not_write_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            create_pdf(source_pdf, ["unreadable"])
            image_paths = create_image_placeholders(root / "images", "source", 1)

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
                    side_effect=RuntimeError("tesseract unavailable"),
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "All OCR profiles failed",
                ):
                    process_document(
                        pdf_path=source_pdf,
                        image_dir=root / "images",
                        json_dir=root / "json",
                        base_name="source",
                    )

            self.assertFalse((root / "json").exists())


class PageFilterPersonaTests(unittest.TestCase):
    """P-06: A filter user must not receive an empty or destructive result."""

    def test_no_matching_word_preserves_source_and_writes_no_filtered_pdf(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "source.pdf"
            create_pdf(source_pdf, ["ordinary page"])
            source_before = source_pdf.read_bytes()
            image_paths = create_image_placeholders(root / "images", "source", 1)
            filtered_pdf = root / "source.filtered.pdf"

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
                    return_value=OcrResult("ordinary page", 90.0),
                ),
            ):
                with self.assertRaisesRegex(
                    PageFilterError,
                    "No pages satisfied",
                ):
                    process_document(
                        pdf_path=source_pdf,
                        image_dir=root / "images",
                        json_dir=root / "json",
                        base_name="source",
                        filter_terms=("invoice",),
                        filtered_pdf_path=filtered_pdf,
                    )

            self.assertEqual(source_pdf.read_bytes(), source_before)
            self.assertFalse(filtered_pdf.exists())
            self.assertFalse((root / "json").exists())


class WebUserPersonaTests(unittest.IsolatedAsyncioTestCase):
    """P-05/P-07: Browser users need clear validation and cleanup."""

    async def test_rejects_missing_and_non_pdf_uploads(self) -> None:
        with self.assertRaises(HTTPException) as missing:
            await web_app.process_pdfs(files=None)
        self.assertEqual(missing.exception.status_code, 400)

        upload = AsyncUpload("notes.txt", b"not a pdf")
        with self.assertRaises(HTTPException) as invalid:
            await web_app.process_pdfs(files=[upload])  # type: ignore[list-item]
        self.assertEqual(invalid.exception.status_code, 400)
        self.assertIn("Only PDF files", str(invalid.exception.detail))
        self.assertTrue(upload.closed)

        invalid_mode_upload = AsyncUpload("document.pdf", b"pdf")
        with self.assertRaises(HTTPException) as invalid_mode:
            await web_app.process_pdfs(  # type: ignore[list-item]
                files=[invalid_mode_upload],
                filter_mode="unsupported",
            )
        self.assertEqual(invalid_mode.exception.status_code, 400)
        self.assertTrue(invalid_mode_upload.closed)

    async def test_rejects_excessive_uploads_and_filter_terms(self) -> None:
        uploads = [
            AsyncUpload(f"document-{index}.pdf", b"pdf")
            for index in range(web_app.MAX_UPLOAD_FILES + 1)
        ]
        with self.assertRaises(HTTPException) as excessive_files:
            await web_app.process_pdfs(files=uploads)  # type: ignore[list-item]
        self.assertEqual(excessive_files.exception.status_code, 400)
        self.assertTrue(all(upload.closed for upload in uploads))

        upload = AsyncUpload("document.pdf", b"pdf")
        terms = ",".join(
            f"term-{index}"
            for index in range(web_app.MAX_FILTER_TERMS + 1)
        )
        with self.assertRaises(HTTPException) as excessive_terms:
            await web_app.process_pdfs(  # type: ignore[list-item]
                files=[upload],
                filter_words=terms,
            )
        self.assertEqual(excessive_terms.exception.status_code, 400)
        self.assertTrue(upload.closed)

    async def test_rejects_duplicate_processing_job_id(self) -> None:
        progress_store = web_app.ProgressStore()
        self.assertTrue(progress_store.start("duplicate-job"))
        upload = AsyncUpload("document.pdf", b"pdf")
        with (
            patch.object(web_app, "PROGRESS_STORE", progress_store),
            self.assertRaises(HTTPException) as duplicate,
        ):
            await web_app.process_pdfs(  # type: ignore[list-item]
                files=[upload],
                job_id="duplicate-job",
            )
        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertTrue(upload.closed)

    async def test_reports_processing_progress(self) -> None:
        progress_store = web_app.ProgressStore()
        progress_store.start("persona-job")
        progress_store.update("persona-job", 50, "Running OCR")
        with patch.object(web_app, "PROGRESS_STORE", progress_store):
            response = await web_app.processing_progress("persona-job")

        self.assertEqual(response["status"], "processing")
        self.assertEqual(response["percent"], 50.0)
        self.assertEqual(response["message"], "Running OCR")

    async def test_empty_pdf_failure_leaves_no_partial_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "uploads"
            image_dir = root / "images"
            json_dir = root / "json"
            pdf_dir = root / "pdfs"
            for path in (upload_dir, image_dir, json_dir, pdf_dir):
                path.mkdir()

            upload = AsyncUpload("empty.pdf", b"")
            with (
                patch.object(web_app, "UPLOAD_DIR", upload_dir),
                patch.object(web_app, "IMAGE_DIR", image_dir),
                patch.object(web_app, "JSON_DIR", json_dir),
                patch.object(web_app, "PDF_DIR", pdf_dir),
            ):
                response = await web_app.process_pdfs(  # type: ignore[list-item]
                    files=[upload]
                )

            result = response["results"][0]
            self.assertEqual(result["status"], "failed")
            self.assertIn("empty", str(result["error"]).lower())
            self.assertEqual(list(upload_dir.iterdir()), [])
            self.assertEqual(list(image_dir.iterdir()), [])
            self.assertEqual(list(json_dir.iterdir()), [])
            self.assertEqual(list(pdf_dir.iterdir()), [])
            progress = web_app.PROGRESS_STORE.get(str(response["job_id"]))
            self.assertEqual(progress["status"], "failed")

    async def test_corrects_ocr_text_and_refreshes_searchable_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "uploads"
            json_dir = root / "json"
            pdf_dir = root / "pdfs"
            zip_dir = root / "zips"
            for path in (upload_dir, json_dir, pdf_dir, zip_dir):
                path.mkdir()

            source_pdf = upload_dir / "document.pdf"
            create_pdf(source_pdf, [""])
            verified_json = json_dir / "document.verified.json"
            verified_json.write_text(
                json.dumps(
                    {
                        "verification": {"review_required_pages": 1},
                        "pages": [
                            {
                                "page_number": 1,
                                "text": "wrong text",
                                "review_required": True,
                                "review_reasons": ["low_ocr_confidence"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            async def run_immediately(
                function: object,
                *args: object,
                **kwargs: object,
            ) -> object:
                return function(*args, **kwargs)  # type: ignore[operator]

            with (
                patch.object(web_app, "UPLOAD_DIR", upload_dir),
                patch.object(web_app, "JSON_DIR", json_dir),
                patch.object(web_app, "PDF_DIR", pdf_dir),
                patch.object(web_app, "ZIP_DIR", zip_dir),
                patch.object(
                    web_app,
                    "run_in_threadpool",
                    new=run_immediately,
                ),
            ):
                response = await web_app.correct_ocr(
                    "document.verified.json",
                    web_app.OcrCorrectionRequest(
                        pages=[
                            web_app.OcrPageCorrectionRequest(
                                page_number=1,
                                text="corrected searchable text",
                            )
                        ]
                    ),
                )

            self.assertEqual(response["status"], "completed")
            self.assertEqual(response["review_required_pages"], 0)
            searchable = fitz.open(pdf_dir / "document.searchable.pdf")
            self.assertTrue(
                searchable[0].search_for("corrected searchable text")
            )
            searchable.close()
            self.assertTrue((zip_dir / "document.results.zip").is_file())

    def test_zip_failure_rolls_back_ocr_correction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_pdf = root / "document.pdf"
            verified_json = root / "document.verified.json"
            searchable_pdf = root / "document.searchable.pdf"
            zip_dir = root / "zips"
            zip_dir.mkdir()
            result_zip = zip_dir / "document.results.zip"
            create_pdf(source_pdf, [""])
            verified_json.write_text(
                json.dumps(
                    {
                        "verification": {"review_required_pages": 1},
                        "pages": [
                            {
                                "page_number": 1,
                                "text": "old text",
                                "review_required": True,
                                "review_reasons": ["low_ocr_confidence"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            searchable_pdf.write_bytes(b"old searchable")
            result_zip.write_bytes(b"old zip")
            original_json = verified_json.read_bytes()

            with (
                patch.object(web_app, "ZIP_DIR", zip_dir),
                patch.object(
                    web_app,
                    "refresh_result_bundle",
                    side_effect=OSError("zip disk full"),
                ),
                self.assertRaisesRegex(OSError, "zip disk full"),
            ):
                web_app.correct_document_outputs(
                    "document",
                    verified_json,
                    source_pdf,
                    searchable_pdf,
                    [web_app.PageCorrection(1, "new text")],
                )

            self.assertEqual(verified_json.read_bytes(), original_json)
            self.assertEqual(searchable_pdf.read_bytes(), b"old searchable")
            self.assertEqual(result_zip.read_bytes(), b"old zip")


if __name__ == "__main__":
    unittest.main()
