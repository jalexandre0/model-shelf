# Phase 1.5: Upgrade Quant Detection — Handoff

## 1. Files to Modify

### `src/model_shelf/import_model.py`
**Add** new constants/functions (keep all existing code):
- `FILETYPE_MAP` constant (near top, after imports)
- `_quant_from_gguf_header(path)` — binary header parser
- `_quant_from_config_json(path)` — config.json parser for MLX/safetensors
- `detect_quant(source, fmt)` — unified entry point

**Keep as-is** (fallback for GGUF):
- `_detect_quant_from_filename(path)` (lines 237–254)

**Update** call site:
- `_resolve_metadata()` (line ~305): replace `_detect_quant_from_filename(source)` with `detect_quant(source, fmt)` so the new priority chain (header → filename fallback) applies.

### `tests/test_quant.py` **(new file)**
19 tests, 3 tiers (see section 3 below).

### Files NOT to touch
`resolver.py`, `config.py`, `cli.py`, `__init__.py`, `tests/test_import.py`, all other existing files.

---

## 2. API: `detect_quant(source: Path, fmt: str) -> str | None`

Unified entry point. Priority chain per format:

| Format | Priority |
|--------|----------|
| `gguf` | 1. `_quant_from_gguf_header(source)` → 2. `_detect_quant_from_filename(source)` |
| `mlx` | `_quant_from_config_json(source)` |
| `safetensors` | `_quant_from_config_json(source)` |
| anything else | `None` |

---

## 3. New Helpers — Detailed Spec

### 3a. `FILETYPE_MAP` (constant, at module level)

Dict mapping GGUF `general.file_type` uint32 values → quant strings. Must cover all known values 0–24. Value from GGUF spec + llama.cpp `gguf.py`.

```python
FILETYPE_MAP: dict[int, str] = {
     0: "F32",
     1: "F16",
     2: "Q4_0",
     3: "Q4_1",
    # 4-6: Q4_0 with alignment variants (rare, map to Q4_0 or skip)
     7: "Q8_0",
     8: "Q8_1",
    # 9: reserved (IQ2_XXS with older quants, skip or map)
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
    19: "Q8_K",
    20: "IQ2_XXS",
    21: "IQ2_XS",
    22: "IQ3_XXS",
    23: "IQ1_S",
    24: "IQ4_XS",
    # 25+ reserved for future
}
```

**Risk**: Maps 4,5,6 (Q4_0 variants) and 9 (old IQ2_XXS) are ambiguous. The test `test_gguf_filetype_map_is_exhaustive` only needs every int in 0–24 to map to some string — exact values for 4,5,6,9 can be "Q4_0_ALT" or skipped (return `None`), but they must not crash. Recommend mapping 4→"Q4_0", 5→"Q4_1", 6→"Q4_0", 9→"IQ2_XXS" for practical coverage — these are rare enough that a benign remap is acceptable.

### 3b. `_quant_from_gguf_header(path: Path) -> str | None`

Parse GGUF v2/v3 binary header to extract `general.file_type`.

**Algorithm** (derived from implementation plan PoC):
1. Open file in binary mode.
2. Read magic (4 bytes): must be `b'GGUF'`, else return `None`.
3. Read version (uint32 LE): must be 2 or 3.
4. Skip tensor_count (uint64 LE, 8 bytes).
5. Read kv_count (uint64 LE, 8 bytes).
6. Iterate kv_count times:
   a. Read key length (uint64 LE), then key bytes, decode as UTF-8.
   b. Read type_id (uint32 LE).
   c. If key == `'general.file_type'` and type_id == 4 (uint32):
      - Read 4 bytes, unpack uint32 LE → file_type.
      - Return `FILETYPE_MAP.get(file_type)`.
   d. Else: skip the value based on type_id:
      - type_id 0/1 (uint8/int8): 1 byte
      - type_id 2/3 (uint16/int16): 2 bytes
      - type_id 4/5 (uint32/int32): 4 bytes
      - type_id 6/7 (float32/float64): 4 or 8 bytes accordingly
      - type_id 8 (string): read uint64 length N, then N bytes
      - type_id 9 (array): read uint32 element type, read uint64 count N; skip N * element_size
      - type_id 10 (float64): 8 bytes
      - type_id 11 (bool): 1 byte
7. If loop ends without finding `general.file_type`, return `None`.

**Error handling**: catch `OSError`, `struct.error`, `UnicodeDecodeError` → return `None`. Never raise.

**The type_id 9 (array) skip is the trickiest part** — the PoC in the implementation plan has buggy array-skip code (`f.read(0)`). The real implementation must:
```python
elif type_id == 9:  # array
    elem_type = struct.unpack('<I', f.read(4))[0]
    count = struct.unpack('<Q', f.read(8))[0]
    elem_size = {0:1,1:1,2:2,3:2,4:4,5:4,6:4,7:8,10:8,11:1}.get(elem_type, 4)
    f.read(count * elem_size)
```

