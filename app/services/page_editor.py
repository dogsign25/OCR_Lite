from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

from app.services.artifact_transaction import (
    StagedArtifact,
    commit_staged_artifacts,
    staging_path,
)
from app.services.json_writer import write_ocr_result
from app.services.searchable_pdf import SearchablePage, write_searchable_pdf


class PageEditError(RuntimeError):
    """Raised when page order or rotation cannot be applied."""


@dataclass(frozen=True)
class PageEdit:
    page_number: int
    rotation: int = 0


def _read_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload["pages"], list):
            raise TypeError("pages must be a list")
        seen: set[int] = set()
        for page in payload["pages"]:
            if not isinstance(page, dict):
                raise TypeError("page must be an object")
            page_number = page.get("page_number")
            if (
                isinstance(page_number, bool)
                or not isinstance(page_number, int)
                or page_number < 1
                or page_number in seen
            ):
                raise TypeError("page numbers must be unique positive integers")
            seen.add(page_number)
        return payload
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise PageEditError(f"Invalid OCR JSON: {path.name}") from exc


def _ordered_pages(
    pages: list[object],
    edits: list[PageEdit],
    filename: str,
) -> list[dict[str, Any]]:
    page_map = {page["page_number"]: page for page in pages}
    edit_numbers = [edit.page_number for edit in edits]
    if set(edit_numbers) != set(page_map):
        raise PageEditError(
            f"Page edits must include every retained page in {filename} exactly once."
        )

    ordered: list[dict[str, Any]] = []
    for output_number, edit in enumerate(edits, start=1):
        page = page_map[edit.page_number]
        page["output_page_number"] = output_number
        page["rotation"] = edit.rotation
        ordered.append(page)
    return ordered


def _write_edited_pdf(
    source_pdf: Path,
    output_pdf: Path,
    edits: list[PageEdit],
) -> Path:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    temporary_pdf = output_pdf.with_name(f".{output_pdf.name}.tmp")
    source: fitz.Document | None = None
    edited: fitz.Document | None = None
    try:
        source = fitz.open(source_pdf)
        edited = fitz.open()
        for edit in edits:
            page_index = edit.page_number - 1
            if page_index < 0 or page_index >= source.page_count:
                raise PageEditError(
                    f"Page {edit.page_number} is outside the source PDF."
                )
            edited.insert_pdf(source, from_page=page_index, to_page=page_index)
            output_page = edited.load_page(edited.page_count - 1)
            output_page.set_rotation((output_page.rotation + edit.rotation) % 360)
        edited.save(temporary_pdf)
        edited.close()
        edited = None
        source.close()
        source = None
        temporary_pdf.replace(output_pdf)
    except PageEditError:
        raise
    except Exception as exc:
        raise PageEditError(str(exc)) from exc
    finally:
        if edited is not None:
            edited.close()
        if source is not None:
            source.close()
        temporary_pdf.unlink(missing_ok=True)
    return output_pdf


def apply_page_edits(
    source_pdf: Path,
    verified_json: Path,
    candidate_jsons: Iterable[Path],
    edited_pdf: Path,
    searchable_pdf: Path,
    page_edits: Iterable[PageEdit],
) -> dict[str, Any]:
    edits = list(page_edits)
    page_numbers = [edit.page_number for edit in edits]
    if not edits:
        raise PageEditError("At least one page edit is required.")
    if len(page_numbers) != len(set(page_numbers)):
        raise PageEditError("Each page can only appear once in the output order.")
    if any(edit.rotation not in (0, 90, 180, 270) for edit in edits):
        raise PageEditError("Page rotation must be 0, 90, 180, or 270.")

    verified_payload = _read_payload(verified_json)
    verification = verified_payload.get("verification")
    if isinstance(verification, dict):
        expected_candidates = verification.get("candidate_count")
        if (
            isinstance(expected_candidates, int)
            and not isinstance(expected_candidates, bool)
            and expected_candidates > 0
        ):
            candidate_jsons = list(candidate_jsons)
            if len(candidate_jsons) != expected_candidates:
                raise PageEditError(
                    "All candidate OCR JSON files are required for page editing."
                )
    verified_payload["pages"] = _ordered_pages(
        verified_payload["pages"],
        edits,
        verified_json.name,
    )
    candidate_payloads = [
        (path, _read_payload(path))
        for path in candidate_jsons
    ]
    for path, payload in candidate_payloads:
        payload["pages"] = _ordered_pages(payload["pages"], edits, path.name)

    staged_edited_pdf = staging_path(edited_pdf)
    staged_searchable_pdf = staging_path(searchable_pdf)
    staged_jsons = [
        (staging_path(path), path, payload)
        for path, payload in candidate_payloads
    ]
    staged_verified_json = staging_path(verified_json)
    try:
        _write_edited_pdf(source_pdf, staged_edited_pdf, edits)
        write_searchable_pdf(
            source_pdf,
            staged_searchable_pdf,
            (
                SearchablePage(
                    page_number=page["page_number"],
                    text=str(page.get("text", "")),
                    rotation=int(page.get("rotation", 0)),
                )
                for page in verified_payload["pages"]
            ),
        )
        for staged, _, payload in staged_jsons:
            write_ocr_result(payload, staged)
        write_ocr_result(verified_payload, staged_verified_json)
        commit_staged_artifacts(
            [
                StagedArtifact(staged_edited_pdf, edited_pdf),
                StagedArtifact(staged_searchable_pdf, searchable_pdf),
                *(
                    StagedArtifact(staged, target)
                    for staged, target, _ in staged_jsons
                ),
                StagedArtifact(staged_verified_json, verified_json),
            ]
        )
    except PageEditError:
        raise
    except Exception as exc:
        raise PageEditError(
            "Page edits could not be saved without changing existing outputs."
        ) from exc
    finally:
        staged_edited_pdf.unlink(missing_ok=True)
        staged_searchable_pdf.unlink(missing_ok=True)
        staged_verified_json.unlink(missing_ok=True)
        for staged, _, _ in staged_jsons:
            staged.unlink(missing_ok=True)
    return verified_payload
