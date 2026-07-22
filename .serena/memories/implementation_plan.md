# Implementation Plan — model-shelf contributions

## Phase 1: Migration Script (companion, lives at ~/Projects/ansible-playbooks/)

**File**: `~/Projects/ansible-playbooks/model-shelf-migrate` (executable Python script, no .py extension)

### Steps
1. Scan all 7 user locations, SHA256 every file > 10MB.
2. Infer org/model/format/quant from path:
   - `~/models/Qwythos-9B-v2-MTP-Q4_K_M.gguf` → org=empero-ai, model=Qwythos-9B-v2-GGUF, format=gguf, quant=Q4_K_M
   - `~/.models/gguf/protoLabsAI/Ornith-1.0-9B-MTP-GGUF/` → org=protoLabsAI, format=gguf
   - `~/.omlx/models/llama-3.1-8b/` → org=mlx-community, model=Llama-3.1-8B-Instruct-4bit, format=mlx
   - Path heuristics: match against known naming patterns, fall back to interactive prompt
3. SHA256 all Ollama blobs (`~/.ollama/models/blobs/*`), cross-reference with catalog.
4. Print interactive table:
   ```
   Model                          Size    SHA256 (first 8)   Duplicate of
   ─────                          ────    ────────────────   ────────────
   ~/models/Qwythos-9B...gguf     5.5GB   cfdd00ac           [ORIGINAL]
   ~/.cache/hf/.../Qwythos...gguf 5.9GB   cfdd00ac           ← SAME AS ABOVE
   ```
5. Ask user: "Save X GB by hardlinking these N duplicates? (y/n/choose)"
6. For each non-duplicate: call `model-shelf import <path> --hardlink`
7. For each duplicate: create hardlink from shelf to canonical copy
8. Call `model-shelf manifest --rebuild`
9. Report: "Removed X GB of duplicates. Y models now tracked in ~/.cache/model-shelf/models/"

### Dependencies
- Python stdlib only (hashlib, pathlib, subprocess for model-shelf calls)
- Runs before model-shelf code changes (import command used, but migration script is standalone)

---

## Phase 2: `import` command

### New file: `src/model_shelf/import_model.py`

```python
# Public API
def import_model(config: Config, source: Path, *, format: str | None = None,
                 org: str | None = None, hardlink: bool = True) -> ImportResult:
    ...

# Dataclass
@dataclass
class ImportResult:
    status: str        # "imported" | "skipped_duplicate" | "error"
    repo_id: str       # inferred org/repo
    format: str
    path: Path | None  # new shelf path
    sha256: str
    message: str
```

### Key logic
1. Detect format (gguf by extension, mlx/safetensors by `config.json` presence).
2. Infer org/repo from path heuristics (parent dir names, filename patterns).
3. Compute SHA256.
4. Check manifest for existing entry with same SHA256 → skip.
5. Create target dir: `shelf_root/{format}/{org}/{repo}/`.
6. For GGUF: hardlink/copy the .gguf file, auto-detect quant from filename.
7. For MLX/safetensors: hardlink/copy all files, require `config.json`.
8. Update manifest.json atomically.

### CLI integration (cli.py)
```python
def cmd_import(args, cfg) -> int:
    result = import_model(cfg, Path(args.path), ...)
    if args.json: print(json.dumps(result.to_dict()))
    else: _print_import_pretty(result)
    return 0 if result.status != "error" else 1
```

### Tests: `tests/test_import.py`
- `test_import_gguf_file` — imports a .gguf, verifies shelf path, manifest entry
- `test_import_mlx_directory` — imports dir with config.json, verifies all files copied
- `test_import_rejects_dir_without_config_json` — raises error
- `test_import_hardlink_same_fs` — verifies `os.link()` used, same inode
- `test_import_skips_duplicate` — second import of same SHA256 returns "skipped_duplicate"
- `test_import_updates_manifest` — manifest.json has entry after import
- `test_import_handles_org_override` — `--org custom-org` respected
- `test_import_auto_detect_quant` — quant extracted from GGUF filename

---

## Phase 3: `manifest` command

### New file: `src/model_shelf/manifest.py`

```python
MANIFEST_PATH = "manifest.json"  # relative to shelf_root

# Public API
def load_manifest(shelf_root: Path) -> dict: ...
def save_manifest(shelf_root: Path, data: dict) -> None: ...  # atomic write
def rebuild_manifest(config: Config) -> ManifestResult: ...
def get_manifest_entry(shelf_root: Path, repo_id: str) -> dict | None: ...
def add_manifest_entry(shelf_root: Path, repo_id: str, entry: dict) -> None: ...
def remove_manifest_entry(shelf_root: Path, repo_id: str) -> None: ...
```

