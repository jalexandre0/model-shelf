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