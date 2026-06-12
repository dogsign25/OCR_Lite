from __future__ import annotations

from pathlib import Path
from math import ceil

import fitz

DEFAULT_MAX_PAGES = 500
DEFAULT_MAX_RENDER_PIXELS = 25_000_000


class PdfConversionError(RuntimeError):
    """Raised when a PDF cannot be opened or rendered."""


def convert_pdf_to_png(
    pdf_path: Path,
    output_dir: Path,
    base_name: str,
    dpi: int = 200,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_render_pixels: int = DEFAULT_MAX_RENDER_PIXELS,
) -> list[Path]:
    """Render every PDF page as `<base_name>(<page>).png`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    document: fitz.Document | None = None

    try:
        document = fitz.open(pdf_path)
        if document.needs_pass:
            raise PdfConversionError("Password-protected PDFs are not supported.")
        if document.page_count == 0:
            raise PdfConversionError("The PDF contains no pages.")
        if document.page_count > max_pages:
            raise PdfConversionError(
                f"The PDF has {document.page_count} pages; the limit is {max_pages}."
            )
        if dpi < 1:
            raise PdfConversionError("Render DPI must be at least 1.")

        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            width = ceil(page.rect.width * zoom)
            height = ceil(page.rect.height * zoom)
            if width * height > max_render_pixels:
                raise PdfConversionError(
                    f"Page {page_index + 1} is too large to render safely."
                )
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
