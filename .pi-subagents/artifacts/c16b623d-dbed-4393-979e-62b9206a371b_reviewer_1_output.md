Now I have all the data. Let me compile the final review.

---

## Review

### Correct ✅

- **All 79 tests pass** (0.22s, no failures, no skips)
- **Convention compliance**: `from __future__ import annotations` in all 7 source files; `pathlib.Path` everywhere; dataclasses with `to_dict()` for all result types
- **Module boundaries**: Clean separation — `import_model.py` is its own module (not merged into resolver), `config.py` has no business logic
- **Atomic manifest writes**: `_save_manifest` uses tmp file + `os.replace` with `fsync`
- **Hardlink with same-fs detection**: `_ingest_file` checks `st_dev`, falls back to `shutil.copy2` with a stderr warning
- **SHA256 via `hashlib.sha256()`**: Consistent 64-char hex digests
- **No todos, fixmes, hacks**: Clean production code
- **No `.env` files or dotenv usage**: Only proper `os.environ.get("MODEL_SHELF_CONFIG")`
- **Type hints throughout**: All public functions annotated
- **Duplicate detection**: Works correctly — SHA256-based, idempotent, works with dry-run
- **`--json` flag** on import command follows CLI convention

### Blocker 🔴

**1. `src/model_shelf/cli.py:78` — Dead code: "error" status check never fires**

```python
return 0 if result.status != "error" else 1
```

`import_model()` never returns `status="error"`. It returns `"imported"`, `"skipped_duplicate"`, or `"dry_run"`, and raises `ValueError` on failures (caught by `main()` → exit code 2). The `1` return path is unreachable. If an error-producing path were ever added to `import_model`, exit code 1 vs 2 would be inconsistent.

**Fix**: Either add an actual error-return path to `import_model`, or simplify to `return 0` and rely on the outer `except ValueError` (exit code 2) for errors.

### Note ⚠️

**2. `src/model_shelf/import_model.py:120` — Manifest `updated` top-level field is always `""`**

`_load_manifest` seeds `"updated": ""` for new manifests. `_save_manifest` never sets it. The field serves no purpose — it's a dead field that could confuse future readers.

**3. `src/model_shelf/resolver.py:127` — `import re` inside `detect_format()` function body**

Local import is inconsistent with `import_model.py:18` which imports `re` at module level. No functional impact but violates the project's clean-imports pattern.

**4. `src/model_shelf/import_model.py:262-274` — `_infer_org_repo_dir` grandparent heuristic assumes 3-level depth**

```python
if (source.parent.parent.name.lower() in _KNOWN_PUBLISHERS
        or "-" in source.parent.parent.name.lower()):
    return source.parent.parent.name, repo
```

If the directory depth differs (e.g., `~/Downloads/mlx-community/Qwen3-14B-4bit` vs `~/some/deep/path/mlx-community/Qwen3-14B-4bit`), inference silently falls back to `"local"`. The GGUF path has the same issue.

**5. `src/model_shelf/cli.py:69` — No confirmation or `--dry-run` default for destructive import**

The convention states destructive operations should "require `--dry-run` default or explicit confirmation." Import writes files and modifies manifest without confirmation. `--dry-run` is opt-in (`store_true`, defaults to `False`). This is consistent with how `resolve` and `init` also skip confirmation, but the convention says otherwise.

**6. Manifest.json — forward compatibility assessment**

| Change | Safe? | Notes |
|--------|-------|-------|
| Add new top-level key | ✅ Yes | Code accesses `manifest["models"]` specifically |
| Add new entry field | ✅ Yes | `_check_duplicate` uses `.get()` safely |
| Rename `models` key | ❌ Breaks | Hard-coded string access |
| Change field type | ❌ Breaks | No schema version check on load |
| Add version migration | ❌ Missing | `version: 1` is written but never validated; no migration path |

The `version` field is currently ornamental — set to `1` but never read, checked, or migrated. If schema v2 arrives, there's no mechanism to handle old manifests.

### Tests: Honesty Assessment ✅

- **No `t.Skip`, `xfail`, or `mark.skip`** anywhere in the test suite
- All fixtures use `tmp_path` (pytest temp dirs) — no reliance on real `/Volumes/` or home dirs
- `monkeypatch` used to isolate `discover_primary_shelf`, `USER_CONFIG`, `list_shelf_candidates`
- Regression tests have explicit comments (`# v0.7.1 regression fix`, `# Regression test: ...`)
- Tests would catch regressions: the import tests create real files, verify inode for hardlinks, check manifest contents, and confirm dry-run doesn't write

### Residual Risks

- Manifest schema has no version negotiation or migration mechanism — adding required fields later would break readers
- No test coverage for `_save_manifest` error path (the `except Exception: os.unlink; raise` cleanup) — if both the write and cleanup fail, the original error gets masked
- `_check_duplicate` is O(n) linear scan — acceptable for now but won't scale to thousands of imported models
- The `import` command has no `--format` validation against actual source contents when `--format` is explicitly passed (e.g., `--format gguf` on a directory silently fails at ingest time)

---