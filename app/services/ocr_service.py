from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from pytesseract import Output


@dataclass(frozen=True)
class OcrProfile:
    name: str
    description: str
    config: str
    preprocess: Callable[[Image.Image], Image.Image]


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float


def _original(image: Image.Image) -> Image.Image:
    return image.convert("RGB")


def _high_contrast(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.grayscale(image)
    return ImageOps.autocontrast(grayscale).convert("RGB")


def _sharpened(image: Image.Image) -> Image.Image:
    grayscale = ImageOps.autocontrast(ImageOps.grayscale(image))
    contrasted = ImageEnhance.Contrast(grayscale).enhance(1.35)
    return contrasted.filter(
        ImageFilter.UnsharpMask(radius=1.5, percent=170, threshold=3)
    ).convert("RGB")


OCR_PROFILES = (
    OcrProfile(
        name="balanced",
        description="Automatic page segmentation on the original image",
        config="--oem 3 --psm 3",
        preprocess=_original,
    ),
    OcrProfile(
        name="uniform-block",
        description="High-contrast image treated as one text block",
        config="--oem 3 --psm 6",
        preprocess=_high_contrast,
    ),
    OcrProfile(
        name="sparse-text",
        description="Sharpened image with sparse text detection",
        config="--oem 3 --psm 11",
        preprocess=_sharpened,
    ),
)


class OcrConfigurationError(RuntimeError):
    """Raised when Tesseract or a requested language is unavailable."""


@lru_cache(maxsize=None)
def validate_ocr_language(language: str) -> None:
    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception as exc:
        raise OcrConfigurationError(f"Tesseract is not available: {exc}") from exc

    requested = {item.strip() for item in language.split("+") if item.strip()}
    missing = sorted(requested - installed)
    if missing:
        raise OcrConfigurationError(
            "Missing Tesseract language pack(s): " + ", ".join(missing)
        )


def _text_and_confidence(data: dict[str, list[object]]) -> OcrResult:
    lines: list[str] = []
    current_key: tuple[object, ...] | None = None
    current_words: list[str] = []
    confidences: list[float] = []

    for index, raw_text in enumerate(data["text"]):
        text = str(raw_text).strip()
        if not text:
            continue

        line_key = (
            data["page_num"][index],
            data["block_num"][index],
            data["par_num"][index],
            data["line_num"][index],
        )
        if current_key is not None and line_key != current_key:
            lines.append(" ".join(current_words))
            current_words = []
        current_key = line_key
        current_words.append(text)

        confidence = float(data["conf"][index])
        if confidence >= 0:
            confidences.append(confidence)

    if current_words:
        lines.append(" ".join(current_words))

    average_confidence = (
        round(sum(confidences) / len(confidences), 2) if confidences else 0.0
    )
    return OcrResult(text="\n".join(lines).strip(), confidence=average_confidence)


def extract_ocr_result(
    image_path: Path,
    profile: OcrProfile,
    language: str = "kor+eng",
    timeout_seconds: int = 30,
) -> OcrResult:
    """Extract text and mean word confidence using one OCR profile."""
    with Image.open(image_path) as image:
        processed_image = profile.preprocess(image)
        data = pytesseract.image_to_data(
            processed_image,
            lang=language,
            config=profile.config,
            output_type=Output.DICT,
            timeout=timeout_seconds,
        )
    return _text_and_confidence(data)


def extract_text(
    image_path: Path,
    language: str = "kor+eng",
    timeout_seconds: int = 30,
) -> str:
    """Extract Korean and English text from one PNG with Tesseract."""
    return extract_ocr_result(
        image_path,
        profile=OCR_PROFILES[0],
        language=language,
        timeout_seconds=timeout_seconds,
    ).text
