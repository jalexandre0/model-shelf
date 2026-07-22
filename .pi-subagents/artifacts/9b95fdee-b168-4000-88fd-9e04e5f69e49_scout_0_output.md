# Phase 5 Handoff: audit, remove, gc

## Overview

Three new modules in one phase. All read the shelf and manifest — none modify the manifest or shelf I/O pathways (those live in `manifest.py`). Each module has a result dataclass, a main function, and a CLI subcommand following the existing `cmd_*` pattern.

---

## Files Retrieved

1. **`src/model_shelf/manifest.py`** (lines 1-320, full) — canonical manifest I/O. `load_manifest(shelf_root) -> dict` returns `{"version": 1, "updated": "", "models": {}}`. `remove_manifest_entry(shelf_root, repo_id)` handles the remove case. CRUD helpers: `get_manifest_entry`, `add_manifest_entry`, `remove_manifest_entry`. **Do not modify.**

2. **`src/model_shelf/import_model.py`** (lines 149-156, `_sha256_file`) — SHA256 hashing used by audit for staleness checks. `_sha256_file(path: Path) -> str` returns lowercase hex digest. **Import from here; do not modify.**

3. **`src/model_shelf/cli.py`** (lines 1-350, full) — CLI patterns. Each subcommand has:
   - `p_<cmd> = sub.add_parser("cmdname", ...)` with `--json` and `--dry-run`/`--execute` flags
   - `cmd_<cmd>(args, cfg) -> int` following a consistent shape: `check_storage_available(cfg)`, run logic, `if args.json: print(json.dumps(result.to_dict()))`, return exit code
   - Exception handling in `main()` catches `StorageNotAvailableError` (→2), `ValueError` (→2), generic `Exception` (→3)

4. **`src/model_shelf/dedup.py`** (lines 1-310, full) — pattern exemplar for destructive commands. Key patterns:
   - `DedupResult` dataclass with `to_dict()`
   - `find_duplicates(config, ...)` — scan-only (dry-run safe)
   - `execute_dedup(config, result)` — mutation path
   - CLI: `cmd_dedup` calls `find_duplicates`, then conditionally `execute_dedup` based on `args.execute`
   - Hardlink safety: `_is_same_fs()`, st_dev checks
   - Shelf-root-relative file discovery: walks `SUPPORTED_FORMATS` dirs, excludes dot-files and `.cache/`

5. **`src/model_shelf/__init__.py`** (lines 1-45) — current exports. Add 6 new names:
   - `AuditResult`, `run_audit`
   - `RemoveResult`, `remove_model`
   - `GCResult`, `run_gc`

6. **`src/model_shelf/resolver.py`** (lines 44-49, Config; line 102, check_storage_available) — `Config(shelf_root: Path | None, allow_downloads: bool)`. `check_storage_available(config)` raises if unmounted/uninitialized. `SUPPORTED_FORMATS = ("gguf", "mlx", "safetensors")`.

7. **`.serena/memories/implementation_plan.md`** (Phase 5 section) — spec for audit, remove, gc. Dataclass shapes and logic outline.

8. **`.serena/memories/test_specs.md`** (Phases 5a/5b/5c) — 23 tests across three test files.

9. **`.serena/memories/conventions.md`** — ansible conventions (not directly relevant; model-shelf Python conventions derived from code itself).

10. **Existing tests** (`tests/test_dedup.py`, `tests/test_import.py`) — patterns:
    - `_config(tmp_path) -> Config` helper
    - `init_shelf(cfg)` before writes
    - `tmp_path` fixtures, pytest
    - `from __future__ import annotations`, type hints

---

## Key Code & Architecture

### Data Flow (common to all three modules)

