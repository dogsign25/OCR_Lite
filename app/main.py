from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.artifact_transaction import preserve_artifacts
from app.services.document_processor import process_document
from app.services.document_locks import DocumentLockStore
from app.services.naming import safe_stem
from app.services.ocr_correction import (
    OcrCorrectionError,
    PageCorrection,
    apply_ocr_corrections,
)
from app.services.page_editor import PageEdit, PageEditError, apply_page_edits
from app.services.page_filter import (
    parse_filter_terms,
    validate_filter_match_mode,
)
from app.services.pdf_converter import PdfConversionError
from app.services.progress_tracker import ProgressStore
from app.services.result_bundle import BundleFile, write_result_bundle

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
IMAGE_DIR = BASE_DIR / "outputs" / "images"
JSON_DIR = BASE_DIR / "outputs" / "json"
PDF_DIR = BASE_DIR / "outputs" / "pdfs"
ZIP_DIR = BASE_DIR / "outputs" / "zips"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_FILES = 20
MAX_FILTER_INPUT_CHARS = 10_000
MAX_FILTER_TERMS = 100
MAX_CORRECTION_TOTAL_CHARS = 5_000_000
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "kor+eng")
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
PROGRESS_STORE = ProgressStore()
DOCUMENT_LOCKS = DocumentLockStore()
logger = logging.getLogger(__name__)

for directory in (UPLOAD_DIR, IMAGE_DIR, JSON_DIR, PDF_DIR, ZIP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PDF to PNG OCR", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


class OcrPageCorrectionRequest(BaseModel):
    page_number: int = Field(ge=1)
    text: str = Field(max_length=1_000_000)


class OcrCorrectionRequest(BaseModel):
    pages: list[OcrPageCorrectionRequest] = Field(min_length=1, max_length=500)


class PageEditRequest(BaseModel):
    page_number: int = Field(ge=1)
    rotation: Literal[0, 90, 180, 270] = 0


class PageLayoutRequest(BaseModel):
    pages: list[PageEditRequest] = Field(min_length=1, max_length=500)


def json_outputs_for(base_name: str) -> list[Path]:
    return [
        *sorted(JSON_DIR.glob(f"{base_name}.candidate-*.json")),
        JSON_DIR / f"{base_name}.verified.json",
    ]


def pdf_outputs_for(base_name: str) -> list[Path]:
    return [
        PDF_DIR / f"{base_name}.filtered.pdf",
        PDF_DIR / f"{base_name}.edited.pdf",
        PDF_DIR / f"{base_name}.searchable.pdf",
    ]


def reserve_upload(filename: str) -> tuple[str, Path]:
    base = safe_stem(filename)
    while True:
        occupied_outputs = any(
            path.is_file()
            for path in [
                *json_outputs_for(base),
                *pdf_outputs_for(base),
                ZIP_DIR / f"{base}.results.zip",
            ]
        ) or any(
            IMAGE_DIR.glob(f"{base}(?*")
        )
        candidate = f"{base}_{uuid4().hex[:8]}" if occupied_outputs else base
        destination = UPLOAD_DIR / f"{candidate}.pdf"
        try:
            destination.touch(exist_ok=False)
        except FileExistsError:
            base = f"{safe_stem(filename)}_{uuid4().hex[:8]}"
            continue
        return candidate, destination


def cleanup_web_outputs(base_name: str) -> None:
    for path in IMAGE_DIR.glob(f"{base_name}(*)"):
        path.unlink(missing_ok=True)
    for path in json_outputs_for(base_name):
        path.unlink(missing_ok=True)
    for path in pdf_outputs_for(base_name):
        path.unlink(missing_ok=True)
    (ZIP_DIR / f"{base_name}.results.zip").unlink(missing_ok=True)


def refresh_result_bundle(base_name: str) -> Path:
    files = [
        *(
            BundleFile(path, "json")
            for path in json_outputs_for(base_name)
        ),
        *(
            BundleFile(path, "images")
            for path in sorted(IMAGE_DIR.glob(f"{base_name}(*)"))
        ),
        *(
            BundleFile(path, "pdf")
            for path in pdf_outputs_for(base_name)
        ),
    ]
    return write_result_bundle(ZIP_DIR / f"{base_name}.results.zip", files)


def correct_document_outputs(
    base_name: str,
    verified_json: Path,
    source_pdf: Path,
    searchable_pdf: Path,
    corrections: list[PageCorrection],
) -> tuple[dict[str, object], Path]:
    with DOCUMENT_LOCKS.hold(base_name):
        result_zip = ZIP_DIR / f"{base_name}.results.zip"
        with preserve_artifacts([verified_json, searchable_pdf, result_zip]):
            payload = apply_ocr_corrections(
                verified_json=verified_json,
                source_pdf=source_pdf,
                searchable_pdf=searchable_pdf,
                corrections=corrections,
            )
            return payload, refresh_result_bundle(base_name)


def edit_document_outputs(
    base_name: str,
    verified_json: Path,
    source_pdf: Path,
    candidate_jsons: list[Path],
    edited_pdf: Path,
    searchable_pdf: Path,
    page_edits: list[PageEdit],
) -> tuple[dict[str, object], Path]:
    with DOCUMENT_LOCKS.hold(base_name):
        result_zip = ZIP_DIR / f"{base_name}.results.zip"
        with preserve_artifacts(
            [
                verified_json,
                *candidate_jsons,
                edited_pdf,
                searchable_pdf,
                result_zip,
            ]
        ):
            payload = apply_page_edits(
                source_pdf=source_pdf,
                verified_json=verified_json,
                candidate_jsons=candidate_jsons,
                edited_pdf=edited_pdf,
                searchable_pdf=searchable_pdf,
                page_edits=page_edits,
            )
            return payload, refresh_result_bundle(base_name)


async def save_upload(upload: UploadFile, destination: Path) -> None:
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{upload.filename} exceeds the 50 MB upload limit.",
                    )
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"{upload.filename} is empty.")


