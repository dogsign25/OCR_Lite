from __future__ import annotations

import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import uuid4


@dataclass(frozen=True)
class StagedArtifact:
    staged: Path
    target: Path


def staging_path(target: Path) -> Path:
    token = uuid4().hex
    return target.with_name(
        f".{target.stem}.{token}.stage{target.suffix}"
    )


def commit_staged_artifacts(artifacts: list[StagedArtifact]) -> None:
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    try:
        for artifact in artifacts:
            if not artifact.staged.is_file():
                raise FileNotFoundError(
                    f"Staged output is missing: {artifact.staged.name}"
                )
            artifact.target.parent.mkdir(parents=True, exist_ok=True)
            backup: Path | None = None
            if artifact.target.is_file():
                backup = artifact.target.with_name(
                    f".{artifact.target.name}.{uuid4().hex}.backup"
                )
                shutil.copy2(artifact.target, backup)
            backups[artifact.target] = backup
            artifact.staged.replace(artifact.target)
            committed.append(artifact.target)
    except Exception:
        for target in reversed(committed):
            backup = backups.get(target)
            if backup is None:
                target.unlink(missing_ok=True)
            elif backup.is_file():
                backup.replace(target)
        raise
    finally:
        for artifact in artifacts:
            artifact.staged.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)


@contextmanager
def preserve_artifacts(paths: list[Path]) -> Iterator[None]:
    snapshots: dict[Path, Path | None] = {}
    try:
        for path in paths:
            snapshot: Path | None = None
            if path.is_file():
                snapshot = path.with_name(
                    f".{path.name}.{uuid4().hex}.snapshot"
                )
                shutil.copy2(path, snapshot)
            snapshots[path] = snapshot
        yield
    except Exception:
        for path, snapshot in snapshots.items():
            if snapshot is None:
                path.unlink(missing_ok=True)
            elif snapshot.is_file():
                snapshot.replace(path)
        raise
    finally:
        for snapshot in snapshots.values():
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)
