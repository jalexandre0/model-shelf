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
import struct
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from model_shelf.resolver import SUPPORTED_FORMATS, Config, check_storage_available


# ---------------------------------------------------------------------------
# GGUF file type → quant string mapping (from llama.cpp gguf.py spec)
# ---------------------------------------------------------------------------

FILETYPE_MAP: dict[int, str] = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    4: "Q4_0",   # Q4_0 alt variant (rare)
    5: "Q4_1",   # Q4_1 alt variant (rare)
    6: "Q4_0",   # Q4_0 alt variant (rare)
    7: "Q8_0",
    8: "Q8_1",
    9: "IQ2_XXS",  # old IQ2_XXS (rare)
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
    19: "Q8_K",
    20: "IQ2_XXS",
    21: "IQ2_XS",
    22: "IQ3_XXS",
    23: "IQ1_S",
    24: "IQ4_XS",
    25: "IQ4_NL",
    26: "IQ3_S",
    27: "IQ3_M",
    28: "IQ2_S",
    29: "IQ2_M",
    30: "IQ4_K_S",
    31: "IQ4_K_M",
}

# GGUF value element sizes in bytes, keyed by type_id
_GGUF_ELEM_SIZES: dict[int, int] = {
    0: 1,    # uint8
    1: 1,    # int8
    2: 2,    # uint16
    3: 2,    # int16
    4: 4,    # uint32
    5: 4,    # int32
    6: 4,    # float32
    7: 8,    # float64 (deprecated, mapping to type_id 10)
    8: 0,    # string (special: length-prefixed)
    9: 0,    # array (special: type + count + items)
    10: 8,   # float64
    11: 1,   # bool
}


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

def _is_gguf_file(path: Path) -> bool:
    """Return True if *path* is a GGUF file, regardless of extension.

    Checks magic bytes (b'GGUF'), not file extension. Works for Ollama blobs
    and any other content-addressed storage that strips extensions.
    """
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"GGUF"
    except OSError:
        return False


def _detect_format_from_path(source: Path) -> str:
    """Detect model format from a local file or directory.

    Rules:
        1. File ending in .gguf → "gguf"
        2. File without extension but with GGUF magic bytes → "gguf"
           (Ollama blobs, content-addressed storage)
        3. Directory with config.json + *.safetensors → "safetensors"
        4. Directory with config.json but no safetensors files → "mlx"
        5. Directory without config.json → ValueError
        6. Other files → ValueError
    """
    if source.is_file():
        if source.suffix.lower() == ".gguf":
            return "gguf"
        if _is_gguf_file(source):
            return "gguf"
        raise ValueError(
            f"unsupported file type for import: {source.suffix or '<no extension>'}; "
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

# Re-exported from manifest.py (single source of truth for manifest I/O)
from model_shelf.manifest import load_manifest as _load_manifest
from model_shelf.manifest import save_manifest as _save_manifest


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
        r"(q[2-8]_[klo]_[ms])",     # Q4_K_M, Q5_K_L (3-segment, MUST come first)
        r"(q[2-8]_[0-1])",          # Q5_0, Q8_0
        r"(q[2-8]_k)(?![a-z0-9])",  # Q2_K, Q6_K, Q8_K (2-segment, no trailing char)
        r"(iq[1-4]_[a-z]+)",         # IQ3_XXS, IQ4_XS
        r"(f16|f32|fp16|fp32)",     # F16, F32
    ]
    for pat in patterns:
        m = re.search(pat, name)
        if m:
            return m.group(1).upper()
    return None


