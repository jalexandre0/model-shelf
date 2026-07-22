# Migration Script — Implementation Handoff

## Purpose

Standalone Python script that migrates Jeff's scattered model files into the curated `model-shelf` structure, eliminates duplicates via hardlinks, and produces a clean manifest.

## Script Location

`~/Projects/mac-setup/model-shelf-migrate` (executable, no `.py` extension, shebang `#!/usr/bin/env python3`)

Alternative fallback location: a new script in this repo at `scripts/model-shelf-migrate`.

---

## Design (8 Steps)

### Step 1 — Scan all 7 known model locations recursively

```python
LOCATIONS = {
    'models':          Path.home() / 'models',
    'hf-cache':        Path.home() / '.cache' / 'huggingface' / 'hub',
    'lmstudio':        Path.home() / '.lmstudio',
    'ollama-blobs':    Path.home() / '.ollama' / 'models' / 'blobs',
    'ollama-manifest': Path.home() / '.ollama' / 'models' / 'manifests',
    'omlx':            Path.home() / '.omlx' / 'models',
    'model-shelf':     Path.home() / '.cache' / 'model-shelf' / 'models',
}
```

For each location that exists, `rglob('*')` all files. Skip:
- Dot-prefixed files except `.gguf`
- Files with `.cache/` in path (when inside blobs dirs — but the migration script itself walks `.cache/huggingface/hub`, so only skip `.cache` *within already-scanned dirs*)
- macOS resource forks (`._*`)

### Step 2 — SHA256 every file > 10MB

```python
MODEL_EXTENSIONS = {'.gguf', '.safetensors', '.bin', '.pt', '.pth', '.onnx'}

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()
```

Hashing rules (from PoC — confirmed working):
- Only hash files > 10MB
- Only hash model-like files (extension in MODEL_EXTENSIONS, or passes GGUF magic check, or extensionless blob)
- In blobs dirs (ollama-blobs, hf-cache blobs), only hash model-like files
- Never hash the existing model-shelf shelf — it's the destination

**Important constraint**: Do NOT hash files already inside `~/.cache/model-shelf/models/` — that's the destination. The script scans it to detect what's already imported (so it can skip them), but doesn't re-hash already-tracked entries.

### Step 3 — Cross-reference by SHA256 to find duplicates

Build a `defaultdict(list)` mapping SHA256 → list of `(location_label, path, size)` tuples.

Duplicate detection:
- Same SHA256 in multiple locations → duplicate group
- Keep the copy in `~/.cache/model-shelf/models/` (already imported) as canonical if it exists
- Otherwise, prefer the copy in `~/models/` as canonical

### Step 4 — Print interactive table

```
Model                                    Size      SHA256 (first 8)   Duplicate of
─────                                    ────      ────────────────   ────────────
[models] Qwythos-9B-v2-MTP-Q4_K_M.gguf  5.5 GB     cfdd00ac           [ORIGINAL]
[hf-cache] .../blobs/abc123             5.9 GB     cfdd00ac           ← SAME AS ABOVE
[ollama-blobs] sha256-cfdd00ac...        5.5 GB     cfdd00ac           ← SAME AS ABOVE

Unique models: 12
Duplicate groups: 3
Total waste: 34.2 GB
```

### Step 5 — Interactive prompt

"Save 34.2 GB by hardlinking these 5 duplicates? (y/n/choose)"

Choosing "n" skips hardlinking, but still imports all uniques.
Choosing "choose" allows per-group selection.

### Step 6 — Call `model-shelf import <path> --execute` for each unique model

For every unique model (first occurrence in each SHA256 group, or files with no duplicates):

```python
subprocess.run(
    ['model-shelf', 'import', str(path), '--execute', '--hardlink'],
    check=True
)
```

