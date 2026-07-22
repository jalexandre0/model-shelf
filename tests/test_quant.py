"""Tests for quant detection: GGUF header, config.json, filename fallback."""

from __future__ import annotations

import json
import struct

from pathlib import Path

from model_shelf.import_model import (
    FILETYPE_MAP,
    _detect_quant_from_filename,
    _quant_from_config_json,
    _quant_from_gguf_header,
    detect_quant,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal synthetic GGUF v3 header for testing
# ---------------------------------------------------------------------------

def _make_gguf_header(metadata: dict[str, tuple[int, bytes]]) -> bytes:
    """Build a minimal GGUF v3 header with given metadata keys.

    metadata: key → (type_id, value_bytes)
    """
    buf = bytearray()
    buf += b"GGUF"                           # magic
    buf += struct.pack("<I", 3)              # version
    buf += struct.pack("<Q", 0)              # tensor_count
    buf += struct.pack("<Q", len(metadata))  # kv_count
    for key, (type_id, val_bytes) in metadata.items():
        key_enc = key.encode()
        buf += struct.pack("<Q", len(key_enc))
        buf += key_enc
        buf += struct.pack("<I", type_id)
        buf += val_bytes
    return bytes(buf)


# ===========================================================================
# Tier 1 — Pure logic
# ===========================================================================

# --- FILETYPE_MAP ----------------------------------------------------------

def test_gguf_filetype_map_is_exhaustive():
    """Every integer 0-31 must be a key in FILETYPE_MAP (no gaps)."""
    for i in range(0, 32):
        assert i in FILETYPE_MAP, f"FILETYPE_MAP missing key {i}"


# --- _detect_quant_from_filename --------------------------------------------

def test_detect_quant_from_filename_q4_k_m():
    assert _detect_quant_from_filename(Path("Qwen3-14B-Q4_K_M.gguf")) == "Q4_K_M"


def test_detect_quant_from_filename_iq3_xxs():
    assert _detect_quant_from_filename(Path("model-IQ3_XXS.gguf")) == "IQ3_XXS"


def test_detect_quant_from_filename_f16():
    assert _detect_quant_from_filename(Path("llama-f16.gguf")) == "F16"


def test_detect_quant_from_filename_no_match():
    assert _detect_quant_from_filename(Path("model.gguf")) is None


def test_detect_quant_from_filename_q2_k():
    assert _detect_quant_from_filename(Path("model-Q2_K.gguf")) == "Q2_K"


def test_detect_quant_from_filename_q6_k():
    assert _detect_quant_from_filename(Path("qwen-q6_k.gguf")) == "Q6_K"


def test_detect_quant_from_filename_q8_k():
    assert _detect_quant_from_filename(Path("llama-3.1-q8_k.gguf")) == "Q8_K"


# --- _quant_from_config_json -----------------------------------------------

def test_detect_quant_config_mlx_bits_4(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"quantization": {"group_size": 64, "bits": 4}}')
    assert _quant_from_config_json(tmp_path) == "Q4"


def test_detect_quant_config_mlx_no_quantization(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"model_type": "llama"}')
    assert _quant_from_config_json(tmp_path) is None


def test_detect_quant_config_gptq(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"quantization_config": {"quant_method": "gptq", "bits": 4}}'
    )
    assert _quant_from_config_json(tmp_path) == "GPTQ-4bit"


def test_detect_quant_config_awq(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"quantization_config": {"quant_method": "awq", "bits": 4}}'
    )
    assert _quant_from_config_json(tmp_path) == "AWQ-4bit"


def test_detect_quant_config_torch_dtype_f16(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"torch_dtype": "float16"}')
    assert _quant_from_config_json(tmp_path) == "F16"


def test_detect_quant_config_torch_dtype_bf16(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"torch_dtype": "bfloat16"}')
    assert _quant_from_config_json(tmp_path) == "BF16"


def test_detect_quant_config_torch_dtype_f32(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"torch_dtype": "float32"}')
    assert _quant_from_config_json(tmp_path) == "F32"


