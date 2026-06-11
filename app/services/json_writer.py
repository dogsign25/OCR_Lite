from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_ocr_result(data: dict[str, Any], output_path: Path) -> Path:
    """Write the combined page results as one UTF-8 JSON file per PDF."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as json_file:
        json.dump(data, json_file, ensure_ascii=False, indent=2)
        json_file.write("\n")
    return output_path
