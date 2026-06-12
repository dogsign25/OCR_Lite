from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from app.services.document_processor import PIPELINE_VERSION, process_document
from app.services.json_writer import write_ocr_result
from app.services.naming import safe_stem
from app.services.ocr_service import OCR_PROFILES
from app.services.page_filter import normalize_filter_terms


@dataclass(frozen=True)
class BatchItem:
    source_pdf: str
    output_directory: str
    status: str
    total_pages: int = 0
    source_total_pages: int = 0
    verified_json: str = ""
    filtered_pdf: str = ""
    warning_count: int = 0
    review_required_pages: int = 0
    error: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert every PDF in a folder to PNG and cross-verified OCR JSON."
        )
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        default=Path("input"),
        help="Folder containing PDF files (default: input)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("batch_outputs"),
        help="Root folder for per-PDF results (default: batch_outputs)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(2, os.cpu_count() or 1),
        help="Number of PDFs processed concurrently (default: up to 2)",
    )
    parser.add_argument(
        "--language",
        default=os.getenv("OCR_LANGUAGE", "kor+eng"),
        help="Tesseract language setting (default: OCR_LANGUAGE or kor+eng)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Find PDFs in nested input folders",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Reprocess PDFs whose verified JSON already exists",
    )
    parser.add_argument(
        "--filter-word",
        action="append",
        default=[],
        help=(
            "Keep only pages containing this OCR text. "
            "Repeat the option to register multiple words."
        ),
    )
    return parser.parse_args()


def discover_pdfs(input_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in input_dir.glob(pattern)
        if path.is_file() and path.suffix.casefold() == ".pdf"
    )


def assign_output_names(pdf_paths: list[Path], input_dir: Path) -> dict[Path, str]:
    grouped: dict[str, list[Path]] = {}
    for pdf_path in pdf_paths:
        grouped.setdefault(safe_stem(pdf_path.name), []).append(pdf_path)

    names: dict[Path, str] = {}
    for base_name, matching_paths in grouped.items():
        for pdf_path in matching_paths:
            if len(matching_paths) == 1:
                names[pdf_path] = base_name
                continue
            relative = str(pdf_path.relative_to(input_dir))
            suffix = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:8]
            names[pdf_path] = f"{base_name}_{suffix}"
    return names


def clear_generated_files(document_dir: Path) -> None:
    for pattern in (
        "images/*.png",
        "json/*.json",
        "*.filtered.pdf",
        "manifest.json",
    ):
        for path in document_dir.glob(pattern):
            path.unlink()


