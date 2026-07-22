"""Import a local model file or directory into the curated shelf.

Supports:
    gguf         single .gguf file
    mlx          directory with config.json (no .safetensors files)
    safetensors  directory with config.json + .safetensors files

Performs format detection, SHA256 hashing, duplicate detection via manifest,
and ingests files via hardlink (same filesystem) or copy.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile

from dataclasses import dataclass, field
from pathlib import Path

from model_shelf.resolver import SUPPORTED_FORMATS, Config, check_storage_available


@dataclass
class ImportResult:
    status: str       # "imported" | "skipped_duplicate" | "error"
    repo_id: str      # inferred "org/repo" (e.g. "Qwen/Qwen3-14B-GGUF")
    format: str       # "gguf" | "mlx" | "safetensors"
    path: Path | None  # new shelf path (None on error/skip)
    sha256: str       # hex digest of primary file or all files concat
    message: str      # human-readable explanation
    checks: list[dict] = field(default_factory=list)  # detail about each step

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "repo_id": self.repo_id,
            "format": self.format,
            "path": str(self.path) if self.path else None,
            "sha256": self.sha256,
            "message": self.message,
            "checks": list(self.checks),
        }


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def _detect_format_from_path(source: Path) -> str:
    """Detect model format from a local file or directory.

    Rules:
        1. File ending in .gguf → "gguf"
        2. Directory with config.json + *.safetensors → "safetensors"
        3. Directory with config.json but no safetensors files → "mlx"
        4. Directory without config.json → ValueError
        5. Non-.gguf file → ValueError
    """
    if source.is_file():
        if source.suffix.lower() == ".gguf":
            return "gguf"
        raise ValueError(
            f"unsupported file type for import: {source.suffix}; "
            "only .gguf files are supported for single-file import"
        )

    if source.is_dir():
        has_config = (source / "config.json").is_file()
        if not has_config:
            raise ValueError(
                f"directory lacks config.json — cannot determine format: {source}"
            )
        safetensors_files = list(source.glob("*.safetensors"))
        if safetensors_files:
            return "safetensors"
        return "mlx"

    raise ValueError(f"source path does not exist: {source}")


# ---------------------------------------------------------------------------
# SHA256 helpers
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """Return lowercase hex SHA256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _sha256_directory(path: Path) -> str:
    """Return SHA256 over all regular files (sorted by name, concatenated)."""
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file() and not f.name.startswith("._"):
            h.update(f.name.encode())
            with open(f, "rb") as fh:
                while chunk := fh.read(65536):
                    h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _load_manifest(shelf_root: Path) -> dict:
    """Load manifest.json from shelf_root. Returns empty dict if missing."""
    manifest_path = shelf_root / "manifest.json"
    if not manifest_path.is_file():
        return {"version": 1, "updated": "", "models": {}}
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != 1:
        raise ValueError(
            f"unsupported manifest version: {manifest.get('version')}; "
            "expected version 1"
        )
    return manifest


def _save_manifest(shelf_root: Path, data: dict) -> None:
    """Atomic write: manifest.json.tmp → os.replace → manifest.json."""
    manifest_path = shelf_root / "manifest.json"
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(shelf_root),
        prefix="manifest.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(manifest_path))
    except Exception:
        os.unlink(tmp.name)
        raise


# ---------------------------------------------------------------------------
# Org / repo inference
# ---------------------------------------------------------------------------

_KNOWN_PUBLISHERS = frozenset({
    "bartowski",
    "mlx-community",
    "lmstudio-community",
    "unsloth",
})


def _infer_org_repo(
    source: Path,
    fmt: str,
    org: str | None,
    repo: str | None,
) -> tuple[str, str]:
    """Infer (org, repo) from source path, respecting overrides.

    Strategy:
        1. If --org and --repo are both passed → use them directly.
        2. If only --org is passed:
           - repo = source.stem (gguf) or source.parent.name (dir)
        3. If neither is passed:
           - Look at parent dir names for known publishers.
           - Fallback: org = "local", repo = source.stem or source.name.
    """
    if org is not None and repo is not None:
        return org, repo

    if fmt == "gguf":
        return _infer_org_repo_gguf(source, org, repo)
    return _infer_org_repo_dir(source, org, repo)


