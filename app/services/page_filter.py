from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import fitz

FILTER_MATCH_MODES = ("any", "all")


class PageFilterError(RuntimeError):
    """Raised when a filtered PDF cannot be created."""


@dataclass(frozen=True)
class PageFilterDecision:
    keep: bool
    matched_terms: tuple[str, ...]
    excluded_terms: tuple[str, ...]


def normalize_filter_terms(terms: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = unicodedata.normalize("NFKC", " ".join(term.split()))
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return tuple(normalized)


def parse_filter_terms(value: str) -> tuple[str, ...]:
    return normalize_filter_terms(re.split(r"[,\r\n]+", value))


def find_matching_terms(
    texts: Iterable[str],
    filter_terms: Iterable[str],
) -> list[str]:
    searchable_texts = [
        unicodedata.normalize("NFKC", " ".join(text.split())).casefold()
        for text in texts
        if text.strip()
    ]
    return [
        term
        for term in normalize_filter_terms(filter_terms)
        if any(term.casefold() in text for text in searchable_texts)
    ]


def validate_filter_match_mode(match_mode: str) -> str:
    normalized = match_mode.strip().casefold()
    if normalized not in FILTER_MATCH_MODES:
        supported = ", ".join(FILTER_MATCH_MODES)
        raise ValueError(f"Filter match mode must be one of: {supported}")
    return normalized


def evaluate_page_filter(
    texts: Iterable[str],
    filter_terms: Iterable[str] = (),
    match_mode: str = "any",
    exclude_terms: Iterable[str] = (),
) -> PageFilterDecision:
    active_terms = normalize_filter_terms(filter_terms)
    active_exclude_terms = normalize_filter_terms(exclude_terms)
    normalized_mode = validate_filter_match_mode(match_mode)
    page_texts = tuple(texts)
    matched_terms = tuple(find_matching_terms(page_texts, active_terms))
    excluded_terms = tuple(
        find_matching_terms(page_texts, active_exclude_terms)
    )

    if not active_terms:
        include_matches = True
    elif normalized_mode == "all":
        include_matches = len(matched_terms) == len(active_terms)
    else:
        include_matches = bool(matched_terms)

    return PageFilterDecision(
        keep=include_matches and not excluded_terms,
        matched_terms=matched_terms,
        excluded_terms=excluded_terms,
    )


def write_filtered_pdf(
    source_pdf: Path,
    output_pdf: Path,
    page_numbers: Iterable[int],
) -> Path:
    selected_pages = list(page_numbers)
    if not selected_pages:
        raise PageFilterError(
            "No pages satisfied the registered filter conditions."
        )
    if len(selected_pages) != len(set(selected_pages)):
        raise PageFilterError("Filtered PDF page numbers must be unique.")

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    temporary_pdf = output_pdf.with_name(f".{output_pdf.name}.tmp")
    source: fitz.Document | None = None
    filtered: fitz.Document | None = None

    try:
        source = fitz.open(source_pdf)
        filtered = fitz.open()
        for page_number in selected_pages:
            page_index = page_number - 1
            if page_index < 0 or page_index >= source.page_count:
                raise PageFilterError(
                    f"Page {page_number} is outside the source PDF."
                )
            filtered.insert_pdf(
                source,
                from_page=page_index,
                to_page=page_index,
            )
        filtered.save(temporary_pdf)
        filtered.close()
        filtered = None
        source.close()
        source = None
        temporary_pdf.replace(output_pdf)
    except PageFilterError:
        raise
    except Exception as exc:
        raise PageFilterError(str(exc)) from exc
    finally:
        if filtered is not None:
            filtered.close()
        if source is not None:
            source.close()
        temporary_pdf.unlink(missing_ok=True)

    return output_pdf