```
CLI (cli.py)
  → parse args
  → load_config(args.config) → Config
  → check_storage_available(cfg)   [raises ShelfNotInitializedError if missing]
  → cmd_audit / cmd_remove / cmd_gc
      → load_manifest(cfg.shelf_root) → dict
      → walk shelf_root/{gguf,mlx,safetensors}/
      → cross-reference or mutate
      → return result dataclass
  → json.dumps(result.to_dict())  OR  pretty-print
  → return int exit code
```

### Shelf Layout (from resolver.py `SUPPORTED_FORMATS`)

```
{shelf_root}/
  manifest.json
  gguf/{publisher}/{repo}/{file}.gguf
  mlx/{publisher}/{repo}/{config.json, *.safetensors, ...}
  safetensors/{publisher}/{repo}/{config.json, *.safetensors, ...}
```

### Manifest Entry Shape (from manifest.py, real entries from import_model.py)

```python
{
  "repo_id": "Qwen/Qwen3-14B-GGUF",
  "format": "gguf",
  "quant": "Q4_K_M",
  "sha256": "cfdd00ac...",
  "files": ["Qwen3-14B-Q4_K_M.gguf"],
  "size_bytes": 5903822528,
  "source": "imported",          # or "rebuild"
  "imported_from": "/Users/...",  # optional
  "imported": "2025-07-21T...",   # ISO timestamp
  "hardlinks": [],                # list of str paths
  "params": {"architecture": "llama"}  # optional
}
```

---

## MODULE 1: AUDIT — `src/model_shelf/audit.py`

### Purpose
Read-only cross-reference of manifest entries against filesystem. Exit 0 if clean, 1 if any issues found.

### Dataclass

```python
@dataclass
class AuditResult:
    missing: list[str] = field(default_factory=list)       # repo_ids from manifest whose files don't exist
    untracked: list[str] = field(default_factory=list)     # filesystem paths not in manifest (str, not Path)
    stale: list[str] = field(default_factory=list)         # repo_ids whose SHA256 doesn't match filesystem

    def to_dict(self) -> dict:
        return {
            "missing": list(self.missing),
            "untracked": list(self.untracked),
            "stale": list(self.stale),
        }
```

### Main Function

```python
def run_audit(config: Config) -> AuditResult:
```

**Algorithm:**

1. `check_storage_available(config)` — fail fast if shelf unreachable
2. `manifest = load_manifest(config.shelf_root)`
3. `models = manifest.get("models", {})`
4. Build set of all manifest-tracked paths:
   - For each entry: `{shelf_root}/{fmt}/{publisher}/{repo}/{file}` for each file in `entry["files"]`