def test_detect_quant_config_missing_file(tmp_path: Path):
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    # No config.json in subdir
    assert _quant_from_config_json(subdir) is None


def test_detect_quant_config_invalid_json(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text('not json')  # invalid JSON
    assert _quant_from_config_json(tmp_path) is None


# ===========================================================================
# Tier 2 — Synthetic GGUF binary headers
# ===========================================================================

def test_gguf_header_extracts_q4_k_m(tmp_path: Path):
    """Synthetic GGUF v3 with general.file_type=15 returns Q4_K_M."""
    header = _make_gguf_header(
        {"general.file_type": (4, struct.pack("<I", 15))}
    )
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(header)
    assert _quant_from_gguf_header(gguf) == "Q4_K_M"


def test_gguf_header_extracts_f16(tmp_path: Path):
    """Synthetic GGUF v3 with general.file_type=1 returns F16."""
    header = _make_gguf_header(
        {"general.file_type": (4, struct.pack("<I", 1))}
    )
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(header)
    assert _quant_from_gguf_header(gguf) == "F16"


def test_gguf_header_extracts_iq3_xxs(tmp_path: Path):
    """Synthetic GGUF v3 with general.file_type=22 returns IQ3_XXS."""
    header = _make_gguf_header(
        {"general.file_type": (4, struct.pack("<I", 22))}
    )
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(header)
    assert _quant_from_gguf_header(gguf) == "IQ3_XXS"


def test_gguf_header_not_a_gguf(tmp_path: Path):
    """File starting with b'NOTA' is not a GGUF — returns None."""
    fake = tmp_path / "fake.gguf"
    fake.write_bytes(b"NOTA rubbish content here")
    assert _quant_from_gguf_header(fake) is None


def test_gguf_header_missing_file_type(tmp_path: Path):
    """Synthetic GGUF v3 with only general.name (not general.file_type) returns None."""
    name_bytes = b"test-model"
    str_val = struct.pack("<Q", len(name_bytes)) + name_bytes
    header = _make_gguf_header({"general.name": (8, str_val)})
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(header)
    assert _quant_from_gguf_header(gguf) is None


# ===========================================================================
# detect_quant — unified entry point smoke
# ===========================================================================

def test_detect_quant_gguf_delegates_to_header(tmp_path: Path):
    """detect_quant with gguf fmt uses header first, then filename fallback."""
    header = _make_gguf_header(
        {"general.file_type": (4, struct.pack("<I", 10))}
    )
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(header)
    assert detect_quant(gguf, "gguf") == "Q2_K"


def test_detect_quant_gguf_falls_back_to_filename(tmp_path: Path):
    """When GGUF header has no file_type, falls back to filename detection."""
    name_bytes = b"test-model"
    str_val = struct.pack("<Q", len(name_bytes)) + name_bytes
    header = _make_gguf_header({"general.name": (8, str_val)})
    gguf = tmp_path / "Qwen3-14B-Q4_K_M.gguf"
    gguf.write_bytes(header)
    assert detect_quant(gguf, "gguf") == "Q4_K_M"


def test_detect_quant_unknown_format_returns_none():
    """Unknown format strings produce None."""
    assert detect_quant(Path("anything"), "bin") is None


# ===========================================================================
# Tier 3 — Real model regression smoke (read-only)
# ===========================================================================

def test_gguf_header_real_model_nomic():
    """Real GGUF model downloaded from HuggingFace: nomic-embed-text-v1.5 Q2_K.

    Downloads a tiny 47 MB Q2_K GGUF on first run (cached by huggingface_hub).
    Non-destructive: read-only, no writes. Fails hard if download is impossible
    (fail-open crime: no t.Skip).
    """
    from huggingface_hub import hf_hub_download
    model = hf_hub_download(
        "nomic-ai/nomic-embed-text-v1.5-GGUF",
        filename="nomic-embed-text-v1.5.Q2_K.gguf",
    )
    result = _quant_from_gguf_header(model)
    assert result == "Q2_K", f"Expected Q2_K from GGUF header, got {result}"
