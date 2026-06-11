from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.services.ocr_service import OcrResult


@dataclass(frozen=True)
class VerifiedOcrResult:
    text: str
    confidence: float
    selected_candidate: str
    agreement_score: float
    selection_score: float


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def select_verified_result(
    candidates: dict[str, OcrResult],
) -> VerifiedOcrResult:
    """Select the result with the strongest agreement and OCR confidence."""
    if not candidates:
        return VerifiedOcrResult("", 0.0, "", 0.0, 0.0)

    normalized = {
        name: _normalize(result.text) for name, result in candidates.items()
    }
    scored: list[tuple[float, float, str, OcrResult]] = []

    for name, result in candidates.items():
        comparisons = [
            _similarity(normalized[name], other_text)
            for other_name, other_text in normalized.items()
            if other_name != name
        ]
        agreement = sum(comparisons) / len(comparisons) if comparisons else 1.0
        exact_support = (
            sum(
                normalized[name] == other_text
                for other_name, other_text in normalized.items()
                if other_name != name
            )
            / len(comparisons)
            if comparisons
            else 1.0
        )
        confidence = max(0.0, min(result.confidence, 100.0)) / 100
        score = (
            (agreement * 0.40)
            + (confidence * 0.50)
            + (exact_support * 0.10)
        )
        if not normalized[name]:
            score = -1.0
        scored.append((score, agreement, name, result))

    score, agreement, name, result = max(
        scored,
        key=lambda item: (item[0], item[3].confidence, len(item[3].text)),
    )
    return VerifiedOcrResult(
        text=result.text,
        confidence=result.confidence,
        selected_candidate=name,
        agreement_score=round(agreement, 4),
        selection_score=round(score, 4),
    )
