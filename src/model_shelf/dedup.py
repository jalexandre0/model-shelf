"""Find and deduplicate identical model files across the shelf and external caches.

Scans the curated shelf (gguf, mlx, safetensors) and optionally external
tool caches (Ollama blobs, HuggingFace cache blobs). Groups files with
identical SHA256 digests. On --execute, replaces duplicates with hardlinks
pointing to the shelf copy (the canonical keep).

Safety rules (hard constraints):
    1. Default dry-run — --execute required for any mutation.
    2. Never hardlink across filesystems (st_dev check before os.link).
    3. External blobs (Ollama, HF cache) are destinations only — never unlinked.
    4. Shelf copy is canonical KEEP — externals are hardlinked to it.
    5. Manifest hardlinks field is updated after dedup for ALL affected entries.
"""

from __future__ import annotations

import datetime
import os

from dataclasses import dataclass, field
from pathlib import Path

from model_shelf.config import Config
from model_shelf.manifest import load_manifest, save_manifest
from model_shelf.resolver import SUPPORTED_FORMATS, check_storage_available

# Reuse the canonical SHA256 helper from import_model.
from model_shelf.import_model import _sha256_file  # noqa: PLC2701


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# External cache roots for detection / safety guards.
_KNOWN_OLLAMA_BLOBS = Path.home() / ".ollama" / "models" / "blobs"
_KNOWN_HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"

# Only deduplicate model weight files, never metadata.
# .gitattributes, README.md, config.json, tokenizer.json etc. are boilerplate
# that happens to be identical across models — hardlinking them breaks dirs.
_WEIGHT_EXTENSIONS = frozenset({".gguf", ".safetensors", ".bin"})


def _is_weight_file(path: Path) -> bool:
    """Return True if *path* is a model weight file, not metadata."""
    return path.suffix.lower() in _WEIGHT_EXTENSIONS


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DedupGroup:
    """One set of files sharing the same SHA256 digest."""

    sha256: str
    files: list[Path]
    size_bytes: int
    duplicate_bytes: int


