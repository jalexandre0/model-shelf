"""Tests for import_model — format detection, SHA256, hardlink, duplicate skip."""

from pathlib import Path

import pytest

from model_shelf.import_model import (
    ImportResult,
    _detect_format_from_path,
    _load_manifest,
    _sha256_file,
    _sha256_directory,
    import_model,
)
from model_shelf.resolver import Config, init_shelf


# --- helpers ---------------------------------------------------------------

def _config(tmp_path: Path, *, allow_downloads: bool = False) -> Config:
    shelf = tmp_path / "shelf"
    shelf.mkdir(parents=True, exist_ok=True)
    return Config(shelf_root=shelf, allow_downloads=allow_downloads)


# --- format detection -------------------------------------------------------

def test_detect_format_gguf_file(tmp_path: Path):
    source = tmp_path / "model.gguf"
    source.write_bytes(b"mock")
    assert _detect_format_from_path(source) == "gguf"


def test_detect_format_mlx_dir(tmp_path: Path):
    source = tmp_path / "model-dir"
    source.mkdir()
    (source / "config.json").write_text("{}")
    assert _detect_format_from_path(source) == "mlx"


def test_detect_format_safetensors_dir(tmp_path: Path):
    source = tmp_path / "model-dir"
    source.mkdir()
    (source / "config.json").write_text("{}")
    (source / "model.safetensors").write_bytes(b"weights")
    assert _detect_format_from_path(source) == "safetensors"


def test_detect_format_rejects_unknown_file(tmp_path: Path):
    source = tmp_path / "model.bin"
    source.write_bytes(b"x")
    with pytest.raises(ValueError, match="unsupported file type"):
        _detect_format_from_path(source)


def test_detect_format_rejects_dir_without_config_json(tmp_path: Path):
    source = tmp_path / "some-folder"
    source.mkdir()
    (source / "random.bin").write_bytes(b"x")
    with pytest.raises(ValueError, match="config.json"):
        _detect_format_from_path(source)


# --- SHA256 -----------------------------------------------------------------

