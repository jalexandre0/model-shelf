# Handoff: `import` Command for model-shelf

## Files to Create

| File | Purpose |
|---|---|
| `src/model_shelf/import_model.py` | Core import logic: format detection, SHA256, hardlink/copy, manifest update |
| `tests/test_import.py` | 8 tests covering gguf, mlx, duplicates, hardlinks, org override, quant detection |

## Files to Modify

| File | Change |
|---|---|
| `src/model_shelf/cli.py` | Add `cmd_import(args, cfg) -> int`, wire `import` subparser to `main()` |
| `src/model_shelf/__init__.py` | Add `ImportResult` and `import_model` to `__all__` and imports |

## Files NOT to Touch

- `src/model_shelf/resolver.py`
- `src/model_shelf/config.py`
- `src/model_shelf/detect.py`
- `src/model_shelf/relocate.py`
- `src/model_shelf/search.py`
- `tests/test_resolver.py`
- `tests/test_config.py`
- `tests/test_detect.py`
- `tests/test_relocate.py`
- `tests/test_search.py`

---

## 1. API Contract

### 1.1 `ImportResult` dataclass

File: `src/model_shelf/import_model.py` (lines 1-30)

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
```

**Pattern match**: mirrors `ResolveResult` in `resolver.py` lines 50-60 — same `to_dict()` shape, same `status`/`path`/`checks` fields. `sha256` and `message` are the delta.

### 1.2 `import_model()` function signature

```python
def import_model(
    config: Config,
    source: Path,
    *,
    format: str | None = None,
    org: str | None = None,
    repo: str | None = None,
    quant: str | None = None,
    hardlink: bool = True,
) -> ImportResult:
    """Import a model file or directory into the curated shelf."""
```

**Pattern match**: mirrors `resolve_model()` in `resolver.py` line 197 — takes `Config` as first positional, keyword-only args after `*`, returns a dataclass.

---

## 2. Key Logic (in `import_model.py`)

### 2.1 Format detection (no existing helper to reuse — `detect_format()` works on repo_id strings, not files)

```
Input: Path to a file (gguf) or directory (mlx/safetensors)

1. If source is a file ending in `.gguf`:
   → format = "gguf"
2. If source is a directory:
   a. Has `config.json`? → check for `*.safetensors` files → "safetensors"
   b. Has `config.json` but no safetensors files? → "mlx"
   c. No `config.json`? → ValueError("directory lacks config.json — cannot determine format")
3. If source is a file that's not `.gguf` → ValueError("unsupported file type for import, only .gguf files are supported for single-file import")
```

This is a **new helper** `_detect_format_from_path(source: Path) -> str`. It is NOT the same as `resolver.detect_format()` which tokenises a repo_id string.

### 2.2 Infer org/repo from path

```
Given: /Users/jeff/models/Qwen3-8B-Q4_K_M.gguf

Strategy (in order):
1. If `--org` and `--repo` are both passed → use them directly.
2. If only `--org` is passed:
   - repo = source.stem (filename without extension) for gguf
   - repo = source.parent.name for directories
3. If neither is passed:
   - For gguf: look at parent dir name.
     - If parent dir looks like a publisher (contains hyphens, common-org names like "bartowski",
       "mlx-community", "lmstudio-community", "unsloth") → org = parent dir name, repo = stem
     - Otherwise: org = "local", repo = stem
   - For directories: org = source.parent.parent.name OR source.parent.name (if deep enough),
     repo = source.parent.name (for the innermost dir)
     - If parent dir is a known publisher pattern → use it as org
     - Otherwise: org = "local", repo = source.name

Fallback: org = "local", repo = source.stem (gguf) or source.name (dir)
```

**Key constraint**: `repo_id` must always be `org/repo` format. `_split_repo_id()` in `resolver.py` line 112 enforces this.

### 2.3 SHA256 computation

```python
import hashlib

