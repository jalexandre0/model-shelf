"""Garbage collection — find and clean up incomplete downloads, orphaned
files, and empty directories on the curated shelf.

Dry-run by default.  Never touches .cache/ or dot-prefixed paths.

Public API:
    GCResult  – dataclass with lists and reclaimable byte count
    run_gc()  – main entry point (scan-only; execution happens in CLI)
"""

from __future__ import annotations

import os
import shutil

from dataclasses import dataclass, field
from pathlib import Path

from model_shelf.manifest import (
    build_tracked_path_set,
    load_manifest,
    should_skip_shelf_path,
)
from model_shelf.resolver import (
    SUPPORTED_FORMATS,
    Config,
    check_storage_available,
)


@dataclass
class GCResult:
    """Result of a garbage-collection scan."""

    incomplete_downloads: list[str] = field(default_factory=list)
    orphaned_files: list[str] = field(default_factory=list)
    empty_dirs: list[str] = field(default_factory=list)
    total_reclaimable_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "incomplete_downloads": list(self.incomplete_downloads),
            "orphaned_files": list(self.orphaned_files),
            "empty_dirs": list(self.empty_dirs),
            "total_reclaimable_bytes": self.total_reclaimable_bytes,
        }


def _find_incomplete_downloads(shelf_root: Path) -> list[str]:
    """Find model dirs that appear to be incomplete downloads."""
    incomplete: list[str] = []
    for fmt in SUPPORTED_FORMATS:
        fmt_dir = shelf_root / fmt
        if not fmt_dir.is_dir():
            continue
        for publisher in sorted(fmt_dir.iterdir()):
            if not publisher.is_dir() or should_skip_shelf_path(publisher):
                continue
            for repo in sorted(publisher.iterdir()):
                if not repo.is_dir() or should_skip_shelf_path(repo):
                    continue
                repo_str = str(repo)
                if fmt == "gguf":
                    gguf_files = [
                        f for f in repo.glob("*.gguf")
                        if not should_skip_shelf_path(f)
                    ]
                    if not gguf_files:
                        incomplete.append(repo_str)
                elif fmt == "mlx":
                    if not (repo / "config.json").is_file():
                        incomplete.append(repo_str)
                else:  # safetensors
                    config_json = repo / "config.json"
                    if not config_json.is_file():
                        incomplete.append(repo_str)
                    else:
                        st_files = [
                            f for f in repo.glob("*.safetensors")
                            if not should_skip_shelf_path(f)
                        ]
                        if not st_files:
                            incomplete.append(repo_str)
    return incomplete


def _find_orphaned_files(
    shelf_root: Path, tracked_set: set[str]
) -> tuple[list[str], int]:
    """Find files on shelf not in manifest. Returns (paths, total_bytes)."""
    orphaned: list[str] = []
    reclaimable: int = 0
    scanned_dirs: set[str] = set()

    for fmt in SUPPORTED_FORMATS:
        fmt_dir = shelf_root / fmt
        if not fmt_dir.is_dir():
            continue
        for publisher in sorted(fmt_dir.iterdir()):
            if not publisher.is_dir() or should_skip_shelf_path(publisher):
                continue
            for repo in sorted(publisher.iterdir()):
                if not repo.is_dir() or should_skip_shelf_path(repo):
                    continue
                scanned_dirs.add(str(repo))
                for f in sorted(repo.rglob("*")):
                    if not f.is_file() or should_skip_shelf_path(f):
                        continue
                    f_str = str(f)
                    if f_str not in tracked_set:
                        orphaned.append(f_str)
                        try:
                            reclaimable += f.stat().st_size
                        except OSError:
                            pass

            # Also scan for loose files at publisher level (no repo subdir)
            for f in sorted(publisher.rglob("*")):
                if not f.is_file() or should_skip_shelf_path(f):
                    continue
                parent_str = str(f.parent)
                if parent_str in scanned_dirs:
                    continue
                f_str = str(f)
                if f_str not in tracked_set:
                    orphaned.append(f_str)
                    try:
                        reclaimable += f.stat().st_size
                    except OSError:
                        pass

    return orphaned, reclaimable


def _find_empty_dirs(shelf_root: Path) -> list[str]:
    """Find empty directories on the shelf (deepest first)."""
    empty: list[str] = []
    for fmt in SUPPORTED_FORMATS:
        fmt_dir = shelf_root / fmt
        if not fmt_dir.is_dir():
            continue
        all_dirs = sorted(
            (d for d in fmt_dir.rglob("*") if d.is_dir()),
            key=lambda d: -len(d.parts),
        )
        for d in all_dirs:
            if should_skip_shelf_path(d):
                continue
            try:
                contents = [
                    c for c in d.iterdir()
                    if not should_skip_shelf_path(c)
                ]
            except OSError:
                continue
            if not contents:
                empty.append(str(d))
    return empty


def run_gc(config: Config) -> GCResult:
    """Scan the shelf for reclaimable space.

    Returns GCResult with incomplete downloads, orphaned files, empty
    directories, and total reclaimable bytes. This function is read-only;
    the CLI handler performs actual deletion when --execute is passed.
    """
    check_storage_available(config)
    shelf_root = config.shelf_root

    manifest = load_manifest(shelf_root)
    models = manifest.get("models", {})
    tracked_set = build_tracked_path_set(shelf_root, models)

    incomplete = _find_incomplete_downloads(shelf_root)
    orphaned, reclaimable = _find_orphaned_files(shelf_root, tracked_set)
    empty_dirs = _find_empty_dirs(shelf_root)

    return GCResult(
        incomplete_downloads=sorted(incomplete),
        orphaned_files=sorted(orphaned),
        empty_dirs=sorted(empty_dirs),
        total_reclaimable_bytes=reclaimable,
    )