### Schema (manifest.json at `shelf_root/manifest.json`)
```json
{
  "version": 1,
  "updated": "2025-07-21T18:00:00Z",
  "shelf_root": "/Users/jeffersonsantos/.cache/model-shelf/models",
  "models": {
    "empero-ai/Qwythos-9B-v2-GGUF": {
      "format": "gguf",
      "quant": "Q4_K_M",
      "params": "9B",
      "size_bytes": 5903822528,
      "sha256": "cfdd00ac1c1dc9ced33f23817fb4282f2594067e02e34d82e3e63bc0ea275b05",
      "files": ["Qwythos-9B-v2-MTP-Q4_K_M.gguf"],
      "source": "imported",
      "imported_from": "/Users/jeffersonsantos/models/Qwythos-9B-v2-MTP-Q4_K_M.gguf",
      "downloaded": "2025-07-21T18:00:00Z",
      "hardlinks": []
    }
  }
}
```

### Quantization & params detection (unified — GGUF, MLX, safetensors)

**Goal**: a single `detect_quant(source, fmt)` function that works for all three formats.
Prefer structural metadata (binary header, config.json); fall back to filename heuristics.

#### GGUF — binary header parsing (PoC confirmed ✅)

PoC on real model: `nomic-embed-text-v1.5.Q4_K_M.gguf` (80 MB)

```
GGUF v3, 23 metadata keys
  general.architecture: nomic-bert
  general.name: nomic-embed-text-v1.5
  general.file_type: 15 → Q4_K_M ✅
  filename quant: Q4_K_M
```

**Approach**: read magic + version → skip tensor_count → iterate metadata KV pairs.
Stop after finding `general.file_type`. Required field: `general.file_type` (uint32),
mapped via `FILETYPE_MAP` dict (GGUF spec, 25 known values).

**Code snippet**:
```python
import struct
from pathlib import Path

FILETYPE_MAP = {
    0: 'F32', 1: 'F16', 2: 'Q4_0', 3: 'Q4_1', 7: 'Q8_0', 8: 'Q8_1',
    10: 'Q2_K', 13: 'Q3_K_L', 14: 'Q4_K_S', 15: 'Q4_K_M', 16: 'Q5_K_M',
    17: 'Q6_K', 18: 'Q8_K', 19: 'IQ2_XXS', 20: 'IQ2_XS', 21: 'IQ3_XXS',
    22: 'IQ1_S', 23: 'IQ4_XS', 24: 'IQ1_M',
}
SIZES = {0:1, 1:1, 2:2, 3:2, 4:4, 5:4, 6:4, 7:1, 10:8, 11:8, 12:8}

def _quant_from_gguf_header(path: Path) -> str | None:
    """Extract quant from GGUF binary header. Returns None if not GGUF or missing field."""
    try:
        with open(path, 'rb') as f:
            if f.read(4) != b'GGUF':
                return None
            version = struct.unpack('<I', f.read(4))[0]
            f.read(8)  # tensor_count
            kv_count = struct.unpack('<Q', f.read(8))[0]
            for _ in range(kv_count):
                klen = struct.unpack('<Q', f.read(8))[0]
                key = f.read(klen).decode()
                type_id = struct.unpack('<I', f.read(4))[0]
                if key == 'general.file_type' and type_id == 4:  # uint32
                    file_type = struct.unpack('<I', f.read(4))[0]
                    return FILETYPE_MAP.get(file_type)
                # skip value
                if type_id == 8:
                    slen = struct.unpack('<Q', f.read(8))[0]
                    f.read(slen)
                elif type_id == 9:
                    f.read(4)
                    alen = struct.unpack('<I', f.read(4))[0]
                    f.read(alen * SIZES.get(struct.unpack('<I', f.read(0) or b'\x00'*4)[0] if False else 4, 8))
                elif type_id in SIZES:
                    f.read(SIZES[type_id])
    except (OSError, struct.error, UnicodeDecodeError):
        pass
    return None
```

**Expected result**: `Q4_K_M`, `F16`, `IQ3_XXS`, etc. from header. Fallback to filename regex if header parsing fails.

#### MLX — config.json quantization

```json
// config.json in mlx-community/* repos
{
  "quantization": { "group_size": 64, "bits": 4 }
}
// → "Q4"
```

```python
def _quant_from_config_json(path: Path) -> str | None:
    """Extract quant from config.json (MLX or safetensors repos)."""
    config_path = path / "config.json" if path.is_dir() else None
    if config_path is None or not config_path.is_file():
        return None
    try:
        data = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    # MLX: quantization.bits
    if 'quantization' in data:
        q = data['quantization']
        if 'bits' in q:
            return f"Q{q['bits']}"
    return None
```

#### Safetensors — config.json quantization_config or torch_dtype