5. **Missing check**: for each manifest entry, verify all `files` exist on disk. If any file is missing, add `repo_id` to `missing` list.
6. **Stale check**: for each manifest entry that passed missing check, compute `_sha256_file` for each tracked file. If SHA256 differs from `entry["sha256"]`, add `repo_id` to `stale` list.
   - For GGUF: single file SHA256 matches `entry["sha256"]`
   - For MLX/safetensors: directory SHA256 (all files sorted) matches `entry["sha256"]`
   - **Important**: use `from model_shelf.import_model import _sha256_file` for individual files. For directory SHA256, replicate `_sha256_directory` logic or import from `manifest._sha256_dir_for_rebuild` (which excludes `.cache/` and dot-files — match the same exclusion logic that `rebuild_manifest` uses so audit doesn't flag expected differences).
7. **Untracked check**: walk `{shelf_root}/{gguf,mlx,safetensors}/**/*`, collect all files that:
   - Are regular files
   - Don't start with `._` (macOS resource forks)
   - Don't have `.cache` in any path part
   - Are NOT in the manifest-tracked path set from step 4
   - Add relative-to-shelf-root paths (or absolute) to `untracked` list. **Recommendation: use absolute paths** as strings for consistency with dedup's pattern.
8. Return `AuditResult(missing=..., untracked=..., stale=...)`

**Edge cases:**
- Empty shelf (no models dirs, empty manifest) → all lists empty, exit 0
- Manifest with entries but no corresponding files on disk → all in `missing`
- MLX/safetensors entries with multiple files — check all exist, SHA256 over directory
- Entry format not in SUPPORTED_FORMATS → skip (shouldn't happen, but defensive)

### CLI Integration (cli.py)

```python
# In main(), add subparser:
p_audit = sub.add_parser("audit", help="cross-check manifest vs filesystem")
p_audit.add_argument("--json", action="store_true", help="emit JSON")

# Handler:
def cmd_audit(args: argparse.Namespace, cfg: Config) -> int:
    result = run_audit(cfg)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        # Pretty print: list counts and each item
        print(f"Audit: {len(result.missing)} missing, {len(result.stale)} stale, "
              f"{len(result.untracked)} untracked")
        if result.missing:
            print("\nMissing (manifest entry, files gone):")
            for repo_id in result.missing:
                print(f"  {repo_id}")
        if result.stale:
            print("\nStale (SHA256 mismatch):")
            for repo_id in result.stale:
                print(f"  {repo_id}")
        if result.untracked:
            print("\nUntracked (on disk, not in manifest):")
            for path in result.untracked:
                print(f"  {path}")
        if not result.missing and not result.stale and not result.untracked:
            print("Shelf is clean — no issues found.")
    # Exit 0 clean, 1 if any issues
    return 0 if (not result.missing and not result.stale and not result.untracked) else 1
```

**dispatch in `main()`:**
```python
if args.command == "audit":
    return cmd_audit(args, cfg)
```

### Dependencies (imports needed)

```python
from model_shelf.manifest import load_manifest
from model_shelf.import_model import _sha256_file
from model_shelf.resolver import Config, SUPPORTED_FORMATS, check_storage_available
```

---

## MODULE 2: REMOVE — `src/model_shelf/remove.py`

### Purpose
Remove a single model (by repo_id) from the shelf. Dry-run by default. Warns if files have hardlinks elsewhere.

### Dataclass

```python
@dataclass
class RemoveResult:
    removed: list[str] = field(default_factory=list)            # paths that were deleted (str)
    hardlinks_warn: list[str] = field(default_factory=list)     # other paths sharing inodes (str)

    def to_dict(self) -> dict:
        return {
            "removed": list(self.removed),
            "hardlinks_warn": list(self.hardlinks_warn),
        }
```

### Main Function

```python
def remove_model(config: Config, repo_id: str, *, dry_run: bool = True) -> RemoveResult:
```

**Algorithm:**

1. `check_storage_available(config)` — fail fast
2. `manifest = load_manifest(config.shelf_root)`
3. `entry = manifest.get("models", {}).get(repo_id)`
   - If `None`: raise `ValueError(f"model '{repo_id}' not found in manifest")` (or return a result with error status — the existing pattern in import_model uses exceptions for errors, as seen in `ValueError` handling in `main()`)
4. Reconstruct paths from entry:
   - `fmt = entry["format"]`
   - `publisher, _, repo_name = repo_id.partition("/")`
   - For GGUF: `model_dir = config.shelf_root / fmt / publisher / repo_name`
   - For each file in `entry["files"]`: `file_path = model_dir / fname`
5. **Hardlink check**: for each file, `st = os.stat(file_path)`. If `st.st_nlink > 1`:
   - Record a warning (`hardlinks_warn`). The file will still be removed (st_nlink decrements), but other hardlinks survive.
   - **Note**: We cannot easily enumerate all paths sharing the same inode across the filesystem. Record the inode and note that hardlinks exist. Format: `f"{file_path} (st_nlink={st.st_nlink})"`
6. **Dry-run**: if `dry_run=True`, return `RemoveResult(removed=[str(p) for p in all_file_paths], hardlinks_warn=...)` without deleting anything.
7. **Execute**:
   - For each file in `entry["files"]`: `os.unlink(file_path)`
   - Remove manifest entry: `remove_manifest_entry(config.shelf_root, repo_id)`
   - Clean up empty parent directories (walk up from `model_dir` to `config.shelf_root`, remove empty dirs):
     ```python
     parent = model_dir
     while parent != config.shelf_root:
         try:
             if not any(parent.iterdir()):
                 parent.rmdir()
             else:
                 break  # directory not empty, stop walking up
         except OSError:
             break
         parent = parent.parent
     ```
8. Return `RemoveResult(removed=..., hardlinks_warn=...)`

**Edge cases:**
- Model not in manifest → `ValueError`
- Files already gone (race condition) → skip, don't fail
- GGUF publisher directory shared with other models → only remove the specific repo dir, not parent
- `repo_id` is `"publisher/model_name"` — the repo dir name from the partition might differ from the entry's `repo_id` split. **Important**: Use `repo_id.partition("/")[2]` (the part after the first `/`) as the directory name. For GGUF entries, the files are in `{shelf_root}/gguf/{publisher}/{repo_name}/`. The entry has `repo_id` which is always `publisher/repo_name`.

### CLI Integration (cli.py)

```python
# Subparser:
p_remove = sub.add_parser("remove", help="remove a model from the shelf")
p_remove.add_argument("repo_id", help='e.g. "Qwen/Qwen3-14B-GGUF"')
p_remove.add_argument("--execute", action="store_true", help="actually delete (default dry-run)")
p_remove.add_argument("--json", action="store_true", help="emit JSON")

# Handler:
def cmd_remove(args: argparse.Namespace, cfg: Config) -> int:
    result = remove_model(cfg, args.repo_id, dry_run=not args.execute)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        action = "Would remove" if not args.execute else "Removed"
        if result.removed:
            print(f"{action}:")
            for p in result.removed:
                print(f"  {p}")
        if result.hardlinks_warn:
            print("Hardlink warnings:")
            for w in result.hardlinks_warn:
                print(f"  {w}")
        if not result.removed and not result.hardlinks_warn:
            print("No files to remove.")
    return 0
```

### Dependencies

```python
from model_shelf.manifest import load_manifest, remove_manifest_entry
from model_shelf.resolver import Config, check_storage_available
```

---

## MODULE 3: GC — `src/model_shelf/gc.py`

### Purpose
Find and optionally clean up incomplete downloads, orphaned files, and empty directories. Dry-run default.

### Dataclass

```python
@dataclass
class GCResult:
    incomplete_downloads: list[str] = field(default_factory=list)    # dir paths (str)
    orphaned_files: list[str] = field(default_factory=list)          # file paths (str)
    empty_dirs: list[str] = field(default_factory=list)              # dir paths (str)
    total_reclaimable_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "incomplete_downloads": list(self.incomplete_downloads),
            "orphaned_files": list(self.orphaned_files),
            "empty_dirs": list(self.empty_dirs),
            "total_reclaimable_bytes": self.total_reclaimable_bytes,
        }
```

### Main Function

```python
def run_gc(config: Config) -> GCResult:
```

**Algorithm:**

1. `check_storage_available(config)`
2. `manifest = load_manifest(config.shelf_root)`
3. Build the set of all manifest-tracked files (absolute paths) — same as in audit, but pre-built for fast lookup.
4. Walk `{shelf_root}/{gguf,mlx,safetensors}/` recursively.

**Skip rules (apply to all three checks below):**
- Any path where any component starts with `.` (dot-prefixed dirs, dotfiles)
- Any path containing `.cache` in any component
- Files starting with `._` (macOS resource forks)

**Detection — three categories:**

**a) Incomplete downloads** (dirs without model files):
   - For each directory under `{shelf_root}/{fmt}/{publisher}/`:
     - GGUF: a dir without any `.gguf` files → incomplete
     - MLX: a dir with no `config.json` → incomplete
     - Safetensors: a dir with `config.json` but no `*.safetensors` → incomplete
   - Add to `incomplete_downloads`

**b) Orphaned files:**
   - Any regular file not in the manifest-tracked set → orphaned
   - Add to `orphaned_files`
   - Accumulate `st_size` into `total_reclaimable_bytes`

