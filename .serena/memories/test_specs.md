# Test Specifications — All Phases

Discipline: fail-open is crime, honest fixtures (wire-format → real parser → real entry point → assert),
three tiers, one test owner per contract, self-describing names, no t.Skip.

---

## Phase 1.5: `detect_quant` upgrade

### Tier 1 — Pure logic (stdlib only, no filesystem)

**test_gguf_filetype_map_is_exhaustive**
- Input: iterate all known GGUF file_type values (0-24)
- Assert: every int maps to a string via `FILETYPE_MAP`, no gaps in covered range

**test_detect_quant_from_filename_q4_k_m**
- Input: `Path("Qwen3-14B-Q4_K_M.gguf")`
- Call: `_detect_quant_from_filename(path)`
- Assert: returns `"Q4_K_M"` exactly

**test_detect_quant_from_filename_iq3_xxs**
- Input: `Path("model-IQ3_XXS.gguf")`
- Assert: `"IQ3_XXS"` (case normalization to uppercase)

**test_detect_quant_from_filename_f16**
- Input: `Path("llama-f16.gguf")`
- Assert: `"F16"`

**test_detect_quant_from_filename_no_match**
- Input: `Path("model.gguf")` (no quant in name)
- Assert: returns `None`

**test_detect_quant_config_mlx_bits_4**
- Input: write `{"quantization": {"group_size": 64, "bits": 4}}` to `tmp_path/config.json`
- Call: `_quant_from_config_json(tmp_path)`
- Assert: `"Q4"`

**test_detect_quant_config_mlx_no_quantization**
- Input: write `{"model_type": "llama"}` to `tmp_path/config.json` (no quantization key)
- Assert: returns `None`

**test_detect_quant_config_gptq**
- Input: write `{"quantization_config": {"quant_method": "gptq", "bits": 4}}` to `tmp_path/config.json`
- Assert: `"GPTQ-4bit"`

**test_detect_quant_config_awq**
- Input: write `{"quantization_config": {"quant_method": "awq", "bits": 4}}`
- Assert: `"AWQ-4bit"`

**test_detect_quant_config_torch_dtype_f16**
- Input: write `{"torch_dtype": "float16"}` to `tmp_path/config.json`
- Assert: `"F16"`

**test_detect_quant_config_torch_dtype_bf16**
- Input: write `{"torch_dtype": "bfloat16"}`
- Assert: `"BF16"`

**test_detect_quant_config_torch_dtype_f32**
- Input: write `{"torch_dtype": "float32"}`
- Assert: `"F32"`

**test_detect_quant_config_missing_file**
- Input: `tmp_path/subdir/` (no config.json)
- Assert: returns `None` (no crash)

**test_detect_quant_config_invalid_json**
- Input: write `not json` to `tmp_path/config.json`
- Assert: returns `None` (no crash, no exception)

### Tier 2 — Real .gguf bytes (synthetic GGUF header)

**test_gguf_header_extracts_q4_k_m**
- Input: synthetic GGUF v3 header with `general.file_type = uint32(15)` at correct offset
- Call: `_quant_from_gguf_header(path)`
- Assert: `"Q4_K_M"`

**test_gguf_header_extracts_f16**
- Input: synthetic GGUF v3 header with `general.file_type = uint32(1)`
- Assert: `"F16"`

**test_gguf_header_extracts_iq3_xxs**
- Input: synthetic GGUF v3 header with `general.file_type = uint32(21)`
- Assert: `"IQ3_XXS"`

**test_gguf_header_not_a_gguf**
- Input: file with `b"NOTA"` as first 4 bytes
- Assert: returns `None` (no crash)

**test_gguf_header_missing_file_type**
- Input: synthetic GGUF v3 header with no `general.file_type` key (only `general.name`)
- Assert: returns `None`

### Tier 3 — Real models on filesystem (regression smoke)

**test_gguf_header_real_model_nomic**
- Input: `~/.lmstudio/.../nomic-embed-text-v1.5.Q4_K_M.gguf` (80 MB real)
- Assert: `_quant_from_gguf_header()` returns `"Q4_K_M"` (matches filename)
- NON-DESTRUCTIVE: read-only, no writes

---

## Phase 3: `manifest` command

### Tier 1 — Pure logic

**test_rebuild_empty_shelf**
- Input: `tmp_path/shelf/` with gguf/mlx/safetensors subdirs, all empty
- Call: `rebuild_manifest(Config(shelf_root=tmp_path/shelf))`
- Assert: manifest has `version: 1`, `updated` is non-empty ISO timestamp, `models: {}`

