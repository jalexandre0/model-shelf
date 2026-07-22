# Handoff: `import` Command — Phase 2

> **Goal:** Implement `src/model_shelf/import_model.py` and `tests/test_import.py` as a standalone module.
> CLI integration lives in a separate phase — this module exposes a pure Python API consumed by
> the CLI later and by the migration script immediately.

---

## 1. Exact Files to Create

| File | Purpose |
|---|---|
| `src/model_shelf/import_model.py` | Core import logic, `ImportResult` dataclass, manifest I/O helpers |
| `tests/test_import.py` | 8 test cases covering gguf, mlx, duplicate, hardlink, overrides |

**No existing files are modified in this phase.**

---

## 2. API Contract — `src/model_shelf/import_model.py`

### 2.1 Module header

```python
"""Import a model file from an arbitrary local path into the curated shelf.

Supported source formats:
    *.gguf          single file   → shelf_root/gguf/<org>/<repo>/<file>.gguf
    dir + config.json  directory → shelf_root/mlx|safetensors/<org>/<repo>/

The module maintains manifest.json alongside the shelf — a JSON index of every
imported model keyed by repo_id, with SHA256 for duplicate detection.
"""
from __future__ import annotations
```

### 2.2 `ImportResult` dataclass

```python
@dataclass
class ImportResult:
    status: str        # "imported" | "skipped_duplicate" | "error"
    repo_id: str       # inferred org/repo, e.g. "empero-ai/Qwythos-9B-v2-GGUF"
    format: str        # "gguf" | "mlx" | "safetensors"
    path: Path | None  # new shelf path (file for gguf, dir for mlx/safetensors)
    sha256: str        # hex digest
    message: str       # human-readable summary for CLI/pretty-print

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "repo_id": self.repo_id,
            "format": self.format,
            "path": str(self.path) if self.path else None,
            "sha256": self.sha256,
            "message": self.message,
        }
```

### 2.3 Public function

```python
def import_model(
    config: Config,
    source: Path,
    *,
    format: str | None = None,
    org: str | None = None,
    hardlink: bool = True,
) -> ImportResult:
    """Import a model at `source` into the curated shelf.

    Args:
        config:   Resolver Config with shelf_root + allow_downloads.
        source:   Path to a .gguf file or a directory containing a model.
        format:   Force a format. Auto-detected when None:
                  - *.gguf file → "gguf"
                  - directory with config.json → "mlx" (default for dir formats)
        org:      Publisher/org name. Inferred from parent dir heuristics when None.
        hardlink: Use os.link() when source and shelf are on the same filesystem.
                  Falls back to copy when cross-filesystem. If False, always copy.

    Returns:
        ImportResult with status, path, sha256, and message.
    """
```

### 2.4 Key logic — step by step

