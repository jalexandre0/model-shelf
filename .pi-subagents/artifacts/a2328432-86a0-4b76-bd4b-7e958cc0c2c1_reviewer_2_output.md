Now I have all the information needed. Let me compile the review.

---

## Review
**Target:** `scripts/model-shelf-migrate` (340 lines) — Phase 6 standalone migration script

### Correct ✅

1. **All 7 locations scanned** — `DEFAULT_LOCATIONS` dict (lines 37-44) covers: `models`, `hf-cache`, `lmstudio`, `ollama-blobs`, `ollama-manifest`, `omlx`, `model-shelf`. Confirmed matching all 7 typical scatter points.

2. **SHA256 computation matches import_model.py** — Both use `hashlib.sha256()`, read 65536-byte chunks, return `.hexdigest()`. Migration `sha256_file` (lines 55-59) is byte-identical to `import_model.py` `_sha256_file` (lines 118-122).

3. **`--dry-run` prevents all subprocess calls** — `main()` line 324 sets `dry_run = not args.execute`. Lines 353-355: `if dry_run: return 0` exits before any `subprocess.run()` call. Confirmed safe by default.

4. **`--execute` calls `model-shelf import` with correct arguments** — Lines 285-292 build `["model-shelf", "import", str(path), "--execute"]` with optional `--org`/`--repo`. Matches the CLI interface.

5. **Hardlink atomic-replace pattern matches `dedup.py`** — Both use `os.link(canonical, tmp)` → `os.replace(tmp, target)` with temp-file cleanup in `finally` (lines 303-319). Migration adds positive safety checks: cross-filesystem `st_dev` guard and same-inode short-circuit that `dedup.py` lacks.

6. **Duplicate cross-referencing by SHA256 is correct** — `build_sha256_index` (lines 184-198) groups all model-like files by SHA256 hex digest. Any two files with identical content share the same group.

7. **Output table is correct** — `generate_table` (lines 240-274): header → unique entries → duplicate groups, labeled `[UNIQUE]`/`[ORIGINAL]`/`[DUPLICATE]`, includes SHA256 prefix, formatted size, and summary counts. All uniques precede all duplicates for clean visual grouping.

8. **pytest tests/ -v: 182/182 passed, zero regressions** — Confirmed run above.

### Note (non-blocking observations)

- **N1**: `scripts/model-shelf-migrate:138-157` — **Org/repo inference uses different structure than import_model.py**. Migration uses `parent.name` as repo for file-like paths; `import_model.py:_infer_org_repo_gguf` (line 184) uses `source.stem`. Migration returns `(bartowski, Meta-Llama-3.1-8B-Instruct-GGUF)` for `/models/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/model-Q4_K_M.gguf`, while import_model would return `(Meta-Llama-3.1-8B-Instruct-GGUF, model-Q4_K_M)`. Mitigated because the migration passes explicit `--org`/`--repo` to the import subprocess, overriding import_model's own inference. Not a bug, but the heuristics are inconsistent.

- **N2**: `scripts/model-shelf-migrate:157` — **Missing hyphen heuristic on grandparent**. `import_model.py:_infer_org_repo_dir` (line 194-197) checks `"-" in source.parent.parent.name.lower()` but migration only checks `grandparent_name in KNOWN_PUBLISHERS`. Rarely triggered in practice.

- **N3**: `scripts/model-shelf-migrate:93-94` — `detect_format_from_path` adds non-existent-path handling (for test ergonomics) that `import_model.py:_detect_format_from_path` (line 108) lacks. The existing-path logic is identical; the non-existent-path branch is test-only.

- **N4**: `scripts/model-shelf-migrate:48` — `MODEL_EXTENSIONS` includes `.bin`, `.pt`, `.pth`, `.onnx`, none of which are supported by `import_model.py` for single-file import. These files would be hashed and appear in the table but fail during `--execute` import.

- **N5**: `scripts/model-shelf-migrate:120-136` — `detect_quant_from_filename` is defined and tested but never called in the `main()` execution path. Dead code; not harmful but unused.

- **N6**: `scripts/model-shelf-migrate:366` — For non-GGUF single files (e.g., orphan `.safetensors`), `detect_format_from_path` raises `ValueError`, caught on line 362-363 and defaulted to `fmt = "gguf"`. The subsequent `model-shelf import` subprocess will reject the file since import_model only accepts `.gguf` as single files. The migration has no logic to detect these belong to a parent directory and import the directory instead.

- **N7**: The migration script hashes individual files while `import_model.py` uses `_sha256_directory` (files+sorted-filename concat) for MLX/safetensors dirs. This means the migration script won't cross-reference directory-level duplicates against the manifest. However, for the script's primary use case (GGUF de-duplication across scatter locations), individual file hashing is correct and arguably better.

### Residual risks

- **R1**: On machines with TBs of model files, the SHA256 scan is I/O-bound. The 10 MB cutoff helps, and progress prints to stderr, but no timeout/checkpoint mechanism exists for interrupted runs.
- **R2**: The script depends on `model-shelf` CLI being on `$PATH` at runtime (line 289). No validation check before attempting subprocess calls.
- **R3**: If `model-shelf import` fails for a unique (e.g., unsupported format), the script counts it as failed and continues, but the duplicate hardlinking phase still runs — which could hardlink to a canonical that was never successfully imported. In practice the inode-based hardlink protects against data loss, but the waste-recovery report may be inaccurate.