**c) Empty directories:**
   - Any directory that contains no files (after filtering dot/dot-cache)
   - Add to `empty_dirs`
   - Process bottom-up (post-order) so a dir that becomes empty after removing orphaned files is caught

5. Return `GCResult(incomplete_downloads=..., orphaned_files=..., empty_dirs=..., total_reclaimable_bytes=...)`

**Important detail on "empty dirs":** The spec says to find empty dirs. When `--execute` is used, removing orphaned files may create new empty dirs. The scan should detect currently-empty dirs. For `--execute`, after deleting orphans, re-scan for newly-empty dirs and remove them too.

### CLI Integration (cli.py)

```python
# Subparser:
p_gc = sub.add_parser("gc", help="find and clean up incomplete downloads, orphans, empty dirs")
p_gc.add_argument("--execute", action="store_true", help="actually delete (default dry-run)")
p_gc.add_argument("--json", action="store_true", help="emit JSON")

# Handler:
def cmd_gc(args: argparse.Namespace, cfg: Config) -> int:
    from model_shelf.gc import GCResult, run_gc  # noqa: PLC0415

    result = run_gc(cfg)
    if not args.execute:
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            _print_gc_report(result, dry_run=True)
        return 0

    # --execute path
    removed_count = 0
    removed_bytes = 0
    # Remove orphaned files
    for fpath_str in result.orphaned_files:
        fpath = Path(fpath_str)
        try:
            st = fpath.stat()
            os.unlink(fpath)
            removed_count += 1
            removed_bytes += st.st_size
        except OSError:
            pass
    # Remove incomplete download dirs
    for dpath_str in result.incomplete_downloads:
        dpath = Path(dpath_str)
        try:
            shutil.rmtree(dpath)
        except OSError:
            pass
    # Remove empty dirs (post-order, from deepest to shallowest)
    empty_sorted = sorted(result.empty_dirs, key=lambda p: -len(Path(p).parts))
    for dpath_str in empty_sorted:
        dpath = Path(dpath_str)
        try:
            if dpath.is_dir() and not any(dpath.iterdir()):
                dpath.rmdir()
        except OSError:
            pass
    # Re-scan for newly-empty dirs after deletions
    # (walk up from deleted files/dirs, remove empty parents)
    _cleanup_empty_parents(config.shelf_root)  # helper

    # Build result
    exec_result = GCResult(
        incomplete_downloads=result.incomplete_downloads,
        orphaned_files=result.orphaned_files,
        empty_dirs=result.empty_dirs,
        total_reclaimable_bytes=result.total_reclaimable_bytes,
    )
    if args.json:
        print(json.dumps(exec_result.to_dict(), indent=2))
    else:
        _print_gc_report(exec_result, dry_run=False)
        print(f"Removed {removed_count} files ({_fmt_size(removed_bytes)} reclaimed)")
    return 0

def _print_gc_report(result: GCResult, *, dry_run: bool) -> None:
    prefix = "Would clean" if dry_run else "Cleaned"
    total = len(result.incomplete_downloads) + len(result.orphaned_files) + len(result.empty_dirs)
    print(f"{prefix} {total} items ({_fmt_size(result.total_reclaimable_bytes)} reclaimable):")
    if result.incomplete_downloads:
        print(f"\n  Incomplete downloads ({len(result.incomplete_downloads)}):")
        for p in result.incomplete_downloads:
            print(f"    {p}")
    if result.orphaned_files:
        print(f"\n  Orphaned files ({len(result.orphaned_files)}):")
        for p in result.orphaned_files:
            print(f"    {p}")
    if result.empty_dirs:
        print(f"\n  Empty directories ({len(result.empty_dirs)}):")
        for p in result.empty_dirs:
            print(f"    {p}")
```

