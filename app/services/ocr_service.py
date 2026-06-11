from __future__ import annotations

from pathlib import Path

import pytesseract
from PIL import Image


def extract_text(
    image_path: Path,
    language: str | None = None,
    timeout_seconds: int = 30,
) -> str:
    """Extract text from one PNG using the locally installed Tesseract binary."""
    with Image.open(image_path) as image:
        text = pytesseract.image_to_string(
            image,
            lang=language,
            timeout=timeout_seconds,
        )
    return text.strip()