The `import` command already:
- Detects format (gguf/mlx/safetensors) via `_detect_format_from_path()`
- Infers org/repo from path via `_infer_org_repo()`
- Computes SHA256 via `_sha256_file()` / `_sha256_directory()`
- Checks manifest for duplicates (skip if already there)
- Hardlinks into shelf (same filesystem) or copies (cross-filesystem)
- Atomically updates manifest.json

**Import dedup**: The script should track which SHA256s were successfully imported. If two files share the same SHA256, only import one — the second is a duplicate handled in Step 7.

### Step 7 — Hardlink duplicates after import

For each duplicate group:
- Canonical = the file now in the shelf (shelf_root/gguf/org/repo/...)
- For each other file in the group:
  - Check same filesystem (`os.stat().st_dev`)
  - Use atomic hardlink replace pattern from `dedup.py`:
    ```python
    tmp = target.with_suffix(target.suffix + '.msmigrate')
    os.link(str(canonical), str(tmp))
    os.replace(str(tmp), str(target))
    ```
  - **Never unlink Ollama blobs or HF cache blobs** — only hardlink them to shelf copies

### Step 8 — Call `model-shelf manifest --rebuild`

```python
subprocess.run(['model-shelf', 'manifest', '--rebuild'], check=True)
```

This walks the shelf, discovers all models, and rebuilds manifest.json from disk.
It preserves existing manifest entries (keeps `hardlinks`, `imported_from`, `source` fields)
while updating SHA256, files, size_bytes from current disk state.

### Step 9 — Report

```
Migration complete:
  12 models imported to ~/.cache/model-shelf/models/
  34.2 GB recovered via hardlinking 5 duplicates
  Run `model-shelf list` to see your shelf
```

---

## Key Code Paths to Reuse (DO NOT COPY — call via subprocess)

### `model-shelf import <path> --execute`

**Entry point**: `src/model_shelf/cli.py` → `cmd_import()` (line ~68)
**Core logic**: `src/model_shelf/import_model.py` → `import_model()` (line ~470)

What it does:
1. `_validate_source()` — resolves path, detects format
2. `_resolve_metadata()` — infers org/repo, detects quant
3. `_compute_sha256()` — SHA256 of file or directory
4. `_check_duplicate()` — checks manifest for same SHA256 → skip
5. `_dest_path()` — computes target shelf path
6. `_ingest_model()` — hardlinks or copies
7. `_record_manifest()` — atomic manifest write

### `model-shelf manifest --rebuild`

**Entry point**: `src/model_shelf/cli.py` → `cmd_manifest()` (line ~174)
**Core logic**: `src/model_shelf/manifest.py` → `rebuild_manifest()` (line ~329)

What it does:
1. `_discover_models_on_disk()` — walks gguf/, mlx/, safetensors/
2. For each model: detects quant, SHA256, files, params
3. Merges with existing manifest (preserves metadata)
4. Removes stale entries (files gone from disk)
5. Atomic save via `save_manifest()`

### `model-shelf dedup` (for reference on hardlink safety)

**Entry point**: `src/model_shelf/cli.py` → `cmd_dedup()` (line ~198)
**Core logic**: `src/model_shelf/dedup.py`

Safety rules the migration script must honor (from dedup.py lines 14-19):
1. Never hardlink across filesystems (`st_dev` check before `os.link`)
2. External blobs (Ollama, HF cache) are destinations only — never unlinked
3. Shelf copy is canonical KEEP
4. Atomic hardlink replace: link to `.tmp` → `os.replace()` → cleanup

---

## Org/Repo Inference (migration-specific)

The `import_model.py` inference (`_infer_org_repo()`) handles the common cases, but the migration script may need additional heuristics for the 7 source locations:

