Now I have all the evidence needed to compile the full review.

---

## Review

### Correct
- **Test discipline**: Zero `t.Skip`/`pytest.mark.skip`; all 12 tests pass (53s); uses honest `tmp_path` fixtures; exact asserts (`assert org == "bartowski"`); self-describing names (`test_infer_format_from_path_gguf`, `test_migration_scan_finds_all_locations`).
- **Standalone**: 12 imports, all stdlib. Confirmed via AST parse: `argparse`, `hashlib`, `os`, `re`, `struct`, `subprocess`, `sys`, `collections.defaultdict`, `pathlib.Path`, `typing.Any`, `json` (inline). No `model_shelf`, no `huggingface_hub`.
- **Quant patterns**: All 5 regexes byte-for-byte identical to `import_model.py:_detect_quant_from_filename`.
- **KNOWN_PUBLISHERS**: Identical frozenset: `bartowski`, `lmstudio-community`, `mlx-community`, `unsloth`.
- **Format detection**: Core logic (file→gguf, dir+config+safetensors→safetensors, dir+config→mlx) matches exactly. Migrate adds a non-existent-path suffix heuristic for testability, which is benign.
- **Hardlink pattern**: Atomic replace (`os.link`→`os.replace` with temp `.msmigrate` suffix) correctly adapted from `dedup.py:_hardlink_replace`; adds `st_dev` cross-fs guard and `st_ino` already-linked check.
- **Missing locations**: `if not root.is_dir(): continue` — silent skip (line 217).
- **Permission errors**: `OSError` caught in `f.stat()` (line 228) and `sha256_file` call (line 128).
- **Dot-files**: `._*` skipped, `.*` skipped except `.gguf`, `.cache` subdirs skipped (lines 221-226).
- **JSON output**: Well-structured dict with `unique_count`, `duplicate_groups`, `total_waste_bytes`, nested entries arrays. Valid JSON via `json.dumps(indent=2)`. Field names consistent with table output.
- **Subprocess args**: `model-shelf import` accepts `--org`/`--repo` (confirmed in `cli.py:575-576`).

### Note (non-blocking observations)

1. **`scripts/model-shelf-migrate:16` — Dead import `struct`**: `import struct` is never used anywhere in the file. The script uses `is_gguf()` which only reads magic bytes (no `struct.unpack`), unlike `import_model.py` which uses `struct` for GGUF header parsing. Severity: low.

2. **`tests/test_migrate.py:217-219` — Unused `os.stat` snapshots in real-scan test**: `before = os.stat(...)` and `after = os.stat(...)` are captured but never asserted against. The test only checks output shape (`len(files) >= 0`, `"Unique models:" in table`). It doesn't actually verify read-only behavior. Severity: low.

3. **`scripts/model-shelf-migrate:490` — `--json` only works in dry-run mode**: In `--execute` mode, the code path goes directly to import/hardlink logic and prints human-readable text to stdout/stderr. No JSON is emitted. If an agent expects `--json` to work with `--execute`, it would get unstructured text. Severity: low (by design — migration should be reviewed before execution).

4. **`scripts/model-shelf-migrate:179-196` — `_QUANT_PATTERNS` tuples have unused second element**: `list[tuple[str, int]]` — the integer `1` in each tuple is never consumed (loop uses `for pat, _ in …`). The original `import_model.py` uses a plain `list[str]`. Severity: very low.

5. **`scripts/model-shelf-migrate:147-148` — `infer_org_repo` always checks grandparent**: In `import_model.py`, `_infer_org_repo_gguf` only checks the immediate parent; grandparent fallback is exclusive to `_infer_org_repo_dir`. The migrate version checks grandparent for both file and dir paths. This strictly expands detection (cannot cause incorrect inferences), but means the two code paths are not exact mirrors. Severity: very low.

6. **`scripts/model-shelf-migrate:241-245` — Extensionless files >10MB always hashed**: `_is_model_like` returns `True` for any extensionless file above `MIN_FILE_BYTES` (10MB). This is intentional for Ollama blobs and HF cache blobs, but means a large extensionless non-model file in a scanned location would waste SHA256 I/O. Severity: very low.

7. **Symlink cycles**: `Path.rglob("*")` follows symlinks by default. No cycle detection. Same risk exists in `import_model.py`. Severity: low (preexisting, not new).

### Blocker
None.

---