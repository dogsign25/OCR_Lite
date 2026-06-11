from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.json_writer import write_ocr_result
from app.services.ocr_service import (
    OCR_PROFILES,
    OcrResult,
    extract_ocr_result,
    validate_ocr_language,
)
from app.services.ocr_verifier import select_verified_result
from app.services.pdf_converter import convert_pdf_to_png

PIPELINE_VERSION = "3"


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
) -> ProcessedDocument:
    """Convert one PDF and create three OCR candidates plus a verified result."""
    validate_ocr_language(ocr_language)
    source_pdf = source_name or pdf_path.name
    image_paths = convert_pdf_to_png(pdf_path, image_dir, base_name)
    warnings: list[str] = []
    candidate_pages: dict[str, list[dict[str, object]]] = {
        profile.name: [] for profile in OCR_PROFILES
    }
    verified_pages: list[dict[str, object]] = []

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
                    "image_file": image_path.name,
                    "text": ocr_result.text,
                    "confidence": ocr_result.confidence,
                }
            )

        if successful_profiles == 0:
            raise RuntimeError(
                f"All OCR profiles failed for page {page_number}. "
                "No verified result was written."
            )

        verified = select_verified_result(page_candidates)
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
                "image_file": image_path.name,
                "text": verified.text,
                "confidence": verified.confidence,
                "selected_candidate": verified.selected_candidate,
                "agreement_score": verified.agreement_score,
                "selection_score": verified.selection_score,
                "review_required": bool(review_reasons),
                "review_reasons": review_reasons,
            }
        )

    json_outputs: list[JsonOutput] = []
    for index, profile in enumerate(OCR_PROFILES, start=1):
        candidate_payload = {
            "source_pdf": source_pdf,
            "total_pages": len(image_paths),
            "ocr_language": ocr_language,
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

    return ProcessedDocument(
        source_pdf=source_pdf,
        image_paths=image_paths,
        json_outputs=json_outputs,
        warnings=warnings,
        review_required_pages=sum(
            bool(page["review_required"]) for page in verified_pages
        ),
    )
