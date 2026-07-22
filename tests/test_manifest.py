"""Tests for manifest.py — manifest I/O, rebuild, and CRUD helpers."""

from __future__ import annotations

import json
import os
import struct

from pathlib import Path

import pytest

from model_shelf.manifest import (
    ManifestResult,
    _read_gguf_params,
    add_manifest_entry,
    get_manifest_entry,
    load_manifest,
    rebuild_manifest,
    remove_manifest_entry,
    save_manifest,
)
from model_shelf.resolver import Config, init_shelf


# --- helpers ---------------------------------------------------------------

def _config(tmp_path: Path) -> Config:
    shelf = tmp_path / "shelf"
    shelf.mkdir(parents=True, exist_ok=True)
    return Config(shelf_root=shelf)


# --- Tier 1 - 14 tests -----------------------------------------------------

# 1. Rebuild empty shelf
def test_rebuild_empty_shelf(tmp_path: Path):
    """rebuild_manifest() on shelf with empty subdirs → version 1, updated non-empty, models {}."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    assert result.models_count == 0
    assert result.errors == []

    manifest = load_manifest(cfg.shelf_root)
    assert manifest["version"] == 1
    assert manifest["updated"] != ""
    assert manifest["models"] == {}


# 2. Rebuild with GGUF model
def test_rebuild_with_gguf_model(tmp_path: Path):
    """Create a GGUF file → rebuild picks it up with correct format, quant, sha256, files, size."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    # Create a synthetic GGUF v3 with general.file_type = Q4_K_M (type_id 4, value 15)
    content = _make_gguf({"general.file_type": (4, struct.pack("<I", 15))})
    repo_dir = cfg.shelf_root / "gguf" / "Qwen" / "Qwen3-14B-GGUF"
    repo_dir.mkdir(parents=True)
    gguf_path = repo_dir / "model-Q4_K_M.gguf"
    gguf_path.write_bytes(content)

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    assert result.models_count == 1

    manifest = load_manifest(cfg.shelf_root)
    entry = manifest["models"]["Qwen/model-Q4_K_M"]
    assert entry["format"] == "gguf"
    assert entry["quant"] == "Q4_K_M"
    assert entry["files"] == ["model-Q4_K_M.gguf"]
    assert entry["size_bytes"] == len(content)
    assert len(entry["sha256"]) == 64


# 3. Rebuild with MLX model
def test_rebuild_with_mlx_model(tmp_path: Path):
    """Create MLX dir with config.json + model.safetensors + tokenizer.json → format mlx."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    repo_dir = cfg.shelf_root / "mlx" / "mlx-community" / "Qwen3-14B-4bit"
    repo_dir.mkdir(parents=True)
    (repo_dir / "config.json").write_text('{"model_type": "qwen3"}')
    (repo_dir / "model.safetensors").write_bytes(b"mock weights")
    (repo_dir / "tokenizer.json").write_text('{"vocab_size": 151936}')

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    assert result.models_count == 1

    manifest = load_manifest(cfg.shelf_root)
    entry = manifest["models"]["mlx-community/Qwen3-14B-4bit"]
    assert entry["format"] == "mlx"
    assert "config.json" in entry["files"]
    assert "model.safetensors" in entry["files"]
    assert "tokenizer.json" in entry["files"]
    assert len(entry["sha256"]) == 64


# 4. Rebuild skips .cache
def test_rebuild_skips_dot_cache(tmp_path: Path):
    """Model dir with .cache/ subdir → contents excluded from files list and SHA256."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    repo_dir = cfg.shelf_root / "mlx" / "mlx-community" / "Qwen3-14B-4bit"
    repo_dir.mkdir(parents=True)
    (repo_dir / "config.json").write_text('{"model_type": "qwen3"}')
    (repo_dir / "model.safetensors").write_bytes(b"weights")

    cache_dir = repo_dir / ".cache"
    cache_dir.mkdir()
    (cache_dir / "huggingface").mkdir()
    (cache_dir / "huggingface" / "refs").write_text("main-ref")

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    entry = load_manifest(cfg.shelf_root)["models"]["mlx-community/Qwen3-14B-4bit"]
    # .cache contents must not appear in files list
    for fname in entry["files"]:
        assert ".cache" not in fname