**test_rebuild_with_gguf_model**
- Fixture: create `tmp_path/shelf/gguf/Qwen/Qwen3-14B-GGUF/Qwen3-14B-Q4_K_M.gguf` with known content
- Call: `rebuild_manifest(config)`
- Assert: `manifest["models"]["Qwen/Qwen3-14B-GGUF"]["format"] == "gguf"`
- Assert: `["quant"] == "Q4_K_M"` (auto-detected from filename)
- Assert: `["sha256"]` matches `hashlib.sha256(known_content).hexdigest()`
- Assert: `["files"] == ["Qwen3-14B-Q4_K_M.gguf"]`
- Assert: `["size_bytes"] == len(known_content)`

**test_rebuild_with_mlx_model**
- Fixture: create dir with `config.json` + `model.safetensors` + `tokenizer.json`
- Assert: format = "mlx", files list sorted, SHA256 over all files

**test_rebuild_skips_dot_cache**
- Fixture: model dir with `.cache/huggingface/` subdir
- Assert: `.cache/` contents not in manifest files list, not hashed

**test_rebuild_skips_hidden_files**
- Fixture: model dir with `._.DS_Store` and `._model.gguf` (macOS resource forks)
- Assert: these files excluded from files list and SHA256

**test_rebuild_detects_params_from_config_json**
- Fixture: MLX model with `config.json` containing `{"model_type": "qwen3", "num_hidden_layers": 40, ...}`
- Assert: entry has `params` field extracted (architecture or parameter count)

**test_rebuild_detects_params_from_gguf_header**
- Fixture: synthetic GGUF v3 with `general.architecture` = "llama", `general.parameter_count` = uint32(8000000000)
- Assert: entry has `params` = "8B" or similar

**test_rebuild_handles_non_model_dirs**
- Fixture: dir with `readme.md` only (no config.json, no .gguf)
- Assert: NOT added to manifest, no crash

**test_load_manifest_missing_file**
- Input: `tmp_path/shelf/` without `manifest.json`
- Call: `load_manifest(shelf_root)`
- Assert: returns `{"version": 1, "updated": "", "models": {}}`

**test_load_manifest_invalid_json**
- Input: `manifest.json` with `{broken`
- Assert: raises `ValueError` with clear message, does NOT silently return empty dict

**test_load_manifest_wrong_version**
- Input: `manifest.json` with `{"version": 2, ...}`
- Assert: raises `ValueError("unsupported manifest version: 2; expected version 1")`

**test_save_manifest_is_atomic**
- Fixture: write manifest, simulate crash (kill after write, before rename)
- Assert: NO `manifest.json.tmp` left behind
- Assert: original `manifest.json` unchanged OR fully written (never half-written)

**test_add_entry_to_manifest**
- Call: `add_manifest_entry(shelf_root, "test/model", entry_dict)`
- Assert: `load_manifest()` now contains `"test/model"` with correct fields

**test_remove_entry_from_manifest**
- Setup: add entry, then remove
- Assert: `load_manifest()` no longer has the entry
- Assert: other entries untouched (exact match, not partial key collision)

**test_get_manifest_entry_existing**
- Setup: add entry
- Assert: `get_manifest_entry(shelf_root, "test/model")` returns the entry dict
- Assert: `get_manifest_entry(shelf_root, "nonexistent/repo")` returns `None`

### Tier 2 — tmp_path integration

**test_rebuild_preserves_existing_manifest_fields**
- Setup: write manifest with custom `"source": "migrated"` field on an entry
- Call: `rebuild_manifest(config)` — should merge, not clobber
- Assert: custom field preserved OR (if rebuild is destructive) documented as such

**test_manifest_cli_rebuild_flag**
- Call: `main(["manifest", "--rebuild"])`
- Assert: exit code 0, manifest.json created/updated

**test_manifest_cli_json_output**
- Call: `main(["manifest", "--json"])`
- Assert: stdout is valid JSON with `models` key

---

## Phase 4: `dedup` command

### Tier 1 — Pure logic

**test_find_duplicates_empty_shelf**
- Input: shelf with no files
- Assert: `find_duplicates()` returns empty groups, `total_duplicate_bytes == 0`

**test_find_duplicates_two_identical_guffs**
- Fixture: two .gguf files with same content in different publisher dirs
- Assert: 1 duplicate group, `potential_savings_bytes == file_size`

