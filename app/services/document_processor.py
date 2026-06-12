from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.services.json_writer import write_ocr_result
from app.services.ocr_service import (
    OCR_PROFILES,
    OcrResult,
    extract_ocr_result,
    validate_ocr_language,
)
from app.services.ocr_verifier import select_verified_result
from app.services.page_filter import (
    evaluate_page_filter,
    normalize_filter_terms,
    validate_filter_match_mode,
    write_filtered_pdf,
)
from app.services.pdf_converter import convert_pdf_to_png
from app.services.searchable_pdf import SearchablePage, write_searchable_pdf

PIPELINE_VERSION = "7"
ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class JsonOutput:
    kind: str
    label: str
    path: Path


@dataclass(frozen=True)
class ProcessedDocument:
    source_pdf: str
    image_paths: list[Path]
    json_outputs: list[JsonOutput]
    warnings: list[str]
    review_required_pages: int
    source_total_pages: int
    filtered_pdf: Path | None = None
    searchable_pdf: Path | None = None

    @property
    def total_pages(self) -> int:
        return len(self.image_paths)

    @property
    def verified_json(self) -> Path:
        return self.json_outputs[0].path


def process_document(
    pdf_path: Path,
    image_dir: Path,
    json_dir: Path,
    base_name: str,
    source_name: str | None = None,
    ocr_language: str = "kor+eng",
    filter_terms: tuple[str, ...] = (),
    filter_match_mode: str = "any",
    exclude_terms: tuple[str, ...] = (),
    filtered_pdf_path: Path | None = None,
    searchable_pdf_path: Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProcessedDocument:
    """Convert one PDF and create three OCR candidates plus a verified result."""
    validate_ocr_language(ocr_language)
    source_pdf = source_name or pdf_path.name
    active_filter_terms = normalize_filter_terms(filter_terms)
    active_exclude_terms = normalize_filter_terms(exclude_terms)
    active_match_mode = validate_filter_match_mode(filter_match_mode)
    filter_enabled = bool(active_filter_terms or active_exclude_terms)
    image_paths = convert_pdf_to_png(pdf_path, image_dir, base_name)
    if progress_callback:
        progress_callback(0.05, "PDF pages converted to images.")
    source_total_pages = len(image_paths)
    warnings: list[str] = []
    candidate_pages: dict[str, list[dict[str, object]]] = {
        profile.name: [] for profile in OCR_PROFILES
    }
    verified_pages: list[dict[str, object]] = []
    completed_ocr_runs = 0
    total_ocr_runs = max(1, source_total_pages * len(OCR_PROFILES))

    for page_number, image_path in enumerate(image_paths, start=1):
        page_candidates: dict[str, OcrResult] = {}
        successful_profiles = 0
        for profile in OCR_PROFILES:
            try:
                ocr_result = extract_ocr_result(
                    image_path,
                    profile=profile,
                    language=ocr_language,
                )
                successful_profiles += 1
            except Exception as exc:
                ocr_result = OcrResult(text="", confidence=0.0)
                warnings.append(
                    f"Page {page_number}, {profile.name}: OCR failed ({exc})"
                )

            page_candidates[profile.name] = ocr_result
            candidate_pages[profile.name].append(
                {
                    "page_number": page_number,
                    "output_page_number": page_number,
                    "rotation": 0,
                    "image_file": image_path.name,
                    "text": ocr_result.text,
                    "confidence": ocr_result.confidence,
                }
            )
            completed_ocr_runs += 1
            if progress_callback:
                progress_callback(
                    0.05 + (0.75 * completed_ocr_runs / total_ocr_runs),
                    (
                        f"Running OCR on page {page_number}/{source_total_pages} "
                        f"with {profile.name}."
                    ),
                )

        if successful_profiles == 0:
            raise RuntimeError(
                f"All OCR profiles failed for page {page_number}. "
                "No verified result was written."
            )

        verified = select_verified_result(page_candidates)
        filter_decision = evaluate_page_filter(
            (result.text for result in page_candidates.values()),
            filter_terms=active_filter_terms,
            match_mode=active_match_mode,
            exclude_terms=active_exclude_terms,
        )
        review_reasons: list[str] = []
        if not verified.text:
            review_reasons.append("no_text_detected")
        if verified.confidence < 60:
            review_reasons.append("low_ocr_confidence")
        if verified.agreement_score < 0.5:
            review_reasons.append("low_candidate_agreement")
        verified_pages.append(
            {
                "page_number": page_number,
                "output_page_number": page_number,
                "rotation": 0,
                "image_file": image_path.name,
                "text": verified.text,
                "confidence": verified.confidence,
                "selected_candidate": verified.selected_candidate,
                "agreement_score": verified.agreement_score,
                "selection_score": verified.selection_score,
                "review_required": bool(review_reasons),
                "review_reasons": review_reasons,
                "filter_matched": filter_decision.keep,
                "matched_filter_terms": list(filter_decision.matched_terms),
                "excluded_filter_terms": list(filter_decision.excluded_terms),
            }
        )

    filtered_pdf: Path | None = None
    if filter_enabled:
        if progress_callback:
            progress_callback(0.84, "Applying page filter conditions.")
        retained_page_numbers = [
            int(page["page_number"])
            for page in verified_pages
            if page["filter_matched"]
        ]
        filtered_pdf = write_filtered_pdf(
            pdf_path,
            filtered_pdf_path
            or json_dir.parent / f"{base_name}.filtered.pdf",
            retained_page_numbers,
        )
        retained_pages = set(retained_page_numbers)
        discarded_images = [
            path
            for page_number, path in enumerate(image_paths, start=1)
            if page_number not in retained_pages
        ]
        for image_path in discarded_images:
            image_path.unlink(missing_ok=True)
        image_paths = [
            path
            for page_number, path in enumerate(image_paths, start=1)
            if page_number in retained_pages
        ]
        verified_pages = [
            page
            for page in verified_pages
            if int(page["page_number"]) in retained_pages
        ]
        for profile in OCR_PROFILES:
            candidate_pages[profile.name] = [
                page
                for page in candidate_pages[profile.name]
                if int(page["page_number"]) in retained_pages
            ]

    page_filter = {
        "enabled": filter_enabled,
        "terms": list(active_filter_terms),
        "match_mode": active_match_mode,
        "exclude_terms": list(active_exclude_terms),
        "text_source": "all_ocr_candidates",
        "source_total_pages": source_total_pages,
        "retained_pages": len(verified_pages),
        "discarded_pages": source_total_pages - len(verified_pages),
    }
    json_outputs: list[JsonOutput] = []
    if progress_callback:
        progress_callback(0.88, "Writing OCR result files.")
    for index, profile in enumerate(OCR_PROFILES, start=1):
        candidate_payload = {
            "source_pdf": source_pdf,
            "total_pages": len(image_paths),
            "ocr_language": ocr_language,
            "page_filter": page_filter,
            "candidate": {
                "number": index,
                "name": profile.name,
                "description": profile.description,
                "tesseract_config": profile.config,
            },
            "pages": candidate_pages[profile.name],
        }
        candidate_path = write_ocr_result(
            candidate_payload,
            json_dir / f"{base_name}.candidate-{index}-{profile.name}.json",
        )
        json_outputs.append(
            JsonOutput(
                kind="candidate",
                label=f"Candidate {index}: {profile.name}",
                path=candidate_path,
            )
        )

    verified_payload = {
        "source_pdf": source_pdf,
        "total_pages": len(verified_pages),
        "ocr_language": ocr_language,
        "page_filter": page_filter,
        "verification": {
            "candidate_count": len(OCR_PROFILES),
            "method": (
                "40% cross-candidate agreement + 50% OCR confidence "
                "+ 10% exact-match support"
            ),
            "review_required_pages": sum(
                bool(page["review_required"]) for page in verified_pages
            ),
        },
        "pages": verified_pages,
    }
    verified_path = write_ocr_result(
        verified_payload,
        json_dir / f"{base_name}.verified.json",
    )
    json_outputs.insert(
        0,
        JsonOutput(
            kind="verified",
            label="Verified result",
            path=verified_path,
        ),
    )
    searchable_pdf = write_searchable_pdf(
        pdf_path,
        searchable_pdf_path
        or json_dir.parent / f"{base_name}.searchable.pdf",
        (
            SearchablePage(
                page_number=int(page["page_number"]),
                text=str(page["text"]),
            )
            for page in verified_pages
        ),
    )
    if progress_callback:
        progress_callback(1.0, "Searchable PDF created.")

    return ProcessedDocument(
        source_pdf=source_pdf,
        image_paths=image_paths,
        json_outputs=json_outputs,
        warnings=warnings,
        review_required_pages=sum(
            bool(page["review_required"]) for page in verified_pages
        ),
        source_total_pages=source_total_pages,
        filtered_pdf=filtered_pdf,
        searchable_pdf=searchable_pdf,
    )