def is_pdf(upload: UploadFile) -> bool:
    filename = upload.filename or ""
    return Path(filename).suffix.lower() == ".pdf"


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/api/process")
async def process_pdfs(
    files: Annotated[list[UploadFile] | None, File()] = None,
    filter_words: Annotated[str, Form()] = "",
    filter_mode: Annotated[str, Form()] = "any",
    exclude_words: Annotated[str, Form()] = "",
    job_id: Annotated[str, Form()] = "",
) -> dict[str, object]:
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one PDF file.")
    if len(files) > MAX_UPLOAD_FILES:
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=400,
            detail=f"Upload at most {MAX_UPLOAD_FILES} PDF files at once.",
        )
    if (
        len(filter_words) > MAX_FILTER_INPUT_CHARS
        or len(exclude_words) > MAX_FILTER_INPUT_CHARS
    ):
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=400,
            detail="Filter input is too long.",
        )

    try:
        active_filter_mode = validate_filter_match_mode(filter_mode)
    except ValueError as exc:
        for upload in files:
            await upload.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    invalid = [upload.filename or "unnamed file" for upload in files if not is_pdf(upload)]
    if invalid:
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are allowed: {', '.join(invalid)}",
        )

    active_job_id = job_id or uuid4().hex
    if not JOB_ID_PATTERN.fullmatch(active_job_id):
        for upload in files:
            await upload.close()
        raise HTTPException(status_code=400, detail="Invalid processing job ID.")

    filter_terms = parse_filter_terms(filter_words)
    exclude_terms = parse_filter_terms(exclude_words)
    if len(filter_terms) + len(exclude_terms) > MAX_FILTER_TERMS:
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=400,
            detail=f"Register at most {MAX_FILTER_TERMS} filter terms.",
        )
    if not PROGRESS_STORE.start(active_job_id):
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=409,
            detail="The processing job ID is already in use.",
        )

    results: list[dict[str, object]] = []
    for file_index, upload in enumerate(files):
        original_name = Path(upload.filename or "document.pdf").name
        base_name = ""
        saved_pdf: Path | None = None

        try:
            base_name, saved_pdf = reserve_upload(original_name)
            PROGRESS_STORE.update(
                active_job_id,
                (file_index / len(files)) * 100,
                f"Uploading {original_name}.",
            )
            await save_upload(upload, saved_pdf)

            def report_document_progress(fraction: float, message: str) -> None:
                overall_percent = (
                    (file_index + max(0.0, min(1.0, fraction))) / len(files)
                ) * 100
                PROGRESS_STORE.update(
                    active_job_id,
                    overall_percent,
                    f"{original_name}: {message}",
                )

            processed = await run_in_threadpool(
                process_document,
                pdf_path=saved_pdf,
                image_dir=IMAGE_DIR,
                json_dir=JSON_DIR,
                base_name=base_name,
                source_name=original_name,
                ocr_language=OCR_LANGUAGE,
                filter_terms=filter_terms,
                filter_match_mode=active_filter_mode,
                exclude_terms=exclude_terms,
                filtered_pdf_path=PDF_DIR / f"{base_name}.filtered.pdf",
                searchable_pdf_path=PDF_DIR / f"{base_name}.searchable.pdf",
                progress_callback=report_document_progress,
            )
            result_zip = await run_in_threadpool(refresh_result_bundle, base_name)
            verified_payload = json.loads(
                processed.verified_json.read_text(encoding="utf-8")
            )
            json_outputs = [
                {
                    "kind": output.kind,
                    "label": output.label,
                    "filename": output.path.name,
                    "download_url": f"/download/json/{output.path.name}",
                }
                for output in processed.json_outputs
            ]
            results.append(
                {
                    "status": "completed",
                    "source_pdf": original_name,
                    "saved_pdf": saved_pdf.name,
                    "total_pages": processed.total_pages,
                    "source_total_pages": processed.source_total_pages,
                    "images": [
                        {
                            "filename": path.name,
                            "download_url": f"/download/image/{path.name}",
                        }
                        for path in processed.image_paths
                    ],
                    "json_file": processed.verified_json.name,
                    "json_download_url": (
                        f"/download/json/{processed.verified_json.name}"
                    ),
                    "json_files": json_outputs,
                    "warnings": processed.warnings,
                    "review_required_pages": processed.review_required_pages,
                    "filter_terms": list(filter_terms),
                    "filter_mode": active_filter_mode,
                    "exclude_terms": list(exclude_terms),
                    "ocr_pages": verified_payload["pages"],
                    "filtered_pdf": (
                        {
                            "filename": processed.filtered_pdf.name,
                            "download_url": (
                                f"/download/pdf/{processed.filtered_pdf.name}"
                            ),
                        }
                        if processed.filtered_pdf
                        else None
                    ),
                    "searchable_pdf": {
                        "filename": processed.searchable_pdf.name,
                        "download_url": (
                            f"/download/pdf/{processed.searchable_pdf.name}"
                        ),
                    },
                    "result_zip": {
                        "filename": result_zip.name,
                        "download_url": f"/download/zip/{result_zip.name}",
                    },
                }
            )
        except HTTPException as exc:
            if base_name:
                cleanup_web_outputs(base_name)
            if saved_pdf is not None:
                saved_pdf.unlink(missing_ok=True)
            results.append(
                {
                    "status": "failed",
                    "source_pdf": original_name,
                    "error": str(exc.detail),
                }
            )
        except PdfConversionError as exc:
            if base_name:
                cleanup_web_outputs(base_name)
            if saved_pdf is not None:
                saved_pdf.unlink(missing_ok=True)
            results.append(
                {
                    "status": "failed",
                    "source_pdf": original_name,
                    "error": f"Could not convert {original_name}: {exc}",
                }
            )
        except Exception as exc:
            if base_name:
                cleanup_web_outputs(base_name)
            if saved_pdf is not None:
                saved_pdf.unlink(missing_ok=True)
            logger.exception("Unexpected processing failure for %s", original_name)
            results.append(
                {
                    "status": "failed",
                    "source_pdf": original_name,
                    "error": (
                        f"Could not process {original_name}: "
                        "an unexpected processing error occurred."
                    ),
                }
            )
        finally:
            await upload.close()
            PROGRESS_STORE.update(
                active_job_id,
                ((file_index + 1) / len(files)) * 100,
                f"Finished {original_name}.",
            )

    failed_count = sum(result["status"] == "failed" for result in results)
    if failed_count == len(results):
        PROGRESS_STORE.fail(active_job_id, "All files failed to process.")
    elif failed_count:
        PROGRESS_STORE.finish(
            active_job_id,
            f"Finished with {failed_count} failed file(s).",
        )
    else:
        PROGRESS_STORE.finish(active_job_id)
    return {"job_id": active_job_id, "results": results}


