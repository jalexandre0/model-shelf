# Phase 3: manifest command — Implementation Report

## Summary

Implemented the manifest command as specified. Created `manifest.py` as the canonical manifest I/O module, modified `import_model.py` to re-export from it, added CLI subcommand and dispatch, and wired `__init__.py` exports.

## Changes

### Created Files

1. **`src/model_shelf/manifest.py`** (~330 lines) — Single source of truth for manifest I/O.
   - `load_manifest()` / `save_manifest()` — atomic JSON read/write
   - `get_manifest_entry()` / `add_manifest_entry()` / `remove_manifest_entry()` — CRUD helpers
   - `rebuild_manifest(config)` — walks `shelf_root/{gguf,mlx,safetensors}/`, discovers models, rebuilds manifest
   - `ManifestResult` dataclass with `to_dict()`
   - Custom `_sha256_dir_for_rebuild()` that excludes `.cache/` subtrees
   - `_read_gguf_params()` for extracting architecture from GGUF headers
   - `_read_config_params()` for extracting model_type, num_hidden_layers, etc.
   - Lazy imports of `detect_quant`/`_sha256_file` from import_model to avoid circular imports

2. **`tests/test_manifest.py`** (~280 lines) — 17 tests (14 Tier 1 + 3 Tier 2)
   - All 17 pass

### Modified Files

3. **`src/model_shelf/import_model.py`** — Replaced `_load_manifest`/`_save_manifest` function bodies with re-exports from manifest.py. Removed unused `import tempfile`.

4. **`src/model_shelf/cli.py`** — Added `cmd_manifest()` handler, `p_manifest` subparser with `--rebuild`/`--json` flags, and dispatch in `main()`.

5. **`src/model_shelf/__init__.py`** — Added 7 manifest exports to `__all__` and import block.

## Validation

- **pytest tests/test_manifest.py -v**: 17 passed
- **pytest tests/ -v**: 119 passed (102 existing + 17 new), zero regressions
- **_load_manifest is load_manifest**: `True` (verified re-export identity)
- **_save_manifest is save_manifest**: `True`
- **`model-shelf manifest --help`**: Shows usage with --rebuild and --json
- **`model-shelf manifest --rebuild`**: Walks shelf, prints "Rebuilt manifest: N models tracked"
- **`model-shelf manifest --rebuild --json`**: Emits valid JSON `{"status": "ok", "models_count": N, "errors": []}`
- **`model-shelf manifest --json`**: Emits full manifest JSON with models key
- **No duplicate `_load_manifest`/`_save_manifest`** in import_model.py (verified via grep)
- **No staged files**: Only 3 modified + 2 untracked (new) files

## Circular Import Resolution

The handoff claimed module-level imports were safe, but Python's import order (import_model → manifest → import_model) caused `ImportError`. Fixed by moving `detect_quant` and `_sha256_file` imports inside `_discover_gguf_models()` and `_discover_dir_models()` as lazy imports.

## Design Decision: MLX detection in rebuild

The handoff spec said to skip directories under `mlx/` that contain `.safetensors` files, but the test `test_rebuild_with_mlx_model` creates exactly this scenario (MLX dir with config.json + model.safetensors + tokenizer.json). MLX models legitimately contain `.safetensors` files (shared weight format). The format is determined by the parent directory, not file contents. Removed the skip rule for `mlx/` — only `safetensors/` directories without `.safetensors` files are skipped.

## Open Risks

1. **Multiple GGUF files in one repo**: Each `.gguf` gets a unique repo_id using `{publisher}/{stem}`. If two GGUF files in different subdirectories produce the same stem, there could be a collision. Current behavior: last one wins (add_manifest_entry overwrites). Acceptable for Phase 3.

2. **Rebuild only discovers new models**: Models manually deleted from disk are detected and entries are removed (with warning). This is correct behavior — the audit command (Phase 5) can handle more sophisticated stale-entry detection.

3. **`_sha256_dir_for_rebuild` vs `_sha256_directory`**: manifest.py uses its own directory SHA256 that excludes `.cache/`. The original `_sha256_directory` in import_model.py is unchanged and still excludes only `._` files. This is deliberate — rebuild needs `.cache/` exclusion per spec.