def _sha256_file(path: Path) -> str:
    """Return lowercase hex SHA256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):  # 64KB chunks
            h.update(chunk)
    return h.hexdigest()


def _sha256_directory(path: Path) -> str:
    """Return SHA256 over all regular files (sorted by name, concatenated)."""
    h = hashlib.sha256()
    for f in sorted(path.rglob("*")):
        if f.is_file() and not f.name.startswith("._"):
            h.update(f.name.encode())  # include filename in hash
            with open(f, "rb") as fh:
                while chunk := fh.read(65536):
                    h.update(chunk)
    return h.hexdigest()
```

### 2.4 Manifest check (duplicate detection)

```python
from pathlib import Path

def _load_manifest(shelf_root: Path) -> dict:
    """Load manifest.json from shelf_root. Returns empty dict if missing."""
    manifest_path = shelf_root / "manifest.json"
    if not manifest_path.is_file():
        return {"version": 1, "updated": "", "models": {}}
    import json
    return json.loads(manifest_path.read_text())


def _save_manifest(shelf_root: Path, data: dict) -> None:
    """Atomic write: manifest.json.tmp → os.rename → manifest.json."""
    import json, os, tempfile
    manifest_path = shelf_root / "manifest.json"
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=str(shelf_root), prefix="manifest.", suffix=".tmp",
        delete=False, encoding="utf-8",
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
```

Duplicate check:

```python
manifest = _load_manifest(config.shelf_root)
for entry in manifest["models"].values():
    if entry["sha256"] == sha256_hex:
        return ImportResult(
            status="skipped_duplicate",
            repo_id=repo_id,
            format=fmt,
            path=None,
            sha256=sha256_hex,
            message=f"Duplicate of {entry.get('repo_id', 'unknown')} — SHA256 {sha256_hex[:8]} already tracked",
        )
```

### 2.5 Hardlink / copy

```python
import os, shutil

def _ingest_file(source: Path, dest: Path, *, hardlink: bool) -> None:
    """Copy or hardlink a single file into the shelf. Creates parent dirs."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if hardlink and source.stat().st_dev == dest.parent.stat().st_dev:
        os.link(str(source), str(dest))
    else:
        if hardlink:
            # warn about cross-filesystem fallback
            print(f"model-shelf: warning: source is on a different filesystem — falling back to copy", file=sys.stderr)
        shutil.copy2(str(source), str(dest))
```

For GGUF: ingest the single `.gguf` file.
For MLX/safetensors: walk the source directory, ingest every file (skip `._` dotfiles).

### 2.6 Auto-detect quant from filename (GGUF)

```python
import re

def _detect_quant_from_filename(path: Path) -> str | None:
    """Extract quant tag from GGUF filename.
    Examples:
        Qwen3-14B-Q4_K_M.gguf     → Q4_K_M
        qwen3-8b-q5_1.gguf        → Q5_1
        llama-3.1-8b-f16.gguf     → F16
    """
    name = path.stem.lower()
    # Match common quant patterns: Q4_K_M, Q5_0, Q8_0, IQ4_XS, F16, etc.
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
```

### 2.7 Manifest entry construction

```python
import datetime

entry = {
    "repo_id": repo_id,
    "format": fmt,
    "quant": quant,           # None for mlx/safetensors
    "size_bytes": total_size,
    "sha256": sha256_hex,
    "files": [f.name for f in sorted(dest_dir.rglob("*")) if f.is_file()],
    "source": "imported",
    "imported_from": str(source.resolve()),
    "imported": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "hardlinks": [],
}
```

### 2.8 Full `import_model()` flow

```
1. Resolve source to absolute path.
2. `_detect_format_from_path(source)` → format.
3. Validate format is in SUPPORTED_FORMATS.
4. Infer org/repo/quant (respecting overrides).
5. Build repo_id = f"{org}/{repo}".
6. Compute SHA256 (`_sha256_file` for gguf, `_sha256_directory` for dirs).
7. Load manifest, check for duplicate SHA256 → early return "skipped_duplicate".
8. Determine destination path:
   - GGUF: shelf_root / "gguf" / org / repo / filename
   - MLX/safetensors: shelf_root / fmt / org / repo /
