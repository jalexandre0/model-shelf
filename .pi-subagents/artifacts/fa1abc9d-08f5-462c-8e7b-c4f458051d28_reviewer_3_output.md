## Review

### Source: `src/model_shelf/dedup.py` + `tests/test_dedup.py`

---

### Correct
- **All 19 tests pass** — `pytest tests/test_dedup.py -v` → 19 passed in 0.21s
- **Full suite zero regressions** — `pytest tests/ -v` → 138 passed in 0.45s
- **No `t.Skip`, no `xfail`, no conditional execution** — clean audit with `grep`; zero matches
- **`from __future__ import annotations`** — present in `dedup.py:16`, all other source files, and `test_dedup.py:3`
- **Dataclasses used**: `DedupGroup` (line 37), `DedupResult` (line 55) — both decorated with `@dataclass`
- **`pathlib.Path`** throughout (no `os.path` or `str` abuse)
- **Self-describing test names** — all follow `test_<what>_<condition>` pattern (e.g., `test_dedup_handles_three_way_duplicate`)
- **Honest fixtures** — real file writes via `_setup_shelf_gguf` / `_setup_shelf_mlx` in `tmp_path`; no mocked I/O
- **All 5 safety rules implemented** and verifiable in production code:
  1. Dry-run default (`dedup.py:243` `if not args.execute` in CLI)
  2. `st_dev` check (`dedup.py:102-106` `_is_same_fs`)
  3. External blobs are destinations (`dedup.py:293` `if _is_external` guard, `_hardlink_replace` never unlinks source)
  4. Shelf copy is canonical KEEP (`dedup.py:278` `next(f for f in group.files if _is_in_shelf(...)`)
  5. Manifest hardlinks updated (`dedup.py:158-180` `_update_manifest_for_dedup`)
- **No duplicate logic** — `_sha256_file` reused from `import_model.py`
- **No generic names** — all function/variable names are descriptive
- **Edge cases handled correctly in production code**:
  - Three-way duplicates: correct (`dedup.py:268` iterates all non-canonical files)
  - Cross-fs detection: correct (`_is_same_fs` compares `st_dev`)
  - Empty shelf: correct (`find_duplicates` returns empty `DedupResult`)
  - Unique-only shelf: correct (groups with <2 entries filtered out, `dedup.py:244`)

---

### Note (non-blocking observations)

#### N1: Cross-fs test doesn't actually test cross-fs
- **File**: `tests/test_dedup.py:219-249`
- **Severity**: Note — production code is correct, but test spec is not satisfied
- The test `test_dedup_skips_across_filesystems` creates two files on the same `tmp_path` filesystem and asserts `skipped_cross_fs == 0`. It never monkeypatches `st_dev` to differ, so the cross-fs skip path in `execute_dedup` is **never exercised**. The test comment at lines 226-234 admits this limitation. The spec at `.serena/memories/test_specs.md` line 212 explicitly asks: *"Fixture: mock `st_dev` difference between two files (via monkeypatch)"* — this is not done. The test name promises cross-fs testing but the body only tests same-fs happy path.

#### N2: `include_ollama=True` external scanning path is untested
- **File**: `tests/test_dedup.py:251-279`
- **Severity**: Note — production code is correct, but test does not exercise the include flag
- The test creates a mock `tmp_path/ollama/models/blobs/` directory (line 258-261) but never monkeypatches `Path.home()` to point to `tmp_path`. The production code at `dedup.py:214` uses `Path.home() / ".ollama" / "models" / "blobs"`, which resolves to the real `~/.ollama/`. The test then falls back to creating a second shelf file (line 276) to test shelf-to-shelf duplicates instead. The `include_ollama=True` code path (`dedup.py:213-227`) is never visited with a mock directory. The spec at line 215 explicitly asks: *"Fixture: identical file in shelf and in `~/.ollama/models/blobs/sha256-xxx` / Assert: detected as duplicate group"*

#### N3: `include_hf_cache=True` external scanning path is untested
- **File**: `tests/test_dedup.py:284-298`
- **Severity**: Note — same gap as N2
- The test only verifies shelf-shelf duplicate detection with the flag toggled. It never creates a mock HF cache blob that the code would actually scan. The `include_hf_cache=True` codepath (`dedup.py:229-244`) is never exercised with a mock directory.

#### N4: Weak `>=` asserts instead of exact `==` asserts
- **File**: `tests/test_dedup.py`
- **Severity**: Note — tests pass but violate spec discipline rule "Exact asserts: `==` not `>=`"
- Locations (10 occurrences):
  - `:166` `hardlinks_created >= 1` (should be `== 1` for 2 copies in clean `tmp_path`)
  - `:171` `st_nlink >= 2` (should be `== 2`)
  - `:213` `hardlinks_created >= 1` (should be `== 1`)
  - `:249` `hardlinks_created >= 1` (should be `== 1`)
  - `:317` `hardlinks_created >= 1` (should be `== 1`)
  - `:371` `hardlinks_created >= 1` (should be `== 1`)
  - `:378` `len(...) >= 1` (should be `== 1` for 2-file group)
  - `:398` `hardlinks_created >= 2` (should be `== 2` for 3 files)
  - `:404` `st_nlink >= 3` (should be `== 3` for 3 copies in clean `tmp_path`)

#### N5: Functions exceed 40-line guideline
- **File**: `src/model_shelf/dedup.py`
- `find_duplicates` (lines 193-262): ~70 lines
- `execute_dedup` (lines 265-335): ~70 lines
- Both are well-structured but could be split for readability.

#### N6: `_hardlink_replace` deletes pre-existing `.msdedup` files on failure
- **File**: `src/model_shelf/dedup.py:127-136`
- **Severity**: Note — unlikely in practice but worth documenting
- If `os.link()` fails because `tmp` already exists (e.g., leftover from a previous crashed run), the `finally` block at line 135-136 unconditionally deletes `tmp`. It cannot distinguish "we created it" from "someone else created it." In practice, `.msdedup` suffix is unique enough to avoid collisions, but there's no `FileExistsError` handling at the `os.link` call.

---

### Edge Case Coverage

| Edge Case | Status | Evidence |
|-----------|--------|----------|
| Three-way duplicates | ✅ Covered | `test_dedup_handles_three_way_duplicate:386` — `st_nlink=3`, `duplicate_bytes==2*size` |
| Cross-fs detection (different st_dev) | ⚠️ Prod correct, test gap | `_is_same_fs` compares `st_dev` correctly; test only checks same-fs |
| Empty shelf | ✅ Covered | `test_find_duplicates_empty_shelf:81` — groups=[], bytes=0 |
| Only unique models | ✅ Covered | `test_find_duplicates_ignores_different_content:98` — groups=[] |
| Ollama include flag scans | ⚠️ Prod correct, test gap | N2 above |
| HF cache include flag scans | ⚠️ Prod correct, test gap | N3 above |

---

### Anti-Pattern Check

| Check | Status |
|-------|--------|
| Duplicate logic | ✅ None — `_sha256_file` reused from `import_model.py` |
| Functions >40 lines | ⚠️ `find_duplicates` (~70L), `execute_dedup` (~70L) |
| Generic names | ✅ None |
| `from __future__ import annotations` | ✅ All source + test files |
| Dataclasses | ✅ `DedupGroup`, `DedupResult` |
| `pathlib.Path` | ✅ Throughout |

---