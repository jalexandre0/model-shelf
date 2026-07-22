"""Tests for audit — run_audit, AuditResult, CLI integration."""

from __future__ import annotations

import io
import json
import sys

from pathlib import Path

import pytest

from model_shelf.config import Config
from model_shelf.manifest import (
    _sha256_dir_for_rebuild,
    load_manifest,
    save_manifest,
)
from model_shelf.import_model import _sha256_file
from model_shelf.resolver import init_shelf
from model_shelf.audit import AuditResult, run_audit


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


class TestAuditDataclass:
    """Tier 1 — pure logic."""

    def test_audit_dataclass_defaults(self):
        r = AuditResult()
        assert r.missing == []
        assert r.stale == []
        assert r.untracked == []
        d = r.to_dict()
        assert d["missing"] == []
        assert d["stale"] == []
        assert d["untracked"] == []


class TestAuditCleanShelf:
    """Tier 2 — filesystem integration."""

    def test_audit_clean_shelf(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"clean shelf model content" * 50
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

        result = run_audit(cfg)
        assert result.missing == []
        assert result.stale == []
        assert result.untracked == []

    def test_audit_missing_entry_directory_gone(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/repo": {
                    "repo_id": "pub/repo", "format": "gguf",
                    "sha256": "a" * 64, "files": ["model.gguf"],
                    "size_bytes": 100,
                },
            },
        })

        result = run_audit(cfg)
        assert result.missing == ["pub/repo"]
        assert result.stale == []
        assert result.untracked == []

    def test_audit_missing_file_in_directory(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"multi-file model" * 50
        (cfg.shelf_root / "mlx" / "pub" / "repo").mkdir(parents=True)
        f1 = cfg.shelf_root / "mlx" / "pub" / "repo" / "config.json"
        f2 = cfg.shelf_root / "mlx" / "pub" / "repo" / "weights.safetensors"
        f1.write_bytes(content)
        f2.write_bytes(content)

        sha = _sha256_dir_for_rebuild(cfg.shelf_root / "mlx" / "pub" / "repo")
        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/repo": {
                    "repo_id": "pub/repo", "format": "mlx",
                    "sha256": sha,
                    "files": ["config.json", "weights.safetensors", "gone.file"],
                    "size_bytes": 500,
                },
            },
        })

        result = run_audit(cfg)
        assert result.missing == ["pub/repo"]

    def test_audit_stale_sha256(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"original content" * 50
        model_path = _setup_gguf_model(
            cfg.shelf_root, "pub", "repo", "model.gguf", content,
        )

        # Save manifest with a *wrong* SHA256
        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/repo": {
                    "repo_id": "pub/repo", "format": "gguf",
                    "sha256": "b" * 64, "files": ["model.gguf"],
                    "size_bytes": model_path.stat().st_size,
                },
            },
        })

        result = run_audit(cfg)
        assert result.missing == []
        assert result.stale == ["pub/repo"]
        assert result.untracked == []

    def test_audit_untracked_file(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # Create an orphaned file on disk with no manifest entry
        orphan = cfg.shelf_root / "gguf" / "pub" / "orphan" / "lonely.gguf"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"orphaned model" * 50)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {},
        })

        result = run_audit(cfg)
        assert result.untracked == [str(orphan)]
        assert result.missing == []
        assert result.stale == []

    def test_audit_multiple_issues_in_one_run(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"valid model" * 50
        p_valid = _setup_gguf_model(
            cfg.shelf_root, "pub", "valid", "model.gguf", content,
        )
        sha_valid = _sha256_file(p_valid)

        # Stale entry — file exists but SHA256 in manifest is wrong
        stale_content = b"stale model content" * 50
        p_stale = _setup_gguf_model(
            cfg.shelf_root, "pub", "stale", "model.gguf", stale_content,
        )

        # Untracked file
        orphan = cfg.shelf_root / "gguf" / "pub" / "orphan" / "lonely.gguf"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"orphan" * 50)

        # Untracked file #2 — different publisher
        orphan2 = cfg.shelf_root / "safetensors" / "other" / "stray" / "model.safetensors"
        orphan2.parent.mkdir(parents=True)
        orphan2.write_bytes(b"orphan2" * 50)

        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/valid": {
                    "repo_id": "pub/valid", "format": "gguf",
                    "sha256": sha_valid, "files": ["model.gguf"],
                    "size_bytes": p_valid.stat().st_size,
                },
                # Missing entry — no files on disk
                "pub/missing": {
                    "repo_id": "pub/missing", "format": "gguf",
                    "sha256": "c" * 64, "files": ["gone.gguf"],
                    "size_bytes": 100,
                },
                # Stale entry — file exists but SHA256 is wrong
                "pub/stale": {
                    "repo_id": "pub/stale", "format": "gguf",
                    "sha256": "d" * 64, "files": ["model.gguf"],
                    "size_bytes": p_stale.stat().st_size,
                },
            },
        })

        result = run_audit(cfg)
        assert "pub/missing" in result.missing
        assert "pub/stale" in result.stale
        assert len(result.untracked) == 2
        assert str(orphan) in result.untracked
        assert str(orphan2) in result.untracked

    def test_audit_stale_sha256_mlx(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        # Create an MLX model dir with config.json
        model_dir = cfg.shelf_root / "mlx" / "pub" / "mlx-model"
        model_dir.mkdir(parents=True)
        (model_dir / "config.json").write_bytes(b'{"model_type": "llama"}')
        (model_dir / "model.safetensors").write_bytes(b"weights" * 100)

        # Save manifest with a *wrong* SHA256
        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/mlx-model": {
                    "repo_id": "pub/mlx-model", "format": "mlx",
                    "sha256": "f" * 64, "files": ["config.json", "model.safetensors"],
                    "size_bytes": 700,
                },
            },
        })

        result = run_audit(cfg)
        assert "pub/mlx-model" in result.stale
        assert result.missing == []


class TestAuditCli:
    """Tier 3 — CLI integration."""

    def test_audit_cli_json_output(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"cli json audit" * 50
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

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = main(["--config", str(config_path), "audit", "--json"])
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        output = json.loads(captured.getvalue())
        assert output["missing"] == []
        assert output["stale"] == []
        assert output["untracked"] == []

    def test_audit_cli_exit_code_clean(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"clean exit" * 50
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

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        rc = main(["--config", str(config_path), "audit"])
        assert rc == 0

    def test_audit_cli_exit_code_dirty(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        init_shelf(cfg)

        # Missing entry in manifest with no files on disk
        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/missing": {
                    "repo_id": "pub/missing", "format": "gguf",
                    "sha256": "e" * 64, "files": ["gone.gguf"],
                    "size_bytes": 100,
                },
            },
        })

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        rc = main(["--config", str(config_path), "audit"])
        assert rc == 1
