from __future__ import annotations

import textwrap
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import fitz


class SearchablePdfError(RuntimeError):
    """Raised when a searchable PDF cannot be created."""


@dataclass(frozen=True)
class SearchablePage:
    page_number: int
    text: str
    rotation: int = 0


def _wrapped_lines(text: str, width: int = 120) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines() or [""]:
        wrapped = textwrap.wrap(
            line,
            width=width,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        lines.extend(wrapped or [""])
    return lines


def _insert_invisible_text(page: fitz.Page, text: str) -> None:
    wrap_width = max(20, min(120, int((page.rect.width - 10) / 2.5)))
    lines = _wrapped_lines(text.strip(), width=wrap_width)
    if not any(lines):
        return

    # Small invisible text preserves searchability without changing page layout.
    lines_per_block = max(1, int((page.rect.height - 12) / 2.4))
    for start in range(0, len(lines), lines_per_block):
        page.insert_text(
            (5, 10),
            "\n".join(lines[start:start + lines_per_block]),
            fontname="korea",
            fontsize=2,
            lineheight=1.2,
            render_mode=3,
            overlay=True,
        )


def write_searchable_pdf(
    source_pdf: Path,
    output_pdf: Path,
    pages: Iterable[SearchablePage],
) -> Path:
    searchable_pages = list(pages)
    if not searchable_pages:
        raise SearchablePdfError("A searchable PDF requires at least one page.")

    page_numbers = [page.page_number for page in searchable_pages]
    if len(page_numbers) != len(set(page_numbers)):
        raise SearchablePdfError("Searchable PDF page numbers must be unique.")
    if any(page.rotation not in (0, 90, 180, 270) for page in searchable_pages):
        raise SearchablePdfError("Page rotation must be 0, 90, 180, or 270.")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    temporary_pdf = output_pdf.with_name(f".{output_pdf.name}.tmp")
    source: fitz.Document | None = None
    searchable: fitz.Document | None = None

    try:
        source = fitz.open(source_pdf)
        searchable = fitz.open()
        for searchable_page in searchable_pages:
            page_index = searchable_page.page_number - 1
            if page_index < 0 or page_index >= source.page_count:
                raise SearchablePdfError(
                    f"Page {searchable_page.page_number} is outside the source PDF."
                )
            searchable.insert_pdf(
                source,
                from_page=page_index,
                to_page=page_index,
            )
            output_page = searchable.load_page(searchable.page_count - 1)
            output_page.set_rotation(
                (output_page.rotation + searchable_page.rotation) % 360
            )
            _insert_invisible_text(output_page, searchable_page.text)

        searchable.save(temporary_pdf)
        searchable.close()
        searchable = None
        source.close()
        source = None
        temporary_pdf.replace(output_pdf)
    except SearchablePdfError:
        raise
    except Exception as exc:
        raise SearchablePdfError(str(exc)) from exc
    finally:
        if searchable is not None:
            searchable.close()
        if source is not None:
            source.close()
        temporary_pdf.unlink(missing_ok=True)

    return output_pdf