```json
// GPTQ/AWQ quantized
{ "quantization_config": { "quant_method": "gptq", "bits": 4 } }
// → "GPTQ-4bit"

// Full precision
{ "torch_dtype": "float16" }
// → "F16"
```

```python
def _quant_from_config_json(path: Path) -> str | None:
    # ... same function as MLX, extended:
    # Safetensors GPTQ/AWQ: quantization_config.quant_method + bits
    if 'quantization_config' in data:
        qc = data['quantization_config']
        method = qc.get('quant_method', '').upper()
        bits = qc.get('bits', '')
        if method and bits:
            return f"{method}-{bits}bit"
    # Safetensors full precision: torch_dtype
    if 'torch_dtype' in data:
        dtype = data['torch_dtype']
        MAP = {'float16': 'F16', 'bfloat16': 'BF16', 'float32': 'F32'}
        if dtype in MAP:
            return MAP[dtype]
    return None
```

#### Unified entry point

```python
def detect_quant(source: Path, fmt: str) -> str | None:
    """Detect quantization for a model. Header/config.json first, filename fallback."""
    if fmt == 'gguf':
        return _quant_from_gguf_header(source) or _quant_from_filename(source)
    if fmt in ('mlx', 'safetensors'):
        return _quant_from_config_json(source)
    return None
```

#### GGUF params detection (architecture, parameter_count)
- Read first 4 bytes → magic number `GGUF`.
- Read version, then key-value metadata table.
- Extract `general.architecture`, `general.parameter_count`, or compute from config.
- If header parsing fails, infer from filename (e.g., `*9B*` → "9B").

### CLI integration
```python
def cmd_manifest(args, cfg) -> int:
    if args.rebuild:
        result = rebuild_manifest(cfg)
    else:
        data = load_manifest(cfg.shelf_root)
        result = ManifestResult(status="ok", data=data)
    ...
```

### Tests: `tests/test_manifest.py`
- `test_rebuild_empty_shelf` — manifest has version and empty models dict
- `test_rebuild_with_models` — shelf has gguf + mlx, manifest entries created
- `test_rebuild_detects_params_from_config_json` — MLX model params from config.json
- `test_rebuild_detects_params_from_gguf_header` — GGUF params from binary header
- `test_rebuild_skips_dot_dirs` — `.cache/` filtered out
- `test_load_manifest_missing_file` — returns empty default
- `test_save_manifest_atomic` — no partial writes
- `test_add_remove_entry` — CRUD operations on manifest

### Tests: `tests/test_quant.py` (new — unified quant detection)
- `test_gguf_header_q4_k_m` — PoC-confirmed: `general.file_type=15` → `Q4_K_M`
- `test_gguf_header_f16` — `general.file_type=1` → `F16`
- `test_gguf_header_iq3_xxs` — `general.file_type=21` → `IQ3_XXS`
- `test_gguf_fallback_to_filename` — non-GGUF binary → filename regex fallback
- `test_mlx_config_bits` — `config.json` with `quantization.bits=4` → `Q4`
- `test_safetensors_gptq` — `config.json` with `quantization_config.quant_method=gptq, bits=4` → `GPTQ-4bit`
- `test_safetensors_awq` — `config.json` with `quantization_config.quant_method=awq, bits=4` → `AWQ-4bit`
- `test_safetensors_full_precision_f16` — `config.json` with `torch_dtype=float16` → `F16`
- `test_unified_detect_quant_gguf` — `detect_quant(path, 'gguf')` uses header + filename
- `test_unified_detect_quant_mlx` — `detect_quant(path, 'mlx')` uses config.json
- `test_unified_detect_quant_safetensors` — `detect_quant(path, 'safetensors')` uses config.json

---

## Phase 4: `dedup` command

### New file: `src/model_shelf/dedup.py`

```python
@dataclass
class DedupResult:
    groups: list[DedupGroup]  # each group = files with same SHA256
    total_duplicate_bytes: int
    potential_savings_bytes: int

@dataclass
class DedupGroup:
    sha256: str
    files: list[Path]
    size_bytes: int
    duplicate_bytes: int  # (len(files) - 1) * size_bytes
```

### Key logic
1. Build SHA256 map of all files in shelf (walk `shelf_root/{gguf,mlx,safetensors}/`).
2. If `--include-ollama`: SHA256 all `~/.ollama/models/blobs/*`.
3. If `--include-hf-cache`: SHA256 all `~/.cache/huggingface/hub/blobs/*`.
4. Group by SHA256, filter to groups with > 1 entry.
5. Print table (or JSON).
6. If not `--dry-run`: for each group, keep shelf copy as canonical, `os.link()` others to it,
   then `os.unlink()` the originals.
7. Update manifest hardlinks field.