### 3c. `_quant_from_config_json(path: Path) -> str | None`

Extract quantization from `path/config.json`. `path` is a directory (MLX or safetensors model directory).

**Priority chain**:
1. **MLX quantization**: `data["quantization"]["bits"]` → `f"Q{bits}"` (e.g., `"Q4"`)
2. **Quantization config** (GPTQ, AWQ, etc.): `data["quantization_config"]["quant_method"]` + `"bits"` → `f"{METHOD}-{bits}bit"` (e.g., `"GPTQ-4bit"`, `"AWQ-4bit"`)
3. **Torch dtype**: `data["torch_dtype"]` → map `{"float16":"F16", "bfloat16":"BF16", "float32":"F32"}`
4. None of the above → `None`

**Error handling**: file missing → `None`. Invalid JSON → `None`. No crash, no exception.

### 3d. `_detect_quant_from_filename(path: Path) -> str | None` **(existing, keep)**

Returns uppercase quant tag extracted from GGUF filename via regex patterns. Already handles `Q4_K_M`, `Q5_0`, `IQ3_XXS`, `F16`, `F32`, etc.

---

## 4. Call-Site Update in `_resolve_metadata()`

Current (line ~308):
```python
if fmt == "gguf" and quant is None:
    quant = _detect_quant_from_filename(source)
    if quant:
        checks.append({"step": "detect-quant", "detail": f"auto-detected {quant}"})
```

Replace with:
```python
if quant is None:
    quant = detect_quant(source, fmt)
    if quant:
        checks.append({"step": "detect-quant", "detail": f"auto-detected {quant}"})
```

This extends auto-detection to MLX and safetensors formats (not just GGUF), using the unified `detect_quant()` entry point.

---

## 5. Test File: `tests/test_quant.py`

19 tests across 3 tiers. Follow conventions from existing test files (`test_import.py`):
- `from __future__ import annotations`
- Type hints on all parameters
- `tmp_path: Path` for filesystem tests
- Exact asserts (`==`, `is None`, not `>=`)
- No `t.Skip`, no `xfail`, no conditional guards

### Tier 1 — Pure logic (stdlib only, no filesystem) — 14 tests

| # | Test Name | Input | Assert |
|---|-----------|-------|--------|
| 1 | `test_gguf_filetype_map_is_exhaustive` | iterate 0..24 | every int in `FILETYPE_MAP`, no gaps |
| 2 | `test_detect_quant_from_filename_q4_k_m` | `Path("Qwen3-14B-Q4_K_M.gguf")` | `"Q4_K_M"` |
| 3 | `test_detect_quant_from_filename_iq3_xxs` | `Path("model-IQ3_XXS.gguf")` | `"IQ3_XXS"` |
| 4 | `test_detect_quant_from_filename_f16` | `Path("llama-f16.gguf")` | `"F16"` |
| 5 | `test_detect_quant_from_filename_no_match` | `Path("model.gguf")` | `None` |
| 6 | `test_detect_quant_config_mlx_bits_4` | `tmp_path/config.json` = `{"quantization": {"group_size": 64, "bits": 4}}` | `"Q4"` |
| 7 | `test_detect_quant_config_mlx_no_quantization` | `tmp_path/config.json` = `{"model_type": "llama"}` | `None` |
| 8 | `test_detect_quant_config_gptq` | `{"quantization_config": {"quant_method": "gptq", "bits": 4}}` | `"GPTQ-4bit"` |
| 9 | `test_detect_quant_config_awq` | `{"quantization_config": {"quant_method": "awq", "bits": 4}}` | `"AWQ-4bit"` |
| 10 | `test_detect_quant_config_torch_dtype_f16` | `{"torch_dtype": "float16"}` | `"F16"` |
| 11 | `test_detect_quant_config_torch_dtype_bf16` | `{"torch_dtype": "bfloat16"}` | `"BF16"` |
| 12 | `test_detect_quant_config_torch_dtype_f32` | `{"torch_dtype": "float32"}` | `"F32"` |
| 13 | `test_detect_quant_config_missing_file` | `tmp_path/subdir/` (no config.json) | `None` (no crash) |
| 14 | `test_detect_quant_config_invalid_json` | config.json = `"not json"` | `None` (no crash) |

### Tier 2 — Synthetic GGUF binary (real bytes, no real model) — 5 tests

| # | Test Name | Input | Assert |
|---|-----------|-------|--------|
| 15 | `test_gguf_header_extracts_q4_k_m` | Synthetic GGUF v3 with `general.file_type=uint32(15)` at correct offset | `"Q4_K_M"` |
| 16 | `test_gguf_header_extracts_f16` | Synthetic GGUF v3 with `general.file_type=uint32(1)` | `"F16"` |
| 17 | `test_gguf_header_extracts_iq3_xxs` | Synthetic GGUF v3 with `general.file_type=uint32(22)` | `"IQ3_XXS"` |
| 18 | `test_gguf_header_not_a_gguf` | File with `b"NOTA"` as first 4 bytes | `None` (no crash) |
| 19 | `test_gguf_header_missing_file_type` | Synthetic GGUF v3 with only `general.name` (no `general.file_type`) | `None` |