**test_find_duplicates_ignores_different_content**
- Fixture: two .gguf files with different content
- Assert: 0 duplicate groups

**test_find_duplicates_same_content_different_names**
- Fixture: `model.gguf` and `model-copy.gguf` with identical bytes
- Assert: detected as duplicates (SHA256 ignores filename)

**test_dedup_group_dataclass**
- Input: `DedupGroup(sha256="abc", files=[Path("/a"), Path("/b")], size_bytes=100)`
- Assert: `duplicate_bytes == 100` (one copy is waste)

**test_dedup_result_dataclass**
- Input: `DedupResult(groups=[group1, group2], total_duplicate_bytes=500)`
- Assert: `potential_savings_bytes` > 0

### Tier 2 — tmp_path filesystem

**test_dedup_creates_hardlinks_same_fs**
- Fixture: two identical files on same tmp_path filesystem
- Call: `execute_dedup()` (not dry-run)
- Assert: `os.stat(file1).st_ino == os.stat(file2).st_ino` (same inode)
- Assert: `os.stat(file1).st_nlink == 2` (hardlink count)
- Assert: file1 still exists with original content

**test_dedup_dry_run_makes_no_changes**
- Fixture: two identical files
- Call: `dedup --dry-run`
- Assert: files unchanged, no hardlinks created, `st_nlink` stays 1

**test_dedup_keeps_canonical_in_shelf**
- Fixture: one file in shelf, one in `/tmp/random/`
- Assert: shelf copy is the KEEP, external copy gets hardlinked from shelf

**test_dedup_skips_across_filesystems**
- Fixture: mock `st_dev` difference between two files (via monkeypatch)
- Assert: `execute_dedup()` does NOT attempt `os.link()`, logs warning
- Assert: returns `skipped_cross_fs` or similar status

**test_dedup_include_ollama_blobs**
- Fixture: identical file in shelf and in `~/.ollama/models/blobs/sha256-xxx`
- Call: `find_duplicates(include_ollama=True)`
- Assert: detected as duplicate group

**test_dedup_include_hf_cache_blobs**
- Fixture: identical file in shelf and in `~/.cache/huggingface/hub/.../blobs/xxx`
- Call: `find_duplicates(include_hf_cache=True)`
- Assert: detected as duplicate group

**test_dedup_ollama_blob_not_unlinked**
- Fixture: dedup with Ollama blob
- Call: `execute_dedup()`
- Assert: Ollama blob path still exists (hardlink destination, not source)
- Assert: `st_nlink` increased on blob file

**test_dedup_hf_cache_blob_not_unlinked**
- Fixture: dedup with HF cache blob
- Assert: HF blob path still exists (HF might re-download if we delete)

**test_dedup_preserves_manifest_hardlinks_field**
- Setup: manifest with entry `"hardlinks": []`
- Call: `execute_dedup()`
- Assert: manifest entry updated with `"hardlinks": ["/path/to/linked/file"]`

**test_dedup_handles_three_way_duplicate**
- Fixture: three identical files
- Assert: 1 group with 3 entries, `duplicate_bytes == 2 * file_size`
- Assert: after dedup, all 3 share same inode and st_nlink=3

### Tier 3 — CLI integration

**test_dedup_cli_dry_run_default**
- Call: `main(["dedup"])`
- Assert: exit code 0, dry-run report printed, no files modified

**test_dedup_cli_json_output**
- Call: `main(["dedup", "--json"])`
- Assert: stdout is valid JSON with `groups`, `total_duplicate_bytes`, `potential_savings_bytes`

**test_dedup_cli_execute_flag**
- Call: `main(["dedup", "--execute"])`
- Assert: hardlinks actually created

---

## Phase 5a: `audit` command

### Tier 1 — Pure logic

**test_audit_dataclass_defaults**
- Input: `AuditResult()`
- Assert: `missing == []`, `untracked == []`, `stale == []`

**test_audit_clean_shelf**
- Fixture: manifest with 1 entry, corresponding file exists with matching SHA256
- Assert: `run_audit()` returns clean result (all lists empty), exit 0

**test_audit_missing_entry_directory_gone**
- Fixture: manifest has entry for `ghost/model`, but `shelf/gguf/ghost/model/` doesn't exist
- Assert: `missing` list contains `"ghost/model"`
- Assert: exit code 1