def _quant_from_gguf_header(path: Path) -> str | None:
    """Parse GGUF v2/v3 binary header to extract general.file_type.

    Returns the quant string from FILETYPE_MAP, or None if not found / not a GGUF.
    Never raises — catches OSError, struct.error, UnicodeDecodeError.
    """
    try:
        with open(path, "rb") as f:
            # 1. Magic
            magic = f.read(4)
            if magic != b"GGUF":
                return None

            # 2. Version (uint32 LE)
            version_raw = f.read(4)
            if len(version_raw) < 4:
                return None
            version = struct.unpack("<I", version_raw)[0]
            if version not in (2, 3):
                return None

            # 3. Tensor count (uint64 LE)
            f.read(8)  # skip tensor_count (uint64 LE)

            # 4. KV count (uint64 LE)
            kv_raw = f.read(8)
            if len(kv_raw) < 8:
                return None
            kv_count = struct.unpack("<Q", kv_raw)[0]

            # 5. Iterate KV pairs
            for _ in range(kv_count):
                key_len_raw = f.read(8)
                if len(key_len_raw) < 8:
                    return None
                key_len = struct.unpack("<Q", key_len_raw)[0]
                key_raw = f.read(key_len)
                if len(key_raw) < key_len:
                    return None
                key = key_raw.decode("utf-8")

                type_raw = f.read(4)
                if len(type_raw) < 4:
                    return None
                type_id = struct.unpack("<I", type_raw)[0]

                if key == "general.file_type" and type_id == 4:  # uint32
                    val_raw = f.read(4)
                    if len(val_raw) < 4:
                        return None
                    file_type = struct.unpack("<I", val_raw)[0]
                    return FILETYPE_MAP.get(file_type)

                # Skip value by type_id
                _skip_gguf_value(f, type_id)

            return None
    except (OSError, struct.error, UnicodeDecodeError):
        return None


def _skip_gguf_value(f, type_id: int) -> None:
    """Skip a single GGUF value of the given type_id, consuming bytes from f."""
    if type_id == 8:  # string
        str_len_raw = f.read(8)
        if len(str_len_raw) >= 8:
            str_len = struct.unpack("<Q", str_len_raw)[0]
            f.read(str_len)
    elif type_id == 9:  # array
        elem_type_raw = f.read(4)
        count_raw = f.read(8)
        if len(elem_type_raw) >= 4 and len(count_raw) >= 8:
            elem_type = struct.unpack("<I", elem_type_raw)[0]
            count = struct.unpack("<Q", count_raw)[0]
            esize = _GGUF_ELEM_SIZES.get(elem_type, 4)
            f.read(count * esize)
    else:
        size = _GGUF_ELEM_SIZES.get(type_id, 0)
        if size > 0:
            f.read(size)


def _quant_from_config_json(path: Path) -> str | None:
    """Extract quantization info from path/config.json (MLX or safetensors dir).

    Priority chain:
        1. MLX quantization.bits → "Q{bits}"
        2. Quantization config (GPTQ, AWQ, etc.) → "{METHOD}-{bits}bit"
        3. torch_dtype → mapped to "F16"/"BF16"/"F32"
        4. None of above → None

    Never raises — returns None for missing file, invalid JSON, or no match.
    """
    config_file = path / "config.json"
    try:
        if not config_file.is_file():
            return None
        data = json.loads(config_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    # 1. MLX quantization
    quant_obj = data.get("quantization")
    if isinstance(quant_obj, dict) and "bits" in quant_obj:
        bits = quant_obj["bits"]
        return f"Q{bits}"

    # 2. Quantization config (GPTQ, AWQ, etc.)
    quant_cfg = data.get("quantization_config")
    if isinstance(quant_cfg, dict):
        method = quant_cfg.get("quant_method", "")
        bits = quant_cfg.get("bits")
        if method and bits is not None:
            return f"{method.upper()}-{bits}bit"

    # 3. torch_dtype
    dtype = data.get("torch_dtype")
    if isinstance(dtype, str):
        dtype_map: dict[str, str] = {
            "float16": "F16",
            "bfloat16": "BF16",
            "float32": "F32",
        }
        if dtype in dtype_map:
            return dtype_map[dtype]

    return None


def detect_quant(source: Path, fmt: str) -> str | None:
    """Unified quant detection — dispatches based on format.

    Priority chain per format:
        gguf:        1. GGUF header → 2. filename fallback
        mlx:          config.json
        safetensors:  config.json
        else:         None
    """
    if fmt == "gguf":
        from_header = _quant_from_gguf_header(source)
        if from_header is not None:
            return from_header
        return _detect_quant_from_filename(source)
    if fmt in ("mlx", "safetensors"):
        return _quant_from_config_json(source)
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
    if quant is None:
        quant = detect_quant(source, fmt)
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
        "quant": quant,
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
