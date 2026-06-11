from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.services.document_processor import process_document
from app.services.naming import safe_stem
from app.services.pdf_converter import PdfConversionError

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
IMAGE_DIR = BASE_DIR / "outputs" / "images"
JSON_DIR = BASE_DIR / "outputs" / "json"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "kor+eng")

for directory in (UPLOAD_DIR, IMAGE_DIR, JSON_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PDF to PNG OCR", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def reserve_upload(filename: str) -> tuple[str, Path]:
    base = safe_stem(filename)
    while True:
        occupied_outputs = any(JSON_DIR.glob(f"{base}*.json")) or any(
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
    for path in JSON_DIR.glob(f"{base_name}*.json"):
        path.unlink(missing_ok=True)


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
) -> dict[str, object]:
    if not files:
        raise HTTPException(status_code=400, detail="Select at least one PDF file.")

    invalid = [upload.filename or "unnamed file" for upload in files if not is_pdf(upload)]
    if invalid:
        for upload in files:
            await upload.close()
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are allowed: {', '.join(invalid)}",
        )

    results: list[dict[str, object]] = []
    for upload in files:
        original_name = Path(upload.filename or "document.pdf").name
        base_name, saved_pdf = reserve_upload(original_name)

        try:
            await save_upload(upload, saved_pdf)
            processed = await run_in_threadpool(
                process_document,
                pdf_path=saved_pdf,
                image_dir=IMAGE_DIR,
                json_dir=JSON_DIR,
                base_name=base_name,
                source_name=original_name,
                ocr_language=OCR_LANGUAGE,
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
                }
            )
        except HTTPException as exc:
            cleanup_web_outputs(base_name)
            saved_pdf.unlink(missing_ok=True)
            results.append(
                {
                    "status": "failed",
                    "source_pdf": original_name,
                    "error": str(exc.detail),
                }
            )
        except PdfConversionError as exc:
            cleanup_web_outputs(base_name)
            saved_pdf.unlink(missing_ok=True)
            results.append(
                {
                    "status": "failed",
                    "source_pdf": original_name,
                    "error": f"Could not convert {original_name}: {exc}",
                }
            )
        except Exception as exc:
            cleanup_web_outputs(base_name)
            saved_pdf.unlink(missing_ok=True)
            results.append(
                {
                    "status": "failed",
                    "source_pdf": original_name,
                    "error": f"Could not process {original_name}: {exc}",
                }
            )

    return {"results": results}


def file_from_directory(directory: Path, filename: str) -> Path:
    candidate = (directory / filename).resolve()
    if candidate.parent != directory.resolve() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    return candidate


@app.get("/download/json/{filename}")
async def download_json(filename: str):
    path = file_from_directory(JSON_DIR, filename)
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/download/image/{filename}")
async def download_image(filename: str):
    path = file_from_directory(IMAGE_DIR, filename)
    return FileResponse(path, media_type="image/png", filename=path.name)