@app.patch("/api/ocr/{filename}")
async def correct_ocr(
    filename: str,
    correction: OcrCorrectionRequest,
) -> dict[str, object]:
    if not filename.endswith(".verified.json"):
        raise HTTPException(
            status_code=400,
            detail="Only verified OCR JSON files can be corrected.",
        )

    verified_json = file_from_directory(JSON_DIR, filename)
    base_name = filename.removesuffix(".verified.json")
    source_pdf = file_from_directory(UPLOAD_DIR, f"{base_name}.pdf")
    searchable_pdf = PDF_DIR / f"{base_name}.searchable.pdf"
    if sum(len(page.text) for page in correction.pages) > MAX_CORRECTION_TOTAL_CHARS:
        raise HTTPException(
            status_code=400,
            detail="The total OCR correction text is too large.",
        )

    try:
        payload, result_zip = await run_in_threadpool(
            correct_document_outputs,
            base_name=base_name,
            verified_json=verified_json,
            source_pdf=source_pdf,
            searchable_pdf=searchable_pdf,
            corrections=[
                PageCorrection(page.page_number, page.text)
                for page in correction.pages
            ],
        )
    except OcrCorrectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    verification = payload.get("verification", {})
    review_required_pages = (
        verification.get("review_required_pages", 0)
        if isinstance(verification, dict)
        else 0
    )
    return {
        "status": "completed",
        "pages": payload["pages"],
        "review_required_pages": review_required_pages,
        "searchable_pdf": {
            "filename": searchable_pdf.name,
            "download_url": f"/download/pdf/{searchable_pdf.name}",
        },
        "result_zip": {
            "filename": result_zip.name,
            "download_url": f"/download/zip/{result_zip.name}",
        },
    }