```
1.  VALIDATE source exists
      - source.is_file() → treat as GGUF (unless format overridden)
      - source.is_dir()  → treat as MLX/safetensors dir
      - neither → raise FileNotFoundError

2.  DETECT FORMAT (unless `format=` is provided)
      - *.gguf file → "gguf"
      - directory that contains config.json → "mlx"
      - directory without config.json → ValueError("directory must contain config.json")
      - (safetensors dir import works identically to mlx — same code path)

3.  INFER ORG + REPO (unless `org=` is provided)
      - For .gguf file:
          filename = source.stem   # e.g. "Qwythos-9B-v2-MTP-Q4_K_M"
          org  = source.parent.name  # heuristic: parent dir is the org
          repo = filename            # repo = filename stem
          quant = auto-detect from filename (see §2.5)
          repo_id = f"{org}/{repo}"
      - For directory:
          repo = source.name
          org  = source.parent.name
          repo_id = f"{org}/{repo}"
      - If org is provided, use it instead:
          repo_id = f"{org}/{source.name if dir else source.stem}"
      - Fallback: if any inference is ambiguous, raise ValueError with a clear message.

4.  COMPUTE SHA256
      - Single file (gguf): sha256_file(source) — read in 64 KB chunks
      - Directory (mlx/safetensors): walk all files sorted, sha256 each, then
        sha256 the concatenated hex digests to produce a composite hash.
        Rationale: the composite hash allows duplicate detection across directory imports.

5.  CHECK MANIFEST for duplicate SHA256
      - Load manifest.json from config.shelf_root / "manifest.json"
      - If any entry has the same SHA256 → return ImportResult(status="skipped_duplicate", ...)
      - Manifest loading helper: load_manifest(shelf_root) → dict (returns default empty
        {"version": 1, "models": {}} when file is missing)

6.  CREATE TARGET PATH
      - GGUF:   shelf_root / "gguf" / org / repo / source.name
      - MLX:    shelf_root / "mlx" / org / repo / (all files)
      - Create parent directories (mkdir(parents=True, exist_ok=True))

7.  TRANSFER FILES
      - GGUF (single file):
          if hardlink and same filesystem:
              os.link(source, target)
          else:
              shutil.copy2(source, target)  # copy2 preserves metadata
          Warn if hardlink requested but cross-fs copy was used.
      - Directory (MLX/safetensors):
          Iterate source.rglob("*") sorted, skipping dot-prefixed entries.
          For each file, compute relative path, mirror in target dir.
          Same hardlink-or-copy logic per file.

8.  UPDATE MANIFEST ATOMICALLY
      - Add entry: manifest["models"][repo_id] = { ... }
      - Write to manifest.json.tmp, then os.rename() to manifest.json
      - Entry shape matches the schema from the implementation plan:
          {
            "format": "gguf",
            "quant": "Q4_K_M",
            "params": "9B",
            "size_bytes": 5903822528,
            "sha256": "cfdd00ac...",
            "files": ["Qwythos-9B-v2-MTP-Q4_K_M.gguf"],
            "source": "imported",
            "imported_from": str(source),
            "downloaded": "2025-07-21T18:00:00Z",
            "hardlinks": []
          }
      - For directory imports: "files" lists all relative paths, drop "quant".

9.  RETURN ImportResult(status="imported", ...)
```

### 2.5 Quant auto-detection from GGUF filename

Pattern used by migration script (see implementation plan §Phase 1 step 2):

```
Input:  "Qwythos-9B-v2-MTP-Q4_K_M.gguf"
Output: quant = "Q4_K_M"

Logic:
  - Strip `.gguf` extension.
  - Match known quant pattern: Q[1-8]_[KkMm]_[0-9]+  or similar (Q4_K_M, Q5_K_M, Q8_0, etc.)
  - Extract the last matching segment.
  - If no quant found, quant = None (still importable — "params" in manifest will be None).
```

### 2.6 Manifest I/O helpers (inline, not a separate module yet)

These live in `import_model.py` for Phase 2. Phase 3 will extract them into `manifest.py`.

```python
def _load_manifest(shelf_root: Path) -> dict:
    """Load manifest.json. Returns default empty dict when file is missing."""
    manifest_path = shelf_root / "manifest.json"
    if not manifest_path.is_file():
        return {"version": 1, "models": {}}
    import json
    return json.loads(manifest_path.read_text())

def _save_manifest(shelf_root: Path, data: dict) -> None:
    """Atomically write manifest.json via temp file + rename."""
    import json
    manifest_path = shelf_root / "manifest.json"
    tmp_path = shelf_root / "manifest.json.tmp"
    tmp_path.write_text(json.dumps(data, indent=2))
    os.rename(str(tmp_path), str(manifest_path))
```

### 2.7 SHA256 helpers

