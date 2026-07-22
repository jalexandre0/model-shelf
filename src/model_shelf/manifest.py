"""Manifest I/O — single source of truth for reading/writing manifest.json.

Public API:
    load_manifest()       – load manifest.json, returns dict
    save_manifest()       – atomic write to manifest.json
    get_manifest_entry()  – look up a single entry by repo_id
    add_manifest_entry()  – add/overwrite an entry
    remove_manifest_entry() – remove an entry
    rebuild_manifest()    – walk shelf, build/update manifest from disk

Other modules (import_model, future audit/dedup/remove/gc) must import from
here — never read or write manifest.json directly.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import struct
import tempfile

from dataclasses import dataclass, field
from pathlib import Path

from model_shelf.resolver import Config

MANIFEST_PATH = "manifest.json"  # relative to shelf_root


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ManifestResult:
    """Result of a manifest rebuild operation."""

    status: str  # "ok" | "error"
    models_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "models_count": self.models_count,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# GGUF reader helpers (for params extraction during rebuild)
# ---------------------------------------------------------------------------

_GGUF_ELEM_SIZES: dict[int, int] = {
    0: 1,
    1: 1,
    2: 2,
    3: 2,
    4: 4,
    5: 4,
    6: 4,
    7: 8,
    8: 0,
    9: 0,
    10: 8,
    11: 1,
}


def _read_gguf_string(f) -> str:
    """Read a length-prefixed UTF-8 string from a GGUF file."""
    raw = f.read(8)
    if len(raw) < 8:
        return ""
    strlen = struct.unpack("<Q", raw)[0]
    return f.read(strlen).decode("utf-8", errors="replace")


def _skip_gguf_value(f, type_id: int) -> None:
    """Skip a single GGUF value of the given type_id."""
    if type_id == 8:  # string
        raw = f.read(8)
        if len(raw) >= 8:
            f.read(struct.unpack("<Q", raw)[0])
    elif type_id == 9:  # array
        f.read(12)  # elem_type (4) + count (8)
    else:
        size = _GGUF_ELEM_SIZES.get(type_id, 0)
        if size > 0:
            f.read(size)


def _read_gguf_params(path: Path) -> dict | None:
    """Extract params metadata from a GGUF header (architecture, etc.).

    Returns a dict with keys like 'architecture', or None if unparseable.
    """
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return None
            version_raw = f.read(4)
            if len(version_raw) < 4:
                return None
            version = struct.unpack("<I", version_raw)[0]
            if version not in (2, 3):
                return None
            f.read(8)  # tensor_count
            kv_raw = f.read(8)
            if len(kv_raw) < 8:
                return None
            kv_count = struct.unpack("<Q", kv_raw)[0]

            params: dict = {}
            for _ in range(kv_count):
                key = _read_gguf_string(f)
                type_raw = f.read(4)
                if len(type_raw) < 4:
                    return params if params else None
                type_id = struct.unpack("<I", type_raw)[0]

                if key == "general.architecture" and type_id == 8:
                    val = _read_gguf_string(f)
                    params["architecture"] = val
                else:
                    _skip_gguf_value(f, type_id)
            return params if params else None
    except (OSError, struct.error, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Directory SHA256 (custom for rebuild — also excludes .cache/)
# ---------------------------------------------------------------------------

def _sha256_dir_for_rebuild(path: Path) -> str:
    """SHA256 over all regular files sorted by path, excluding dot-prefixed
    files/dirs and .cache/ subtrees."""
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        # Exclude anything inside a .cache/ directory
        if any(part.startswith(".cache") for part in f.parts):
            continue
        if f.is_file() and not f.name.startswith("._"):
            h.update(f.name.encode())
            with open(f, "rb") as fh:
                while chunk := fh.read(65536):
                    h.update(chunk)
    return h.hexdigest()


def _list_dir_files(path: Path) -> list[str]:
    """Return sorted list of non-dot filenames under path, excluding .cache/."""
    files: list[str] = []
    for f in sorted(path.rglob("*")):
        if any(part.startswith(".cache") for part in f.parts):
            continue
        if f.is_file() and not f.name.startswith("._"):
            files.append(str(f.relative_to(path)))
    return files


# ---------------------------------------------------------------------------
# Core I/O
# ---------------------------------------------------------------------------

def load_manifest(shelf_root: Path) -> dict:
    """Load manifest.json from shelf_root. Returns empty dict if missing.

    Raises ValueError if manifest version is not 1.
    """
    manifest_path = shelf_root / MANIFEST_PATH
    if not manifest_path.is_file():
        return {"version": 1, "updated": "", "models": {}}
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError:
        raise ValueError(
            f"failed to parse {manifest_path}: file contains invalid JSON"
        )
    if not isinstance(manifest, dict):
        raise ValueError(
            f"failed to parse {manifest_path}: expected a JSON object"
        )
    if manifest.get("version") != 1:
        raise ValueError(
            f"unsupported manifest version: {manifest.get('version')}; "
            "expected version 1"
        )
    return manifest


def save_manifest(shelf_root: Path, data: dict) -> None:
    """Atomic write: manifest.json.tmp → os.replace → manifest.json.

    Uses NamedTemporaryFile with delete=False, then os.fsync + os.replace.
    Never leaves a partial .tmp file on error — the exception handler unlinks it.
    """
    manifest_path = shelf_root / MANIFEST_PATH
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
# CRUD helpers
# ---------------------------------------------------------------------------

def get_manifest_entry(shelf_root: Path, repo_id: str) -> dict | None:
    """Return the manifest entry for repo_id, or None if not found."""
    manifest = load_manifest(shelf_root)
    return manifest.get("models", {}).get(repo_id)


def add_manifest_entry(shelf_root: Path, repo_id: str, entry: dict) -> None:
    """Add or overwrite a manifest entry for repo_id. Saves atomically."""
    manifest = load_manifest(shelf_root)
    manifest.setdefault("models", {})[repo_id] = entry
    manifest["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_manifest(shelf_root, manifest)


def remove_manifest_entry(shelf_root: Path, repo_id: str) -> None:
    """Remove a manifest entry for repo_id. No-op if not present. Saves atomically."""
    manifest = load_manifest(shelf_root)
    if repo_id in manifest.get("models", {}):
        del manifest["models"][repo_id]
        manifest["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_manifest(shelf_root, manifest)


# ---------------------------------------------------------------------------
# Shared helpers (used by audit, remove, gc)
# ---------------------------------------------------------------------------

def build_tracked_path_set(shelf_root: Path, models: dict) -> set[str]:
    """Build a set of absolute str paths for every file listed in the manifest.

    This is the canonical implementation shared by audit.py and gc.py.
    """
    from model_shelf.resolver import SUPPORTED_FORMATS  # noqa: PLC0415

    tracked: set[str] = set()
    for entry in models.values():
        fmt = entry.get("format", "")
        if fmt not in SUPPORTED_FORMATS:
            continue
        repo_id = entry.get("repo_id", "")
        if "/" not in repo_id:
            continue
        publisher, _, repo_name = repo_id.partition("/")
        model_dir = shelf_root / fmt / publisher / repo_name
        for fname in entry.get("files", []):
            tracked.add(str(model_dir / fname))
    return tracked


def should_skip_shelf_path(path: Path) -> bool:
    """Return True if *path* should be excluded from shelf scans.

    Rules (conservative, shared by audit and GC):
      - macOS resource forks:  ._ prefix on filename
      - .cache/ anywhere in path (HF resumability metadata)
      - Dot-prefixed directories anywhere in path (hidden dirs)
    """
    if path.name.startswith("._"):
        return True
    for part in path.parts:
        if part.startswith(".cache"):
            return True
        if part.startswith(".") and part != "." and part != "..":
            return True
    return False


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------

def _discover_models_on_disk(shelf_root: Path) -> dict[str, dict]:
    """Walk shelf_root/{gguf,mlx,safetensors}/ and return {repo_id: entry_dict}.

    Each entry dict has keys: repo_id, format, quant, sha256, files, size_bytes, params.
    """
    discovered: dict[str, dict] = {}
    formats = ("gguf", "mlx", "safetensors")

    for fmt in formats:
        fmt_dir = shelf_root / fmt
        if not fmt_dir.is_dir():
            continue

        for publisher in sorted(fmt_dir.iterdir()):
            if not publisher.is_dir() or publisher.name.startswith("."):
                continue

            for repo in sorted(publisher.iterdir()):
                if not repo.is_dir() or repo.name.startswith("."):
                    continue

                if fmt == "gguf":
                    _discover_gguf_models(
                        discovered, fmt_dir, publisher, repo, fmt
                    )
                else:
                    _discover_dir_models(
                        discovered, publisher, repo, fmt
                    )

    return discovered


def _discover_gguf_models(
    discovered: dict[str, dict],
    fmt_dir: Path,
    publisher: Path,
    repo: Path,
    fmt: str,
) -> None:
    """Discover GGUF models: each .gguf file is a separate model entry."""
    # Lazy import to avoid circular import with import_model
    from model_shelf.import_model import detect_quant, _sha256_file  # noqa: PLC0415

    gguf_files = sorted(
        f for f in repo.glob("*.gguf")
        if not f.name.startswith("._")
    )
    for gguf_path in gguf_files:
        stem = gguf_path.stem
        repo_id = f"{publisher.name}/{stem}"

        quant = detect_quant(gguf_path, "gguf")
        sha256_hex = _sha256_file(gguf_path)
        size_bytes = gguf_path.stat().st_size
        files = [gguf_path.name]
        params = _read_gguf_params(gguf_path)

        entry: dict = {
            "repo_id": repo_id,
            "format": fmt,
            "sha256": sha256_hex,
            "files": files,
            "size_bytes": size_bytes,
        }
        if quant:
            entry["quant"] = quant
        if params:
            entry["params"] = params

        discovered[repo_id] = entry


def _discover_dir_models(
    discovered: dict[str, dict],
    publisher: Path,
    repo: Path,
    fmt: str,
) -> None:
    """Discover MLX or safetensors models in a directory."""
    # Lazy import to avoid circular import with import_model
    from model_shelf.import_model import detect_quant  # noqa: PLC0415

    config_json = repo / "config.json"
    if not config_json.is_file():
        return

    has_safetensors = any(repo.glob("*.safetensors"))

    # When walking the shelf, format is determined by the parent directory.
    # MLX models may legitimately contain .safetensors files (weights format).
    # Only reject safetensors/ dirs that lack .safetensors files.
    if fmt == "safetensors" and not has_safetensors:
        # Directory has config.json but no .safetensors — skip
        return

    repo_id = f"{publisher.name}/{repo.name}"

    quant = detect_quant(repo, fmt)
    sha256_hex = _sha256_dir_for_rebuild(repo)
    files = _list_dir_files(repo)
    size_bytes = sum(
        (repo / fname).stat().st_size
        for fname in files
        if (repo / fname).is_file()
    )
    params = _read_config_params(config_json)

    entry: dict = {
        "repo_id": repo_id,
        "format": fmt,
        "sha256": sha256_hex,
        "files": files,
        "size_bytes": size_bytes,
    }
    if quant:
        entry["quant"] = quant
    if params:
        entry["params"] = params

    discovered[repo_id] = entry


def _read_config_params(config_json: Path) -> dict | None:
    """Extract params metadata from a config.json file.

    Returns a dict with model metadata keys (model_type, num_hidden_layers, etc.),
    or None if unparseable.
    """
    try:
        data = json.loads(config_json.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    param_keys = (
        "model_type",
        "num_hidden_layers",
        "hidden_size",
        "num_attention_heads",
        "num_key_value_heads",
        "intermediate_size",
        "vocab_size",
        "max_position_embeddings",
        "architectures",
    )
    params: dict = {}
    for k in param_keys:
        if k in data:
            params[k] = data[k]

    return params if params else None


def rebuild_manifest(config: Config) -> ManifestResult:
    """Walk shelf, discover models, rebuild manifest.json.

    Strategy:
      - Discover all models on disk (walking gguf/, mlx/, safetensors/).
      - For models already in the manifest whose files still exist on disk,
        preserve the EXISTING entry (to keep metadata like hardlinks, source, etc.).
      - For models on disk not in manifest, add new entries.
      - For manifest entries whose files no longer exist on disk, remove them.
    """
    shelf_root = config.shelf_root
    errors: list[str] = []

    # Load existing manifest
    try:
        existing = load_manifest(shelf_root)
    except ValueError as e:
        return ManifestResult(status="error", models_count=0, errors=[str(e)])

    existing_models = existing.get("models", {})

    # Discover current state on disk
    discovered = _discover_models_on_disk(shelf_root)

    # Build new manifest models dict
    new_models: dict[str, dict] = {}

    for repo_id, new_entry in discovered.items():
        if repo_id in existing_models:
            # Preserve existing entry (keeps hardlinks, source, imported, etc.)
            preserved = dict(existing_models[repo_id])
            # Update fields that are derived from disk content
            preserved["sha256"] = new_entry["sha256"]
            preserved["files"] = new_entry["files"]
            preserved["size_bytes"] = new_entry["size_bytes"]
            if "quant" in new_entry:
                preserved["quant"] = new_entry["quant"]
            if "params" in new_entry:
                preserved["params"] = new_entry["params"]
            new_models[repo_id] = preserved
        else:
            # New model — add with rebuild metadata
            entry = dict(new_entry)
            entry["source"] = "rebuild"
            entry.setdefault("hardlinks", [])
            new_models[repo_id] = entry

    # Remove entries for models no longer on disk, track as warnings
    for repo_id in existing_models:
        if repo_id not in discovered:
            errors.append(
                f"model '{repo_id}' was removed from disk — entry dropped from manifest"
            )

    # Save
    manifest_data: dict = {
        "version": 1,
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "models": new_models,
    }
    save_manifest(shelf_root, manifest_data)

    return ManifestResult(
        status="ok",
        models_count=len(new_models),
        errors=errors,
    )
