# Phase 4 Handoff: `dedup` Command

## Files Retrieved

1. **`src/model_shelf/import_model.py`** (lines 119-155) — `_sha256_file` and `_sha256_directory` are the canonical SHA256 helpers. `_ingest_file` (lines 260-271) shows the hardlink/copy pattern with same-fs check. Dedup must reuse these or replicate the same logic.

2. **`src/model_shelf/manifest.py`** (lines 1-308) — `load_manifest(shelf_root)`, `save_manifest(shelf_root, data)`, `add_manifest_entry`, `get_manifest_entry`, `remove_manifest_entry`. Dedup creates hardlinks and must update each affected manifest entry's `hardlinks` list. `save_manifest` provides atomic writes (NamedTemporaryFile → os.replace).

3. **`src/model_shelf/cli.py`** (lines 1-286) — Subparser registration pattern. `cmd_import` is the closest precedent: dry-run default, `--execute` flag, `--json` flag, `_print_*_pretty` helper, dispatching in `main()`. Dedup should follow the same pattern exactly.

4. **`src/model_shelf/__init__.py`** (lines 1-40) — Exports pattern. Dedup dataclasses and public functions must be added here.

5. **`/tmp/poc_dedup.py`** (lines 1-72) — Working scan logic. Key patterns:
   - `LOCATIONS` dict maps labels → Paths (models, hf-cache, lmstudio, ollama-blobs, ollama-manifests, omlx, model-shelf)
   - `sha256(p)` function (64KB chunks, identical to `_sha256_file`)
   - `MODEL_EXTS` = `{'.gguf', '.safetensors', '.bin', '.pt', '.pth', '.onnx'}`
   - Groups by SHA256, filters groups with >1 entry
   - `same_fs_all` check via `st_dev` comparison
   - Cross-tool detection: labels → tool categories
   - Canonical = first entry in group, KEEP

6. **`.serena/memories/implementation_plan.md`** (Phase 4 section) — Spec for `DedupResult`, `DedupGroup` dataclasses, `find_duplicates()`, `execute_dedup()`. Safety constraints documented.

7. **`.serena/memories/test_specs.md`** (Phase 4 section) — 18 tests across 3 tiers:
   - Tier 1 (pure logic): 6 tests
   - Tier 2 (tmp_path filesystem): 10 tests
   - Tier 3 (CLI integration): 3 tests

8. **`.serena/memories/conventions.md`** — Not directly relevant (ansible playbook conventions).

9. **`src/model_shelf/config.py`** — `Config` dataclass: `shelf_root: Path | None`, `allow_downloads: bool`. Dedup needs `Config` to know the shelf root.

10. **`src/model_shelf/detect.py`** — `StorageCandidate` and `detect_storage_candidates()`. Not directly needed for dedup but shows the pattern for scanning volumes.

---

## Architecture

### Data flow

```
CLI (cli.py)
  │
  ├─ cmd_dedup(args, cfg)
  │     │
  │     ├─ find_duplicates(cfg, include_ollama, include_hf_cache) → DedupResult
  │     │     │
  │     │     ├─ Walk shelf_root/{gguf,mlx,safetensors}/
  │     │     ├─ [opt] Walk ~/.ollama/models/blobs/*
  │     │     ├─ [opt] Walk ~/.cache/huggingface/hub/blobs/*
  │     │     ├─ SHA256 every file (reuse _sha256_file from import_model)
  │     │     ├─ Group by SHA256, filter groups with len > 1
  │     │     └─ Return DedupResult with DedupGroup list
  │     │
  │     ├─ If --dry-run (default): print report, return 0
  │     │
  │     └─ If --execute:
  │           │
  │           ├─ execute_dedup(cfg, result) → DedupResult
  │           │     │
  │           │     ├─ For each group:
  │           │     │   ├─ Keep shelf copy as canonical (first in group that lives in shelf_root)
  │           │     │   ├─ For each other file:
  │           │     │   │   ├─ Check st_dev (same filesystem?)
  │           │     │   │   ├─ If same-fs: os.link(canonical, other), os.unlink(other)
  │           │     │   │   ├─ If external source (ollama/hf): NEVER unlink, only hardlink destination
  │           │     │   │   └─ If cross-fs: skip, log warning
  │           │     │   └─ Update manifest hardlinks field for each affected entry
  │           │     └─ Return updated DedupResult
  │           │
  │           └─ print report
```

