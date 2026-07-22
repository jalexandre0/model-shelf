I now have all the evidence I need. Let me compile the review.

---

## Review

### Correct

1. **All 6 public functions implemented** — `load_manifest`, `save_manifest`, `get_manifest_entry`, `add_manifest_entry`, `remove_manifest_entry`, `rebuild_manifest` — all present in `src/model_shelf/manifest.py` with correct signatures and behavior.

2. **`rebuild_manifest()` shelf walk correct** — `_discover_models_on_disk()` iterates `{gguf,mlx,safetensors}/` subdirs, walks publisher/repo nesting, delegates to `_discover_gguf_models()` for `.gguf` files and `_discover_dir_models()` for MLX/safetensors dirs. Format is determined by parent directory (`fmt` argument), not file contents.

3. **SHA256 computation** — GGUF uses `_sha256_file()` (lazy-imported from `import_model`), dirs use `_sha256_dir_for_rebuild()` which excludes dot-files and `.cache/` subtrees. Both produce correct 64-char hex digests.

4. **`save_manifest()` atomic write** — Lines 168-184: `NamedTemporaryFile(delete=False)` → `json.dump` → `tmp.flush()` → `os.fsync(tmp.fileno())` → `tmp.close()` → `os.replace(tmp.name, manifest_path)`. Exception handler `os.unlink(tmp.name)`. Correct.

5. **`load_manifest()` error handling** — Lines 145-167:
   - Missing file → returns `{"version": 1, "updated": "", "models": {}}`
   - Invalid JSON → `ValueError("… contains invalid JSON")`
   - Non-dict JSON → `ValueError("… expected a JSON object")`
   - Wrong version → `ValueError("unsupported manifest version: N; expected version 1")`
   All verified by tests 9–11.

6. **`import_model.py` re-exports** — Lines 121-122 are the `from model_shelf.manifest import …` re-exports. `grep` confirms **zero** leftover `def _load_manifest` or `def _save_manifest` bodies. Identity check: `import_model._load_manifest is manifest.load_manifest` → `True`. No residual `import tempfile`.

7. **CLI wiring** — `cmd_manifest()` defined at cli.py line ~222, `p_manifest` subparser at line ~260 with `--rebuild` and `--json` flags, dispatch at line ~299 in `main()`. `__init__.py` exports all 7 manifest names. Correct.

8. **All 119 tests pass, zero regressions** — Exceeds the 116+ expectation.

### Blocker

**None.** No issue that prevents shipping.

### Note: `_skip_gguf_value` array handling differs from `import_model.py` (latent correctness bug)

- **`src/model_shelf/manifest.py:86-87`** — The manifest.py `_skip_gguf_value` for `type_id == 9` (array) reads only 12 bytes (elem_type + count headers) but does **not** skip the array element data:

  ```python
  elif type_id == 9:  # array
      f.read(12)  # elem_type (4) + count (8)
  ```

- **`src/model_shelf/import_model.py:352-359`** — The import_model.py version correctly computes `count * elem_size` and skips that:

  ```python
  elif type_id == 9:  # array
      elem_type_raw = f.read(4)
      count_raw = f.read(8)
      ...
      esize = _GGUF_ELEM_SIZES.get(elem_type, 4)
      f.read(count * esize)
  ```

- **Impact**: If `general.architecture` (the target key in `_read_gguf_params`) appears **after** an array-type KV pair (e.g., `tokenizer.ggml.tokens`) in a GGUF header, the parser will misread subsequent keys. In practice, `general.architecture` is almost always among the first few KV pairs in real GGUF files, so this is unlikely to trigger today. The 17 tests pass because the synthetic GGUF fixtures never include array-type KVs.

- **Severity**: Low (latent, unlikely to manifest with real models). Recommend aligning manifest.py's `_skip_gguf_value` with the import_model.py version before a future phase adds heavier GGUF param extraction.

### Note: Duplicate `_GGUF_ELEM_SIZES` across two modules

- Both `manifest.py:57-69` and `import_model.py:53-65` define identical `_GGUF_ELEM_SIZES` dicts. Consolidate into a shared constant in a future cleanup pass.

### Note: `_sha256_dir_for_rebuild` vs `_sha256_directory` divergence

- `manifest.py:_sha256_dir_for_rebuild` excludes `.cache/` subtrees; `import_model.py:_sha256_directory` does not. By design (rebuild spec requires `.cache/` exclusion), but worth documenting that SHA256 for the same model can differ between import and rebuild if `.cache/` content exists.