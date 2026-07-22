"""Tests for dedup — find_duplicates, execute_dedup, DedupGroup, DedupResult, CLI."""

from __future__ import annotations

import io
import json
import os
import sys

from pathlib import Path
from unittest.mock import patch

import pytest

from model_shelf.config import Config
from model_shelf.dedup import (
    DedupGroup,
    DedupResult,
    _KNOWN_HF_CACHE,
    _KNOWN_OLLAMA_BLOBS,
    _collect_hf_cache_blobs,
    _collect_ollama_blobs,
    execute_dedup,
    find_duplicates,
)
from model_shelf.manifest import load_manifest
from model_shelf.resolver import init_shelf
from model_shelf.import_model import _sha256_file


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> Config:
    shelf = tmp_path / "shelf"
    return Config(shelf_root=shelf, allow_downloads=False)


def _setup_shelf_gguf(shelf_root: Path, publisher: str, repo: str,
                       filename: str, content: bytes) -> Path:
    model_path = shelf_root / "gguf" / publisher / repo / filename
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(content)
    return model_path


# ---------------------------------------------------------------------------
# Tier 1 — Pure logic
# ---------------------------------------------------------------------------


class TestTier1PureLogic:
    """Tests that exercise find_duplicates logic without hardlink execution."""

    def test_find_duplicates_empty_shelf(self, tmp_path: Path):
        cfg = _config(tmp_path)
        cfg.shelf_root.mkdir(parents=True)
        result = find_duplicates(cfg)
        assert result.groups == []
        assert result.total_duplicate_bytes == 0
        assert result.potential_savings_bytes == 0

    def test_find_duplicates_two_identical_ggufs(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"identical gguf content" * 100
        _setup_shelf_gguf(cfg.shelf_root, "pub-a", "repo-a", "model.gguf", content)
        _setup_shelf_gguf(cfg.shelf_root, "pub-b", "repo-b", "model.gguf", content)
        result = find_duplicates(cfg)
        assert len(result.groups) == 1
        g = result.groups[0]
        assert len(g.files) == 2
        assert g.size_bytes > 0
        assert g.duplicate_bytes == g.size_bytes

    def test_find_duplicates_ignores_different_content(self, tmp_path: Path):
        cfg = _config(tmp_path)
        _setup_shelf_gguf(cfg.shelf_root, "pub-a", "repo-a", "model.gguf", b"content A" * 100)
        _setup_shelf_gguf(cfg.shelf_root, "pub-b", "repo-b", "model.gguf", b"content B" * 100)
        result = find_duplicates(cfg)
        assert result.groups == []

    def test_find_duplicates_same_content_different_names(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"same under different names" * 50
        _setup_shelf_gguf(cfg.shelf_root, "pub-a", "repo-a", "model-q4.gguf", content)
        _setup_shelf_gguf(cfg.shelf_root, "pub-b", "repo-b", "model-q8.gguf", content)
        result = find_duplicates(cfg)
        assert len(result.groups) == 1
        names = {f.name for f in result.groups[0].files}
        assert names == {"model-q4.gguf", "model-q8.gguf"}

    def test_dedup_group_dataclass(self):
        g = DedupGroup(sha256="a" * 64, files=[Path("/a"), Path("/b")], size_bytes=1000, duplicate_bytes=1000)
        assert g.duplicate_bytes == g.size_bytes

    def test_dedup_result_dataclass(self):
        r = DedupResult(groups=[], total_duplicate_bytes=500, potential_savings_bytes=500)
        assert r.potential_savings_bytes == 500
        assert r.total_duplicate_bytes == r.potential_savings_bytes
        d = r.to_dict()
        assert d["total_duplicate_bytes"] == 500
        assert d["potential_savings_bytes"] == 500


# ---------------------------------------------------------------------------
# Tier 2 — tmp_path filesystem
# ---------------------------------------------------------------------------


class TestTier2Filesystem:
    """Tests that create and verify hardlinks on the filesystem."""

    def test_dedup_creates_hardlinks_same_fs(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"hardlink test content" * 200
        p1 = _setup_shelf_gguf(cfg.shelf_root, "pub-a", "model-a", "model.gguf", content)
        p2 = _setup_shelf_gguf(cfg.shelf_root, "pub-b", "model-b", "model.gguf", content)
        assert p1.stat().st_ino != p2.stat().st_ino

        result = find_duplicates(cfg)
        assert len(result.groups) == 1
        exec_result = execute_dedup(cfg, result)
        assert exec_result.hardlinks_created == 1   # exactly 1 hardlink for 2 copies
        assert p1.stat().st_ino == p2.stat().st_ino
        assert p1.stat().st_nlink == 2              # exactly 2 links
        assert p1.read_bytes() == content
        assert p2.read_bytes() == content

    def test_dedup_dry_run_makes_no_changes(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"dry run content" * 200
        p1 = _setup_shelf_gguf(cfg.shelf_root, "pub-a", "model-a", "model.gguf", content)
        p2 = _setup_shelf_gguf(cfg.shelf_root, "pub-b", "model-b", "model.gguf", content)
        ino1_before = p1.stat().st_ino
        ino2_before = p2.stat().st_ino
        nlink1_before = p1.stat().st_nlink

        result = find_duplicates(cfg)
        assert len(result.groups) == 1
        # find_duplicates is read-only
        assert p1.stat().st_ino == ino1_before
        assert p2.stat().st_ino == ino2_before
        assert p1.stat().st_nlink == nlink1_before

    def test_dedup_keeps_canonical_in_shelf(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"canonical keep test" * 200
        p_keep = _setup_shelf_gguf(cfg.shelf_root, "publisher", "repo-keep", "model.gguf", content)
        p_dup = _setup_shelf_gguf(cfg.shelf_root, "publisher", "repo-dup", "model.gguf", content)

        result = find_duplicates(cfg)
        exec_result = execute_dedup(cfg, result)
        assert exec_result.hardlinks_created == 1
        assert p_keep.stat().st_ino == p_dup.stat().st_ino
        assert p_keep.read_bytes() == content

    def test_dedup_skips_across_filesystems(self, tmp_path: Path, monkeypatch):
        """Cross-fs: monkeypatch st_dev on second file → skipped_cross_fs == 1.  (Fix 2)"""
        cfg = _config(tmp_path)
        content = b"cross-fs test" * 200
        p_shelf = _setup_shelf_gguf(cfg.shelf_root, "pub", "repo", "model.gguf", content)
        p_dup = _setup_shelf_gguf(cfg.shelf_root, "pub2", "repo2", "model.gguf", content)

        result = find_duplicates(cfg)
        assert len(result.groups) == 1

        # Patch os.stat to return different st_dev for p_dup
        real_stat = os.stat
        def fake_stat(path, *a, **kw):
            st = real_stat(path, *a, **kw)
            if str(path) == str(p_dup):
                # Return a result with a different st_dev
                return os.stat_result((st.st_mode, st.st_ino, st.st_dev + 999,
                                       st.st_nlink, st.st_uid, st.st_gid,
                                       st.st_size, st.st_atime, st.st_mtime, st.st_ctime))
            return st

        monkeypatch.setattr(os, "stat", fake_stat)
        exec_result = execute_dedup(cfg, result)
        assert exec_result.skipped_cross_fs == 1
        assert exec_result.hardlinks_created == 0

    def test_dedup_include_ollama_blobs(self, tmp_path: Path, monkeypatch):
        """include_ollama=True detects shelf + ollama duplicates.  (Fix 3)"""
        cfg = _config(tmp_path)
        content = b"ollama dup test" * 200

        _setup_shelf_gguf(cfg.shelf_root, "pub", "repo", "model.gguf", content)

        # Create mock ollama blobs inside tmp_path
        ollama_blobs = tmp_path / "mock-ollama" / "models" / "blobs"
        ollama_blobs.mkdir(parents=True)
        (ollama_blobs / "sha256-abc123").write_bytes(content)

        monkeypatch.setattr(
            "model_shelf.dedup._KNOWN_OLLAMA_BLOBS", ollama_blobs,
        )
        result = find_duplicates(cfg, include_ollama=True)
        assert len(result.groups) == 1
        assert len(result.groups[0].files) == 2

    def test_dedup_include_hf_cache_blobs(self, tmp_path: Path, monkeypatch):
        """include_hf_cache=True detects shelf + hf-cache duplicates.  (Fix 4)"""
        cfg = _config(tmp_path)
        content = b"hf-cache dup test" * 200

        _setup_shelf_gguf(cfg.shelf_root, "pub", "repo", "model.gguf", content)

        # Create mock hf cache hub inside tmp_path
        hf_hub = tmp_path / "mock-hf" / "hub"
        hf_hub.mkdir(parents=True)
        (hf_hub / "models--test--model" / "blobs" / "sha256-xyz").parent.mkdir(parents=True, exist_ok=True)
        (hf_hub / "models--test--model" / "blobs" / "sha256-xyz").write_bytes(content)
        (hf_hub / "models--test--model" / "snapshots" / "aaa" / "model.gguf").parent.mkdir(parents=True, exist_ok=True)
        (hf_hub / "models--test--model" / "snapshots" / "aaa" / "model.gguf").write_bytes(content)

        monkeypatch.setattr(
            "model_shelf.dedup._KNOWN_HF_CACHE", hf_hub,
        )
        result = find_duplicates(cfg, include_hf_cache=True)
        # 3 copies total: 1 shelf + 2 hf-cache → 1 group with 3 files
        assert len(result.groups) == 1
        assert len(result.groups[0].files) == 3

    def test_dedup_ollama_blob_not_unlinked(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"do not unlink ollama" * 200
        p_shelf = _setup_shelf_gguf(cfg.shelf_root, "pub", "repo", "model.gguf", content)
        p_dup = _setup_shelf_gguf(cfg.shelf_root, "pub2", "repo2", "model.gguf", content)

        result = find_duplicates(cfg)
        exec_result = execute_dedup(cfg, result)
        assert exec_result.hardlinks_created == 1
        assert p_shelf.exists()
        assert p_dup.exists()
        assert p_shelf.read_bytes() == content
        assert p_dup.read_bytes() == content

    def test_dedup_hf_cache_blob_not_unlinked(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"do not unlink hf-cache" * 200
        p1 = _setup_shelf_gguf(cfg.shelf_root, "pub-a", "repo-a", "model.gguf", content)
        p2 = _setup_shelf_gguf(cfg.shelf_root, "pub-b", "repo-b", "model.gguf", content)

        result = find_duplicates(cfg)
        exec_result = execute_dedup(cfg, result)
        assert exec_result.hardlinks_created == 1
        assert p1.exists()
        assert p2.exists()
        assert p1.read_bytes() == content
        assert p2.read_bytes() == content

    def test_dedup_preserves_manifest_hardlinks_field(self, tmp_path: Path):
        cfg = _config(tmp_path)
        init_shelf(cfg)

        content = b"manifest update test" * 200
        p1 = _setup_shelf_gguf(cfg.shelf_root, "publisher", "repo-one", "model.gguf", content)
        p2 = _setup_shelf_gguf(cfg.shelf_root, "publisher", "repo-two", "model.gguf", content)

        from model_shelf.manifest import save_manifest
        sha = _sha256_file(p1)
        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "publisher/repo-one": {"repo_id": "publisher/repo-one", "format": "gguf",
                                       "sha256": sha, "files": ["model.gguf"],
                                       "size_bytes": p1.stat().st_size, "hardlinks": []},
                "publisher/repo-two": {"repo_id": "publisher/repo-two", "format": "gguf",
                                       "sha256": sha, "files": ["model.gguf"],
                                       "size_bytes": p2.stat().st_size, "hardlinks": []},
            }})

        result = find_duplicates(cfg)
        exec_result = execute_dedup(cfg, result)
        assert exec_result.hardlinks_created == 1

        updated = load_manifest(cfg.shelf_root)
        entry_one = updated["models"]["publisher/repo-one"]
        entry_two = updated["models"]["publisher/repo-two"]
        # Both entries should have hardlinks pointing to the other  (Fix 7)
        assert len(entry_one.get("hardlinks", [])) == 1
        assert len(entry_two.get("hardlinks", [])) == 1

    def test_dedup_handles_three_way_duplicate(self, tmp_path: Path):
        cfg = _config(tmp_path)
        content = b"three-way duplicate" * 200
        p1 = _setup_shelf_gguf(cfg.shelf_root, "pub", "repo1", "model.gguf", content)
        p2 = _setup_shelf_gguf(cfg.shelf_root, "pub", "repo2", "model.gguf", content)
        p3 = _setup_shelf_gguf(cfg.shelf_root, "pub", "repo3", "model.gguf", content)

        result = find_duplicates(cfg)
        assert len(result.groups) == 1
        g = result.groups[0]
        assert len(g.files) == 3
        assert g.duplicate_bytes == 2 * g.size_bytes

        exec_result = execute_dedup(cfg, result)
        assert exec_result.hardlinks_created == 2                  # 2 hardlinks for 3 copies
        ino1 = p1.stat().st_ino
        assert p2.stat().st_ino == ino1
        assert p3.stat().st_ino == ino1
        assert p1.stat().st_nlink == 3                             # exactly 3 links


# ---------------------------------------------------------------------------
# Tier 3 — CLI integration
# ---------------------------------------------------------------------------


class TestTier3Cli:

    def test_dedup_cli_subcommand_registered(self):
        from model_shelf.cli import main
        with pytest.raises(SystemExit) as exc:
            main(["dedup", "--help"])
        assert exc.value.code == 0

    def test_dedup_cli_json_output(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        cfg.shelf_root.mkdir(parents=True, exist_ok=True)
        init_shelf(cfg)

        content = b"cli json test" * 200
        _setup_shelf_gguf(cfg.shelf_root, "pub", "repo-a", "model.gguf", content)
        _setup_shelf_gguf(cfg.shelf_root, "pub", "repo-b", "model.gguf", content)

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        try:
            rc = main(["--config", str(config_path), "dedup", "--json"])
        finally:
            sys.stdout = old_stdout

        assert rc == 0
        output = json.loads(captured.getvalue())
        assert "groups" in output
        assert len(output["groups"]) == 1
        assert len(output["groups"][0]["files"]) == 2

    def test_dedup_cli_execute_flag(self, tmp_path: Path):
        from model_shelf.cli import main
        from model_shelf.config import write_config

        cfg = _config(tmp_path)
        cfg.shelf_root.mkdir(parents=True, exist_ok=True)
        init_shelf(cfg)

        content = b"cli execute test" * 200
        p1 = _setup_shelf_gguf(cfg.shelf_root, "pub", "repo-a", "model.gguf", content)
        p2 = _setup_shelf_gguf(cfg.shelf_root, "pub", "repo-b", "model.gguf", content)

        from model_shelf.manifest import save_manifest
        sha = _sha256_file(p1)
        save_manifest(cfg.shelf_root, {
            "version": 1, "updated": "", "models": {
                "pub/repo-a": {"repo_id": "pub/repo-a", "format": "gguf", "sha256": sha,
                               "files": ["model.gguf"], "size_bytes": p1.stat().st_size, "hardlinks": []},
                "pub/repo-b": {"repo_id": "pub/repo-b", "format": "gguf", "sha256": sha,
                               "files": ["model.gguf"], "size_bytes": p2.stat().st_size, "hardlinks": []},
            }})

        config_path = tmp_path / "config.toml"
        write_config(config_path, shelf_root=cfg.shelf_root)

        rc = main(["--config", str(config_path), "dedup", "--execute"])
        assert rc == 0
        assert p1.stat().st_ino == p2.stat().st_ino