### Key types

```python
@dataclass
class DedupGroup:
    sha256: str               # hex digest
    files: list[Path]          # all file paths sharing this SHA256
    size_bytes: int            # size of one copy
    duplicate_bytes: int       # (len(files) - 1) * size_bytes (waste)

@dataclass
class DedupResult:
    groups: list[DedupGroup]
    total_duplicate_bytes: int        # sum of all group.duplicate_bytes
    potential_savings_bytes: int      # same as total_duplicate_bytes (bytes we can save)
    skipped_cross_fs: int = 0         # count of groups skipped due to cross-fs
    hardlinks_created: int = 0        # count of hardlinks created (for execute_dedup output)

    def to_dict(self) -> dict: ...
```

### Module boundaries

- **`dedup.py`** — own module. Imports from `manifest.py` (`load_manifest`, `save_manifest`), reuses `_sha256_file` from `import_model.py`. Does NOT import from CLI.
- **`cli.py`** — imports `find_duplicates`, `execute_dedup`, `DedupResult`, `DedupGroup` from `dedup.py`. Adds subparser + `cmd_dedup`.
- **`__init__.py`** — exports `DedupResult`, `DedupGroup`, `find_duplicates`, `execute_dedup`.

### Hardlink safety rules (CRITICAL)

1. **Same filesystem only**: check `os.stat(canonical).st_dev == os.stat(target).st_dev` before `os.link()`.
2. **Shelf copy is canonical**: the file inside `shelf_root` is the KEEP. External files get hardlinked TO the shelf copy.
3. **External blobs are destinations, not sources**: Ollama blobs and HF cache blobs get hardlinked to the shelf copy, but the originals are NEVER unlinked. External tools own those files.
4. **Shelf-to-shelf duplicates**: if both files are in the shelf, keep the first, hardlink the second, unlink the second (replace with hardlink).
5. **Dry-run is default**: `--execute` flag required for any mutation. Matches `import` command convention.

### Manifest update strategy

For each dedup group where hardlinks are created:
1. Load manifest once at start.
2. For each file path in the group, find which manifest entry contains that file (reverse lookup from file path → repo_id).
3. Update `entry["hardlinks"]` list to include the new hardlink target paths.
4. Single atomic save at the end (not per-group).

---

## Files to CREATE

### 1. `src/model_shelf/dedup.py`

New module with:
- `DedupGroup` dataclass
- `DedupResult` dataclass with `to_dict()`
- `find_duplicates(config: Config, *, include_ollama: bool = False, include_hf_cache: bool = False) -> DedupResult`
- `execute_dedup(config: Config, result: DedupResult) -> DedupResult`
- Internal helpers: `_sha256_file(path)`, `_is_same_fs(p1, p2)`, `_is_external(path)`, `_shelf_file_sort_key(path, shelf_root)`, `_update_manifest_hardlinks(shelf_root, groups)`

#### `find_duplicates` algorithm:
```
1. files = []
2. Walk shelf_root/{gguf,mlx,safetensors}/ — collect all regular files (skip ._ and .cache)
3. If include_ollama: walk ~/.ollama/models/blobs/ — collect all files (label as "ollama")
4. If include_hf_cache: walk ~/.cache/huggingface/hub/**/blobs/ — collect blob files (label as "hf-cache")
5. Build SHA256 index: {sha256: [(path, size, source_label), ...]}
6. Filter groups with len(entries) > 1
7. For each group, DedupGroup(
     sha256=sha256,
     files=[p for (p,_,_) in entries],
     size_bytes=entries[0][1],
     duplicate_bytes=(len(entries)-1) * entries[0][1]
   )
8. Return DedupResult(groups=[...], total_duplicate_bytes=sum, potential_savings_bytes=sum)
```