def _infer_org_repo_gguf(
    source: Path,
    org: str | None,
    repo: str | None,
) -> tuple[str, str]:
    stem = source.stem

    if repo is None:
        repo = stem

    if org is not None:
        return org, repo

    # Try parent dir as publisher.
    parent = source.parent.name.lower()
    if parent in _KNOWN_PUBLISHERS or "-" in parent:
        return source.parent.name, repo

    return "local", repo


def _infer_org_repo_dir(
    source: Path,
    org: str | None,
    repo: str | None,
) -> tuple[str, str]:
    if repo is None:
        repo = source.name

    if org is not None:
        return org, repo

    # Try parent dir as publisher.
    parent_name = source.parent.name.lower()
    if parent_name in _KNOWN_PUBLISHERS or "-" in parent_name:
        return source.parent.name, repo

    # Try grandparent as publisher (e.g. source/models/mlx-community/repo).
    if (source.parent.parent.name.lower() in _KNOWN_PUBLISHERS
            or "-" in source.parent.parent.name.lower()):
        return source.parent.parent.name, repo

    return "local", repo


# ---------------------------------------------------------------------------
# Quant detection
# ---------------------------------------------------------------------------

def _detect_quant_from_filename(path: Path) -> str | None:
    """Extract quant tag from GGUF filename.

    Examples:
        Qwen3-14B-Q4_K_M.gguf     → Q4_K_M
        qwen3-8b-q5_1.gguf        → Q5_1
        llama-3.1-8b-f16.gguf     → F16
    """
    name = path.stem.lower()
    patterns = [
        r"(q[2-8]_[klo]_[ms])",     # Q4_K_M, Q5_K_L, etc.
        r"(q[2-8]_[0-1])",          # Q5_0, Q8_0
        r"(iq[1-4]_[a-z]+)",         # IQ3_XXS, IQ4_XS
        r"(f16|f32|fp16|fp32)",     # F16, F32
    ]
    for pat in patterns:
        m = re.search(pat, name)
        if m:
            return m.group(1).upper()
    return None


# ---------------------------------------------------------------------------
# File ingestion
# ---------------------------------------------------------------------------