def source_fingerprint(pdf_path: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    with pdf_path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return {
        "name": pdf_path.name,
        "size": pdf_path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def pipeline_settings(
    language: str,
    filter_terms: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "pipeline_version": PIPELINE_VERSION,
        "ocr_language": language,
        "filter_terms": list(normalize_filter_terms(filter_terms)),
        "profiles": [
            {"name": profile.name, "config": profile.config}
            for profile in OCR_PROFILES
        ],
    }


def load_reusable_manifest(
    manifest_path: Path,
    fingerprint: dict[str, object],
    settings: dict[str, object],
) -> dict[str, object] | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "completed":
            return None
        if manifest.get("source") != fingerprint:
            return None
        if manifest.get("settings") != settings:
            return None

        document_dir = manifest_path.parent.resolve()
        result = manifest["result"]
        output_files = result["output_files"]
        required_fields = (
            "total_pages",
            "source_total_pages",
            "verified_json",
            "warning_count",
            "review_required_pages",
        )
        if not isinstance(output_files, list) or not output_files:
            return None
        if any(field not in result for field in required_fields):
            return None
        if not all(isinstance(name, str) for name in output_files):
            return None
        if str(result["verified_json"]) not in output_files:
            return None
        filtered_pdf = result.get("filtered_pdf", "")
        if filtered_pdf and str(filtered_pdf) not in output_files:
            return None
        if settings.get("filter_terms") and not filtered_pdf:
            return None
        for field in (
            "total_pages",
            "source_total_pages",
            "warning_count",
            "review_required_pages",
        ):
            if not isinstance(result[field], int) or result[field] < 0:
                return None
        if result["total_pages"] > result["source_total_pages"]:
            return None
        for relative_name in output_files:
            candidate = (document_dir / relative_name).resolve()
            if not candidate.is_relative_to(document_dir) or not candidate.is_file():
                return None
        return manifest
    except (KeyError, OSError, TypeError, ValueError):
        return None


def process_batch_item(
    pdf_path: Path,
    output_root: Path,
    output_name: str,
    language: str,
    overwrite: bool,
    filter_terms: tuple[str, ...] = (),
) -> BatchItem:
    document_dir = output_root / output_name
    image_dir = document_dir / "images"
    json_dir = document_dir / "json"
    manifest_path = document_dir / "manifest.json"

    try:
        fingerprint = source_fingerprint(pdf_path)
        settings = pipeline_settings(language, filter_terms)
        manifest = (
            None
            if overwrite
            else load_reusable_manifest(manifest_path, fingerprint, settings)
        )
        if manifest is not None:
            result = manifest["result"]
            return BatchItem(
                source_pdf=str(pdf_path),
                output_directory=str(document_dir),
                status="skipped",
                total_pages=int(result["total_pages"]),
                source_total_pages=int(result["source_total_pages"]),
                verified_json=str(document_dir / str(result["verified_json"])),
                filtered_pdf=(
                    str(document_dir / str(result["filtered_pdf"]))
                    if result.get("filtered_pdf")
                    else ""
                ),
                warning_count=int(result["warning_count"]),
                review_required_pages=int(result["review_required_pages"]),
            )

        clear_generated_files(document_dir)
        processed = process_document(
            pdf_path=pdf_path,
            image_dir=image_dir,
            json_dir=json_dir,
            base_name=output_name,
            source_name=pdf_path.name,
            ocr_language=language,
            filter_terms=filter_terms,
            filtered_pdf_path=document_dir / f"{output_name}.filtered.pdf",
        )
        generated_paths = (
            [*processed.image_paths]
            + [output.path for output in processed.json_outputs]
            + ([processed.filtered_pdf] if processed.filtered_pdf else [])
        )
        output_files = [
            str(path.relative_to(document_dir))
            for path in generated_paths
        ]
        manifest_payload = {
            "status": "completed",
            "source": fingerprint,
            "settings": settings,
            "result": {
                "total_pages": processed.total_pages,
                "source_total_pages": processed.source_total_pages,
                "verified_json": str(
                    processed.verified_json.relative_to(document_dir)
                ),
                "filtered_pdf": (
                    str(processed.filtered_pdf.relative_to(document_dir))
                    if processed.filtered_pdf
                    else ""
                ),
                "warning_count": len(processed.warnings),
                "review_required_pages": processed.review_required_pages,
                "output_files": output_files,
            },
        }
        write_ocr_result(manifest_payload, manifest_path)
    except Exception as exc:
        clear_generated_files(document_dir)
        return BatchItem(
            source_pdf=str(pdf_path),
            output_directory=str(document_dir),
            status="failed",
            error=str(exc),
        )

    return BatchItem(
        source_pdf=str(pdf_path),
        output_directory=str(document_dir),
        status="completed",
        total_pages=processed.total_pages,
        source_total_pages=processed.source_total_pages,
        verified_json=str(processed.verified_json),
        filtered_pdf=str(processed.filtered_pdf or ""),
        warning_count=len(processed.warnings),
        review_required_pages=processed.review_required_pages,
    )


def write_summary(output_dir: Path, items: list[BatchItem]) -> Path:
    summary_path = output_dir / "batch-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {
        status: sum(item.status == status for item in items)
        for status in ("completed", "skipped", "failed")
    }
    payload = {
        "total_files": len(items),
        "counts": counts,
        "results": [asdict(item) for item in items],
    }
    return write_ocr_result(payload, summary_path)


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()

    if args.workers < 1:
        raise SystemExit("--workers must be at least 1")
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    pdf_paths = discover_pdfs(input_dir, args.recursive)
    if not pdf_paths:
        raise SystemExit(f"No PDF files found in: {input_dir}")

    output_names = assign_output_names(pdf_paths, input_dir)
    filter_terms = normalize_filter_terms(args.filter_word)
    print(
        f"Processing {len(pdf_paths)} PDF file(s) with "
        f"{args.workers} worker(s)..."
    )

    items: list[BatchItem] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_batch_item,
                pdf_path,
                output_dir,
                output_names[pdf_path],
                args.language,
                args.overwrite,
                filter_terms,
            ): pdf_path
            for pdf_path in pdf_paths
        }
        for future in as_completed(futures):
            pdf_path = futures[future]
            try:
                item = future.result()
            except Exception as exc:
                item = BatchItem(
                    source_pdf=str(pdf_path),
                    output_directory=str(output_dir / output_names[pdf_path]),
                    status="failed",
                    error=f"Unexpected worker failure: {exc}",
                )
            items.append(item)
            detail = f", {item.total_pages} page(s)" if item.total_pages else ""
            print(f"[{item.status.upper()}] {item.source_pdf}{detail}")
            if item.error:
                print(f"  {item.error}")

    items.sort(key=lambda item: item.source_pdf.casefold())
    summary_path = write_summary(output_dir, items)
    failures = sum(item.status == "failed" for item in items)
    print(f"Summary: {summary_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