### Safety constraints
- Never hardlink across filesystems (check `os.stat().st_dev`).
- Ollama blobs: only hardlink if the GGUF on the shelf is byte-identical.
  Keep the Ollama blob path intact (hardlink destination, not source).
- HF cache: treat as external — hardlink from shelf into cache blobs is OK,
  but don't unlink HF cache blobs (HF might re-download).

### CLI integration
```python
def cmd_dedup(args, cfg) -> int:
    result = find_duplicates(cfg, include_ollama=args.include_ollama,
                             include_hf_cache=args.include_hf_cache)
    if args.dry_run:
        _print_dedup_report(result)
        return 0
    dedup_result = execute_dedup(cfg, result)
    ...
```

### Tests: `tests/test_dedup.py`
- `test_finds_identical_files_in_shelf` — two identical GGUFs detected
- `test_dry_run_makes_no_changes` — files unchanged after dry run
- `test_creates_hardlinks` — `os.link()` called, old file removed, same inode
- `test_reports_correct_savings` — byte maths correct
- `test_include_ollama` — cross-references Ollama blobs
- `test_include_hf_cache` — cross-references HF cache
- `test_skips_across_filesystems` — doesn't try to hardlink across devs
- `test_respects_dot_dir_filter` — `.cache/` ignored

---

## Phase 5: `audit`, `remove`, `gc` commands

### `src/model_shelf/audit.py`

```python
@dataclass
class AuditResult:
    missing: list[str]     # manifest entries whose files don't exist
    untracked: list[Path]  # files on shelf not in manifest
    stale: list[str]       # manifest entries whose SHA256 doesn't match

@dataclass
class RemoveResult:
    removed: list[Path]
    hardlinks_warn: list[Path]  # other paths that shared the same inode

@dataclass
class GCResult:
    incomplete_downloads: list[Path]  # dirs without config.json and no .gguf
    orphaned_files: list[Path]        # files not in manifest
    empty_dirs: list[Path]
    total_reclaimable_bytes: int
```

### `audit` logic
1. Load manifest.
2. For each entry: check each file exists, SHA256 matches → if not, flag as `stale`/`missing`.
3. Walk shelf, find files not in manifest → `untracked`.
4. Exit 0 if clean, 1 if issues.

### `remove` logic
1. Load manifest entry.
2. Check hardlinks: `os.stat().st_nlink > 1` → warn.
3. `--dry-run`: print what would be removed.
4. Otherwise: unlink all files, rmdir if empty, remove manifest entry.

### `gc` logic
1. Walk shelf, find dirs without model files (`config.json` for mlx/safetensors, `.gguf` for gguf).
2. Find files not in manifest and not in `.cache/` or `.` prefixed dirs.
3. Find empty directories.
4. Report total reclaimable bytes.
5. Default `--dry-run`; `--execute` to actually delete.

### CLI integration
```python
# In cli.py
def cmd_audit(args, cfg) -> int: ...
def cmd_remove(args, cfg) -> int: ...
def cmd_gc(args, cfg) -> int: ...
```

### Tests: `tests/test_audit.py`
- `test_audit_clean_shelf` — no issues found, exit 0
- `test_audit_missing_file` — manifest entry with file gone → flagged
- `test_audit_untracked_file` — file on shelf not in manifest → flagged
- `test_audit_stale_sha256` — file modified after manifest → flagged
- `test_remove_deletes_files_and_entry` — model gone after remove
- `test_remove_dry_run_preserves_files` — nothing deleted
- `test_remove_warns_hardlinks` — warns when st_nlink > 1
- `test_gc_finds_incomplete_download` — dir without config.json flagged
- `test_gc_finds_orphaned_files` — file not in manifest flagged
- `test_gc_dry_run_default` — no files deleted without --execute
- `test_gc_skips_dot_dirs` — .cache/ not flagged

---

## Implementation order

```
1. import_model.py + test_import.py     ← done ✅ (Fase 2)
1.5 detect_quant upgrade               ← upgrade _detect_quant_from_filename → detect_quant
                                          (GGUF header + MLX config.json + safetensors config.json)
2. manifest.py + test_manifest.py       ← foundation for audit/dedup
3. dedup.py + test_dedup.py             ← biggest space savings
4. audit.py + test_audit.py             ← ongoing maintenance
5. cli.py updates (wired incrementally) ← after each module
6. Migration script                     ← after import + manifest are done
```

## General notes
- All new modules use the same patterns as existing code: `from __future__ import annotations`,
  type hints, dataclasses with `to_dict()`, `--json` + `--dry-run` flags.
- Atomic manifest writes: write to `manifest.json.tmp`, `os.rename()` to final path.
- SHA256: `hashlib.sha256()`, read files in 64KB chunks for large files.
- GGUF header parsing: vendored minimal parser (only what we need for params + metadata),
  no external dependency.
