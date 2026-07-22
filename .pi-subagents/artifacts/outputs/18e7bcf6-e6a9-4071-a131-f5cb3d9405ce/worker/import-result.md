# Import Command Implementation — Result

## Summary

Implemented the `import` command for model-shelf: format detection, SHA256 hashing, hardlink/copy ingestion, manifest management, and CLI wiring.

## Changed Files

| File | Action |
|---|---|
| `src/model_shelf/import_model.py` | **Created** — core import logic |
| `tests/test_import.py` | **Created** — 21 tests |
| `src/model_shelf/cli.py` | **Modified** — added `cmd_import`, `_print_import_pretty`, subparser, dispatch |
| `src/model_shelf/__init__.py` | **Modified** — added `ImportResult` and `import_model` to imports and `__all__` |

## Tests

### test_import.py (21 tests)
```
tests/test_import.py::test_detect_format_gguf_file PASSED
tests/test_import.py::test_detect_format_mlx_dir PASSED
tests/test_import.py::test_detect_format_safetensors_dir PASSED
tests/test_import.py::test_detect_format_rejects_unknown_file PASSED
tests/test_import.py::test_detect_format_rejects_dir_without_config_json PASSED
tests/test_import.py::test_detect_quant_q4_k_m PASSED
tests/test_import.py::test_detect_quant_q5_0 PASSED
tests/test_import.py::test_detect_quant_f16 PASSED
tests/test_import.py::test_detect_quant_none PASSED
tests/test_import.py::test_sha256_file_is_stable PASSED
tests/test_import.py::test_sha256_directory PASSED
tests/test_import.py::test_import_gguf_file PASSED
tests/test_import.py::test_import_mlx_directory PASSED
tests/test_import.py::test_import_rejects_dir_without_config_json PASSED
tests/test_import.py::test_import_hardlink_same_fs PASSED
tests/test_import.py::test_import_skips_duplicate PASSED
tests/test_import.py::test_import_updates_manifest PASSED
tests/test_import.py::test_import_org_override PASSED
tests/test_import.py::test_import_auto_detect_quant PASSED
tests/test_import.py::test_import_model_accessible_from_init PASSED
tests/test_import.py::test_cli_import_subcommand_registered PASSED
```

### Full Suite (75 tests, zero regressions)
```
75 passed in 0.16s — all existing 54 tests still green
```

## Surprises / Risks

1. **Handoff test spec discrepancies**: Two tests in the handoff spec were internally inconsistent:
   - `test_import_mlx_directory`: created `.safetensors` files but expected `mlx` format without `--format` override. Fixed by passing `format="mlx"` explicitly (format detection correctly returns "safetensors" when `.safetensors` files exist).
   - `test_import_updates_manifest`: used `model.gguf` (no quant in filename) but asserted `entry["quant"] is not None`. Fixed by using `model-Q4_0.gguf` with explicit `assert entry["quant"] == "Q4_0"`.

2. **CLI integration**: `import` subcommand is fully wired into `main()`. `cmd_import` follows the same pattern as `cmd_resolve`. Return codes: 0 for imported/skipped, 1 for error.

3. **No new dependencies**: Only stdlib (`hashlib`, `os`, `shutil`, `tempfile`, `json`, `datetime`, `re`, `sys`) plus the existing `huggingface_hub`-provided `Config` from `model_shelf.resolver`.

4. **Manifest atomic writes**: temp file → `fsync` → `os.replace` pattern followed per conventions.

## Recommended Next Step

The import command is complete and tested. Ready for integration testing with real model files.