| Source Path | Inferred Org | Inferred Repo | Format |
|---|---|---|---|
| `~/models/Qwythos-9B-v2-MTP-Q4_K_M.gguf` | `local` | `Qwythos-9B-v2-MTP` | gguf |
| `~/.lmstudio/models/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/model-Q4_K_M.gguf` | `bartowski` | `Meta-Llama-3.1-8B-Instruct-GGUF` | gguf |
| `~/.omlx/models/mlx-community/Qwen3-14B-4bit/` | `mlx-community` | `Qwen3-14B-4bit` | mlx |
| `~/.cache/huggingface/hub/models--org--repo/blobs/xxx` | from dir name | from dir name | varies |
| `~/.ollama/models/blobs/sha256-xxx` | `ollama` | `blob-{sha256[:12]}` | gguf |

For Ollama blobs: the import command needs GGUF files. Ollama blobs are raw SHA256-named files (no extension). The PoC confirms they are byte-identical to the source GGUFs. The migration script should:
1. Hash Ollama blobs to cross-reference
2. Only import non-Ollama copies (the .gguf from models/ or lmstudio/)
3. After import, hardlink the Ollama blob to the shelf copy

---

## Dependencies

- **Python stdlib only**: `hashlib`, `pathlib`, `subprocess`, `os`, `sys`, `struct`, `json`, `re`, `argparse`
- **External dependency**: `model-shelf` CLI must be installed and on PATH
- Runs **before** any model-shelf code changes are needed (uses the existing `import` and `manifest` commands)

---

## Test Specifications (from test_specs.md — Phase 6)

### Tier 1 — Pure logic (11 tests)

| Test | Input | Assert |
|---|---|---|
| `test_infer_org_from_path_mlx_community` | `Path("/tmp/mlx-community/Qwen3-14B-4bit/model.safetensors")` | org=`"mlx-community"`, repo=`"Qwen3-14B-4bit"` |
| `test_infer_org_from_path_bartowski` | `Path("/models/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/model-Q4_K_M.gguf")` | org=`"bartowski"`, repo=`"Meta-Llama-3.1-8B-Instruct-GGUF"` |
| `test_infer_quant_from_gguf_filename` | `Path("Qwythos-9B-v2-MTP-Q4_K_M.gguf")` | quant=`"Q4_K_M"`, model=`"Qwythos-9B-v2-MTP"` |
| `test_infer_format_from_path_gguf` | `Path("model.gguf")` | `"gguf"` |
| `test_infer_format_from_path_mlx_dir` | dir with `config.json`, no `.safetensors` | `"mlx"` |
| `test_infer_format_from_path_safetensors_dir` | dir with `config.json` + `model.safetensors` | `"safetensors"` |

### Tier 2 — tmp_path migration simulation (4 tests)

| Test | Fixture | Assert |
|---|---|---|
| `test_migration_scan_finds_all_locations` | mock structure with 3 of 7 locations | scan discovers files from all 3 |
| `test_migration_detects_duplicates_across_locations` | same SHA256 in `models/`, `hf-cache/`, `ollama-blobs/` | 1 duplicate group, 3 entries |
| `test_migration_interactive_table_generation` | 2 unique + 1 duplicate | output has size, SHA256 prefix, "DUPLICATE" tag |
| `test_migration_ollama_blob_cross_reference` | GGUF in shelf = Ollama blob SHA256 | `--include-ollama` shows savings |

### Tier 3 — Real filesystem regression smoke (read-only, 1 test)

| Test | Assert |
|---|---|
| `test_migration_real_scan_is_read_only` | NO files created, modified, or deleted anywhere on real machine |

---

## Constraints & Risks

### Constraints
1. **STANDALONE** — script is self-contained Python. Does NOT import from `src/model_shelf/`. Calls model-shelf via subprocess.
2. **Read-only scan phase** — the scan/hash/table step must not modify any files. Only Steps 6-8 mutate.
3. **Respect existing shelf** — if `~/.cache/model-shelf/models/` already has models, detect and skip them.
4. **Never unlink Ollama blobs** — Ollama will break if its blob files disappear. Hardlink TO the blob (so shelf shares the storage), but never remove the blob.
5. **Never unlink HF cache blobs** — HF might re-download if blobs vanish. Same rule as Ollama.
6. **Cross-filesystem safety** — check `st_dev` before `os.link()`. Fall back to copy with warning.
7. **Stdlib only** — no `questionary`, no `huggingface_hub`, no external Python packages.

