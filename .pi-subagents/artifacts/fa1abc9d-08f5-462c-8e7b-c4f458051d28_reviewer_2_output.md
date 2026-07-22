Good. Ollama scan is not affected. Now I have all the evidence needed for a comprehensive review.

---

## Review

### Q1: Does find_duplicates() correctly walk shelf + optional locations?

**Mostly correct, but one blocker bug in the HF cache scan.**

- **Shelf walk**: `find_duplicates()` iterates `SUPPORTED_FORMATS` (`gguf`, `mlx`, `safetensors`), calls `rglob("*")` on each, filters `.is_file()`, `._` prefix, `.cache` in parts, and OSError. This is correct — the `.cache` filter is appropriate here because shelf subtrees like `.cache/huggingface/` should be excluded. ✅

- **Ollama scan**: Uses `iterdir()` (flat, correct for Ollama's blob layout). Filters `.` prefix and OSError. No `.cache` filter issue because Ollama root is `~/.ollama/models/blobs/` (no `.cache` in path parts). ✅

- **HF cache scan**: `rglob("*")` under `~/.cache/huggingface/hub/`, but then filters with `".cache" in f.parts`. **This is a blocker bug.** Every file under the HF cache lives under `.cache/huggingface/hub/…`, so `".cache"` is always in `f.parts`. All HF cache blobs are unconditionally skipped, making `include_hf_cache=True` non-functional. The filter was copy-pasted from the shelf scan without considering that the HF cache root itself contains `.cache` as a path component.

### Q2: Does SHA256 hashing use the same algorithm as import_model.py?

✅ **Yes.** `dedup.py` line 36 imports `_sha256_file` directly from `import_model.py`:

```python
from model_shelf.import_model import _sha256_file  # noqa: PLC2701
```

Both modules use the identical function — `hashlib.sha256()`, 65536-byte chunks, lowercase hex digest. No divergence possible.

### Q3: Does execute_dedup() check st_dev before os.link()?

✅ **Yes.** In `execute_dedup()` (lines 259-267), `_is_same_fs(canonical, other)` is called before `_hardlink_replace()`. `_is_same_fs()` compares `p1.stat().st_dev == p2.stat().st_dev`, returning `False` on OSError. Cross-filesystem pairs are counted in `skipped_cross_fs` and never reach `os.link()`. Additionally, there's a same-inode guard (`st_ino` comparison) that skips already-hardlinked files and falls back to `skipped_cross_fs += 1` on OSError.

### Q4: Are Ollama blobs and HF cache blobs NEVER unlinked?

✅ **Effectively yes — content is preserved.** `_hardlink_replace()` uses `os.link()` + `os.replace()`. The `os.replace()` atomically swaps the directory entry, which unlinks the old inode at the target path (decrementing its link count). However, because the new hardlink points to the shelf canonical's inode and the content is SHA256-identical, no data is lost. The external tool (Ollama/HF) still sees a file at the expected path with identical content. The code comment (lines 149-155) correctly explains the safety rationale: content-addressed storage by SHA256 name means the external tool only cares about data integrity, which is preserved.

**Caveat**: Extended attributes, ACLs, and creation time from the original blob are lost when replaced. In practice this is safe for Ollama/HF, but worth documenting.

### Q5: Is shelf copy always the KEEP (canonical)?

✅ **Yes.** `execute_dedup()` line 247 selects the canonical as:
```python
canonical = next((f for f in group.files if _is_in_shelf(f, shelf_root)), None)
```
This picks the first shelf-resident file in insertion order. Since `find_duplicates()` appends shelf entries first (before ollama, then hf-cache), the canonical is always a shelf file. If no shelf file exists in a group, `skipped_external_only` is incremented and no hardlinks are created.

### Q6: Does dry-run default prevent any writes?

✅ **Yes.** In `cmd_dedup()` (cli.py line ~219): `--execute` is an `action="store_true"` flag (defaults `False`). Without `--execute`, `execute_dedup()` is never called. `find_duplicates()` only hashes files — it never writes. No mutation path exists without `--execute`.

### Q7: Does --execute actually create hardlinks and remove duplicates?

✅ **Yes.** Verified by `test_dedup_creates_hardlinks_same_fs` (st_ino match, st_nlink ≥ 2), `test_dedup_cli_execute_flag` (inode equality after CLI --execute), and `test_dedup_handles_three_way_duplicate` (3-way st_nlink ≥ 3). All 138 tests pass.

### Q8: Is manifest["models"][repo_id]["hardlinks"] updated correctly?

✅ **Yes**, with a note. `_update_manifest_for_dedup()` is called when `hardlinks_created > 0`. It:
1. Loads the manifest, finds the canonical's repo_id via `_path_to_repo_id()`
2. Adds all other group files to `entry["hardlinks"]`
3. Saves atomically via `save_manifest()`

**Note**: Only the canonical's manifest entry is updated. If a non-canonical shelf file in the same group has its own manifest entry, its `hardlinks` field is NOT updated. This is not a correctness bug (both still have the same SHA256 via hardlink), but `rebuild_manifest()` will later drop that stale `hardlinks` data if the entry is rewritten.

### Q9: Run pytest tests/ -v — zero regressions

✅ **138 passed, 0 failed** in 0.47s. Zero regressions.

---

## Findings Summary

| Severity | File:Line | Issue |
|----------|-----------|-------|
| **Blocker** | `src/model_shelf/dedup.py:234` | `".cache" in f.parts` filter unconditionally skips all HF cache blob files because `Path.home() / ".cache" / "huggingface" / "hub"` always contains `".cache"` as a path component. The `include_hf_cache` feature is dead code. Fix: remove the `.cache` filter from the HF cache scan branch, or use a relative-path check against `hf_cache`. |
| Note | `src/model_shelf/dedup.py:230-236` | The same `.cache` filter in the shelf scan (line 196) is correct — it protects against `.cache/` subtrees inside the shelf. The bug is only in the HF cache scan due to copy-paste. |
| Note | `tests/test_dedup.py:189-210` | `test_dedup_include_hf_cache_blobs` is too weak — it only verifies the code doesn't crash with `include_hf_cache=True`, not that HF cache blobs are actually found. The bug above went undetected because the test doesn't create files in the real `~/.cache/huggingface/hub/` path and assert they appear in results. |
| Note | `src/model_shelf/dedup.py:160-183` | `_update_manifest_for_dedup()` only updates the canonical's manifest entry. Non-canonical shelf models in the same group retain stale `hardlinks` fields. Low risk — content integrity is preserved and `rebuild_manifest` will eventually correct this. |
| Observe | `src/model_shelf/dedup.py:37` | `_sha256_file` is a private import from `import_model.py`. Both modules are in `model_shelf` package, so this is acceptable, but renaming `_sha256_file` would silently break dedup (caught only at test/import time). |

---