@dataclass
class DedupResult:
    """Result of a dedup scan or execution."""

    groups: list[DedupGroup] = field(default_factory=list)
    total_duplicate_bytes: int = 0
    potential_savings_bytes: int = 0
    skipped_cross_fs: int = 0
    hardlinks_created: int = 0
    skipped_external_only: int = 0

    def to_dict(self) -> dict:
        return {
            "groups": [
                {
                    "sha256": g.sha256,
                    "files": [str(f) for f in g.files],
                    "size_bytes": g.size_bytes,
                    "duplicate_bytes": g.duplicate_bytes,
                }
                for g in self.groups
            ],
            "total_duplicate_bytes": self.total_duplicate_bytes,
            "potential_savings_bytes": self.potential_savings_bytes,
            "skipped_cross_fs": self.skipped_cross_fs,
            "hardlinks_created": self.hardlinks_created,
            "skipped_external_only": self.skipped_external_only,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_EXTERNAL_ROOTS: dict[Path, str] = {
    _KNOWN_OLLAMA_BLOBS: "ollama",
    _KNOWN_HF_CACHE: "hf-cache",
}


def _is_same_fs(p1: Path, p2: Path) -> bool:
    """Return True if both paths reside on the same filesystem (same st_dev)."""
    try:
        return p1.stat().st_dev == p2.stat().st_dev
    except OSError:
        return False


def _is_external(path: Path) -> bool:
    """Return True if path lives inside an external tool cache (Ollama or HF)."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in _EXTERNAL_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            pass
    return False


def _is_in_shelf(path: Path, shelf_root: Path) -> bool:
    """Return True if path lives inside shelf_root."""
    try:
        path.resolve().relative_to(shelf_root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _hardlink_replace(canonical: Path, target: Path) -> None:
    """Atomically replace *target* with a hardlink to *canonical*."""
    tmp = target.with_suffix(target.suffix + ".msdedup")
    try:
        os.link(str(canonical), str(tmp))
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            os.unlink(str(tmp))


def _path_to_repo_id(path: Path, shelf_root: Path) -> str | None:
    """Infer repo_id from a path inside shelf_root.

    Shelf layout: {shelf_root}/{fmt}/{publisher}/{repo}/...
    """
    try:
        rel = path.resolve().relative_to(shelf_root.resolve())
    except (ValueError, OSError):
        return None
    parts = rel.parts
    if len(parts) < 3:
        return None
    return f"{parts[1]}/{parts[2]}"


# ---------------------------------------------------------------------------
# File collection helpers  (extracted — Fix 6)
# ---------------------------------------------------------------------------


def _collect_shelf_files(shelf_root: Path) -> list[tuple[Path, int, str]]:
    """Collect (path, size, label='shelf') entries from the curated shelf."""
    entries: list[tuple[Path, int, str]] = []
    for fmt in SUPPORTED_FORMATS:
        fmt_dir = shelf_root / fmt
        if not fmt_dir.is_dir():
            continue
        for f in sorted(fmt_dir.rglob("*")):
            if not f.is_file() or f.name.startswith("._"):
                continue
            if ".cache" in f.parts:
                continue
            if not _is_weight_file(f):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            entries.append((f, st.st_size, "shelf"))
    return entries


def _collect_ollama_blobs(
    ollama_root: Path | None = None,
) -> list[tuple[Path, int, str]]:
    """Collect (path, size, label='ollama') from ollama blobs directory."""
    root = ollama_root if ollama_root is not None else _KNOWN_OLLAMA_BLOBS
    entries: list[tuple[Path, int, str]] = []
    if not root.is_dir():
        return entries
    for f in sorted(root.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        entries.append((f, st.st_size, "ollama"))
    return entries


def _collect_hf_cache_blobs(
    hf_root: Path | None = None,
) -> list[tuple[Path, int, str]]:
    """Collect (path, size, label='hf-cache') from HF cache hub directory.

    Uses relative-path .cache filter instead of absolute .parts check so
    that the HF cache root (~/.cache/huggingface/hub/) is not excluded.  (Fix 1)
    """
    root = hf_root if hf_root is not None else _KNOWN_HF_CACHE
    entries: list[tuple[Path, int, str]] = []
    if not root.is_dir():
        return entries
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.name.startswith("._"):
            continue
        try:
            rel = f.relative_to(root)
        except ValueError:
            continue
        if ".cache" in rel.parts:
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        entries.append((f, st.st_size, "hf-cache"))
    return entries


def _build_sha256_index(
    entries: list[tuple[Path, int, str]],
) -> dict[str, list[tuple[Path, int, str]]]:
    """Group entries by SHA256 digest."""
    idx: dict[str, list[tuple[Path, int, str]]] = {}
    for path, size, label in entries:
        try:
            dig = _sha256_file(path)
        except OSError:
            continue
        idx.setdefault(dig, []).append((path, size, label))
    return idx


def _build_groups(
    sha_index: dict[str, list[tuple[Path, int, str]]],
) -> tuple[list[DedupGroup], int]:
    """Convert SHA index into DedupGroup list. Returns (groups, total_dup_bytes)."""
    groups: list[DedupGroup] = []
    total = 0
    for sha256, entries in sha_index.items():
        if len(entries) < 2:
            continue
        size_bytes = entries[0][1]
        dup_bytes = (len(entries) - 1) * size_bytes
        files = [p for (p, _, _) in entries]
        groups.append(DedupGroup(sha256=sha256, files=files, size_bytes=size_bytes, duplicate_bytes=dup_bytes))
        total += dup_bytes
    return groups, total


def _dedup_one_group(
    group: DedupGroup, canonical: Path, shelf_root: Path,
) -> tuple[int, int]:
    """Execute hardlinks for one duplicate group. Returns (hardlinks_created, skipped_cross_fs)."""
    hardlinks_created = 0
    skipped_cross_fs = 0
    for other in group.files:
        if other.resolve() == canonical.resolve():
            continue
        if not _is_same_fs(canonical, other):
            skipped_cross_fs += 1
            continue
        try:
            if canonical.stat().st_ino == other.stat().st_ino:
                continue
        except OSError:
            skipped_cross_fs += 1
            continue
        _hardlink_replace(canonical, other)
        hardlinks_created += 1
    return hardlinks_created, skipped_cross_fs


# ---------------------------------------------------------------------------
# Public API — scan
# ---------------------------------------------------------------------------


def find_duplicates(
    config: Config,
    *,
    include_ollama: bool = False,
    include_hf_cache: bool = False,
) -> DedupResult:
    """Scan the shelf (and optionally external caches) for duplicate files."""
    check_storage_available(config)
    entries = _collect_shelf_files(config.shelf_root)
    if include_ollama:
        entries += _collect_ollama_blobs()
    if include_hf_cache:
        entries += _collect_hf_cache_blobs()
    sha_index = _build_sha256_index(entries)
    groups, total = _build_groups(sha_index)
    return DedupResult(groups=groups, total_duplicate_bytes=total, potential_savings_bytes=total)


# ---------------------------------------------------------------------------
# Public API — execute
# ---------------------------------------------------------------------------


def _update_manifest_for_dedup(
    shelf_root: Path, groups: list[DedupGroup],
) -> None:
    """Update manifest hardlinks for ALL shelf entries in each group.  (Fix 7)"""
    manifest = load_manifest(shelf_root)
    models = manifest.setdefault("models", {})
    changed = False

    for group in groups:
        canonical = next(
            (f for f in group.files if _is_in_shelf(f, shelf_root)), None)
        if canonical is None:
            continue
        # Update every shelf file in the group, not just canonical.
        for fpath in group.files:
            if not _is_in_shelf(fpath, shelf_root):
                continue
            repo_id = _path_to_repo_id(fpath, shelf_root)
            if repo_id is None or repo_id not in models:
                continue
            entry = models[repo_id]
            current = set(entry.get("hardlinks", []))
            for other in group.files:
                if other != fpath:
                    current.add(str(other))
            if current != set(entry.get("hardlinks", [])):
                entry["hardlinks"] = sorted(current)
                changed = True

    if changed:
        manifest["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_manifest(shelf_root, manifest)


def execute_dedup(config: Config, result: DedupResult) -> DedupResult:
    """Execute hardlink deduplication for the groups in *result*."""
    check_storage_available(config)
    shelf_root = config.shelf_root

    total_hardlinks = 0
    total_cross_fs = 0
    total_external_only = 0
    executed_groups: list[DedupGroup] = []

    for group in result.groups:
        canonical = next(
            (f for f in group.files if _is_in_shelf(f, shelf_root)), None)
        if canonical is None:
            total_external_only += 1
            executed_groups.append(group)
            continue
        hlinks, cross = _dedup_one_group(group, canonical, shelf_root)
        total_hardlinks += hlinks
        total_cross_fs += cross
        if hlinks > 0:
            executed_groups.append(group)

    if total_hardlinks > 0:
        _update_manifest_for_dedup(shelf_root, executed_groups)

    return DedupResult(
        groups=executed_groups,
        total_duplicate_bytes=result.total_duplicate_bytes,
        potential_savings_bytes=result.potential_savings_bytes,
        skipped_cross_fs=total_cross_fs,
        hardlinks_created=total_hardlinks,
        skipped_external_only=total_external_only,
    )
