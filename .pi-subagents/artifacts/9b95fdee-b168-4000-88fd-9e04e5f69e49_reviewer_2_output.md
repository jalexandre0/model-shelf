Now I have all the evidence. Let me compile the final review.

---

## Review

### Correct

- **AUDIT Q1 — Cross-reference**: `run_audit()` (`audit.py:67-133`) correctly builds `tracked_paths` from manifest entries, iterates all models checking file existence and SHA256, and walks the filesystem for untracked files. ✓
- **AUDIT Q2 — Detection categories**: MISSING detected via `fp.is_file()` → `all_exist` check (lines 97-105). STALE detected via SHA256 comparison using the same `_sha256_dir_for_rebuild` function that `rebuild_manifest` uses (line 118). UNTRACKED detected via `rglob` walk minus `tracked_paths` set (lines 124-131). ✓
- **AUDIT Q3 — Read-only**: `run_audit()` only calls `load_manifest`, `_sha256_file`, `_sha256_dir_for_rebuild`, and `check_storage_available` — zero write calls. ✓
- **REMOVE Q4 — st_nlink check**: `remove_model()` (`remove.py:109-115`) iterates `all_file_paths`, calls `fp.stat().st_nlink`, and appends warnings when > 1. ✓
- **REMOVE Q5 — Parent dir cleanup**: `_cleanup_empty_parents()` (`remove.py:53-59`) walks from `model_dir` up to (exclusive) `shelf_root`, removing empty dirs. Called after deletion during execute (line 127). ✓
- **REMOVE Q6 — Dry-run default**: `remove_model(…, dry_run: bool = True)` (line 64). CLI passes `dry_run=not args.execute` (`cli.py:253`). ✓
- **REMOVE Q7 — Target-only removal**: Only the files in `entry["files"]` for the given `repo_id` are collected and deleted. Test `test_remove_only_target_model` confirms sibling survival. ✓
- **GC Q8 — Detection completeness**: Incomplete downloads detected for GGUF (no `.gguf` files), safetensors (config.json exists but no `.safetensors`), MLX (no `config.json`). Orphaned files detected via tracked-set subtraction. Empty dirs detected via deepest-first traversal. ✓
- **GC Q9 — Skip .cache/ and dot-prefixed**: `_should_skip_path()` (`gc.py:54-58`) checks `any(part.startswith("."))` and `.cache` at every path component. ✓
- **GC Q10 — --execute gate**: `cmd_gc` (`cli.py:325-326`) returns early when `not args.execute`. All deletion code is behind the `--execute` guard. ✓

### Findings

#### Note 1: `_should_skip_file` inconsistency (audit.py:81-84 vs gc.py:54-58)

```
audit.py:81:  ".cache" in path.parts          # substring match
gc.py:57:     any(part == ".cache" or part.startswith(".cache") for part in path.parts)  # exact-component match
```

The audit version uses a substring check (`".cache" in path.parts`) which is slightly broader. In practice both achieve the same goal, but the inconsistency could trip up someone refactoring later. Not a bug — no path in the shelf would have `.cache` as a non-component substring in a component name.

#### Note 2: GC `--execute` does not warn on hardlinked orphan files (cli.py:350-358)

Unlike `remove_model` which checks `st_nlink` and warns, `cmd_gc` deletes orphaned files via `os.unlink` without any hardlink check. Deleting a hardlink is safe (data survives via other links), but the user receives no warning. Consider adding a hardlink check for GC `--execute` parity with `remove`.

#### Note 3: `_cleanup_empty_parents` duplicated (remove.py:53-59 and cli.py:301-310)

The same function exists in both `remove.py` (used by `remove_model`) and `cli.py` (used by `cmd_gc`). Not a bug, but code duplication. Consider extracting to a shared utility.

#### Note 4: MLX incomplete download detection is minimal (gc.py:162-168)

MLX format only checks for `config.json` absence. An MLX directory with just `config.json` and no model weight files would not be flagged as incomplete. This is consistent with `rebuild_manifest` (which also only requires `config.json` for MLX), but a partially downloaded MLX model could slip through.

#### Note 5: Publisher-level orphan scan does redundant work (gc.py:173-182)

After scanning per-repo, `run_gc` does a `publisher.rglob("*")` scan for loose orphans, using `scanned_dirs` to skip already-scanned repo dirs. Functionally correct, but the double-walk is slightly wasteful.

#### Note 6: Nested empty dirs need two GC passes (gc.py:221-233)

Empty dir detection uses deepest-first ordering but only flags directories that are empty *at scan time*. A directory containing only other (soon-to-be-removed) empty subdirectories won't be flagged until a second `gc --execute` run. Acceptable design tradeoff, not a bug.

### Test results

```
168 passed, 0 failed in 0.52s — zero regressions
```