"""Tests for gc — run_gc, GCResult, CLI integration."""

from __future__ import annotations

import io
import json
import sys

from pathlib import Path

import pytest

from model_shelf.config import Config
from model_shelf.manifest import load_manifest, save_manifest
from model_shelf.import_model import _sha256_file
from model_shelf.resolver import init_shelf
from model_shelf.gc import GCResult, run_gc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> Config:
    shelf = tmp_path / "shelf"
    return Config(shelf_root=shelf, allow_downloads=False)


def _setup_gguf_model(shelf_root: Path, publisher: str, repo: str,
                       filename: str, content: bytes) -> Path:
    model_path = shelf_root / "gguf" / publisher / repo / filename
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(content)
    return model_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGCDataclass:
    """Tier 1 — pure logic."""

    def test_gc_dataclass_defaults(self):
        r = GCResult()
        assert r.incomplete_downloads == []
        assert r.orphaned_files == []
        assert r.empty_dirs == []
        assert r.total_reclaimable_bytes == 0
        d = r.to_dict()
        assert d["incomplete_downloads"] == []
        assert d["orphaned_files"] == []
        assert d["empty_dirs"] == []
        assert d["total_reclaimable_bytes"] == 0


class TestGCFilesystem:
    """Tier 2 — filesystem integration."""

    def test_gc_finds_orphaned_gguf(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # Create an orphaned GGUF file not tracked in manifest
        orphan = cfg.shelf_root / "gguf" / "pub" / "orphan" / "lonely.gguf"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"orphaned gguf" * 50)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_gc(cfg)
        assert str(orphan) in result.orphaned_files
        assert result.total_reclaimable_bytes > 0

    def test_gc_finds_empty_directories(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # Create an empty repo dir
        empty_dir = cfg.shelf_root / "gguf" / "pub" / "empty-repo"
        empty_dir.mkdir(parents=True)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_gc(cfg)
        assert str(empty_dir) in result.empty_dirs

    def test_gc_skips_non_empty_dirs(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"valid model" * 50
        model_path = _setup_gguf_model(
            cfg.shelf_root, "pub", "repo", "model.gguf", content,
        )
        sha = _sha256_file(model_path)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/repo": {
                    "repo_id": "pub/repo", "format": "gguf",
                    "sha256": sha, "files": ["model.gguf"],
                    "size_bytes": model_path.stat().st_size,
                },
            },
        })

        result = run_gc(cfg)
        # Non-empty dir should not be flagged
        non_empty = cfg.shelf_root / "gguf" / "pub" / "repo"
        assert str(non_empty) not in result.empty_dirs
        # The model file itself should be tracked, not orphaned
        assert str(model_path) not in result.orphaned_files

    def test_gc_skips_dot_dirs(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # Create a .cache/ dir with an orphaned file
        cache_dir = cfg.shelf_root / "gguf" / ".cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "cached-file.bin").write_bytes(b"cached" * 50)

        # Create a dot-prefixed publisher dir
        hidden_dir = cfg.shelf_root / "gguf" / ".hidden" / "repo"
        hidden_dir.mkdir(parents=True)
        (hidden_dir / "model.gguf").write_bytes(b"hidden" * 50)

        # Also create another empty dir (should not be flagged)
        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_gc(cfg)
        for orphaned in result.orphaned_files:
            assert ".cache" not in orphaned
            assert "/." not in orphaned.replace(str(cfg.shelf_root), "")
        for d in result.empty_dirs:
            assert ".cache" not in d
            # Check that hidden dirs are excluded
            rel = Path(d).relative_to(cfg.shelf_root)
            assert not any(part.startswith(".") for part in rel.parts)

    def test_gc_calculates_reclaimable_bytes(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        orphan1 = cfg.shelf_root / "gguf" / "pub" / "orphan1" / "a.gguf"
        orphan1.parent.mkdir(parents=True)
        orphan1.write_bytes(b"a" * 1000)

        orphan2 = cfg.shelf_root / "gguf" / "pub" / "orphan2" / "b.gguf"
        orphan2.parent.mkdir(parents=True)
        orphan2.write_bytes(b"b" * 500)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_gc(cfg)
        assert result.total_reclaimable_bytes == 1500

    def test_gc_finds_incomplete_mlx_download(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # MLX dir with config.json but no safetensors → should NOT be incomplete
        # (MLX dirs don't need safetensors)
        mlx_ok = cfg.shelf_root / "mlx" / "pub" / "mlx-repo"
        mlx_ok.mkdir(parents=True)
        (mlx_ok / "config.json").write_bytes(b'{"model_type": "llama"}')

        # Safetensors dir with config.json but no .safetensors → incomplete
        st_incomplete = cfg.shelf_root / "safetensors" / "pub" / "st-incomplete"
        st_incomplete.mkdir(parents=True)
        (st_incomplete / "config.json").write_bytes(b'{"model_type": "llama"}')

        # GGUF dir with no .gguf files → incomplete
        gguf_incomplete = cfg.shelf_root / "gguf" / "pub" / "gguf-incomplete"
        gguf_incomplete.mkdir(parents=True)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_gc(cfg)
        assert str(st_incomplete) in result.incomplete_downloads
        assert str(gguf_incomplete) in result.incomplete_downloads
        assert str(mlx_ok) not in result.incomplete_downloads

    def test_gc_finds_incomplete_gguf_download(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # GGUF dir with no .gguf files → incomplete
        gguf_incomplete = cfg.shelf_root / "gguf" / "pub" / "no-gguf"
        gguf_incomplete.mkdir(parents=True)
        # Add a non-gguf file — still incomplete (no .gguf)
        (gguf_incomplete / "README.md").write_bytes(b"readme")

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_gc(cfg)
        assert str(gguf_incomplete) in result.incomplete_downloads

    def test_gc_finds_orphan_at_publisher_level(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # Loose file at publisher level (no repo subdir) should be orphaned
        stray = cfg.shelf_root / "gguf" / "somepub" / "stray.bin"
        stray.parent.mkdir(parents=True)
        stray.write_bytes(b"orphan at publisher level" * 20)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_gc(cfg)
        assert str(stray) in result.orphaned_files


class TestGCCli:
    """Tier 3 — CLI integration."""

    def test_gc_cli_defaults_to_dry_run(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        init_shelf(cfg)

        orphan = cfg.shelf_root / "gguf" / "pub" / "orphan" / "lonely.gguf"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"should survive dry run" * 50)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        rc = main(["--config", str(config_path), "gc"])
        assert rc == 0
        # File should still be there (dry-run default)
        assert orphan.exists()

    def test_gc_cli_execute_removes_orphans(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        init_shelf(cfg)

        orphan = cfg.shelf_root / "gguf" / "pub" / "orphan" / "lonely.gguf"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"delete me" * 50)

        # Also create an empty dir that should be cleaned
        empty_dir = cfg.shelf_root / "gguf" / "pub" / "empty-repo"
        empty_dir.mkdir(parents=True)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        rc = main(["--config", str(config_path), "gc", "--execute"])
        assert rc == 0
        # Orphaned file should be gone
        assert not orphan.exists()
        # Empty dir should be gone
        assert not empty_dir.exists()

    def test_gc_cli_json_output(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        init_shelf(cfg)

        orphan = cfg.shelf_root / "gguf" / "pub" / "orphan" / "lonely.gguf"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"json gc test" * 50)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = main(["--config", str(config_path), "gc", "--json"])
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        output = json.loads(captured.getvalue())
        assert "incomplete_downloads" in output
        assert "orphaned_files" in output
        assert "empty_dirs" in output
        assert "total_reclaimable_bytes" in output
        assert str(orphan) in output["orphaned_files"]
