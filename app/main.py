from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.services.json_writer import write_ocr_result
from app.services.ocr_service import extract_text
from app.services.pdf_converter import PdfConversionError, convert_pdf_to_png

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
IMAGE_DIR = BASE_DIR / "outputs" / "images"
JSON_DIR = BASE_DIR / "outputs" / "json"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

for directory in (UPLOAD_DIR, IMAGE_DIR, JSON_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="PDF to PNG OCR", version="1.0.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "app" / "templates")


def safe_stem(filename: str) -> str:
    """Return a filesystem-safe base name while preserving Unicode letters."""
    stem = Path(filename).stem.strip()
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE)
    stem = stem.strip("._")
    return stem[:120] or "document"


def unique_base_name(filename: str) -> str:
    base = safe_stem(filename)
    occupied = (
        (UPLOAD_DIR / f"{base}.pdf").exists()
        or (JSON_DIR / f"{base}.json").exists()
        or any(IMAGE_DIR.glob(f"{base}(?*"))
    )
    if not occupied:
        return base
    return f"{base}_{uuid4().hex[:8]}"


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
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are allowed: {', '.join(invalid)}",
        )

    results: list[dict[str, object]] = []
    for upload in files:
        original_name = Path(upload.filename or "document.pdf").name
        base_name = unique_base_name(original_name)
        saved_pdf = UPLOAD_DIR / f"{base_name}.pdf"
        image_paths: list[Path] = []

        try:
            await save_upload(upload, saved_pdf)
            image_paths = convert_pdf_to_png(saved_pdf, IMAGE_DIR, base_name)

            pages: list[dict[str, object]] = []
            warnings: list[str] = []
            for page_number, image_path in enumerate(image_paths, start=1):
                try:
                    text = extract_text(image_path)
                except Exception as exc:
                    text = ""
                    message = f"Page {page_number}: OCR failed ({exc})"
                    warnings.append(message)

                pages.append(
                    {
                        "page_number": page_number,
                        "image_file": image_path.name,
                        "text": text,
                    }
                )

            payload = {
                "source_pdf": original_name,
                "total_pages": len(pages),
                "pages": pages,
            }
            json_path = write_ocr_result(payload, JSON_DIR / f"{base_name}.json")
            results.append(
                {
                    "source_pdf": original_name,
                    "saved_pdf": saved_pdf.name,
                    "total_pages": len(pages),
                    "images": [
                        {
                            "filename": path.name,
                            "download_url": f"/download/image/{path.name}",
                        }
                        for path in image_paths
                    ],
                    "json_file": json_path.name,
                    "json_download_url": f"/download/json/{json_path.name}",
                    "warnings": warnings,
                }
            )
        except HTTPException:
            for image_path in image_paths:
                image_path.unlink(missing_ok=True)
            raise
        except PdfConversionError as exc:
            saved_pdf.unlink(missing_ok=True)
            raise HTTPException(
                status_code=422,
                detail=f"Could not convert {original_name}: {exc}",
            ) from exc
        except Exception as exc:
            for image_path in image_paths:
                image_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=500,
                detail=f"Could not process {original_name}: {exc}",
            ) from exc

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
