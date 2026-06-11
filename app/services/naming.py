from __future__ import annotations

import re
from pathlib import Path


def safe_stem(filename: str) -> str:
    """Return a filesystem-safe base name while preserving Unicode letters."""
    stem = Path(filename).stem.strip()
    stem = re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE)
    stem = stem.strip("._")
    return stem[:120] or "document"
