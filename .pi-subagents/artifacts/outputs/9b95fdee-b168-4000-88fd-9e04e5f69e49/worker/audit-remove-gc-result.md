# Phase 5 Implementation: audit, remove, gc

## Summary

Implemented three new modules (audit, remove, gc), wired them into the CLI, added exports to `__init__.py`, and created 30 tests (10 audit + 8 remove + 10 gc + 2 bonus gc tests beyond the 8-target).

## Changed Files

### Created
- `src/model_shelf/audit.py` — `AuditResult` dataclass + `run_audit(config)` function. Cross-references manifest vs filesystem. Returns missing/stale/untracked lists. Uses `_sha256_dir_for_rebuild` for MLX/safetensors dirs (same exclusion logic as `rebuild_manifest`).
- `src/model_shelf/remove.py` — `RemoveResult` dataclass + `remove_model(config, repo_id, *, dry_run=True)` function. Checks `st_nlink` for hardlinks, cleans empty parent dirs, defaults to dry-run.
- `src/model_shelf/gc.py` — `GCResult` dataclass + `run_gc(config)` function. Detects incomplete downloads, orphaned files, empty dirs. Skips `.cache/`, dot-prefixed paths, `._` files. Read-only; execution handled in CLI.

### Modified
- `src/model_shelf/cli.py` — Added `cmd_audit`, `cmd_remove`, `cmd_gc` handlers + subparsers + dispatch in `main()`. Added `os`/`shutil` imports. Added `_print_gc_report` + `_cleanup_empty_parents` helpers.
- `src/model_shelf/__init__.py` — Added imports: `AuditResult`, `run_audit`, `GCResult`, `run_gc`, `RemoveResult`, `remove_model`. Added to `__all__`.

### Tests Created
- `tests/test_audit.py` — 10 tests: dataclass defaults, clean shelf, missing entry, missing file, stale SHA256, untracked file, multiple issues, CLI JSON, CLI exit 0, CLI exit 1.
- `tests/test_remove.py` — 8 tests: dataclass defaults, delete+manifest, dry-run preserves, hardlink warn, nonexistent ValueError, sibling survival, empty parent dir cleanup, CLI dry-run default, CLI --execute.
- `tests/test_gc.py` — 10 tests: dataclass defaults, orphaned GGUF, empty dirs, non-empty dirs skipped, dot dirs skipped, reclaimable bytes sum, incomplete MLX download, incomplete GGUF download, CLI dry-run default, CLI --execute removes orphans, CLI JSON output.

## Validation

- **pytest tests/test_audit.py tests/test_remove.py tests/test_gc.py -v**: 30 passed, 0 failed
- **pytest tests/ -v**: 168 passed, 0 failed (zero regressions)
- **model-shelf audit --help**: works
- **model-shelf remove --help**: works
- **model-shelf gc --help**: works
- **Dry-run enforcement**: remove defaults `dry_run=True`; gc is scan-only, CLI handler guards `--execute` path

## Key Implementation Decisions

1. **SHA256 for directories**: Audit uses `_sha256_dir_for_rebuild` from `manifest.py` (imported) for MLX/safetensors. This uses the same `.cache/` and `._` exclusion logic that `rebuild_manifest` uses, preventing false stale positives.
2. **Untracked file scanning**: Both audit and GC build a `tracked_set` from manifest entries, then walk `{gguf,mlx,safetensors}/` excluding dot-files, `._` macOS resource forks, and `.cache/` paths.
3. **GC execution in CLI**: `run_gc()` is read-only. The `cmd_gc` handler performs `os.unlink`, `shutil.rmtree`, and `rmdir` when `--execute` is passed, following the same pattern as `cmd_dedup`.
4. **Empty parent cleanup**: Both `remove` and `gc --execute` walk up from deleted directories to `shelf_root`, removing empty intermediate directories. GC does a post-order (deepest-first) pass.

## Open Risks

- **None.** All 30 new tests pass and the full suite shows zero regressions (168 total).

## Recommended Next Step

Phase 5 is complete. The next phase can tackle integration tests or additional features as specified in the implementation plan.