```python
def _sha256_file(path: Path) -> str:
    """SHA256 hex digest of a single file, read in 64 KB chunks."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def _sha256_dir(path: Path) -> str:
    """Composite SHA256: sort all files, hash each, hash the concatenated digests."""
    import hashlib
    files = sorted(
        f for f in path.rglob("*")
        if f.is_file() and not f.name.startswith(".") and not any(
            p.startswith(".") for p in f.relative_to(path).parts
        )
    )
    h = hashlib.sha256()
    for fp in files:
        h.update(_sha256_file(fp).encode())
    return h.hexdigest()
```

### 2.8 Same-filesystem check

```python
def _same_filesystem(a: Path, b: Path) -> bool:
    """True if a and b reside on the same mounted filesystem."""
    try:
        return a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False
```

---

## 3. Exact Files to Modify

**None.** CLI integration (adding the `import` subparser and `cmd_import` to `cli.py`) is a separate phase that follows this one. This module is wired in later.

---

## 4. Test Specifications — `tests/test_import.py`

### Shared fixtures/helpers

```python
def _config(tmp_path: Path, *, allow_downloads: bool = False) -> Config:
    """Create a Config with a temp shelf. Mirrors test_resolver._config."""
    shelf = tmp_path / "shelf"
    shelf.mkdir(parents=True, exist_ok=True)
    return Config(shelf_root=shelf, allow_downloads=allow_downloads)
```

### Test 1: `test_import_gguf_file`

| Aspect | Detail |
|---|---|
| **Description** | Import a `.gguf` file, verify it lands at the correct shelf path and a manifest entry is created. |
| **Setup** | Create a temp `.gguf` file with known content (e.g. `b"fake gguf model data\n"`). Create `_config(tmp_path)`. |
| **Action** | `import_model(cfg, source_gguf)` |
| **Assertions** | `result.status == "imported"`, `result.format == "gguf"`, `result.path.exists()`, `result.path.suffix == ".gguf"`, `result.repo_id` contains a `/`, manifest entry exists with correct SHA256. |

### Test 2: `test_import_mlx_directory`

| Aspect | Detail |
|---|---|
| **Description** | Import a directory containing `config.json` + model files, verify all files are transferred. |
| **Setup** | Create temp dir with `config.json`, `model.safetensors`, `tokenizer.json`. `_config(tmp_path)`. |
| **Action** | `import_model(cfg, source_dir)` |
| **Assertions** | `result.status == "imported"`, `result.format == "mlx"`, `result.path.is_dir()`, all three files present in target dir, manifest `files` list has 3 entries. |

### Test 3: `test_import_rejects_dir_without_config_json`

| Aspect | Detail |
|---|---|
| **Description** | Raise `ValueError` when source is a directory lacking `config.json`. |
| **Setup** | Create empty temp dir (no `config.json`). `_config(tmp_path)`. |
| **Action** | `import_model(cfg, empty_dir)` |
| **Assertions** | `pytest.raises(ValueError, match="config.json")`. Nothing created on shelf. |

### Test 4: `test_import_hardlink_same_fs`

| Aspect | Detail |
|---|---|
| **Description** | When source and shelf are on the same filesystem, `os.link()` is used (same inode). |
| **Setup** | Create a `.gguf` file in a temp dir. Shelf is in the same `tmp_path` (guaranteed same fs). `_config(tmp_path)`. |
| **Action** | `import_model(cfg, source_gguf, hardlink=True)` |
| **Assertions** | `result.status == "imported"`, `os.stat(source).st_ino == os.stat(result.path).st_ino`, file content matches. |

### Test 5: `test_import_skips_duplicate`

| Aspect | Detail |
|---|---|
| **Description** | Importing the same file twice returns `skipped_duplicate` on the second call. |
| **Setup** | Create a `.gguf` with unique content. `_config(tmp_path)`. |
| **Action** | Call `import_model` twice with the same source. |
| **Assertions** | First call: `status == "imported"`. Second call: `status == "skipped_duplicate"`, `message` mentions "duplicate" or "already". Only one manifest entry exists. |

### Test 6: `test_import_updates_manifest`

