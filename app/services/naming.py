from __future__ import annotations

import re
import unicodedata
from pathlib import Path

WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def safe_stem(filename: str) -> str:
    """Return a filesystem-safe base name while preserving Unicode letters."""
    stem = unicodedata.normalize("NFKC", Path(filename).stem).strip()
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE)
    stem = stem.strip("._")
    stem = stem[:120] or "document"
    if stem.casefold() in WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return stem