**dispatch in `main()`:**
```python
if args.command == "gc":
    return cmd_gc(args, cfg)
```

### Dependencies

```python
from model_shelf.manifest import load_manifest
from model_shelf.resolver import Config, SUPPORTED_FORMATS, check_storage_available
```

---

## `__init__.py` Additions

Add to `src/model_shelf/__init__.py`:

```python
# New imports (add after existing dedup imports):
from model_shelf.audit import AuditResult, run_audit
from model_shelf.remove import RemoveResult, remove_model
from model_shelf.gc import GCResult, run_gc

# Add to __all__:
    "AuditResult",
    "GCResult",
    "RemoveResult",
    "remove_model",
    "run_audit",
    "run_gc",
```

---

## Test Specifications (23 tests)

### `tests/test_audit.py` (10 tests — Phases 5a Tier 1 + Tier 2)

| # | Test Name | What It Tests |
|---|-----------|---------------|
| 1 | `test_audit_dataclass_defaults` | `AuditResult()` has empty lists |
| 2 | `test_audit_clean_shelf` | manifest + matching files → clean result, exit 0 |
| 3 | `test_audit_missing_entry_directory_gone` | manifest entry exists, no dir on disk → `missing` |
| 4 | `test_audit_missing_file_in_directory` | entry has 2 files, 1 is gone → `missing` |
| 5 | `test_audit_stale_sha256` | file content changed after manifest → `stale` |
| 6 | `test_audit_untracked_file` | file on shelf not in manifest → `untracked` |
| 7 | `test_audit_multiple_issues_in_one_run` | 1 missing + 1 stale + 2 untracked → all reported |
| 8 | `test_audit_cli_json_output` | `main(["audit", "--json"])` → valid JSON |
| 9 | `test_audit_cli_exit_code_clean` | clean shelf → exit 0 |
| 10 | `test_audit_cli_exit_code_dirty` | shelf with issues → exit 1 |