def _ingest_file(source: Path, dest: Path, *, hardlink: bool) -> None:
    """Copy or hardlink a single file into the shelf. Creates parent dirs."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if hardlink and source.stat().st_dev == dest.parent.stat().st_dev:
        os.link(str(source), str(dest))
    else:
        if hardlink:
            print(
                "model-shelf: warning: source is on a different filesystem "
                "— falling back to copy",
                file=sys.stderr,
            )
        shutil.copy2(str(source), str(dest))


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _validate_source(
    source: Path, format: str | None, checks: list[dict]
) -> tuple[Path, str]:
    """Resolve source, validate existence, detect format. Returns (source, fmt)."""
    source = source.resolve()
    if not source.exists():
        raise ValueError(f"source path does not exist: {source}")
    if format is not None:
        return source, format
    fmt = _detect_format_from_path(source)
    checks.append({"step": "detect-format", "detail": f"auto-detected {fmt}"})
    return source, fmt


def _resolve_metadata(
    source: Path,
    fmt: str,
    org: str | None,
    repo: str | None,
    quant: str | None,
    checks: list[dict],
) -> tuple[str, str, str, str | None]:
    """Infer org/repo/quant. Returns (org_name, repo_name, repo_id, quant)."""
    org_name, repo_name = _infer_org_repo(source, fmt, org, repo)
    repo_id = f"{org_name}/{repo_name}"
    if fmt == "gguf" and quant is None:
        quant = _detect_quant_from_filename(source)
        if quant:
            checks.append({"step": "detect-quant", "detail": f"auto-detected {quant}"})
    return org_name, repo_name, repo_id, quant


def _compute_sha256(source: Path, fmt: str) -> str:
    """Return SHA256 for a model file (gguf) or directory (mlx/safetensors)."""
    if fmt == "gguf":
        return _sha256_file(source)
    return _sha256_directory(source)


def _check_duplicate(manifest: dict, sha256: str) -> str | None:
    """Return existing repo_id if sha256 is already tracked, else None."""
    for entry in manifest["models"].values():
        if entry.get("sha256") == sha256:
            return entry.get("repo_id", "unknown")
    return None


def _compute_total_size(dest_path: Path, fmt: str) -> tuple[int, list[str]]:
    """Return (total_size, files) for the ingested model at dest_path."""
    if fmt == "gguf":
        return dest_path.stat().st_size, [dest_path.name]
    total = sum(
        f.stat().st_size for f in dest_path.rglob("*")
        if f.is_file() and not f.name.startswith("._")
    )
    files = sorted(
        f.name for f in dest_path.rglob("*")
        if f.is_file() and not f.name.startswith("._")
    )
    return total, files


def _build_manifest_entry(
    source: Path,
    repo_id: str,
    fmt: str,
    quant: str | None,
    sha256: str,
    files: list[str],
) -> dict:
    """Build a manifest entry dict for a newly imported model."""
    return {
        "repo_id": repo_id,
        "format": fmt,
        "quant": quant if fmt == "gguf" else None,
        "sha256": sha256,
        "files": files,
        "source": "imported",
        "imported_from": str(source),
        "imported": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "hardlinks": [],
    }


def _dest_path(
    shelf_root: Path, fmt: str, org_name: str, repo_name: str, source: Path
) -> Path:
    """Return the destination path for the model inside the shelf."""
    if fmt == "gguf":
        return shelf_root / "gguf" / org_name / repo_name / source.name
    return shelf_root / fmt / org_name / repo_name


def _ingest_model(
    source: Path, dest_path: Path, fmt: str, hardlink: bool
) -> None:
    """Ingest model files from source into dest_path (hardlink or copy)."""
    if fmt == "gguf":
        _ingest_file(source, dest_path, hardlink=hardlink)
    else:
        for f in sorted(source.rglob("*")):
            if f.is_file() and not f.name.startswith("._"):
                _ingest_file(f, dest_path / f.relative_to(source), hardlink=hardlink)


def _record_manifest(
    shelf_root: Path,
    manifest: dict,
    source: Path,
    repo_id: str,
    fmt: str,
    quant: str | None,
    sha256_hex: str,
    dest_path: Path,
) -> None:
    """Compute size, build entry, save manifest."""
    total_size, files = _compute_total_size(dest_path, fmt)
    entry = _build_manifest_entry(source, repo_id, fmt, quant, sha256_hex, files)
    entry["size_bytes"] = total_size
    manifest["models"][repo_id] = entry
    manifest["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _save_manifest(shelf_root, manifest)


# ---------------------------------------------------------------------------
# Main import function
# ---------------------------------------------------------------------------

def import_model(
    config: Config,
    source: Path,
    *,
    format: str | None = None,
    org: str | None = None,
    repo: str | None = None,
    quant: str | None = None,
    hardlink: bool = True,
    dry_run: bool = False,
) -> ImportResult:
    """Import a model file or directory into the curated shelf."""
    checks: list[dict] = []
    source, fmt = _validate_source(source, format, checks)
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported format: {fmt!r}")
    org_name, repo_name, repo_id, quant = _resolve_metadata(
        source, fmt, org, repo, quant, checks)
    sha256_hex = _compute_sha256(source, fmt)
    checks.append({"step": "sha256", "detail": sha256_hex[:16] + "..."})
    manifest = _load_manifest(config.shelf_root)
    dup_id = _check_duplicate(manifest, sha256_hex)
    if dup_id is not None:
        return ImportResult(
            status="skipped_duplicate", repo_id=repo_id, format=fmt, path=None,
            sha256=sha256_hex, checks=checks,
            message=f"Duplicate of {dup_id} — SHA256 {sha256_hex[:8]} already tracked")
    dest_path = _dest_path(config.shelf_root, fmt, org_name, repo_name, source)
    if dry_run:
        return ImportResult(
            status="dry_run", repo_id=repo_id, format=fmt, path=dest_path,
            sha256=sha256_hex, checks=checks,
            message=f"Would import {source} → {dest_path}")
    _ingest_model(source, dest_path, fmt, hardlink)
    _record_manifest(config.shelf_root, manifest, source, repo_id, fmt, quant,
                     sha256_hex, dest_path)
    return ImportResult(
        status="imported", repo_id=repo_id, format=fmt, path=dest_path,
        sha256=sha256_hex, checks=checks,
        message=f"Imported {source} → {dest_path}")