**test_audit_missing_file_in_directory**
- Fixture: manifest entry has `files: ["model.gguf", "tokenizer.json"]` but `tokenizer.json` is gone
- Assert: `stale` list contains the entry (or `missing` for partial files)

**test_audit_stale_sha256**
- Fixture: manifest entry has `sha256: "aaaa..."` but file content changed
- Assert: `stale` list contains the entry with SHA256 mismatch detail

**test_audit_untracked_file**
- Fixture: extra `mystery.gguf` in shelf not referenced by any manifest entry
- Assert: `untracked` list contains path to `mystery.gguf`

**test_audit_multiple_issues_in_one_run**
- Fixture: 1 missing + 1 stale + 2 untracked
- Assert: report shows all 4 issues, `len(missing) == 1`, `len(stale) == 1`, `len(untracked) == 2`

### Tier 2 — CLI integration

**test_audit_cli_json_output**
- Call: `main(["audit", "--json"])`
- Assert: stdout JSON has `missing`, `stale`, `untracked` arrays

**test_audit_cli_exit_code_clean**
- Fixture: perfectly clean shelf
- Call: `main(["audit"])`
- Assert: exit code 0

**test_audit_cli_exit_code_dirty**
- Fixture: shelf with untracked file
- Call: `main(["audit"])`
- Assert: exit code 1

---

## Phase 5b: `remove` command

### Tier 1 — Pure logic (dataclass)

**test_remove_dataclass_defaults**
- Input: `RemoveResult()`
- Assert: `removed == []`, `hardlinks_warn == []`

### Tier 2 — tmp_path filesystem

**test_remove_deletes_files_and_directory**
- Fixture: shelf with imported model (files + manifest entry)
- Call: `remove_model(config, "org/repo", dry_run=False)`
- Assert: model directory no longer exists
- Assert: manifest entry removed
- Assert: parent empty dirs cleaned up (e.g., `gguf/org/` removed if now empty)

**test_remove_dry_run_preserves_everything**
- Fixture: shelf with imported model
- Call: `remove_model(config, "org/repo", dry_run=True)`
- Assert: ALL files still exist
- Assert: manifest entry still present
- Assert: output message says "Would remove"

**test_remove_warns_on_hardlinks**
- Fixture: model file with `st_nlink > 1` (hardlinked elsewhere)
- Call: `remove_model(config, "org/repo", dry_run=False)`
- Assert: file unlinked (st_nlink decremented)
- Assert: `hardlinks_warn` contains the other path(s) sharing the inode
- Assert: warning printed to stderr

**test_remove_nonexistent_model**
- Call: `remove_model(config, "nonexistent/model")`
- Assert: raises `ValueError` or returns status `"not_found"` (not silent success)

**test_remove_only_target_model**
- Fixture: 2 models in same publisher dir (e.g., `Qwen/Qwen3-14B` and `Qwen/Qwen3-8B`)
- Call: remove only `Qwen3-8B`
- Assert: `Qwen3-14B` untouched, `Qwen/` dir still exists (shared parent)

### Tier 3 — CLI integration

**test_remove_cli_defaults_to_dry_run**
- Call: `main(["remove", "org/repo"])` (no --execute)
- Assert: dry-run message, files preserved

**test_remove_cli_execute_flag**
- Call: `main(["remove", "org/repo", "--execute"])`
- Assert: model actually deleted

---

## Phase 5c: `gc` command

### Tier 1 — Pure logic

**test_gc_dataclass_defaults**
- Input: `GCResult()`
- Assert: all lists empty, `total_reclaimable_bytes == 0`

**test_gc_finds_orphaned_gguf**
- Fixture: `.gguf` file sitting in shelf root (no parent publisher/repo dir)
- Assert: flagged as `orphaned_files`

**test_gc_finds_empty_directories**
- Fixture: `gguf/SomeOrg/EmptyRepo/` with no files
- Assert: flagged as `empty_dirs`

**test_gc_skips_non_empty_dirs**
- Fixture: `gguf/Qwen/Qwen3-14B/` with actual model files
- Assert: NOT flagged

**test_gc_skips_dot_dirs**
- Fixture: `.cache/` subdir, `.hidden_dir/`
- Assert: NOT flagged as empty or orphaned

**test_gc_calculates_reclaimable_bytes**
- Fixture: 3 orphaned files (1GB, 2GB, 500MB)
- Assert: `total_reclaimable_bytes == 3.5GB`

**test_gc_finds_incomplete_mlx_download**
- Fixture: dir with `config.json` but no `.safetensors` files (partial download)
- Assert: flagged as `incomplete_downloads`

