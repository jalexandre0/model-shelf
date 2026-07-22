All 168 tests pass. Here is my complete review:

---

## Review

### 1. Test Discipline

**No skip/xfail crimes.** Zero `t.Skip`, `xfail`, `pytest.mark.skip`, or `skipif` across all three test files.

**Honest fixtures.** All tests create real files in `tmp_path`. The helper `_setup_gguf_model` uses `mkdir(parents=True, exist_ok=True)` and `write_bytes()` — no mocks, no empty stubs.

**Assert quality — mostly exact.** One weak assertion found:

- **Note:** `tests/test_remove.py:139` — `assert len(result.hardlinks_warn) >= 1` uses `>=` instead of exact comparison. Defensible because `st_nlink` depends on OS inode behavior, but a more precise assertion (e.g., `assert any("st_nlink=" in w for w in result.hardlinks_warn)`) would be stronger. The subsequent `assert any("st_nlink=" in w for w in result.hardlinks_warn)` on line 140 partially compensates.

**Self-describing names.** Test names are clear and action-oriented: `test_remove_deletes_files_and_directory`, `test_gc_finds_orphaned_gguf`, `test_audit_multiple_issues_in_one_run`, etc.

### 2. Coverage Gaps

| Gap | Severity | File:Line | Detail |
|-----|----------|-----------|--------|
| Stale SHA256 for MLX/safetensors | **Note** | `audit.py:123-134` | `test_audit_stale_sha256` only tests GGUF. The `else` branch (MLX/safetensors via `_sha256_dir_for_rebuild`) has no stale-detection test. A false-pass is possible if that branch silently fails. |
| Publisher-level loose orphan scan | **Note** | `gc.py:151-167` | The second `publisher.rglob("*")` loop (scanning files whose parent is NOT in `scanned_dirs`) is untested. All test orphans live inside repo directories, so `parent_str in scanned_dirs` always skips. Needs a test with a file at `gguf/pub/stray.bin` (no repo subdirectory). |
| Empty parent cleanup after GC execute | **Note** | `cli.py:434-437` | `test_gc_cli_execute_removes_orphans` verifies the orphan file and empty dir are deleted but does not assert that the now-empty parent directories (e.g., `gguf/pub/orphan/`) were cleaned up by `_cleanup_empty_parents`. |
| `test_gc_skips_dot_dirs` vacuous assertion | **Note** | `tests/test_gc.py:102-118` | The test creates `.cache/` and `.hidden/` dirs with files in them (not empty), so `result.empty_dirs` may be empty. The assertion `assert not any(part.startswith(".") for part in rel.parts)` passes vacuously. Add an empty dot-dir to prove the filter works. |

All three audit states are covered: clean (`test_audit_clean_shelf`), dirty single-issue (missing, stale, untracked each have individual tests), and multiple issues (`test_audit_multiple_issues_in_one_run`).

Remove covers all five scenarios: delete, dry-run, hardlink warn, nonexistent model, sibling preservation.

GC covers all four: incomplete dirs (MLX + GGUF), empty dirs, orphaned files, reclaimable bytes.

### 3. Anti-Patterns

**Functions >40 lines (BLOCKER):**

| Function | File:Line | Lines |
|----------|-----------|-------|
| `run_audit` | `audit.py:66` | 90 |
| `remove_model` | `remove.py:51` | 78 |
| `run_gc` | `gc.py:73` | 118 |

Each of these is the module's main entry point carrying most of its logic. They should be decomposed into smaller helper functions.

**Duplicate logic (BLOCKER):**

| Duplicate | Locations | Detail |
|-----------|-----------|--------|
| `_build_manifest_tracked_set` / `_build_tracked_set` | `audit.py:38` and `gc.py:56` | Identical body, different names. Builds a `set[str]` of manifest-tracked paths. Extract to a shared utility (e.g., in `manifest.py`). |
| `_cleanup_empty_parents` | `remove.py:37` and `cli.py:372` | Identical body, different parameter names (`model_dir` vs `deleted_dir`). Both walk up from a deleted directory removing empty parents. Extract to one location and import. |

**Inconsistent skip logic (Note):**

| Function | File:Line | Skip rule |
|----------|-----------|-----------|
| `_should_skip_file` | `audit.py:57` | Skips `._` prefix names (not all dot-prefixed); skips exact `.cache` parts |
| `_should_skip_path` | `gc.py:45` | Skips ALL dot-prefixed parts; skips `.cache` and `.cache-*` parts |

GC’s version is more aggressive. Audit would flag untracked files inside `.hidden-dir/` while GC would skip them. If the differing behavior is intentional the names should reflect this (e.g., `_should_skip_file_audit` vs `_should_skip_path_gc`). If unintentional, extract a shared `_should_skip_shelf_path` with consistent rules.

**Generic names:** Not found. Production functions and test names are descriptive.

### 4. Module Self-Containment

**No circular imports.** The dependency graph is clean:

```
audit.py  → manifest, import_model, resolver
remove.py → manifest, resolver
gc.py     → manifest, resolver
cli.py    → audit (lazy), remove (lazy), gc (lazy), config, ...
```

CLI uses lazy `# noqa: PLC0415` imports to avoid circularity at module level. `__init__.py` re-exports from audit, gc, and remove — none of which import each other.

---