# 5. Rebuild skips hidden files
def test_rebuild_skips_hidden_files(tmp_path: Path):
    """Model dir with ._ files → excluded from files list."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    repo_dir = cfg.shelf_root / "gguf" / "test" / "model-repo"
    repo_dir.mkdir(parents=True)
    content = _make_gguf({"general.file_type": (4, struct.pack("<I", 1))})
    (repo_dir / "model-F16.gguf").write_bytes(content)
    (repo_dir / "._.DS_Store").write_text("garbage")
    (repo_dir / "._model.gguf").write_text("garbage")

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    entry = load_manifest(cfg.shelf_root)["models"]["test/model-F16"]
    assert entry["files"] == ["model-F16.gguf"]
    # SHA256 should not be affected by hidden files — just check it's valid
    assert len(entry["sha256"]) == 64


# 6. Rebuild detects params from config.json
def test_rebuild_detects_params_from_config_json(tmp_path: Path):
    """MLX model with config.json containing model_type and num_hidden_layers → params field."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    repo_dir = cfg.shelf_root / "mlx" / "mlx-community" / "Qwen3-14B-4bit"
    repo_dir.mkdir(parents=True)
    (repo_dir / "config.json").write_text(
        json.dumps({"model_type": "qwen3", "num_hidden_layers": 40})
    )

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    entry = load_manifest(cfg.shelf_root)["models"]["mlx-community/Qwen3-14B-4bit"]
    assert "params" in entry
    assert entry["params"]["model_type"] == "qwen3"
    assert entry["params"]["num_hidden_layers"] == 40


# 7. Rebuild detects params from GGUF header
def test_rebuild_detects_params_from_gguf_header(tmp_path: Path):
    """Synthetic GGUF v3 with general.architecture → entry has params field."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    # Build a GGUF with general.architecture = "llama" (type_id 8 = string)
    arch_val = b"llama"
    arch_bytes = struct.pack("<Q", len(arch_val)) + arch_val
    content = _make_gguf({"general.architecture": (8, arch_bytes)})

    repo_dir = cfg.shelf_root / "gguf" / "test" / "model-repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / "model-Q4_0.gguf").write_bytes(content)

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    entry = load_manifest(cfg.shelf_root)["models"]["test/model-Q4_0"]
    assert "params" in entry
    assert entry["params"]["architecture"] == "llama"


# 8. Rebuild handles non-model dirs
def test_rebuild_handles_non_model_dirs(tmp_path: Path):
    """Dir with only readme.md → NOT in manifest, no crash."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    repo_dir = cfg.shelf_root / "mlx" / "someone" / "docs-only"
    repo_dir.mkdir(parents=True)
    (repo_dir / "readme.md").write_text("# docs")

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    manifest = load_manifest(cfg.shelf_root)
    assert "someone/docs-only" not in manifest["models"]


# 9. load_manifest missing file
def test_load_manifest_missing_file(tmp_path: Path):
    """No manifest.json → returns default dict."""
    cfg = _config(tmp_path)
    cfg.shelf_root.mkdir(parents=True, exist_ok=True)

    data = load_manifest(cfg.shelf_root)

    assert data == {"version": 1, "updated": "", "models": {}}


# 10. load_manifest invalid JSON
def test_load_manifest_invalid_json(tmp_path: Path):
    """manifest.json with broken content → raises ValueError."""
    cfg = _config(tmp_path)
    cfg.shelf_root.mkdir(parents=True, exist_ok=True)
    (cfg.shelf_root / "manifest.json").write_text("{broken")

    with pytest.raises(ValueError, match="invalid JSON"):
        load_manifest(cfg.shelf_root)


# 11. load_manifest wrong version
def test_load_manifest_wrong_version(tmp_path: Path):
    """manifest.json with version 2 → raises ValueError."""
    cfg = _config(tmp_path)
    cfg.shelf_root.mkdir(parents=True, exist_ok=True)
    (cfg.shelf_root / "manifest.json").write_text('{"version": 2}')

    with pytest.raises(ValueError, match="unsupported manifest version: 2"):
        load_manifest(cfg.shelf_root)


# 12. save_manifest is atomic
def test_save_manifest_is_atomic(tmp_path: Path):
    """save_manifest writes atomically — no .tmp left behind."""
    cfg = _config(tmp_path)
    cfg.shelf_root.mkdir(parents=True, exist_ok=True)

    data = {"version": 1, "updated": "test", "models": {"a/b": {"repo_id": "a/b"}}}
    save_manifest(cfg.shelf_root, data)

    # Manifest file must exist
    manifest_path = cfg.shelf_root / "manifest.json"
    assert manifest_path.is_file()

    # No temp files left behind
    tmp_files = list(cfg.shelf_root.glob("manifest.*.tmp"))
    assert tmp_files == []

    # Content is correct
    loaded = json.loads(manifest_path.read_text())
    assert loaded["models"]["a/b"]["repo_id"] == "a/b"


# 13. add_entry_to_manifest
def test_add_entry_to_manifest(tmp_path: Path):
    """add_manifest_entry → load_manifest contains entry."""
    cfg = _config(tmp_path)
    cfg.shelf_root.mkdir(parents=True, exist_ok=True)

    entry = {"repo_id": "test/model", "format": "gguf", "sha256": "abcdef"}
    add_manifest_entry(cfg.shelf_root, "test/model", entry)

    manifest = load_manifest(cfg.shelf_root)
    assert "test/model" in manifest["models"]
    assert manifest["models"]["test/model"]["format"] == "gguf"


