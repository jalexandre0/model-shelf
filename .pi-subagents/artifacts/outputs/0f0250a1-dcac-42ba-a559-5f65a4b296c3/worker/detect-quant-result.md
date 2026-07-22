# Phase 1.5: Upgrade Quant Detection — Implementation Result

## Summary

Implemented `detect_quant()` unified entry point with GGUF binary header parsing, config.json extraction for MLX/safetensors, and filename regex fallback. 22 tests pass, zero regressions across full 102-test suite.

## Changed Files

| File | Change |
|------|--------|
| `src/model_shelf/import_model.py` | Added `import struct`, `FILETYPE_MAP` (25 entries, keys 0–24), `_quant_from_gguf_header()`, `_skip_gguf_value()`, `_quant_from_config_json()`, `detect_quant()`. Updated `_resolve_metadata()` to use `detect_quant()` (all formats). Updated `_build_manifest_entry()` to store `quant` for all formats (not just gguf). |
| `tests/test_quant.py` | **New file** — 22 tests across 3 tiers (19 spec-specified + 3 integration smoke tests for `detect_quant` entry point). |

## Tests Added

22 tests in `tests/test_quant.py`:

**Tier 1 — Pure logic (14 tests):**
- `test_gguf_filetype_map_is_exhaustive` — all keys 0–24 present
- `test_detect_quant_from_filename_q4_k_m` / `_iq3_xxs` / `_f16` / `_no_match`
- `test_detect_quant_config_mlx_bits_4` / `_mlx_no_quantization`
- `test_detect_quant_config_gptq` / `_awq`
- `test_detect_quant_config_torch_dtype_f16` / `_bf16` / `_f32`
- `test_detect_quant_config_missing_file` / `_invalid_json`

**Tier 2 — Synthetic GGUF binary (5 tests):**
- `test_gguf_header_extracts_q4_k_m` / `_f16` / `_iq3_xxs`
- `test_gguf_header_not_a_gguf` / `_missing_file_type`

**Integration smoke (3 tests):**
- `test_detect_quant_gguf_delegates_to_header`
- `test_detect_quant_gguf_falls_back_to_filename`
- `test_detect_quant_unknown_format_returns_none`

## Commands Run

| Command | Result | Summary |
|---------|--------|---------|
| `pytest tests/test_quant.py -v` | passed | 22 passed |
| `pytest tests/ -v` | passed | 102 passed, zero regressions |

## Validation

- FILETYPE_MAP covers all GGUF file_type values 0–24 with no gaps.
- `_quant_from_gguf_header` parses GGUF v2/v3 magic, version, tensor_count, kv_count, and iterates kv pairs with correct type-id skip logic (including array type_id=9 with element-size lookup table).
- `_quant_from_config_json` handles MLX quantization.bits, quantization_config (GPTQ/AWQ), torch_dtype, missing file, and invalid JSON — all fail-open (return None).
- `detect_quant` dispatches gguf → header → filename fallback, mlx/safetensors → config.json, unknown formats → None.
- `_resolve_metadata` now calls `detect_quant` for all formats (not just gguf).
- `_build_manifest_entry` now stores quant for all formats (not gated on `fmt == "gguf"`).
- All 80 existing tests pass unchanged. No new dependencies beyond stdlib (`struct`).

## Residual Risks

- FILETYPE_MAP values 4, 5, 6, 9 are ambiguous in the GGUF spec — mapped to best-effort strings (Q4_0, Q4_1, Q4_0, IQ2_XXS). These are rare alignment variants; benign remap is acceptable per handoff.
- GGUF array-skip size lookup uses `elem_sizes.get(elem_type, 4)` as a fallback for unknown element types — conservative but may skip wrong byte count for truly unknown types (none in current GGUF spec).
- No real-model regression test (Tier 3 from handoff was marked as optional/skip).

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Changed files: src/model_shelf/import_model.py (additions), tests/test_quant.py (new file). Severity: all changes are additive — FILETYPE_MAP, _quant_from_gguf_header, _quant_from_config_json, _skip_gguf_value, detect_quant. Existing functions preserved. 102 tests pass, zero regressions. No DO NOT TOUCH files modified."
    }
  ],
  "changedFiles": [
    "src/model_shelf/import_model.py"
  ],
  "testsAddedOrUpdated": [
    "tests/test_quant.py"
  ],
  "commandsRun": [
    {
      "command": ".venv/bin/python -m pytest tests/test_quant.py -v",
      "result": "passed",
      "summary": "22 passed, 0 failed"
    },
    {
      "command": ".venv/bin/python -m pytest tests/ -v",
      "result": "passed",
      "summary": "102 passed, 0 failed — zero regressions"
    }
  ],
  "validationOutput": [
    "FILETYPE_MAP: 25 entries covering 0–24 with no gaps",
    "_quant_from_gguf_header: correct GGUF v3 parsing with type_id skip logic",
    "_quant_from_config_json: MLX, GPTQ, AWQ, torch_dtype extraction, fail-open",
    "detect_quant: gguf header→filename fallback, mlx/safetensors→config.json, unknown→None",
    "_resolve_metadata: uses detect_quant for all formats",
    "_build_manifest_entry: stores quant for all formats",
    "No new dependencies beyond stdlib (struct)"
  ],
  "residualRisks": [
    "FILETYPE_MAP values 4-6, 9 are ambiguous GGUF alignment variants — best-effort mapping used",
    "Array skip fallback size=4 for unknown element types (none in current spec)"
  ],
  "noStagedFiles": true,
  "diffSummary": "src/model_shelf/import_model.py: +165 lines (FILETYPE_MAP, _quant_from_gguf_header, _skip_gguf_value, _quant_from_config_json, detect_quant; updated _resolve_metadata and _build_manifest_entry). tests/test_quant.py: +195 lines (22 tests).",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "Wrote 22 tests (19 spec-specified + 3 integration smoke for detect_quant entry point). The invalid_json test fix changed from '\"not json\"' (valid JSON string) to 'not json' (truly invalid) — the function correctly returns None in both cases now."
}
```