def test_sha256_file_is_stable(tmp_path: Path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    a = _sha256_file(f)
    b = _sha256_file(f)
    assert a == b
    assert len(a) == 64


def test_sha256_directory(tmp_path: Path):
    d = tmp_path / "dir"
    d.mkdir()
    (d / "a.txt").write_text("hello")
    (d / "b.txt").write_text("world")
    h = _sha256_directory(d)
    assert len(h) == 64


# --- Test 1: import gguf file -----------------------------------------------

def test_import_gguf_file(tmp_path: Path):
    """Import a single .gguf file. Verifies shelf path, manifest entry, SHA256 matches."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "Qwen3-14B-Q4_K_M.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mock gguf content" * 100)

    result = import_model(cfg, source, org="Qwen", repo="Qwen3-14B-GGUF", quant="Q4_K_M", dry_run=False)

    assert result.status == "imported"
    assert result.repo_id == "Qwen/Qwen3-14B-GGUF"
    assert result.format == "gguf"
    assert result.path is not None
    assert result.path.exists()
    assert result.path.name == "Qwen3-14B-Q4_K_M.gguf"

    # Manifest entry exists
    manifest = _load_manifest(cfg.shelf_root)
    entry = manifest["models"]["Qwen/Qwen3-14B-GGUF"]
    assert entry["format"] == "gguf"
    assert entry["sha256"] == result.sha256


# --- Test 2: import mlx directory -------------------------------------------

def test_import_mlx_directory(tmp_path: Path):
    """Import a directory with config.json (MLX). All files should be ingested."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "mlx-community" / "Qwen3-14B-4bit"
    source.mkdir(parents=True)
    (source / "config.json").write_text('{"model_type": "qwen3"}')
    (source / "model.safetensors").write_bytes(b"mock weights")
    (source / "tokenizer.json").write_text('{"vocab_size": 151936}')
    # Detection: dir with config.json + .safetensors = safetensors.
    # Pass --format mlx to override.

    result = import_model(cfg, source, org="mlx-community", repo="Qwen3-14B-4bit", format="mlx", dry_run=False)

    assert result.status == "imported"
    assert result.format == "mlx"

    dest = cfg.shelf_root / "mlx" / "mlx-community" / "Qwen3-14B-4bit"
    assert dest.is_dir()
    assert (dest / "config.json").is_file()
    assert (dest / "model.safetensors").is_file()
    assert (dest / "tokenizer.json").is_file()


# --- Test 3: import rejects dir without config.json -------------------------

def test_import_rejects_dir_without_config_json(tmp_path: Path):
    """A directory without config.json should be rejected (can't determine format)."""
    cfg = _config(tmp_path)

    source = tmp_path / "source" / "some-folder"
    source.mkdir(parents=True)
    (source / "random.bin").write_bytes(b"not a model")

    with pytest.raises(ValueError, match="config.json"):
        import_model(cfg, source)


# --- Test 4: hardlink same filesystem ---------------------------------------

def test_import_hardlink_same_fs(tmp_path: Path):
    """On the same filesystem, hardlink=True should use os.link (same inode)."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content")

    result = import_model(cfg, source, org="test", repo="model-gguf", quant="Q4_0", dry_run=False)

    assert result.status == "imported"
    # Same inode → hardlinked
    assert source.stat().st_ino == result.path.stat().st_ino


# --- Test 5: skip duplicate -------------------------------------------------

def test_import_skips_duplicate(tmp_path: Path):
    """Importing the same file twice should return 'skipped_duplicate' on second call."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"unique content")

    result1 = import_model(cfg, source, org="test", repo="model-gguf", quant="Q4_0", dry_run=False)
    assert result1.status == "imported"

    # Second import of identical file
    result2 = import_model(cfg, source, org="test", repo="model-gguf-v2", quant="Q4_0", dry_run=False)
    assert result2.status == "skipped_duplicate"
    assert "duplicate" in result2.message.lower()
    assert result2.sha256 == result1.sha256


# --- Test 6: manifest updated correctly -------------------------------------

def test_import_updates_manifest(tmp_path: Path):
    """After import, manifest.json should have the new entry with correct fields."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model-Q4_0.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content for manifest test" * 50)

    result = import_model(cfg, source, org="test-org", repo="test-model", dry_run=False)

    manifest = _load_manifest(cfg.shelf_root)
    assert "test-org/test-model" in manifest["models"]
    entry = manifest["models"]["test-org/test-model"]
    assert entry["format"] == "gguf"
    assert entry["sha256"] == result.sha256
    assert entry["source"] == "imported"
    assert entry["quant"] == "Q4_0"
    assert "size_bytes" in entry
    assert "files" in entry
    assert isinstance(entry["files"], list)


# --- Test 7: org override ---------------------------------------------------

def test_import_org_override(tmp_path: Path):
    """--org override should be respected even when source path suggests otherwise."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    # Source path suggests org="bartowski" but we override
    source = tmp_path / "bartowski" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content")

    result = import_model(cfg, source, org="custom-org", repo="custom-repo", quant="Q4_0", dry_run=False)

    assert result.repo_id == "custom-org/custom-repo"
    # Shelf path uses override
    dest = cfg.shelf_root / "gguf" / "custom-org" / "custom-repo"
    assert dest.exists()


# --- Test 8: auto-detect quant ---------------------------------------------

def test_import_auto_detect_quant(tmp_path: Path):
    """Quant should be auto-detected from GGUF filename when not explicitly passed."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "Qwen3-14B-Q5_K_M.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content" * 20)

    # Don't pass quant — should be detected from filename
    result = import_model(cfg, source, org="Qwen", repo="Qwen3-14B-GGUF", dry_run=False)

    assert result.status == "imported"
    manifest = _load_manifest(cfg.shelf_root)
    entry = manifest["models"]["Qwen/Qwen3-14B-GGUF"]
    assert entry["quant"] == "Q5_K_M"


# --- Integration: from __init__ --------------------------------------------

def test_import_model_accessible_from_init():
    """Verify ImportResult and import_model are exposed via the top-level package."""
    from model_shelf import ImportResult as IR, import_model as im
    assert IR is ImportResult
    assert im is import_model


# --- Integration: CLI subcommand exists ------------------------------------

def test_cli_import_subcommand_registered():
    """Verify 'import' subcommand is recognised by the CLI parser."""
    from model_shelf.cli import main

    # Just checking the subparser is registered — missing required path should
    # not crash with "unknown command".
    with pytest.raises(SystemExit) as exc:
        main(["import"])
    # argparse exits with 2 when a required positional arg is missing.
    assert exc.value.code == 2


# --- dry-run ----------------------------------------------------------------

def test_import_dry_run_computes_but_does_not_write(tmp_path: Path):
    """dry_run=True should compute SHA256 and dest path but NOT ingest or write manifest."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"dry run test content" * 20)

    result = import_model(cfg, source, org="test", repo="model-gguf", quant="Q4_0", dry_run=True)

    assert result.status == "dry_run"
    assert result.path is not None
    assert not result.path.exists()  # nothing written to disk
    assert len(result.sha256) == 64
    assert "Would import" in result.message

    # Manifest must NOT be updated.
    manifest = _load_manifest(cfg.shelf_root)
    assert len(manifest["models"]) == 0


def test_import_dry_run_detects_duplicate_without_writing(tmp_path: Path):
    """Even with dry_run=True, duplicate detection via manifest should work."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"unique dry run dup check" * 30)

    # First, do a real import.
    result1 = import_model(cfg, source, org="test", repo="model-gguf", quant="Q4_0", dry_run=False)
    assert result1.status == "imported"

    # Now dry-run the same file — should detect duplicate.
    result2 = import_model(cfg, source, org="test", repo="model-gguf-v2", quant="Q4_0", dry_run=True)
    # Dry-run still hits the duplicate path before the dry_run check because
    # duplicate check happens first (step 5 before step 7).
    assert result2.status == "skipped_duplicate"


# --- org inference: hyphenated parent dir ----------------------------------

def test_infer_org_from_hyphenated_parent_dir(tmp_path: Path):
    """Directory import should detect hyphenated parent dir as publisher.

    Regression test: _infer_org_repo_dir was missing the hyphen heuristic
    at the parent level that _infer_org_repo_gguf already had.
    """
    cfg = _config(tmp_path)
    init_shelf(cfg)

    #/mlx-community/repo (hyphen in parent)
    source = tmp_path / "mlx-community" / "Qwen3-14B-4bit"
    source.mkdir(parents=True)
    (source / "config.json").write_text("{}")

    result = import_model(cfg, source, format="mlx", dry_run=False)

    assert result.repo_id == "mlx-community/Qwen3-14B-4bit"
    dest = cfg.shelf_root / "mlx" / "mlx-community" / "Qwen3-14B-4bit"
    assert dest.is_dir()


def test_infer_org_from_hyphenated_parent_dir_gguf(tmp_path: Path):
    """GGUF import should detect hyphenated parent dir as publisher (already works)."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "lmstudio-community" / "model-Q4_K_M.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"gguf hyphen org test")

    result = import_model(cfg, source, quant="Q4_K_M", dry_run=False)

    assert result.repo_id == "lmstudio-community/model-Q4_K_M"
    dest = cfg.shelf_root / "gguf" / "lmstudio-community" / "model-Q4_K_M"
    assert (dest / "model-Q4_K_M.gguf").is_file()


# --- error: missing source file --------------------------------------------

def test_import_missing_source_file_raises(tmp_path: Path):
    """Importing a non-existent path should raise ValueError with clear message."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    missing = tmp_path / "nonexistent" / "model.gguf"
    with pytest.raises(ValueError, match="does not exist"):
        import_model(cfg, missing, dry_run=False)
