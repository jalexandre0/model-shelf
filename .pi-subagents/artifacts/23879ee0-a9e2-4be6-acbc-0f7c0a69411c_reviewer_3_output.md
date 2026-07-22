Now I have all the evidence needed. Let me compile the review.

---

## Review: manifest command — TEST DISCIPLINE and CODE QUALITY

### 1. Test Discipline

**No t.Skip / xfail / conditional execution in manifest tests**
All 17 tests in `tests/test_manifest.py` run unconditionally. No `pytest.skip`, no `xfail`, no `if os.getenv(...)` guards. ✅

**BLOCKER — `pytest.skip` found elsewhere in test suite**
- **`tests/test_quant.py:241`**: `pytest.skip("Real model not available on this machine")` — This is a FAIL-OPEN CRIME per `.serena/memories/test_specs.md` (cross-cutting invariants: "Zero `t.Skip`, zero `xfail`, zero conditional execution"). While this is a Phase 1.5 test, not Phase 3, the contract says this applies to ALL test files. The test silently passes when the real model is absent, hiding regressions.

**Honest fixtures**
All fixtures create real files on `tmp_path` (`.write_text()`, `.write_bytes()`, `.mkdir()`). No `unittest.mock`, `monkeypatch`, or `MagicMock` used. The word "mock" appears only as `b"mock weights"` in test file content. ✅

**Exact asserts**
All 17 tests use `==`, `!=`, `is not None`, `is None`, `in`, or `assert` on booleans. Zero `len(result) > 0` weak asserts. Two `!=` asserts are defensible:
- `tests/test_manifest.py:50` — `assert manifest["updated"] != ""` (can't predict ISO timestamp)
- `tests/test_manifest.py:355` — `assert entry["sha256"] != "oldsha"` (verifies SHA changed, exact value unknown)

✅

**Self-describing names**
All 17 test names follow the `test_<what>_<condition>` convention. No abstract names like `test_1`, `test_A`, `test_step_3`. ✅

**One test owner per contract point**
Each contract point tested once: rebuild, load, save, add, remove, get, params extraction, CLI flags. No duplicate asserts of the same contract across multiple tests. One exception: `get_manifest_entry` is exercised inside `test_remove_entry_from_manifest` rather than a standalone test — acceptable since it covers existing, missing, and removed-entry cases in one flow. ✅

**Test spec coverage gap**
- **`tests/test_manifest.py:247-267` (`test_save_manifest_is_atomic`)**: Tests only the happy path (no `.tmp` files after successful save). The spec calls for simulating a crash mid-save: *"write manifest, simulate crash (kill after write, before rename) → Assert: original manifest.json unchanged OR fully written (never half-written)"*. This crash-atomicity property is untested. Severity: **note**.

---

### 2. Anti-patterns — Duplicate Logic

**Duplicate `_GGUF_ELEM_SIZES`** (Note)
- `manifest.py:55-67` and `import_model.py:56-69` contain identical dicts (same 12 key:value pairs). Single source of truth not established. Severity: **note**.

**Divergent `_skip_gguf_value`** (Note / latent bug)
- `manifest.py:81-92` has a simplified version that skips array values with `f.read(12)` — but this only skips the array **header** (elem_type + count), not the array **elements**. 
- `import_model.py:345-363` has the correct version: reads `elem_type`, `count`, then skips `count * elem_size` bytes.
- In `_read_gguf_params`, if any non-`general.architecture` KV pair has array type (type_id 9), the manifest.py parser loses binary alignment.
- Severity: **note** (practically, GGUF metadata rarely uses array-typed keys, so alignment loss is unlikely; but it's a correctness divergence from the canonical version in import_model.py).

**Duplicate GGUF header parsing loop** (Note)
- `manifest.py:95-131` (`_read_gguf_params`) and `import_model.py:284-342` (`_quant_from_gguf_header`) share the same boilerplate: read magic, version, tensor_count, kv_count, iterate KV pairs. Only the key they match and the value they extract differ. Severity: **note** (different purposes — architecture vs file_type — but shared parsing infrastructure could be consolidated).

**Near‑duplicate directory SHA256** (Note)
- `manifest.py:138-151` (`_sha256_dir_for_rebuild`) vs `import_model.py:155-164` (`_sha256_directory`). The only difference is `.cache/` subtree exclusion in the manifest version. Severity: **note** (documented as deliberate in the worker report, but still duplicated hashing boilerplate).

---

### 3. Function Line Lengths

Two functions exceed 40 lines in `manifest.py`:

| Function | Lines | Lines over |
|---|---|---|
| `_discover_dir_models` (manifest.py:325-372) | **48** | +8 |
| `rebuild_manifest` (manifest.py:408-474) | **67** | +27 |

In `import_model.py`:

| Function | Lines | Lines over |
|---|---|---|
| `_quant_from_gguf_header` (import_model.py:284-342) | **59** | +19 |
| `_quant_from_config_json` (import_model.py:366-410) | **45** | +5 |

Severity: **note** for manifest.py functions. The `rebuild_manifest` function especially could be split (e.g., extract the merge logic).

---

### 4. Conventions

| Convention | manifest.py | test_manifest.py | import_model.py |
|---|---|---|---|
| `from __future__ import annotations` | ✅ line 15 | ✅ line 3 | ✅ line 12 |
| `@dataclass` usage | ✅ `ManifestResult` | N/A | ✅ |
| `pathlib.Path` | ✅ throughout | ✅ | ✅ |
| Type hints on test params | ✅ `tmp_path: Path` | ✅ | N/A |

All checked files follow conventions. ✅

---

### 5. Single Source of Truth for Manifest I/O

`import_model.py:172-173` re-exports `load_manifest`/`save_manifest` from `manifest.py`. No `_load_manifest`/`_save_manifest` function bodies remain in `import_model.py`. Verified via grep — only the two re-export lines and two call sites. ✅

`src/model_shelf/__init__.py` exports 7 manifest names. ✅

---

### Acceptance Report