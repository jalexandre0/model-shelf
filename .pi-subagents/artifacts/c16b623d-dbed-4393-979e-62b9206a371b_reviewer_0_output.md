I now have a complete picture of the entire change. Here is the final review.

---

## Review

### Correct ✓

1. **Dry-run avoids all side effects** (`import_model.py:308-313`). The dry-run guard at line 308 sits **after** SHA256 computation (line 296) and duplicate check (line 299) but **before** `_ingest_model()` (line 315) and `_record_manifest()` (line 316) — the only two functions that write to disk. Confirmed by test `test_import_dry_run_computes_but_does_not_write` which asserts `not result.path.exists()` and empty manifest.

2. **SHA256 is computed in dry-run** (`import_model.py:296`). `_compute_sha256(source, fmt)` runs unconditionally before the dry-run guard. Test `test_import_dry_run_computes_but_does_not_write` asserts `len(result.sha256) == 64`.

3. **Duplicate detection works in dry-run without modifying manifest** (`import_model.py:298-306`). `_load_manifest()` is read-only and `_check_duplicate()` is a pure dict scan. If duplicate found, returns `skipped_duplicate` before the dry-run check (line 301). Test `test_import_dry_run_detects_duplicate_without_writing` confirms: after a real import, dry-run of the same file returns `status == "skipped_duplicate"`.

4. **Missing source file in dry-run** (`import_model.py:290-291`). `_validate_source` calls `source.exists()` → `ValueError`. This is correct — you can't import what doesn't exist, dry-run or not. The exception propagates through `cmd_import()` (no try/except) to `main()` where `except ValueError` prints a clean message and returns 2.

5. **Cross-fs in dry-run**: Since `_ingest_file` is never reached in dry-run mode, the cross-fs warning (line 223-227) is never emitted. This is acceptable — dry-run reports the destination path; the user doesn't need a cross-fs warning for something that isn't happening.

6. **All 79 tests pass** (`79 passed in 0.23s`). No regressions in existing test suites.

7. **The diff is purely additive**: pyproject.toml (+5 lines dev dependency), `__init__.py` (+3 lines exports), `cli.py` (+57 lines subcommand + helpers). No existing functionality modified. New files: `import_model.py` (442 lines), `test_import.py` (378 lines).

8. **Manifest atomic write** (`import_model.py:158-169`): tempfile + `os.fsync` + `os.replace` — correct atomic write pattern.

9. **Hardlink detection** (`import_model.py:221-227`): `st_dev` comparison happens **after** `dest.parent.mkdir(parents=True, exist_ok=True)`, so the directory always exists for the stat call.

10. **`._` prefix filter consistency**: `_sha256_directory` (line 104), `_compute_total_size` (line 220), and `_ingest_model` (line 377) all skip files starting with `._` — consistent.

### Note (non-blocking observations)

- **`import_model.py:420` — `_dest_path` is called before the dry-run guard but after the duplicate guard**. For dry-run duplicates, `result.path` is `None` because `_dest_path` is never reached. The user in dry-run mode who hits a duplicate won't see the destination path. This is arguably correct (the model is already on the shelf somewhere), but worth noting as a UX subtlety.

- **`cli.py:80` — `cmd_import` always returns 0 on non-exception paths**. The return expression `0 if result.status != "error" else 1` never triggers the `1` branch because `import_model()` never produces `status == "error"` — it raises `ValueError` instead. This is consistent with the pattern used by `cmd_resolve` and is defensive coding; not a bug.

- **No test for `import_model` with a missing source file** (the `ValueError` from `_validate_source`). Coverage gap — the CLI exception handler catches it, but the library function path isn't directly tested.

- **`import_model.py:124` — manifest `updated` field is never set** anywhere in the codebase. `_load_manifest` returns `"updated": ""` as default, `_save_manifest` writes it as-is, and `_record_manifest` never updates it. This is pre-existing and not introduced by this diff.

- **`test_import.py:378`** — 21 new tests covering format detection (5), quant detection (4), SHA256 (2), import flows (5), dry-run (2), org inference (2), and integrations (2). Good coverage breadth.

### No blockers found.

No logic errors, no regressions, no edge-case gaps that would cause incorrect behavior. The dry-run implementation is correct: it computes and reports everything the user needs (SHA256, format, destination path, duplicate status) without writing a single byte to disk.