**test_gc_finds_incomplete_gguf_download**
- Fixture: dir with partial `.gguf` file (size 0 or missing)
- Assert: flagged as incomplete

### Tier 2 — CLI integration

**test_gc_cli_defaults_to_dry_run**
- Call: `main(["gc"])` (no --execute)
- Assert: dry-run report, nothing deleted

**test_gc_cli_execute_removes_orphans**
- Call: `main(["gc", "--execute"])`
- Assert: orphaned files gone, empty dirs gone

**test_gc_cli_json_output**
- Call: `main(["gc", "--json"])`
- Assert: valid JSON with `incomplete_downloads`, `orphaned_files`, `empty_dirs`, `total_reclaimable_bytes`

---

## Phase 6: Migration script (standalone)

### Tier 1 — Pure logic

**test_infer_org_from_path_mlx_community**
- Input: `Path("/tmp/mlx-community/Qwen3-14B-4bit/model.safetensors")`
- Call: `_infer_org_repo(path)`
- Assert: org=`"mlx-community"`, repo=`"Qwen3-14B-4bit"`

**test_infer_org_from_path_bartowski**
- Input: `Path("/models/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/model-Q4_K_M.gguf")`
- Assert: org=`"bartowski"`, repo=`"Meta-Llama-3.1-8B-Instruct-GGUF"`

**test_infer_quant_from_gguf_filename**
- Input: `Path("Qwythos-9B-v2-MTP-Q4_K_M.gguf")`
- Assert: quant=`"Q4_K_M"`, model=`"Qwythos-9B-v2-MTP"`

**test_infer_format_from_path_gguf**
- Input: `Path("model.gguf")`
- Assert: `"gguf"`

**test_infer_format_from_path_mlx_dir**
- Input: tmp_path dir with `config.json` but no `.safetensors`
- Assert: `"mlx"`

**test_infer_format_from_path_safetensors_dir**
- Input: tmp_path dir with `config.json` + `model.safetensors`
- Assert: `"safetensors"`

### Tier 2 — tmp_path migration simulation

**test_migration_scan_finds_all_locations**
- Fixture: create mock structure with 3 of 7 known locations populated
- Assert: scan discovers files from all 3

**test_migration_detects_duplicates_across_locations**
- Fixture: same SHA256 in `models/` and `hf-cache/` and `ollama-blobs/`
- Assert: 1 duplicate group with 3 entries

**test_migration_interactive_table_generation**
- Fixture: 2 unique models + 1 duplicate
- Assert: output contains size, SHA256 prefix, "DUPLICATE" tag on the right rows

**test_migration_ollama_blob_cross_reference**
- Fixture: GGUF in shelf has same SHA256 as `ollama/models/blobs/sha256-xxx`
- Assert: cross-reference detected, `--include-ollama` shows savings

### Tier 3 — Real filesystem (regression smoke, read-only)

**test_migration_real_scan_is_read_only**
- Call: scan all 7 locations on real machine
- Assert: NO files created, modified, or deleted anywhere
- Assert: report prints correctly

---

## Cross-cutting invariants (apply to ALL test files)

### What every test file MUST have
- `from __future__ import annotations`
- Type hints on every test function parameter (`tmp_path: Path`)
- `_config(tmp_path)` helper creating `Config(shelf_root=tmp_path/"shelf")`
- `init_shelf(cfg)` call before any test that writes to shelf
- Zero `t.Skip`, zero `xfail`, zero conditional execution
- Exact asserts: `==` not `>=`, specific strings not substring matches (unless testing partial output)

### What NO test file may have
- `t.Skip("requires X")` — fail-open crime
- `if os.getenv(...):` guards — fail-open crime
- Direct internal struct construction (bypassing parse/validate boundary)
- `len(result) > 0` — weak assert, hides wrong bytes
- Test cleanup that swallows errors (use `tmp_path` auto-cleanup instead)
- Duplicate assert of same contract point in multiple files
- Abstract test names (`test-1`, `test-A`, `test_step_3`)

### Naming convention
- `test_<what_happens>_<under_what_condition>` — self-describing
- ✅ `test_remove_warns_on_hardlinks`
- ✅ `test_dedup_dry_run_makes_no_changes`
- ✅ `test_gguf_header_not_a_gguf_returns_none`
- ❌ `test_remove_1`, `test_dedup_A`, `T1_gc_empty`