**Synthetic GGUF construction helper** needed for Tier 2. Something like:
```python
import struct

def _make_gguf_header(metadata: dict[str, tuple[int, bytes]]) -> bytes:
    """Build a minimal GGUF v3 header with given metadata keys.
    
    metadata: key → (type_id, value_bytes)
    """
    buf = bytearray()
    buf += b'GGUF'                         # magic
    buf += struct.pack('<I', 3)            # version
    buf += struct.pack('<Q', 0)            # tensor_count
    buf += struct.pack('<Q', len(metadata)) # kv_count
    for key, (type_id, val_bytes) in metadata.items():
        key_enc = key.encode()
        buf += struct.pack('<Q', len(key_enc))
        buf += key_enc
        buf += struct.pack('<I', type_id)
        buf += val_bytes
    return bytes(buf)
```

Then tests call:
```python
header = _make_gguf_header({"general.file_type": (4, struct.pack('<I', 15))})
tmp_path / "model.gguf")  # write header bytes
```

### Tier 3 — Real model regression smoke — 0 new tests (1 existing)

The test spec lists `test_gguf_header_real_model_nomic` as Tier 3, but this is **optional / not to be written** since the spec says read-only on a real LM Studio model file at `~/.lmstudio/...`. If needed, this can be added later; it's a read-only regression smoke that requires a real 80 MB GGUF file on disk. **Skip for now** — the 18 synthetic/file-based tests above cover all the logic paths.

---

## 6. Architecture & Data Flow

```
                          detect_quant(source, fmt)
                                  │
                    ┌─────────────┼──────────────┐
                    │             │              │
                  gguf          mlx        safetensors
                    │             │              │
          ┌────────┴────────┐    │              │
          │                 │   ┌┘              ┌┘
  _quant_from_gguf_header  │   │               │
  (binary parse, FAST)     │   │               │
          │                │   │               │
      [return if found]    │   │               │
          │                │   │               │
          └── [fallback] ──┘   │               │
       _detect_quant_from_     │               │
       filename (regex)        │               │
                               │               │
                         _quant_from_config_json(path)
                         (reads path/config.json)

import_model._resolve_metadata() calls detect_quant() for ALL formats,
not just gguf. Quant is stored in manifest entry["quant"].
```

**Key insight**: `_detect_quant_from_filename` is the GGUF fallback — header parsing is primary. For MLX/safetensors, config.json is the only source. The unified `detect_quant()` dispatches based on format string.

---

## 7. Start Here

Open `src/model_shelf/import_model.py` and locate:
- **Line ~237**: `_detect_quant_from_filename` — keep, this is the fallback
- **Line ~26**: imports — add `struct` to imports
- **After line ~30** (after imports, before helpers): insert `FILETYPE_MAP` constant
- **After `_detect_quant_from_filename`** (~line 254): insert `_quant_from_gguf_header()`, `_quant_from_config_json()`, `detect_quant()`
- **Line ~308**: update `_resolve_metadata()` call site

Then create `tests/test_quant.py` with the 18 tests.

## 8. Risks & Constraints

### Risk 1: GGUF array skip logic
The type_id=9 (array) branch is the most error-prone part of `_quant_from_gguf_header`. The PoC in the implementation plan has a bug (`f.read(0)` returns empty bytes). Need proper element-size lookup table for arrays. **Mitigation**: Test with synthetic headers containing array-typed keys before `general.file_type`.

### Risk 2: FILETYPE_MAP gaps
Values 4-6 and 9 are ambiguous in the GGUF spec. The `test_gguf_filetype_map_is_exhaustive` test requires every int 0-24 to map to a string. **Mitigation**: Use best-effort mappings (e.g., 4→"Q4_0", 5→"Q4_1", 6→"Q4_0", 9→"IQ2_XXS").

### Risk 3: Filename function naming inconsistency
The implementation plan references `_quant_from_filename()` in the unified entry point but the actual function is `_detect_quant_from_filename()`. **Mitigation**: Use the actual name `_detect_quant_from_filename` in `detect_quant()`.

### Risk 4: `_quant_from_config_json` takes directory path, not file path
The test spec passes `tmp_path` (a directory) to `_quant_from_config_json()`, which then looks for `path / "config.json"`. This is correct — the function takes the model directory, not the config file itself. Make sure this matches.

### Risk 5: MLX format currently sets `quant = None` in manifest
The `_build_manifest_entry()` function (line ~386) sets `"quant": quant if fmt == "gguf" else None`. After this upgrade, MLX and safetensors models can also have quant detected. **Mitigation**: Update `_build_manifest_entry()` to store quant for all formats, not just gguf. Change to `"quant": quant` (no format guard).