#### `execute_dedup` algorithm:
```
1. skipped = 0; created = 0
2. For each group in result.groups:
   a. Identify canonical: first file whose path is inside shelf_root
      If no shelf file, skip the entire group (external-only, not actionable)
   b. For each other file in group:
      - If _is_same_fs(canonical, other):
        - Create temp hardlink: other.with_suffix(original.suffix + ".msdedup")
        - os.link(canonical, tmp_path)
        - os.replace(tmp_path, other)  # atomic replace
        - If other is also in shelf (not external): 
          - The replace above handles the old inode; no extra unlink needed
        - If other is external (ollama/hf): 
          - DO NOT unlink — external tools own these
          - The hardlink replaces the old inode but external tool sees same path
        - created += 1
      - Else: skipped += 1, log warning
3. Update manifest hardlinks
4. Return updated DedupResult with skipped_cross_fs and hardlinks_created
```

### 2. `tests/test_dedup.py`

19 tests from spec, structured in 3 tiers.

---

## Files to MODIFY

### 1. `src/model_shelf/cli.py`

**Add import** (near top, after existing model_shelf imports):
```python
from model_shelf.dedup import DedupResult, DedupGroup, find_duplicates, execute_dedup
```

**Add `cmd_dedup` function** (after `cmd_manifest`, around line 222):

```python
def cmd_dedup(args: argparse.Namespace, cfg: Config) -> int:
    """Find and deduplicate identical model files."""
    check_storage_available(cfg)
    result = find_duplicates(
        cfg,
        include_ollama=args.include_ollama,
        include_hf_cache=args.include_hf_cache,
    )
    if not args.execute:
        # Dry-run (default)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            _print_dedup_report(result)
        return 0

    dedup_result = execute_dedup(cfg, result)
    if args.json:
        print(json.dumps(dedup_result.to_dict(), indent=2))
    else:
        _print_dedup_report(dedup_result)
    return 0


def _print_dedup_report(result: DedupResult) -> None:
    if not result.groups:
        print("No duplicates found.")
        return
    print(f"Found {len(result.groups)} duplicate group(s)")
    total_savings = result.potential_savings_bytes
    if total_savings >= 1e9:
        print(f"  Potential savings: {total_savings / 1e9:.2f} GB")
    else:
        print(f"  Potential savings: {total_savings / 1e6:.1f} MB")
    if getattr(result, 'hardlinks_created', 0):
        print(f"  Hardlinks created: {result.hardlinks_created}")
    if getattr(result, 'skipped_cross_fs', 0):
        print(f"  Skipped (cross-fs):  {result.skipped_cross_fs}")
    for g in result.groups:
        print(f"\n  SHA256: {g.sha256[:16]}...  copies: {len(g.files)}  "
              f"waste: {g.duplicate_bytes / 1e6:.1f} MB")
        for i, f in enumerate(g.files):
            mark = " ← KEEP" if i == 0 else ""
            print(f"    {f}{mark}")
```

**Add subparser** (in `main()`, after `p_manifest` block):
```python
p_dedup = sub.add_parser("dedup", help="find and deduplicate identical model files")
p_dedup.add_argument(
    "--include-ollama", action="store_true",
    help="cross-reference Ollama blobs (~/.ollama/models/blobs/)",
)
p_dedup.add_argument(
    "--include-hf-cache", action="store_true",
    help="cross-reference HuggingFace cache blobs",
)
p_dedup.add_argument(
    "--execute", action="store_true",
    help="actually create hardlinks (default is dry-run)",
)
p_dedup.add_argument("--json", action="store_true", help="emit JSON")
```

**Add dispatch** (in `main()`, after `if args.command == "manifest":`):
```python
if args.command == "dedup":
    return cmd_dedup(args, cfg)
```

