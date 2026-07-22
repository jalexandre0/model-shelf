---

## Review

### 1. Follows `.serena/memories/conventions.md`?

| Convention | Status | Evidence |
|---|---|---|
| `from __future__ import annotations` | ✅ | `import_model.py:12` |
| Type hints on all public functions | ✅ | All functions have annotated params + return types |
| Dataclasses for data containers with `to_dict()` | ✅ | `ImportResult` (line 26), `to_dict()` (line 38) |
| `pathlib.Path` everywhere | ✅ | No `os.path` usage |
| Separate module per command | ✅ | `import_model.py` is its own module |
| `cmd_*` returns exit codes (0=success) | ✅ | `cli.py:84` — returns `0 if result.status != "error" else 1` |
| `--json` bypasses pretty-print | ✅ | `cli.py:82-83` |
| SHA256 via `hashlib.sha256()` | ✅ | `import_model.py:91-98, 100-111` |
| Manifest atomic write (temp → fsync → replace) | ✅ | `import_model.py:124-143` |
| `import`: hardlink with `os.link()`, copy+warn otherwise | ✅ | `import_model.py:256-269` |
| `check_storage_available` guard before operations | ✅ | `cli.py:72` calls it before `import_model` |

### 2. Anti-patterns?

- **No unnecessary abstractions**: Only one class (`ImportResult` — a dataclass). No abstract base classes, no interfaces with single implementations.
- **No generic names**: All functions have descriptive, specific names (`_detect_format_from_path`, `_sha256_directory`, `_infer_org_repo_dir`, etc.).
- **No comments repeating code**: Checked all comment lines — none simply restate the adjacent code.

### 3. Functions < 40 lines?

All private helpers pass easily. However:

| Function | Lines | Status |
|---|---|---|
| `_detect_format_from_path` | 30 | ✅ |
| `_sha256_file` | 7 | ✅ |
| `_sha256_directory` | 10 | ✅ |
| `_load_manifest` | 6 | ✅ |
| `_save_manifest` | 20 | ✅ |
| `_infer_org_repo` | 22 | ✅ |
| `_infer_org_repo_gguf` | 19 | ✅ |
| `_infer_org_repo_dir` | 21 | ✅ |
| `_detect_quant_from_filename` | 20 | ✅ |
| `_ingest_file` | 13 | ✅ |
| **`import_model`** | **117** | ❌ **BLOCKER** |

### 4. Type hints complete?

All functions have complete type hints. One minor note: `_load_manifest` returns bare `dict` and `ImportResult.to_dict` returns bare `dict`, but with `from __future__ import annotations` this is the established project pattern (same as `ResolveResult.to_dict` in `resolver.py`).

### 5. Consistent with `resolver.py` + `cli.py` patterns?

| Pattern | `resolver.py` | `import_model.py` | Match? |
|---|---|---|---|
| Dataclass result with `status`, `checks`, `to_dict()` | `ResolveResult` | `ImportResult` | ✅ |
| `check_storage_available` guard | Called before operations | Called in `cmd_import` | ✅ |
| `SUPPORTED_FORMATS` reused | Defines the constant | Imports it | ✅ |
| `cmd_*` function signature: `(args, cfg) -> int` | `cmd_resolve` | `cmd_import` | ✅ |
| `_print_*_pretty` helper | `_print_result_pretty` | `_print_import_pretty` | ✅ |
| Subparser registration pattern | `add_parser(...)` + args | Identical pattern | ✅ |
| Error handling in `main()` | `except ValueError → 2` | Same dispatch path | ✅ |
| Module export in `__init__.py` | `resolve_model`, `ResolveResult` | `import_model`, `ImportResult` | ✅ |

---

### Findings

| Severity | File:Line | Issue | Fix |
|---|---|---|---|
| **blocker** | `import_model.py:275` | `import_model` is 117 lines — nearly **3×** the 40-line convention. The function has 9 numbered steps, many of which could be extracted: `_compute_sha256`, `_check_duplicate`, `_determine_dest_path`, `_ingest_files`, `_compute_total_size`, `_update_manifest_entry`. | Extract helper functions to bring under 40 lines. |
| **fix-now** | `cli.py:248-258` | Missing `--dry-run` flag. Convention states: "All destructive operations require `--dry-run` default or explicit confirmation." Import writes files + modifies manifest; it's destructive. | Add `--dry-run` argument; when set, compute everything but skip the actual file ingestion and manifest write. |
| **fix-now** | `import_model.py:203-221` | `_infer_org_repo_dir` missing the `"-" in parent` heuristic at the **parent** level. `_infer_org_repo_gguf` (line 194) includes `or "-" in parent` for the parent directory, but `_infer_org_repo_dir` (line 211) only checks `_KNOWN_PUBLISHERS` at the parent level and pushes the `-` heuristic to the grandparent. This means `some-publisher/my-model/` → org="local" instead of org="some-publisher". | Add `or "-" in source.parent.name.lower()` at line 211, matching the GGUF logic. |
| **optional** | `tests/test_import.py` | No test for **safetensors directory import via auto-detection** (config.json + .safetensors, no format override). `test_import_mlx_directory` creates `.safetensors` files but passes `format="mlx"` — the auto-detect path for safetensors is never exercised end-to-end. | Add a test that creates a dir with config.json + .safetensors files and imports without `--format` override. |
| **optional** | `tests/test_import.py` | No test for `_detect_quant_from_filename` with `IQ` patterns (`IQ3_XXS`, `IQ4_XS`) or `F32`/`FP32`/`FP16` variants. | Add parameterized tests for the IQ and FP patterns. |
| **optional** | `import_model.py:140` | `_save_manifest` temp file cleanup: if `json.dump()` raises, `tmp` is still open when `os.unlink()` is called. On macOS this works but on some platforms an open file descriptor may prevent unlink. | Use a `try/finally` that always closes and cleans up the temp file. |

---