### `tests/test_remove.py` (6 tests — Phase 5b Tier 2 + Tier 3)

| # | Test Name | What It Tests |
|---|-----------|---------------|
| 1 | `test_remove_dataclass_defaults` | `RemoveResult()` has empty lists |
| 2 | `test_remove_deletes_files_and_directory` | files + manifest entry gone after execute |
| 3 | `test_remove_dry_run_preserves_everything` | dry-run keeps all files and manifest |
| 4 | `test_remove_warns_on_hardlinks` | `st_nlink > 1` → `hardlinks_warn` populated |
| 5 | `test_remove_nonexistent_model` | raises `ValueError` for unknown repo_id |
| 6 | `test_remove_only_target_model` | sibling models in same publisher dir survive |
| 7 | `test_remove_cli_defaults_to_dry_run` | no `--execute` → files preserved |
| 8 | `test_remove_cli_execute_flag` | `--execute` → model actually deleted |

### `tests/test_gc.py` (7 tests — Phase 5c Tier 1 + Tier 2)

| # | Test Name | What It Tests |
|---|-----------|---------------|
| 1 | `test_gc_dataclass_defaults` | `GCResult()` has empty lists, `total_reclaimable_bytes == 0` |
| 2 | `test_gc_finds_orphaned_gguf` | `.gguf` in shelf root not in manifest → flagged |
| 3 | `test_gc_finds_empty_directories` | empty publisher/repo dir → flagged |
| 4 | `test_gc_skips_non_empty_dirs` | populated model dir → not flagged |
| 5 | `test_gc_skips_dot_dirs` | `.cache/`, `.hidden/` → not flagged |
| 6 | `test_gc_calculates_reclaimable_bytes` | orphaned files' sizes summed correctly |
| 7 | `test_gc_finds_incomplete_mlx_download` | dir with `config.json` but no `.safetensors` → flagged |
| 8 | `test_gc_cli_defaults_to_dry_run` | no `--execute` → nothing deleted |
| 9 | `test_gc_cli_execute_removes_orphans` | `--execute` → files + empty dirs gone |
| 10 | `test_gc_cli_json_output` | `--json` → valid JSON with all fields |