| Aspect | Detail |
|---|---|
| **Description** | After a successful import, `manifest.json` contains a correct entry with all required fields. |
| **Setup** | Create a `.gguf` with known content (predictable SHA256). `_config(tmp_path)`. |
| **Action** | `import_model(cfg, source)` |
| **Assertions** | `manifest.json` exists at `cfg.shelf_root / "manifest.json"`. Entry has keys: `format`, `sha256`, `files`, `size_bytes`, `source`, `imported_from`, `downloaded`. SHA256 matches pre-computed value. `files` list contains the filename. |

### Test 7: `test_import_handles_org_override`

| Aspect | Detail |
|---|---|
| **Description** | `--org custom-org` is respected in the repo_id and target path. |
| **Setup** | Create a `.gguf` file: `some-model-Q4_K_M.gguf`. `_config(tmp_path)`. |
| **Action** | `import_model(cfg, source_gguf, org="my-org")` |
| **Assertions** | `result.repo_id == "my-org/some-model-Q4_K_M"`. Target path is under `shelf_root/gguf/my-org/some-model-Q4_K_M/some-model-Q4_K_M.gguf`. |

### Test 8: `test_import_auto_detect_quant`

| Aspect | Detail |
|---|---|
| **Description** | Quant is extracted from the GGUF filename and stored in the manifest entry. |
| **Setup** | Create a `.gguf` named `Qwythos-9B-v2-MTP-Q4_K_M.gguf` (mimics real-world name). `_config(tmp_path)`. |
| **Action** | `import_model(cfg, source_gguf)` |
| **Assertions** | Manifest entry has `"quant": "Q4_K_M"`. If quant detection fails on a filename without a quant pattern, `quant` is `None` but import still succeeds. |

---

## 5. Conventions Checklist

| Convention | Evidence / Source |
|---|---|
| `from __future__ import annotations` | Every source file: `resolver.py:17`, `config.py:16`, `cli.py:3`, `search.py:12`, `detect.py:9`, `relocate.py:14` |
| Type hints on all public functions | `resolver.py` — `resolve_model()`, `init_shelf()`, `check_storage_available()` all have full annotations |
| Dataclasses with `to_dict()` | `ResolveResult` (`resolver.py:58-65`), `FindResult` (`search.py:21-25`) |
| `pathlib.Path` everywhere | Zero uses of `os.path` in any source file |
| `--json` flag convention | `cli.py:84` (`cmd_resolve`), `cli.py:130` (`cmd_find`) |
| `--dry-run` convention | Not yet in codebase, but required per implementation plan for destructive ops. Import is non-destructive except for manifest writes, so `--dry-run` is not on `import_model` itself (CLI will add it). |
| `cmd_*` signature: `(args, cfg) -> int` | `cli.py:75` (`cmd_resolve`), `cli.py:129` (`cmd_find`), `cli.py:177` (`cmd_init`) |
| Exit codes: 0=success, 1=not found, 2=ValueError/StorageError, 3=external API error | `cli.py:86` (resolve returns 0/1), `cli.py:217-228` (exception routing) |
| Error classes subclass `RuntimeError` | `StorageNotAvailableError`, `ShelfNotInitializedError` in `resolver.py:36-39` |
| `_config(tmp_path)` helper in tests | `test_resolver.py:73-76` |
| `monkeypatch` for isolation in tests | `test_resolver.py:172-176` (`_patch_candidates`), `test_config.py:41` |
| Atomic writes: write to `.tmp` + `os.rename()` | Conventions doc §"New module conventions" and implementation plan §"General notes" |
| SHA256 via `hashlib.sha256()` with 64 KB chunks | Conventions doc §"General notes" and implementation plan §"General notes" |
| Dot-prefixed entries skipped | `_print_shelf_contents` in `cli.py:153` and conventions doc |
| Repo ID always `org/repo` with slash | `_split_repo_id()` in `resolver.py:112-118`, enforced with `ValueError` |
| Quant: case-insensitive, extracted from filename | `conventions.md §Naming` |