### 2. `src/model_shelf/__init__.py`

**Add to imports:**
```python
from model_shelf.dedup import DedupGroup, DedupResult, execute_dedup, find_duplicates
```

**Add to `__all__`:**
```python
"DedupGroup",
"DedupResult",
"execute_dedup",
"find_duplicates",
```

---

## Key implementation details

### SHA256 helper

Import from `import_model.py` to ensure consistency:

```python
from model_shelf.import_model import _sha256_file
```

### Same filesystem check

```python
def _is_same_fs(p1: Path, p2: Path) -> bool:
    try:
        return p1.stat().st_dev == p2.stat().st_dev
    except OSError:
        return False
```

### External path detection

```python
_EXTERNAL_ROOTS: dict[Path, str] = {
    Path.home() / ".ollama" / "models" / "blobs": "ollama",
    Path.home() / ".cache" / "huggingface" / "hub": "hf-cache",
}

def _is_external(path: Path) -> bool:
    """Check if path is in an external tool's storage (ollama, hf cache)."""
    for root in _EXTERNAL_ROOTS:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            pass
    return False
```

### File filter for scanning

- Exclude files starting with `._` (macOS resource forks)
- Exclude paths containing `.cache/`
- For shelf: only scan `{gguf,mlx,safetensors}` subdirs
- For ollama: scan `~/.ollama/models/blobs/`
- For HF cache: scan `~/.cache/huggingface/hub/` (blob files have sha256 names in `blobs/` subdirs)
- Default: only scan shelf. Ollama and HF require explicit flags.

### Hardlink execution pattern

```python
def _hardlink_replace(canonical: Path, target: Path) -> None:
    """Atomically replace target with a hardlink to canonical."""
    tmp = target.with_suffix(target.suffix + ".msdedup")
    try:
        os.link(str(canonical), str(tmp))
        os.replace(str(tmp), str(target))
    finally:
        if tmp.exists():
            os.unlink(str(tmp))
```

### Manifest hardlinks update

For each group where hardlinks were created, find each affected manifest entry and add the target path to its `hardlinks` list. Use `add_manifest_entry` from manifest.py:

```python
def _update_manifest_for_dedup(shelf_root: Path, groups: list[DedupGroup]) -> None:
    """Update manifest hardlinks field for every entry affected by dedup."""
    manifest = load_manifest(shelf_root)
    changed = False
    for group in groups:
        # Find shelf files in the group
        shelf_files = [
            f for f in group.files
            if _is_in_shelf(f, shelf_root)
        ]
        for f in shelf_files:
            repo_id = _path_to_repo_id(f, shelf_root)
            if repo_id and repo_id in manifest.get("models", {}):
                entry = manifest["models"][repo_id]
                current = set(entry.get("hardlinks", []))
                # Add all other files in the group as hardlinks
                for other in group.files:
                    if other != f:
                        current.add(str(other))
                entry["hardlinks"] = sorted(current)
                changed = True
    if changed:
        manifest["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_manifest(shelf_root, manifest)
```

---

## Test structure (19 tests)

### Tier 1 — Pure logic (6 tests)

| # | Test name | What it tests |
|---|-----------|---------------|
| 1 | `test_find_duplicates_empty_shelf` | Empty shelf → empty groups, 0 bytes |
| 2 | `test_find_duplicates_two_identical_ggufs` | Two same-content files in different dirs → 1 group |
| 3 | `test_find_duplicates_ignores_different_content` | Different content → 0 groups |
| 4 | `test_find_duplicates_same_content_different_names` | SHA256 ignores filename |
| 5 | `test_dedup_group_dataclass` | `duplicate_bytes == size_bytes` for 2 copies |
| 6 | `test_dedup_result_dataclass` | `potential_savings_bytes > 0` |

### Tier 2 — tmp_path filesystem (10 tests)

