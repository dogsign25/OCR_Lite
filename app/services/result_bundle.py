from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from zlib import crc32
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


class ResultBundleError(RuntimeError):
    """Raised when a result ZIP cannot be created."""


@dataclass(frozen=True)
class BundleFile:
    path: Path
    directory: str

    @property
    def archive_name(self) -> str:
        directory = self.directory.replace("\\", "/").strip("/")
        filename = self.path.name
        path = PurePosixPath(directory)
        if (
            not directory
            or path.is_absolute()
            or any(part in ("", ".", "..") for part in path.parts)
            or "/" in filename
            or "\\" in filename
        ):
            raise ResultBundleError("Result ZIP contains an unsafe archive path.")
        return str(path / filename)


def write_result_bundle(
    output_zip: Path,
    files: Iterable[BundleFile],
) -> Path:
    bundle_files = [item for item in files if item.path.is_file()]
    if not bundle_files:
        raise ResultBundleError("A result ZIP requires at least one output file.")

    archive_names = [item.archive_name for item in bundle_files]
    if len(archive_names) != len(set(archive_names)):
        raise ResultBundleError("Result ZIP file names must be unique.")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    temporary_zip = output_zip.with_name(f".{output_zip.name}.tmp")
    try:
        with ZipFile(temporary_zip, "w", compression=ZIP_DEFLATED) as archive:
            for item in bundle_files:
                archive.write(item.path, item.archive_name)
        temporary_zip.replace(output_zip)
    except Exception as exc:
        raise ResultBundleError(str(exc)) from exc
    finally:
        temporary_zip.unlink(missing_ok=True)

    return output_zip


def result_bundle_is_valid(
    bundle_path: Path,
    expected_files: Iterable[BundleFile],
) -> bool:
    files = list(expected_files)
    expected = sorted(item.archive_name for item in files)
    try:
        with ZipFile(bundle_path) as archive:
            if archive.testzip() is not None:
                return False
            if sorted(archive.namelist()) != expected:
                return False
            for item in files:
                info = archive.getinfo(item.archive_name)
                checksum = 0
                size = 0
                with item.path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        checksum = crc32(chunk, checksum)
                        size += len(chunk)
                if size != info.file_size or checksum != info.CRC:
                    return False
            return True
    except (BadZipFile, OSError, ValueError):
        return False