---

## 6. Existing Code Patterns to Follow

### 6.1 Config usage pattern (from `resolver.py`)

```python
# resolver.py:73-76 — test helper (mirror in test_import.py)
def _config(tmp_path: Path, *, allow_downloads: bool = False) -> Config:
    shelf = tmp_path / "shelf"
    shelf.mkdir(parents=True, exist_ok=True)
    return Config(shelf_root=shelf, allow_downloads=allow_downloads)

# resolver.py:88 — accessing shelf_root
cfg.shelf_root / "gguf" / publisher / repo / filename

# resolver.py:84-86 — check_storage_available gate
check_storage_available(config)
```

### 6.2 Dataclass pattern (from `ResolveResult`, `resolver.py:54-65`)

```python
@dataclass
class ResolveResult:
    status: str
    source: str
    format: str
    path: Path | None
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "source": self.source,
            "format": self.format,
            "path": str(self.path) if self.path else None,
            "checks": list(self.checks),
        }
```

Key takeaway: `to_dict()` is a manual method, not `asdict()`. Convert `Path` to `str`. Use `field(default_factory=list)` for mutable defaults.

### 6.3 Error handling pattern (from `resolver.py`)

```python
# resolver.py:36-39 — error class hierarchy
class StorageNotAvailableError(RuntimeError):
    """..."""

class ShelfNotInitializedError(StorageNotAvailableError):
    """..."""

# resolver.py:112-118 — ValueError for bad input
if "/" not in repo_id:
    raise ValueError(
        f"repo_id must be in 'publisher/repo' format ... got: {repo_id!r}"
    )

# resolver.py:131-132 — early validation gate
if fmt not in SUPPORTED_FORMATS:
    raise ValueError(f"unsupported format: {fmt!r}")
```

Key takeaway: `ValueError` for bad input, `RuntimeError` subclass for operational failures. Clear, actionable messages with `!r` for values.

### 6.4 CLI subcommand pattern (from `cli.py` — for reference when wiring later)

```python
# cli.py:75-86 — cmd_* function signature
def cmd_resolve(args: argparse.Namespace, cfg: Config) -> int:
    ...
    return 0 if result.status != "missing" else 1

# cli.py:197-215 — subparser wiring
p_resolve = sub.add_parser("resolve", ...)
p_resolve.add_argument("repo_id", ...)
p_resolve.add_argument("--format", ...)
p_resolve.add_argument("--json", action="store_true", ...)

# cli.py:217-228 — main() dispatch + error routing
try:
    if args.command == "resolve":
        return cmd_resolve(args, cfg)
except StorageNotAvailableError as e:
    print(f"model-shelf: {e}", file=sys.stderr)
    return 2
except ValueError as e:
    print(f"model-shelf: {e}", file=sys.stderr)
    return 2
except Exception as e:
    msg = str(e).strip().splitlines()[-1] if str(e).strip() else type(e).__name__
    print(f"model-shelf: {type(e).__name__}: {msg}", file=sys.stderr)
    return 3
```

### 6.5 Format detection pattern (from `resolver.py:101-108`)

```python
def detect_format(repo_id: str) -> str:
    parts = repo_id.split("/")
    name = parts[-1].lower()
    tokens = set(filter(None, re.split(r"[-_./]", name)))
    if "gguf" in tokens:
        return "gguf"
    org = parts[0].lower() if len(parts) > 1 else ""
    if org == "mlx-community" or "mlx" in tokens:
        return "mlx"
    return "safetensors"
```

For import, the heuristic is different (file-based, not repo-id-based):
- `.gguf` extension → gguf
- Directory with `config.json` → mlx (or safetensors — same treatment)

### 6.6 Shelf path construction (from `resolver.py:120-129`)