@app.patch("/api/pages/{filename}")
async def edit_page_layout(
    filename: str,
    layout: PageLayoutRequest,
) -> dict[str, object]:
    if not filename.endswith(".verified.json"):
        raise HTTPException(
            status_code=400,
            detail="Only verified OCR JSON files can be edited.",
        )

    verified_json = file_from_directory(JSON_DIR, filename)
    base_name = filename.removesuffix(".verified.json")
    source_pdf = file_from_directory(UPLOAD_DIR, f"{base_name}.pdf")
    candidate_jsons = sorted(JSON_DIR.glob(f"{base_name}.candidate-*.json"))
    if not candidate_jsons:
        raise HTTPException(
            status_code=409,
            detail="Candidate OCR JSON files are missing.",
        )
    edited_pdf = PDF_DIR / f"{base_name}.edited.pdf"
    searchable_pdf = PDF_DIR / f"{base_name}.searchable.pdf"

    try:
        payload, result_zip = await run_in_threadpool(
            edit_document_outputs,
            base_name=base_name,
            source_pdf=source_pdf,
            verified_json=verified_json,
            candidate_jsons=candidate_jsons,
            edited_pdf=edited_pdf,
            searchable_pdf=searchable_pdf,
            page_edits=[
                PageEdit(page.page_number, page.rotation)
                for page in layout.pages
            ],
        )
    except PageEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "completed",
        "pages": payload["pages"],
        "edited_pdf": {
            "filename": edited_pdf.name,
            "download_url": f"/download/pdf/{edited_pdf.name}",
        },
        "searchable_pdf": {
            "filename": searchable_pdf.name,
            "download_url": f"/download/pdf/{searchable_pdf.name}",
        },
        "result_zip": {
            "filename": result_zip.name,
            "download_url": f"/download/zip/{result_zip.name}",
        },
    }


def file_from_directory(directory: Path, filename: str) -> Path:
    candidate = (directory / filename).resolve()
    if candidate.parent != directory.resolve() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return candidate


@app.get("/api/progress/{job_id}")
async def processing_progress(job_id: str) -> dict[str, object]:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Processing job not found.")
    progress = PROGRESS_STORE.get(job_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Processing job not found.")
    return progress


@app.get("/download/json/{filename}")
async def download_json(filename: str):
    path = file_from_directory(JSON_DIR, filename)
    return FileResponse(
        path,
        media_type="application/json",
        filename=path.name,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/download/image/{filename}")
async def download_image(filename: str):
    path = file_from_directory(IMAGE_DIR, filename)
    return FileResponse(
        path,
        media_type="image/png",
        filename=path.name,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/download/pdf/{filename}")
async def download_pdf(filename: str):
    path = file_from_directory(PDF_DIR, filename)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/download/zip/{filename}")
async def download_zip(filename: str):
    path = file_from_directory(ZIP_DIR, filename)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