| # | Test name | What it tests |
|---|-----------|---------------|
| 7 | `test_dedup_creates_hardlinks_same_fs` | `st_ino` match, `st_nlink == 2` after execute |
| 8 | `test_dedup_dry_run_makes_no_changes` | Files unchanged, `st_nlink` stays 1 |
| 9 | `test_dedup_keeps_canonical_in_shelf` | Shelf copy is KEEP, external gets hardlinked |
| 10 | `test_dedup_skips_across_filesystems` | Cross-fs → skip, warning logged |
| 11 | `test_dedup_include_ollama_blobs` | `include_ollama=True` detects shelf + ollama duplicates |
| 12 | `test_dedup_include_hf_cache_blobs` | `include_hf_cache=True` detects shelf + hf duplicates |
| 13 | `test_dedup_ollama_blob_not_unlinked` | External blob persists after dedup |
| 14 | `test_dedup_hf_cache_blob_not_unlinked` | HF blob persists after dedup |
| 15 | `test_dedup_preserves_manifest_hardlinks_field` | Manifest updated with hardlink paths |
| 16 | `test_dedup_handles_three_way_duplicate` | 3 copies → 1 group, `duplicate_bytes == 2*size`, `st_nlink=3` |

### Tier 3 — CLI integration (3 tests)

| # | Test name | What it tests |
|---|-----------|---------------|
| 17 | `test_dedup_cli_dry_run_default` | `main(["dedup"])` → exit 0, nothing modified |
| 18 | `test_dedup_cli_json_output` | `main(["dedup", "--json"])` → valid JSON with groups, total_duplicate_bytes, potential_savings_bytes |
| 19 | `test_dedup_cli_execute_flag` | `main(["dedup", "--execute"])` → hardlinks created |

---

## Safety constraints (blockers)

1. **NEVER hardlink across filesystems** — check `st_dev` before `os.link()`. This would fail with `OSError: [Errno 18] Cross-device link`.

2. **NEVER unlink Ollama blobs** — Ollama uses content-addressed blob storage. If we delete a blob, Ollama breaks.

3. **NEVER unlink HF cache blobs** — HF Hub library might re-download, corrupting the cache. HF cache entries are hardlink destinations only.

4. **Dry-run is ALWAYS the default** — `--execute` flag required for any mutation. This matches the `import` command pattern.

5. **Manifest consistency** — after hardlinking, `entry["hardlinks"]` must list all linked paths so rebuild can reconstruct state.

---

## DO NOT MODIFY

These files are off-limits:
- `src/model_shelf/manifest.py`
- `src/model_shelf/import_model.py`
- `src/model_shelf/resolver.py`
- `src/model_shelf/config.py`
- `src/model_shelf/detect.py`
- `src/model_shelf/relocate.py`
- `src/model_shelf/search.py`
- `tests/test_import.py`, `tests/test_manifest.py`, `tests/test_quant.py`, `tests/test_resolver.py`, `tests/test_config.py`, `tests/test_detect.py`, `tests/test_relocate.py`, `tests/test_search.py`

---

## Start Here

Open **`src/model_shelf/cli.py`** first — see the `cmd_import` function (line ~59) and `cmd_manifest` (line ~195) for the exact patterns to follow. Then create **`src/model_shelf/dedup.py`** following the `import_model.py` structure (dataclass + public function + internal helpers).

---

## Open questions

1. **Minimum file size threshold?** The PoC skips files <10MB. The spec doesn't mention a threshold for Phase 4. Recommendation: hash all files regardless of size for correctness; the 10MB threshold is a PoC optimization, not a requirement.

2. **What about non-model file extensions?** The PoC scans for `MODEL_EXTS`. The shelf is already curated (only model files), so extension filtering isn't needed for the shelf walk. For Ollama/HF cache, blobs have sha256 names with no extension. Recommendation: scan all regular files, skip `._` and `.cache/`.

3. **External-only groups?** If all copies in a group are external (e.g., Ollama blob = HF cache blob), there's no shelf copy to hardlink from. Recommendation: skip external-only groups entirely — report them but mark as not actionable.