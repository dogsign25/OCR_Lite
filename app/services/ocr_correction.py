from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.artifact_transaction import (
    StagedArtifact,
    commit_staged_artifacts,
    staging_path,
)
from app.services.json_writer import write_ocr_result
from app.services.searchable_pdf import SearchablePage, write_searchable_pdf


class OcrCorrectionError(RuntimeError):
    """Raised when verified OCR text cannot be corrected."""


@dataclass(frozen=True)
class PageCorrection:
    page_number: int
    text: str


def _validated_pages(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    pages = payload.get("pages")
    if not isinstance(pages, list):
        raise OcrCorrectionError("The verified OCR JSON is invalid.")

    page_map: dict[int, dict[str, Any]] = {}
    validated: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            raise OcrCorrectionError("The verified OCR JSON is invalid.")
        page_number = page.get("page_number")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number < 1
            or page_number in page_map
        ):
            raise OcrCorrectionError(
                "Verified OCR page numbers must be unique positive integers."
            )
        page_map[page_number] = page
        validated.append(page)
    return validated, page_map


def apply_ocr_corrections(
    verified_json: Path,
    source_pdf: Path,
    searchable_pdf: Path,
    corrections: Iterable[PageCorrection],
) -> dict[str, Any]:
    requested = list(corrections)
    page_numbers = [correction.page_number for correction in requested]
    if not requested:
        raise OcrCorrectionError("At least one page correction is required.")
    if len(page_numbers) != len(set(page_numbers)):
        raise OcrCorrectionError("Each page can only be corrected once per request.")

    try:
        payload = json.loads(verified_json.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("payload must be an object")
        pages, pages_by_number = _validated_pages(payload)
    except OcrCorrectionError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise OcrCorrectionError("The verified OCR JSON is invalid.") from exc

    unknown_pages = sorted(set(page_numbers) - set(pages_by_number))
    if unknown_pages:
        joined = ", ".join(str(number) for number in unknown_pages)
        raise OcrCorrectionError(f"Unknown OCR page number(s): {joined}")

    corrected_at = datetime.now(timezone.utc).isoformat()
    for correction in requested:
        page = pages_by_number[correction.page_number]
        if "original_ocr_text" not in page:
            page["original_ocr_text"] = str(page.get("text", ""))
        page["text"] = correction.text
        page["manually_corrected"] = True
        page["corrected_at"] = corrected_at
        page["review_required"] = False
        page["review_reasons"] = []

    verification = payload.setdefault("verification", {})
    if not isinstance(verification, dict):
        raise OcrCorrectionError("The verified OCR verification data is invalid.")
    verification["review_required_pages"] = sum(
        bool(page.get("review_required"))
        for page in pages
        if isinstance(page, dict)
    )
    payload["manual_correction"] = {
        "last_updated_at": corrected_at,
        "corrected_pages": sorted(
            int(page["page_number"])
            for page in pages
            if isinstance(page, dict) and page.get("manually_corrected")
        ),
    }

    staged_pdf = staging_path(searchable_pdf)
    staged_json = staging_path(verified_json)
    try:
        write_searchable_pdf(
            source_pdf,
            staged_pdf,
            (
                SearchablePage(
                    page_number=page["page_number"],
                    text=str(page.get("text", "")),
                    rotation=int(page.get("rotation", 0)),
                )
                for page in pages
            ),
        )
        write_ocr_result(payload, staged_json)
        commit_staged_artifacts(
            [
                StagedArtifact(staged_pdf, searchable_pdf),
                StagedArtifact(staged_json, verified_json),
            ]
        )
    except OcrCorrectionError:
        raise
    except Exception as exc:
        raise OcrCorrectionError(
            "OCR corrections could not be saved without changing existing outputs."
        ) from exc
    finally:
        staged_pdf.unlink(missing_ok=True)
        staged_json.unlink(missing_ok=True)
    return payload
