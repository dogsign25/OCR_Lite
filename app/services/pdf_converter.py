from __future__ import annotations

from pathlib import Path

import fitz


class PdfConversionError(RuntimeError):
    """Raised when a PDF cannot be opened or rendered."""


def convert_pdf_to_png(
    pdf_path: Path,
    output_dir: Path,
    base_name: str,
    dpi: int = 200,
) -> list[Path]:
    """Render every PDF page as `<base_name>(<page>).png`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    document: fitz.Document | None = None

    try:
        document = fitz.open(pdf_path)
        if document.page_count == 0:
            raise PdfConversionError("The PDF contains no pages.")

        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = output_dir / f"{base_name}({page_index + 1}).png"
            pixmap.save(image_path)
            image_paths.append(image_path)
    except PdfConversionError:
        raise
    except Exception as exc:
        for image_path in image_paths:
            image_path.unlink(missing_ok=True)
        raise PdfConversionError(str(exc)) from exc
    finally:
        if document is not None:
            document.close()

    return image_paths