9. Ingest files (hardlink or copy).
10. Build manifest entry, atomically save manifest.
11. Return ImportResult(status="imported", ...).
```

---

## 3. CLI Integration (in `cli.py`)

### 3.1 Subparser registration

Add inside `main()`, alongside the other `sub.add_parser()` calls:

```python
p_import = sub.add_parser("import", help="import a local model into the shelf")
p_import.add_argument("path", help="path to .gguf file or model directory")
p_import.add_argument("--format", choices=SUPPORTED_FORMATS, default=None,
                       help="model format (auto-detected if omitted)")
p_import.add_argument("--org", default=None, help="override publisher/org name")
p_import.add_argument("--repo", default=None, help="override repo/model name")
p_import.add_argument("--quant", default=None, help="quant tag for GGUF (auto-detected if omitted)")
p_import.add_argument("--no-hardlink", action="store_true",
                       help="always copy, never hardlink (even on same filesystem)")
p_import.add_argument("--json", action="store_true", help="emit JSON")
```

### 3.2 Dispatch

Inside `main()`, alongside other `if args.command ==` branches:

```python
if args.command == "import":
    return cmd_import(args, cfg)
```

### 3.3 `cmd_import` function

```python
def cmd_import(args: argparse.Namespace, cfg: Config) -> int:
    from model_shelf.import_model import ImportResult, import_model

    check_storage_available(cfg)
    result = import_model(
        cfg,
        Path(args.path),
        format=args.format,
        org=args.org,
        repo=args.repo,
        quant=args.quant,
        hardlink=not args.no_hardlink,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_import_pretty(result)
    return 0 if result.status != "error" else 1


def _print_import_pretty(result: ImportResult) -> None:
    for c in result.checks:
        print(f"  {c.get('step', ''):<20} {c.get('detail', '')}")
    print()
    print(f"  status      {result.status}")
    print(f"  repo_id     {result.repo_id}")
    print(f"  format      {result.format}")
    print(f"  sha256      {result.sha256[:16]}...")
    if result.path:
        print(f"  path        {result.path}")
    print(f"  message     {result.message}")
```

**Pattern match**: `_print_import_pretty` mirrors `_print_result_pretty` in `cli.py` lines 41-48. `cmd_import` mirrors `cmd_resolve` at `cli.py` lines 50-56.

---

## 4. `__init__.py` updates

Add to imports:

```python
from model_shelf.import_model import ImportResult, import_model
```

Add to `__all__`:

```python
"ImportResult",
"import_model",
```

---

## 5. Test Specs (`tests/test_import.py`)

### Test conventions (from `tests/test_resolver.py`)

- Use `_config(tmp_path)` helper: creates `Config(shelf_root=tmp_path / "shelf", allow_downloads=False)`, ensures shelf root exists.
- Use `tmp_path` fixture for all filesystem operations.
- Use `monkeypatch` to isolate from real `/Volumes/` and home dirs.
- Use `pytest.raises(ValueError, match="...")` for expected errors.
- Each test is independent; no shared state.

### Test 1: `test_import_gguf_file`

```python
def test_import_gguf_file(tmp_path: Path):
    """Import a single .gguf file. Verifies shelf path, manifest entry, SHA256 matches."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    # Create a test gguf file
    source = tmp_path / "source" / "Qwen3-14B-Q4_K_M.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mock gguf content" * 100)  # > 1KB so SHA256 is meaningful

    result = import_model(cfg, source, org="Qwen", repo="Qwen3-14B-GGUF", quant="Q4_K_M")

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
```

### Test 2: `test_import_mlx_directory`

```python
def test_import_mlx_directory(tmp_path: Path):
    """Import a directory with config.json (MLX). All files should be ingested."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "mlx-community" / "Qwen3-14B-4bit"
    source.mkdir(parents=True)
    (source / "config.json").write_text('{"model_type": "qwen3"}')
    (source / "model.safetensors").write_bytes(b"mock weights")
    (source / "tokenizer.json").write_text('{"vocab_size": 151936}')

    result = import_model(cfg, source, org="mlx-community", repo="Qwen3-14B-4bit")

    assert result.status == "imported"
    assert result.format == "mlx"

    dest = cfg.shelf_root / "mlx" / "mlx-community" / "Qwen3-14B-4bit"
    assert dest.is_dir()
    assert (dest / "config.json").is_file()
    assert (dest / "model.safetensors").is_file()
    assert (dest / "tokenizer.json").is_file()
```

### Test 3: `test_import_rejects_dir_without_config_json`

```python
def test_import_rejects_dir_without_config_json(tmp_path: Path):
    """A directory without config.json should be rejected (can't determine format)."""
    cfg = _config(tmp_path)

    source = tmp_path / "source" / "some-folder"
    source.mkdir(parents=True)
    (source / "random.bin").write_bytes(b"not a model")

    with pytest.raises(ValueError, match="config.json"):
        import_model(cfg, source)
```

### Test 4: `test_import_hardlink_same_fs`

```python
def test_import_hardlink_same_fs(tmp_path: Path):
    """On the same filesystem, hardlink=True should use os.link (same inode)."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content")

    result = import_model(cfg, source, org="test", repo="model-gguf", quant="Q4_0")

    assert result.status == "imported"
    # Same inode → hardlinked
    assert source.stat().st_ino == result.path.stat().st_ino
```

### Test 5: `test_import_skips_duplicate`

```python
def test_import_skips_duplicate(tmp_path: Path):
    """Importing the same file twice should return 'skipped_duplicate' on second call."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"unique content")

    result1 = import_model(cfg, source, org="test", repo="model-gguf", quant="Q4_0")
    assert result1.status == "imported"

    # Second import of identical file
    result2 = import_model(cfg, source, org="test", repo="model-gguf-v2", quant="Q4_0")
    assert result2.status == "skipped_duplicate"
    assert "Duplicate" in result2.message or "duplicate" in result2.message.lower()
    assert result2.sha256 == result1.sha256
```

### Test 6: `test_import_updates_manifest`

```python
def test_import_updates_manifest(tmp_path: Path):
    """After import, manifest.json should have the new entry with correct fields."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content for manifest test" * 50)

    result = import_model(cfg, source, org="test-org", repo="test-model")

    manifest = _load_manifest(cfg.shelf_root)
    assert "test-org/test-model" in manifest["models"]
    entry = manifest["models"]["test-org/test-model"]
    assert entry["format"] == "gguf"
    assert entry["sha256"] == result.sha256
    assert entry["source"] == "imported"
    assert entry["quant"] is not None
    assert "size_bytes" in entry
    assert "files" in entry
    assert isinstance(entry["files"], list)
```

### Test 7: `test_import_org_override`

```python
def test_import_org_override(tmp_path: Path):
    """--org override should be respected even when source path suggests otherwise."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    # Source path suggests org="bartowski" but we override
    source = tmp_path / "bartowski" / "model.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content")

    result = import_model(cfg, source, org="custom-org", repo="custom-repo", quant="Q4_0")

    assert result.repo_id == "custom-org/custom-repo"
    # Shelf path uses override
    dest = cfg.shelf_root / "gguf" / "custom-org" / "custom-repo"
    assert dest.exists()