---

## Constraints & Risks

### Must NOT modify:
- `src/model_shelf/manifest.py` — imports only, no edits
- `src/model_shelf/import_model.py` — imports only (for `_sha256_file`)
- `src/model_shelf/dedup.py`
- `src/model_shelf/resolver.py`
- `src/model_shelf/config.py`
- `src/model_shelf/detect.py`
- `src/model_shelf/relocate.py`
- `src/model_shelf/search.py`
- Existing test files (`tests/test_*.py`)

### Must import from (not duplicate):
- `_sha256_file` from `model_shelf.import_model`
- `load_manifest`, `remove_manifest_entry`, `get_manifest_entry` from `model_shelf.manifest`
- `Config`, `SUPPORTED_FORMATS`, `check_storage_available` from `model_shelf.resolver`
- `_fmt_size` from `model_shelf.cli` (or define locally; cli.py already has it as a module-level function)

### Risks:
1. **SHA256 for directories** — `_sha256_file` works for single GGUF files. For MLX/safetensors directories, audit must compute SHA256 over all files. The `_sha256_directory` function in `import_model.py` does NOT skip `.cache/` or dot-files. But `_sha256_dir_for_rebuild` in `manifest.py` DOES skip `.cache/` and dot files. **Risk**: audit may flag MLX/safetensors as stale if it uses a different hashing function than what `rebuild_manifest` used. **Resolution**: For audit's SHA256 comparison of MLX/safetensors dirs, use the same exclusion logic as `_sha256_dir_for_rebuild` from `manifest.py` (import it directly, or replicate the `.cache/` and `._` exclusion logic). The `_sha256_dir_for_rebuild` function is not currently in `manifest.py`'s public API (it's module-private), but it can be imported with a `# noqa` comment or duplicated with the same logic.

2. **Manifest entry `files` list accuracy** — If `files` doesn't list every file on disk, audit may report untracked files that are legitimately part of the model. This is a manifest rebuild concern, not an audit bug — but it means audit results should be interpreted with that in mind.

3. **Race condition between scan and mutate** — For `remove` and `gc`, the scan and the deletion happen in the same process, so this is minimal. But if another process is modifying the shelf concurrently, things can go wrong. Not a new risk (same applies to `dedup`).

4. **Empty parent cleanup in remove** — Removing a model may leave `{fmt}/{publisher}/` empty. The cleanup should walk up and remove empty ancestor dirs until it hits a non-empty dir or `shelf_root`. This is straightforward but must be tested carefully (test 6 in remove suite tests sibling model survival).

5. **GC "incomplete download" detection** — For MLX directories without `config.json`, is that truly an incomplete download, or just a non-model directory? The spec says: "dirs without config.json/.gguf" are incomplete. This could flag legitimate non-model directories. But since we're only walking `{shelf_root}/{gguf,mlx,safetensors}/`, any directory there should contain models. This is reasonable.

6. **GC orphan detection must exclude manifest-tracked files** — The same file can appear in the manifest under multiple entries (if hardlinked). Build a set of all tracked paths before scanning.

---

## Start Here

Open **`src/model_shelf/audit.py`** first — it's the simplest of the three modules, read-only, and establishes the cross-referencing pattern (manifest → filesystem) that GC also needs. The `run_audit` function is the blueprint for the file-collection pattern GC will reuse.

After audit, implement **remove** (simple, uses `remove_manifest_entry` from manifest.py), then **gc** (reuses the file-walk and cross-reference logic from audit).

CLI integration should come last — wire all three subcommands into `cli.py` after the modules are working.

Tests should follow each module: `tests/test_audit.py` after audit, `tests/test_remove.py` after remove, `tests/test_gc.py` after gc.