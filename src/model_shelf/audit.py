"""Audit — cross-reference manifest against filesystem (read-only).

Public API:
    AuditResult  – dataclass with missing/stale/untracked lists
    run_audit()  – main entry point; returns AuditResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from model_shelf.manifest import (
    _sha256_dir_for_rebuild,
    build_tracked_path_set,
    load_manifest,
    should_skip_shelf_path,
)
from model_shelf.import_model import _sha256_file
from model_shelf.resolver import (
    SUPPORTED_FORMATS,
    Config,
    check_storage_available,
)


@dataclass
class AuditResult:
    """Result of a shelf audit."""

    missing: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "missing": list(self.missing),
            "untracked": list(self.untracked),
            "stale": list(self.stale),
        }


def _check_manifest_entries(
    shelf_root: Path, models: dict
) -> tuple[list[str], list[str]]:
    """Check manifest entries against filesystem.

    Returns (missing, stale) lists.
    """
    missing: list[str] = []
    stale: list[str] = []

    for repo_id, entry in models.items():
        fmt = entry.get("format", "")
        if fmt not in SUPPORTED_FORMATS or "/" not in repo_id:
            continue

        publisher, _, repo_name = repo_id.partition("/")
        model_dir = shelf_root / fmt / publisher / repo_name

        # Check every tracked file exists
        for fname in entry.get("files", []):
            if not (model_dir / fname).is_file():
                missing.append(repo_id)
                break
        else:
            # All files exist — verify SHA256
            entry_sha = entry.get("sha256", "")
            if fmt == "gguf":
                gguf_files = entry.get("files", [])
                if gguf_files:
                    try:
                        actual = _sha256_file(model_dir / gguf_files[0])
                    except OSError:
                        missing.append(repo_id)
                        continue
                    if actual != entry_sha:
                        stale.append(repo_id)
            else:
                if model_dir.is_dir():
                    try:
                        actual = _sha256_dir_for_rebuild(model_dir)
                    except OSError:
                        missing.append(repo_id)
                        continue
                    if actual != entry_sha:
                        stale.append(repo_id)
                else:
                    missing.append(repo_id)

    return missing, stale


def _find_untracked_files(
    shelf_root: Path, tracked_paths: set[str]
) -> list[str]:
    """Walk shelf and find files AND directories not in *tracked_paths*."""
    untracked: list[str] = []
    for fmt in SUPPORTED_FORMATS:
        fmt_dir = shelf_root / fmt
        if not fmt_dir.is_dir():
            continue
        for f in fmt_dir.rglob("*"):
            if should_skip_shelf_path(f):
                continue
            f_str = str(f)
            if f.is_file():
                if f_str not in tracked_paths:
                    untracked.append(f_str)
            elif f.is_dir():
                # Only flag MLX/safetensors directories that look like model dirs.
                # GGUF models are single files — their parent dirs are just containers.
                if f_str not in tracked_paths:
                    has_config = (f / "config.json").is_file()
                    if has_config:
                        untracked.append(f_str)
    return untracked


def run_audit(config: Config) -> AuditResult:
    """Cross-reference manifest entries against the filesystem.

    Returns AuditResult with missing, stale, and untracked lists.
    """
    check_storage_available(config)
    shelf_root = config.shelf_root

    manifest = load_manifest(shelf_root)
    models = manifest.get("models", {})

    tracked_paths = build_tracked_path_set(shelf_root, models)

    missing, stale = _check_manifest_entries(shelf_root, models)
    untracked = _find_untracked_files(shelf_root, tracked_paths)

    return AuditResult(
        missing=sorted(missing),
        untracked=sorted(untracked),
        stale=sorted(stale),
    )