```

### Test 8: `test_import_auto_detect_quant`

```python
def test_import_auto_detect_quant(tmp_path: Path):
    """Quant should be auto-detected from GGUF filename when not explicitly passed."""
    cfg = _config(tmp_path)
    init_shelf(cfg)

    source = tmp_path / "source" / "Qwen3-14B-Q5_K_M.gguf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"content" * 20)

    # Don't pass quant — should be detected from filename
    result = import_model(cfg, source, org="Qwen", repo="Qwen3-14B-GGUF")

    assert result.status == "imported"
    manifest = _load_manifest(cfg.shelf_root)
    entry = manifest["models"]["Qwen/Qwen3-14B-GGUF"]
    assert entry["quant"] == "Q5_K_M"
    # Destination filename should contain the quant
    assert "Q5_K_M" in str(result.path)
```

---

## 6. Convention Patterns (Extracted from Existing Code)

### 6.1 Module header pattern

Every file starts with:
```python
"""Docstring explaining the module's purpose."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
```
(Source: `resolver.py` lines 1-18, `search.py` lines 1-8, `detect.py` lines 1-6)

### 6.2 Result dataclass pattern

- Fields: `status: str`, format-specific fields, `checks: list[dict] = field(default_factory=list)`
- Method: `to_dict(self) -> dict` — converts `Path` to `str`, returns dict
- Always imported by `__init__.py` and exposed in `__all__`
(Source: `ResolveResult` in `resolver.py` lines 50-60, `FindResult` in `search.py` lines 18-26)

### 6.3 Function signature pattern

```python
def function_name(
    config: Config,       # first positional
    required_param: str,
    *,
    optional_kw: str | None = None,   # keyword-only after *
) -> ReturnType:
```
(Source: `resolve_model` in `resolver.py` line 197, `find_models` in `search.py` line 28)

### 6.4 CLI dispatch pattern

```python
def cmd_<command>(args: argparse.Namespace, cfg: Config) -> int:
    # logic
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        _print_<command>_pretty(result)
    return 0 if result.status != "error" else 1
```
Return codes: `0` = success, `1` = not-found/error, `2` = storage/config error, `3` = unexpected.
(Source: `cmd_resolve` in `cli.py` lines 50-56, `cmd_find` in `cli.py` lines 158-164)

### 6.5 Test helper pattern

```python
def _config(tmp_path: Path, *, allow_downloads: bool = False) -> Config:
    shelf = tmp_path / "shelf"
    shelf.mkdir(parents=True, exist_ok=True)
    return Config(shelf_root=shelf, allow_downloads=allow_downloads)
```
(Source: `tests/test_resolver.py` lines 83-85)

### 6.6 Error handling pattern

- `ValueError` for bad input, caught in `main()` → exit code 2
- Custom exceptions subclass `RuntimeError` (e.g., `StorageNotAvailableError`)
- Errors are caught with broad `except Exception` in `main()` → exit code 3 with last line of message
(Source: `resolver.py` lines 33-34, `cli.py` lines 247-253)

### 6.7 Shelf path pattern

```python
shelf_root / format / publisher / repo / filename  # for gguf
shelf_root / format / publisher / repo /            # for mlx/safetensors
```
(Source: `shelf_path_gguf` in `resolver.py` lines 134-137, `shelf_path_snapshot` in `resolver.py` lines 140-143)

### 6.8 Atomic write pattern

Write to temp file in the same directory as the target, `os.fsync()`, then `os.replace()`. Clean up temp file on error.
(Source: implementation plan `.serena/memories/conventions.md` lines 18-20)

### 6.9 Dependency list

- No new external deps. `hashlib`, `os`, `shutil`, `tempfile`, `json`, `datetime`, `re`, `sys` are all stdlib.
- The `Config` dataclass is available from `model_shelf.resolver`.
(Source: `pyproject.toml` dependencies, `resolver.py` imports)

---

## 7. Edge Cases & Constraints

| Scenario | Behavior |
|---|---|
| Source file doesn't exist | `ValueError("source path does not exist: {path}")` |
| Source is a `.gguf` but `--repo` not passed | Auto-infer repo from parent dir heuristics |
| Source is a dir with `config.json` but `--format safetensors` | Respect `--format` override; don't re-detect |
| `--no-hardlink` on same filesystem | Always copy via `shutil.copy2`, never `os.link` |
| Cross-filesystem hardlink attempt | Fall back to `shutil.copy2` + print warning to stderr |
| Manifest.json corrupt/missing | Treat as empty, rebuild entry |
| Shelf not initialized (no `gguf/` subdir) | `check_storage_available` raises `ShelfNotInitializedError` → exit 2 |
| `--org` passed without `--repo` | Auto-infer repo from filename; org override is used as-is |
| Empty `.gguf` file (0 bytes) | Still imported; SHA256 of empty file is well-defined |
| Directory with only `config.json` (no weights) | Import succeeds; manifest records the files present |
| Two different repos with same SHA256 | Second import is "skipped_duplicate"; message names the first |

---

## Start Here

Open `src/model_shelf/resolver.py` first to review the existing `Config`, `ResolveResult`, and `check_storage_available` patterns. Then open `src/model_shelf/cli.py` to see how `cmd_resolve` wires up. Then create `src/model_shelf/import_model.py` following the patterns above.