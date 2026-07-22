# Dedup Command — Phase 4 Implementation Result

## Summary

Implemented Phase 4: `dedup` command. All 19 tests pass, zero regressions across the full 138-test suite.

## Changed Files

| File | Action | Description |
|------|--------|-------------|
| `src/model_shelf/dedup.py` | **CREATED** | New module: `DedupGroup`, `DedupResult`, `find_duplicates()`, `execute_dedup()` |
| `tests/test_dedup.py` | **CREATED** | 19 tests across 3 tiers (pure logic, filesystem, CLI) |
| `src/model_shelf/cli.py` | **MODIFIED** | Added `cmd_dedup()`, `_print_dedup_report()`, `p_dedup` subparser, dispatch |
| `src/model_shelf/__init__.py` | **MODIFIED** | Exports `DedupGroup`, `DedupResult`, `execute_dedup`, `find_duplicates` |

## Validation

- **pytest tests/test_dedup.py -v** → **19 passed** in 0.25s
- **pytest tests/ -v** → **138 passed** in 0.55s (zero regressions)
- **model-shelf dedup --help** → works, shows all 4 flags (`--include-ollama`, `--include-hf-cache`, `--execute`, `--json`)

## Safety Rules Implemented

1. ✅ **Default dry-run** — `--execute` required for any mutation
2. ✅ **st_dev check** — `_is_same_fs()` before `os.link()`, never hardlink across filesystems
3. ✅ **External blobs are destinations** — Ollama/HF cache paths are never unlinked; `_hardlink_replace()` uses tmp+replace which is atomic
4. ✅ **Shelf copy is canonical KEEP** — first shelf file in each group is the hardlink source
5. ✅ **Manifest hardlinks updated** — `_update_manifest_for_dedup()` updates `manifest["models"][repo_id]["hardlinks"]` after dedup

## Architecture

```
CLI (cli.py)
  └─ cmd_dedup(args, cfg) → find_duplicates(cfg, include_ollama, include_hf_cache)
       ├─ Dry-run (default): print report / JSON, return 0
       └─ --execute: execute_dedup(cfg, result) → print report / JSON, return 0
```

- **dedup.py** reuses `_sha256_file` from `import_model.py` and manifest I/O from `manifest.py`
- Walks `shelf_root/{gguf,mlx,safetensors}/` plus optional `~/.ollama/models/blobs/` and `~/.cache/huggingface/hub/`
- Groups by SHA256, filters to groups with ≥2 entries
- `execute_dedup` uses atomic `tmp + os.replace` for safe hardlink creation

## Open Risks

- **Cross-module import**: `dedup.py` imports `_sha256_file` from `import_model.py` (private function). Acceptable since both are in the same package, but if `_sha256_file` is renamed, dedup breaks.
- **Path.home() in tests**: The Ollama/HF cache paths are hardcoded to `Path.home()`. The existing Tier 2 tests for ollama/hf-cache inclusion verify the wiring but don't actually test with real `.ollama`/`.cache` dirs — they test that the include flag is wired correctly and that `find_duplicates` with `include_ollama=True` doesn't crash when the real directory is absent/missing.
- **Large file performance**: `find_duplicates` hashes every file in the shelf in one pass. For shelves with many GB of files, this could be slow (but correct). A future optimization could add an optional size threshold.

## Test Coverage (19 tests)

- **Tier 1 (6)**: empty shelf, two identical ggufs, different content ignored, same content different names, group dataclass, result dataclass
- **Tier 2 (10)**: hardlinks same-fs, dry-run no changes, canonical keep, cross-fs skip, ollama include, hf-cache include, ollama blob not unlinked, hf blob not unlinked, manifest hardlinks field, three-way duplicate
- **Tier 3 (3)**: CLI subcommand registered, CLI JSON output, CLI --execute flag