```python
def shelf_path_gguf(shelf_root: Path, repo_id: str, quant: str) -> Path:
    publisher, repo = _split_repo_id(repo_id)
    return shelf_root / "gguf" / publisher / repo / hf_filename(repo_id, quant)

def shelf_path_snapshot(shelf_root: Path, repo_id: str, fmt: str) -> Path:
    publisher, repo = _split_repo_id(repo_id)
    return shelf_root / fmt / publisher / repo
```

Key takeaway: `shelf_root / format / org / repo / file` is the canonical path convention.

---

## 7. Dependencies and Constraints

| Item | Detail |
|---|---|
| **Python stdlib only** | `hashlib`, `json`, `os`, `shutil`, `pathlib`, `dataclasses`, `datetime` — no new PyPI deps |
| **No huggingface_hub usage** | Import is purely local; HF downloads are handled by `resolver.py` |
| **Manifest is shelf-relative** | `manifest.json` lives at `config.shelf_root / "manifest.json"` |
| **Atomic manifest writes** | Write to `.tmp`, `os.rename()` — no partial reads possible |
| **Same-fs hardlink** | Check `st_dev` before `os.link()`; fall back to `shutil.copy2()` with warning |
| **Dot-file filtering** | Skip `.`-prefixed files and directories (e.g., `.cache/`, `.DS_Store`) |
| **Python ≥3.11** | `from __future__ import annotations` enables PEP 604 `X | None` syntax |
| **Config import** | `from model_shelf.resolver import Config` — reuse existing Config dataclass |

---

## 8. Risks and Open Questions

| Risk | Mitigation |
|---|---|
| **Org/repo inference is heuristic** | Accept `org=` override. Fall back to source parent dir name. Document that `--org` is available for ambiguous cases. |
| **SHA256 on large files** | Stream in 64 KB chunks. No memory issue for multi-GB models. |
| **Cross-fs hardlink failure** | Detected via `st_dev` comparison before `os.link()`. Falls back to copy with a warning. |
| **Race on manifest (two concurrent imports)** | `os.rename()` is atomic on POSIX. Last writer wins; both entries would exist. Acceptable for a local CLI tool. |
| **Composite SHA256 for directories** | Hashing each file then hashing the concatenated digests is deterministic but won't match a tarball SHA256. This is fine — duplicate detection only needs to be self-consistent. |
| **Quant detection from filename only** | Not reading GGUF header for Phase 2 (that's Phase 3). Regex on filename is ~95% accurate for well-named files. |
| **safetensors vs mlx** | Both are directory formats with `config.json`. Default to `mlx` when format is not specified. `--format safetensors` override supported. |

---

## 9. Validation Steps (for the implementing agent)

After implementing, verify locally:

```bash
# Run the test suite for the new module only
python -m pytest tests/test_import.py -v

# Ensure existing tests still pass (regression)
python -m pytest tests/ -v

# Manual smoke test (not automated — validation only)
python -c "
from pathlib import Path
from model_shelf.resolver import Config
from model_shelf.import_model import import_model
import tempfile, os

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    shelf = root / 'shelf'
    shelf.mkdir()
    src = root / 'test-model.gguf'
    src.write_bytes(b'fake gguf content\\n')
    cfg = Config(shelf_root=shelf)
    result = import_model(cfg, src)
    print(result.to_dict())
    assert result.status == 'imported'
    assert result.path.exists()
    print('OK')
"
```

---

## 10. Summary for the Next Agent

**You are implementing Phase 2 of the model-shelf import pipeline.** Produce two files and touch nothing else:

1. **`src/model_shelf/import_model.py`** — `ImportResult` dataclass, `import_model()` function, private manifest/SHA256 helpers.
2. **`tests/test_import.py`** — 8 tests as specified in §4.

The module must be importable as `from model_shelf.import_model import import_model, ImportResult` and work with the existing `Config` from `model_shelf.resolver`.

CLI wiring (`cli.py` changes) is explicitly NOT part of this phase. The migration script will call `import_model()` directly.
