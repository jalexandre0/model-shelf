"""Remove a model from the shelf by repo_id.

Public API:
    RemoveResult           – dataclass with removed paths and hardlink warnings
    remove_model()         – main entry point; dry-run by default
    cleanup_empty_parents() – remove empty ancestor dirs (shared with cli.py)
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from pathlib import Path

from model_shelf.manifest import load_manifest, remove_manifest_entry
from model_shelf.resolver import (
    SUPPORTED_FORMATS,
    Config,
    check_storage_available,
)


@dataclass
class RemoveResult:
    """Result of a remove operation (dry-run or execute)."""

    removed: list[str] = field(default_factory=list)
    hardlinks_warn: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "removed": list(self.removed),
            "hardlinks_warn": list(self.hardlinks_warn),
        }


def cleanup_empty_parents(shelf_root: Path, model_dir: Path) -> None:
    """Remove empty ancestor directories up to (but not including) shelf_root.

    Canonical implementation shared by remove.py and cli.py (gc cleanup).
    """
    parent = model_dir
    while parent != shelf_root:
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
            else:
                break
        except OSError:
            break
        parent = parent.parent


def _collect_model_files(
    shelf_root: Path, fmt: str, repo_id: str, entry: dict
) -> list[Path]:
    """Collect existing file paths for a model entry."""
    publisher, _, repo_name = repo_id.partition("/")
    model_dir = shelf_root / fmt / publisher / repo_name
    paths: list[Path] = []
    for fname in entry.get("files", []):
        fp = model_dir / fname
        if fp.is_file():
            paths.append(fp)
    return paths


def _delete_files_and_warn(paths: list[Path]) -> RemoveResult:
    """Delete files, warn on hardlinks. Returns RemoveResult for execute path."""
    hardlinks_warn: list[str] = []
    removed_paths: list[str] = []
    for fp in paths:
        try:
            st = fp.stat()
        except OSError:
            continue
        if st.st_nlink > 1:
            hardlinks_warn.append(f"{fp} (st_nlink={st.st_nlink})")
        removed_paths.append(str(fp))
        try:
            os.unlink(fp)
        except OSError:
            pass
    return RemoveResult(removed=removed_paths, hardlinks_warn=hardlinks_warn)


def _dry_run_result(paths: list[Path]) -> RemoveResult:
    """Build dry-run RemoveResult: check hardlinks without deleting."""
    hardlinks_warn: list[str] = []
    for fp in paths:
        try:
            st = fp.stat()
        except OSError:
            continue
        if st.st_nlink > 1:
            hardlinks_warn.append(f"{fp} (st_nlink={st.st_nlink})")
    return RemoveResult(
        removed=[str(p) for p in paths],
        hardlinks_warn=hardlinks_warn,
    )


def remove_model(
    config: Config, repo_id: str, *, dry_run: bool = True
) -> RemoveResult:
    """Remove the model identified by *repo_id* from the shelf.

    Raises ValueError if *repo_id* is not found in the manifest.
    """
    check_storage_available(config)
    shelf_root = config.shelf_root

    manifest = load_manifest(shelf_root)
    models = manifest.get("models", {})

    entry = models.get(repo_id)
    if entry is None:
        raise ValueError(f"model '{repo_id}' not found in manifest")

    fmt = entry.get("format", "")
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"unsupported format {fmt!r} in manifest entry for '{repo_id}'"
        )

    publisher, _, repo_name = repo_id.partition("/")
    model_dir = shelf_root / fmt / publisher / repo_name
    all_paths = _collect_model_files(shelf_root, fmt, repo_id, entry)

    if dry_run:
        return _dry_run_result(all_paths)

    # Execute
    result = _delete_files_and_warn(all_paths)
    remove_manifest_entry(shelf_root, repo_id)
    cleanup_empty_parents(shelf_root, model_dir)
    return result