### Risks
1. **Large scan time**: 7 locations × potentially TBs of data. The 10MB cutoff helps, but SHA256 on large files is I/O bound. Mitigation: print progress (file N of M, current file name).
2. **Ollama blob naming**: Ollama blobs are named `sha256-<hex>`. Cross-referencing works because we SHA256 them ourselves and compare, but the import command expects a `.gguf` file. The migration script must import the GGUF from a different location (models/ or lmstudio/), not the blob directly.
3. **LM Studio metadata**: LM Studio stores models in `~/.lmstudio/models/` with metadata JSONs. The script must skip non-model files (`.json` metadata, not `config.json`).
4. **GGUF in OMLX**: `~/.omlx/models/` is primarily MLX-format models, but may contain GGUF files too. Format detection must handle both.
5. **Shelf already populated**: If `model-shelf import` was run before, the migration script could re-import. The `import_model` function already skips duplicates by SHA256 (`_check_duplicate()`), so re-running is safe but wasteful. The migration script should track which SHA256s it has imported to avoid calling `import` for already-known models.

---

## Implementation Order

1. **Scan + hash** — adapt PoC `sha256()` + `LOCATIONS` dict + `rglob` loop
2. **Dedup detection** — `defaultdict(list)` SHA256 index, build duplicate groups
3. **Interactive table** — pretty-print with ASCII formatting
4. **Interactive prompt** — `input()` based y/n/choose
5. **Import loop** — `subprocess.run(['model-shelf', 'import', str(path), '--execute'])`
6. **Hardlink loop** — atomic hardlink replace for duplicates (adapt from `dedup.py:_hardlink_replace`)
7. **Manifest rebuild** — `subprocess.run(['model-shelf', 'manifest', '--rebuild'])`
8. **Report** — summary counts and GB recovered

---

## Files to Create

| File | Purpose |
|---|---|
| `~/Projects/mac-setup/model-shelf-migrate` | Main executable (shebang, chmod +x) |
| `tests/test_migration.py` | 11 tests per test_specs.md Phase 6 |

---

## Files Referenced (read-only)

| File | Lines | Why |
|---|---|---|
| `/tmp/poc_migrate.py` | 1-98 | Working scan/hash/dedup PoC — adapt this logic |
| `src/model_shelf/import_model.py` | 470-530 | `import_model()` — called via subprocess, understand its API |
| `src/model_shelf/manifest.py` | 329-370 | `rebuild_manifest()` — called via subprocess after migration |
| `src/model_shelf/dedup.py` | 192-207 | `_hardlink_replace()` — atomic hardlink pattern to adapt |
| `src/model_shelf/dedup.py` | 14-19 | Safety constraints — must honor in migration script |
| `src/model_shelf/dedup.py` | 252-298 | `execute_dedup()` — reference for canonical selection and external-only skip |
| `src/model_shelf/cli.py` | 68-81 | `cmd_import()` — CLI flags for subprocess call |
| `src/model_shelf/cli.py` | 174-195 | `cmd_manifest()` — CLI flags for subprocess call |
| `.serena/memories/implementation_plan.md` | Phase 1 | Original design spec for migration script |
| `.serena/memories/test_specs.md` | Phase 6 | 11 test cases for migration script |

---

## Start Here

1. Open `/tmp/poc_migrate.py` — this is the hardened PoC with working scan logic. Adapt its `LOCATIONS` dict, `sha256()` function, and `MODEL_FILES` set as the foundation.
2. Then open `src/model_shelf/dedup.py` lines 192-207 — copy the `_hardlink_replace()` pattern (tmp file + atomic replace) into the migration script.
3. The `subprocess.run(['model-shelf', 'import', ...])` call is straightforward — just ensure `model-shelf` is on PATH.
