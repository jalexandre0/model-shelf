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

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "Returned concrete findings: 4 files changed/created with exact paths and descriptions; 19 tests added (all passing); 138-test full suite zero regressions; CLI --help verified; all 5 safety rules implemented and verified by tests"
    }
  ],
  "changedFiles": [
    "src/model_shelf/dedup.py",
    "tests/test_dedup.py",
    "src/model_shelf/cli.py",
    "src/model_shelf/__init__.py"
  ],
  "testsAddedOrUpdated": [
    "tests/test_dedup.py"
  ],
  "commandsRun": [
    {
      "command": "pytest tests/test_dedup.py -v",
      "result": "passed",
      "summary": "19 passed in 0.25s"
    },
    {
      "command": "pytest tests/ -v",
      "result": "passed",
      "summary": "138 passed in 0.55s (zero regressions)"
    },
    {
      "command": "model-shelf dedup --help",
      "result": "passed",
      "summary": "Help output shows all 4 flags: --include-ollama, --include-hf-cache, --execute, --json"
    }
  ],
  "validationOutput": [
    "find_duplicates correctly walks shelf_root/{gguf,mlx,safetensors}/ for model files",
    "SHA256 grouping works (same content → same group, different content → different groups)",
    "execute_dedup creates hardlinks with matching st_ino (verified via stat)",
    "Atomic hardlink replacement via tmp + os.replace (no window where target is missing)",
    "st_dev check prevents cross-filesystem hardlinks",
    "External-only groups counted in skipped_external_only",
    "Manifest hardlinks field updated atomically via save_manifest",
    "CLI dry-run default: no mutation without --execute",
    "CLI --json emits valid JSON with groups, total_duplicate_bytes, potential_savings_bytes"
  ],
  "residualRisks": [
    "Cross-module import of _sha256_file from import_model.py: if renamed, dedup.py breaks",
    "Ollama/HF cache path detection uses Path.home() — won't work if those caches are relocated",
    "No file size threshold — hashes all files regardless of size (correct but potentially slow for very large shelves)"
  ],
  "noStagedFiles": true,
  "diffSummary": "Created src/model_shelf/dedup.py (271 lines) with DedupGroup, DedupResult, find_duplicates, execute_dedup. Created tests/test_dedup.py (344 lines) with 19 tests. Modified cli.py: added cmd_dedup, _print_dedup_report, p_dedup subparser, dispatch. Modified __init__.py: added dedup exports.",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": ""
}
```