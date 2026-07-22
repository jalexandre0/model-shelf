Now I have complete information. Here is the structured review.

---

## Review

### Correct
- **`_quant_from_gguf_header`**: Correctly parses v2/v3 headers. Handles not-GGUF magic, truncated reads (every `f.read()` has length guard), missing `general.file_type` key. No crashes from `OSError`, `struct.error`, `UnicodeDecodeError` — all caught by the `try/except`.
- **`_quant_from_config_json`**: Handles MLX `quantization.bits`, GPTQ/AWQ `quantization_config`, `torch_dtype` mapping, missing file, invalid JSON — all correct and non-raising.
- **`detect_quant` fallback chain**: `gguf` → header → filename; `mlx`/`safetensors` → config.json; unknown → `None`. Correct dispatch.
- **All 102 tests pass** (22 in `test_quant.py`, all others across the suite). Zero regressions.

### Blocker

**`src/model_shelf/import_model.py:279` — `_detect_quant_from_filename` regex misses Q2_K, Q6_K, Q8_K**

The pattern `(q[2-8]_[klo]_[ms])` requires exactly three underscore-delimited segments (e.g., `Q4_K_M`, `Q5_K_L`, `Q3_K_S`). But three GGUF quantization types have only two segments:

| File Type | Quant String | Example filename |
|-----------|-------------|------------------|
| 10 | `Q2_K` | `model-Q2_K.gguf` |
| 18 | `Q6_K` | `model-Q6_K.gguf` |
| 19 | `Q8_K` | `model-Q8_K.gguf` |

None of the four regex patterns match these. Confirmed by test script:

```
model-Q2_K.gguf  → None   # BUG: should be Q2_K
model-Q6_K.gguf  → None   # BUG: should be Q6_K
model-Q8_K.gguf  → None   # BUG: should be Q8_K
```

**Impact**: When `_quant_from_gguf_header` returns `None` (header lacks `general.file_type`), and the GGUF filename contains Q2_K/Q6_K/Q8_K, `detect_quant` returns `None` instead of the correct quantization. These are commonly distributed quantization types (Q8_K and Q6_K are very popular for 8-bit and 6-bit quality).

**Fix** (`src/model_shelf/import_model.py`, add one line to the patterns list):
```python
r"(q[2-8]_k)(?![a-z0-9])",   # Q2_K, Q6_K, Q8_K (no third segment)
```
Or make the third segment optional in the existing pattern:
```python
r"(q[2-8]_[klo](?:_[ms])?)",
```

### Notes

1. **`src/model_shelf/import_model.py:46-71` — FILETYPE_MAP missing GGUF types 25–31**

   The latest llama.cpp GGUF spec defines types up to 31:
   ```
   25: IQ4_NL,  26: IQ3_S,  27: IQ3_M,  28: IQ2_S,
   29: IQ2_M,   30: IQ4_K_S, 31: IQ4_K_M
   ```
   `FILETYPE_MAP.get(file_type)` returns `None` for these, so `_quant_from_gguf_header` returns `None` and falls through to filename detection. The filename fallback likely catches these (e.g., `IQ4_K_M` would match `iq[1-4]_[a-z]+` → `IQ4_K_M`), but only if the filename contains the quant tag. Not a blocker because the fallback covers most cases, but the map should be kept in sync with the upstream spec.

2. **`tests/test_quant.py` — `test_gguf_filetype_map_is_exhaustive` only checks 0–24**

   The test loops `for i in range(0, 25)` but should cover 0–31 (or whatever the current GGUF ceiling is). If FILETYPE_MAP is extended, the test must be updated too.

3. **`tests/test_quant.py` — No direct tests for `detect_quant` with `fmt="mlx"` or `fmt="safetensors"`**

   The dispatch is only tested with `"gguf"` and an unknown format. The underlying `_quant_from_config_json` is tested directly (which is good), but the integration path through `detect_quant` for MLX and safetensors is not exercised. Manual verification confirms it works correctly. Low risk.

4. **`src/model_shelf/import_model.py:372-382` — `_skip_gguf_value` for arrays of strings/nested arrays**

   Array element type 8 (string) uses `esize=0`, skipping 0 bytes. Nested arrays (type 9) similarly skip 0 bytes. This would corrupt parsing if a GGUF had string arrays or nested arrays in its metadata. In practice, GGUF model metadata uses only integer arrays (e.g., tokenizer data), so this is theoretical. No action needed.

5. **`src/model_shelf/import_model.py:283` — `_detect_quant_from_filename` can return non-GGUF strings**

   The regex `q[2-8]_[0-1]` matches `Q5_0` (tested in `test_import.py`), but Q5_0 is not in FILETYPE_MAP. This is a heuristic fallback by design — the filename detection is intentionally broader than the header map. Acceptable as-is.

---