# 14. remove_entry_from_manifest
def test_remove_entry_from_manifest(tmp_path: Path):
    """Add then remove → entry gone. get_manifest_entry returns None for removed."""
    cfg = _config(tmp_path)
    cfg.shelf_root.mkdir(parents=True, exist_ok=True)

    add_manifest_entry(cfg.shelf_root, "a/b", {"repo_id": "a/b", "format": "gguf"})
    add_manifest_entry(cfg.shelf_root, "c/d", {"repo_id": "c/d", "format": "mlx"})

    # get_manifest_entry works for existing entry
    entry = get_manifest_entry(cfg.shelf_root, "a/b")
    assert entry is not None
    assert entry["format"] == "gguf"

    # get_manifest_entry returns None for missing entry
    assert get_manifest_entry(cfg.shelf_root, "nonexistent") is None

    # Remove one
    remove_manifest_entry(cfg.shelf_root, "a/b")

    # Gone from manifest
    manifest = load_manifest(cfg.shelf_root)
    assert "a/b" not in manifest["models"]
    assert "c/d" in manifest["models"]

    # get_manifest_entry returns None for removed entry
    assert get_manifest_entry(cfg.shelf_root, "a/b") is None

    # Remove non-existent is no-op
    remove_manifest_entry(cfg.shelf_root, "nonexistent")  # should not raise


# --- Tier 2 - 3 CLI integration tests ---------------------------------------

# 15. Rebuild preserves existing manifest fields
def test_rebuild_preserves_existing_manifest_fields(tmp_path: Path):
    """Write manifest with custom 'source' field → rebuild preserves it when model still on disk."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    # Create model on disk
    content = _make_gguf({"general.file_type": (4, struct.pack("<I", 1))})
    repo_dir = cfg.shelf_root / "gguf" / "test" / "model-repo"
    repo_dir.mkdir(parents=True)
    gguf_path = repo_dir / "model-F16.gguf"
    gguf_path.write_bytes(content)

    # Pre-populate manifest with extra field
    existing_manifest = {
        "version": 1,
        "updated": "old",
        "models": {
            "test/model-F16": {
                "repo_id": "test/model-F16",
                "format": "gguf",
                "sha256": "oldsha",
                "files": ["model-F16.gguf"],
                "source": "migrated",
                "hardlinks": ["/some/path"],
            }
        },
    }
    save_manifest(cfg.shelf_root, existing_manifest)

    result = rebuild_manifest(cfg)

    assert result.status == "ok"
    entry = load_manifest(cfg.shelf_root)["models"]["test/model-F16"]
    assert entry["source"] == "migrated"  # preserved
    assert entry["hardlinks"] == ["/some/path"]  # preserved
    # SHA256 should be updated from disk
    assert entry["sha256"] != "oldsha"
    assert len(entry["sha256"]) == 64


# 16. CLI --rebuild flag
def test_manifest_cli_rebuild_flag(tmp_path: Path):
    """main(['manifest', '--rebuild']) → exit 0, manifest.json created."""
    from model_shelf.cli import main

    cfg = _config(tmp_path)
    init_shelf(cfg)

    # Write config so CLI can find the shelf
    config_path = tmp_path / "config.toml"
    from model_shelf.config import write_config
    write_config(config_path, shelf_root=cfg.shelf_root)

    rc = main(["--config", str(config_path), "manifest", "--rebuild"])
    assert rc == 0

    manifest_path = cfg.shelf_root / "manifest.json"
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text())
    assert data["version"] == 1


# 17. CLI --json output
def test_manifest_cli_json_output(tmp_path: Path):
    """main(['manifest', '--json']) → stdout is valid JSON with models key."""
    from model_shelf.cli import main

    cfg = _config(tmp_path)
    init_shelf(cfg)

    config_path = tmp_path / "config.toml"
    from model_shelf.config import write_config
    write_config(config_path, shelf_root=cfg.shelf_root)

    # Capture stdout
    import io
    import sys
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        rc = main(["--config", str(config_path), "manifest", "--json"])
    finally:
        sys.stdout = old_stdout

    assert rc == 0
    output = json.loads(captured.getvalue())
    assert "models" in output
    assert output["version"] == 1


# --- helpers ---------------------------------------------------------------

def _make_gguf(metadata: dict[str, tuple[int, bytes]]) -> bytes:
    """Build a minimal GGUF v3 header with given metadata keys.

    metadata: key → (type_id, value_bytes)
    """
    buf = bytearray()
    buf += b"GGUF"  # magic
    buf += struct.pack("<I", 3)  # version
    buf += struct.pack("<Q", 0)  # tensor_count
    buf += struct.pack("<Q", len(metadata))  # kv_count
    for key, (type_id, val_bytes) in metadata.items():
        key_enc = key.encode()
        buf += struct.pack("<Q", len(key_enc))
        buf += key_enc
        buf += struct.pack("<I", type_id)
        buf += val_bytes
    return bytes(buf)
