Now let me compile all findings into a structured review.

---

## Review

### Correctness Walkthrough

**1. Format detection (`_detect_format_from_path`, lines 59–85)** — Correct. Three clean rules: `.gguf` file → `gguf`; dir+config+safetensors → `safetensors`; dir+config only → `mlx`; dir w/o config → `ValueError`; non-gguf file → `ValueError`. Well-documented. ✅

**2. SHA256 (`_sha256_file` lines 91–98, `_sha256_directory` lines 101–110)** — Correct. Stable 64KB-chunked hashing. Directory hash includes sorted filenames in the digest (so `a.txt` + `b.txt` ≠ `b.txt` + `a.txt`), skips macOS `._` resource forks. ✅

**3. Manifest atomic write (`_save_manifest`, lines 125–143)** — Correct. Temp file → flush → fsync → close → os.replace. On exception, cleanup via `os.unlink`. One minor note: if `json.dump` fails, `tmp.close()` hasn't been called yet but `os.unlink` still succeeds on Unix (unlinking an open file). The file descriptor leaks until GC — harmless in practice. ✅

**4. Org/repo inference (`_infer_org_repo*`, lines 152–226)** — Mostly correct. The `"-" in parent` heuristic in `_infer_org_repo_gguf` (line 210) is quite broad: any directory name containing a hyphen is treated as a publisher. This could match unintended directories (e.g., `/tmp/model-downloads/model.gguf` → org = `model-downloads`). The `--org`/`--repo` overrides always take precedence, so this is self-correctable. ✅ with a note.

**5. Quant detection (`_detect_quant_from_filename`, lines 230–249)** — Correct. Four regex patterns cover: `Q[2-8]_[KLO]_[MS]`, `Q[2-8]_[0-1]`, `IQ[1-4]_*`, `F16|F32|FP16|FP32`. Case-insensitive matching with `.upper()` normalization. Covers all common GGUF quantization tags. ✅

**6. File ingestion (`_ingest_file`, lines 255–266)** — Correct. Checks `st_dev` before attempting `os.link`. Falls back to `shutil.copy2` on cross-fs with a stderr warning. Creates parent directories. ✅

**7. Import flow (`import_model`, lines 269–392)** — Correct. Nine-step pipeline: resolve → detect format → infer org/repo/quant → SHA256 → duplicate check → dest path → ingest → compute size → write manifest. Duplicate check iterates manifest entries by SHA256 (O(n), fine for practical manifest sizes). ✅

**8. CLI wiring (`cmd_import` in `cli.py`, lines 60–76)** — Correct. Mirrors `cmd_resolve` pattern. `check_storage_available` guard, argparse subparser with `--format`, `--org`, `--repo`, `--quant`, `--no-hardlink`, `--json` flags. Returns 0 for imported/skipped, 1 for error. ✅

**9. Package exports (`__init__.py`)** — Correct. `ImportResult` and `import_model` added to imports and `__all__`. No existing symbols removed or renamed. ✅

---

### Edge Cases Verdict

| Edge case | Handled? | Detail |
|-----------|----------|--------|
| Missing source file | ✅ | `source.resolve().exists()` at import_model:287 |
| Non-model directory (no config.json) | ✅ | `_detect_format_from_path` raises `ValueError` with clear message |
| Non-.gguf single file | ✅ | `_detect_format_from_path` raises `ValueError` |
| Cross-fs hardlink | ✅ | `_ingest_file` checks `st_dev`, falls back to `shutil.copy2` + warning |
| Duplicate (SHA256 collision) | ✅ | Manifest scan before ingest, returns `skipped_duplicate` |
| Symlink source | ✅ | `source.resolve()` before any operations |
| macOS `._` dotfiles | ✅ | Skipped by both `_sha256_directory` and directory ingest |
| Empty directory (MLX/safetensors with config.json only) | ✅ | Accepted; SHA256 of just config.json, files list has it |
| Format override | ✅ | `--format` bypasses auto-detection entirely |
| Quant auto-detect for non-GGUF | ✅ | Auto-detect only runs when `fmt == "gguf"`; manifest stores `None` otherwise |

---

### Findings

- **Correct**: Core logic (format detection, SHA256, hardlink/copy, manifest management, CLI wiring) is correct and well-structured. All 75 tests pass with zero regressions. No existing modules were modified except for additive changes (`__init__.py` exports, `cli.py` subcommand).

- **Note** — `src/model_shelf/import_model.py:210`: The `"-" in parent` heuristic in `_infer_org_repo_gguf` treats any hyphenated directory name as a publisher. This is intentionally broad to catch orgs like `mlx-community`, but it can also match non-publisher directories like `/tmp/my-downloads/model.gguf` → org=`my-downloads`. Low severity because `--org` overrides it.

- **Note** — `src/model_shelf/import_model.py:371`: The manifest `hardlinks` field is always `[]` — never populated. This appears to be a placeholder. When hardlink succeeds vs. copy fallback, there's no programmatic record in the manifest. Only a stderr warning is emitted on fallback.

- **Note** — `src/model_shelf/import_model.py:354–365`: The `files` list in the manifest uses `f.name` (basename only), not relative paths. If a safetensors/MLX directory ever contains nested subdirectories, files with the same basename at different depths would collide in the list. Current model repos have flat structures, so this is theoretical.

- **Note** — No test covers the cross-filesystem hardlink fallback path (hard to test without mocking `st_dev` or using loopback mounts). The logic is correct by inspection.

- **Note** — No test covers the `_save_manifest` exception-unlink path. The logic is simple and correct by inspection, but an edge-case test using a read-only directory would improve coverage.

---

### Blocker

None.

---