## Recommended Next Step

Phase 4 (dedup command) or Phase 5 (audit/remove/gc). manifest.py is ready to serve as the canonical I/O module for all future commands.

---

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Concrete findings with file paths: src/model_shelf/manifest.py (330 lines, created), tests/test_manifest.py (280 lines, 17 tests), src/model_shelf/import_model.py (re-exports only, old bodies removed), src/model_shelf/cli.py (+cmd_manifest, +subparser, +dispatch), src/model_shelf/__init__.py (+7 exports). Circular import resolved via lazy imports. All 119 tests pass."
    }
  ],
  "changedFiles": [
    "src/model_shelf/manifest.py",
    "src/model_shelf/__init__.py",
    "src/model_shelf/cli.py",
    "src/model_shelf/import_model.py",
    "tests/test_manifest.py"
  ],
  "testsAddedOrUpdated": [
    "tests/test_manifest.py (17 tests: 14 Tier 1 + 3 Tier 2)"
  ],
  "commandsRun": [
    {
      "command": "pytest tests/test_manifest.py -v",
      "result": "passed",
      "summary": "17 passed in 0.13s"
    },
    {
      "command": "pytest tests/ -v",
      "result": "passed",
      "summary": "119 passed (102 existing + 17 new), zero regressions"
    },
    {
      "command": "model-shelf manifest --help",
      "result": "passed",
      "summary": "Shows --rebuild and --json flags"
    },
    {
      "command": "model-shelf manifest --rebuild",
      "result": "passed",
      "summary": "Rebuilt manifest: 1 models tracked, exit 0"
    },
    {
      "command": "model-shelf manifest --rebuild --json",
      "result": "passed",
      "summary": "Valid JSON output: {status: ok, models_count: 1, errors: []}"
    },
    {
      "command": "model-shelf manifest --json",
      "result": "passed",
      "summary": "Emits full manifest JSON with models key"
    },
    {
      "command": "Verify _load_manifest is load_manifest (identity check)",
      "result": "passed",
      "summary": "True — import_model.py re-exports from manifest.py"
    },
    {
      "command": "grep for old _load_manifest/_save_manifest definitions in import_model.py",
      "result": "passed",
      "summary": "Old function bodies removed; only re-export lines remain"
    }
  ],
  "validationOutput": [
    "manifest.py is the single source of truth for manifest I/O",
    "import_model.py re-exports _load_manifest/_save_manifest from manifest.py (no duplicate bodies)",
    "CLI subcommand 'manifest' registered with --rebuild and --json flags",
    "All __init__.py exports wired (7 new names in __all__)",
    "Circular import resolved: lazy imports of detect_quant/_sha256_file in rebuild helpers",
    "MLX detection in rebuild: format determined by parent directory, not file contents (fixes handoff contradiction with test expectations)",
    "rebuild_manifest preserves existing fields (hardlinks, source, imported, etc.)",
    "rebuild_manifest removes entries for deleted models with warning",
    "Atomic save via NamedTemporaryFile + os.replace"
  ],
  "residualRisks": [
    "Multiple GGUF files with identical stems in different subdirs would collide (acceptable for Phase 3)",
    "_sha256_dir_for_rebuild vs _sha256_directory divergence: manifest.py has its own dir-SHA256 that excludes .cache/ while import_model's original doesn't. This is by design per spec but worth noting for future consolidation."
  ],
  "noStagedFiles": true,
  "diffSummary": "5 files changed: +manifest.py (+330 lines), +test_manifest.py (+280 lines, 17 tests), import_model.py (-36/+2, re-exports replace old bodies), cli.py (+40, cmd_manifest + subparser + dispatch), __init__.py (+16, 7 exports). Total: 119 tests pass, zero regressions.",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "The handoff spec contradiction about MLX + .safetensors was resolved in favor of the test expectations. MLX models under mlx/ accept .safetensors files — format is determined by shelf directory, not file content. This matches real-world MLX model repositories from mlx-community which often contain .safetensors weight files alongside MLX-specific formats."
}
```
