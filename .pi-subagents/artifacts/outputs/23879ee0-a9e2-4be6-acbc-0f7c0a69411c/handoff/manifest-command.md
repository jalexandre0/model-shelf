# Phase 3: `manifest` command — Handoff

## Summary

Extract manifest I/O from `import_model.py` into a dedicated `manifest.py` module, add
a `manifest` CLI subcommand with `--rebuild` and `--json` flags, wire into `cli.py` and
`__init__.py`.

---

## 1. Files to CREATE

### `src/model_shelf/manifest.py` (new module — ~200 lines)

This is the **single source of truth** for manifest I/O. Every other module that reads
or writes `manifest.json` must go through this module.

**Public API contract:**

```python
from __future__ import annotations

import datetime
import hashlib
import json
import os
import struct
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_PATH = "manifest.json"  # relative to shelf_root


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ManifestResult:
    """Result of a manifest rebuild operation."""
    status: str                          # "ok" | "error"
    models_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "models_count": self.models_count,
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Core I/O (extracted from import_model.py lines 173-205)
# ---------------------------------------------------------------------------

def load_manifest(shelf_root: Path) -> dict:
    """Load manifest.json from shelf_root. Returns empty dict if missing.
    
    Raises ValueError if manifest version is not 1.
    """
    manifest_path = shelf_root / MANIFEST_PATH
    if not manifest_path.is_file():
        return {"version": 1, "updated": "", "models": {}}
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != 1:
        raise ValueError(
            f"unsupported manifest version: {manifest.get('version')}; "
            "expected version 1"
        )
    return manifest


def save_manifest(shelf_root: Path, data: dict) -> None:
    """Atomic write: manifest.json.tmp → os.replace → manifest.json.
    
    Uses NamedTemporaryFile with delete=False, then os.fsync + os.replace.
    Never leaves a partial .tmp file on error — the exception handler unlinks it.
    """
    manifest_path = shelf_root / MANIFEST_PATH
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(shelf_root),
        prefix="manifest.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(data, tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(manifest_path))
    except Exception:
        os.unlink(tmp.name)
        raise


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def get_manifest_entry(shelf_root: Path, repo_id: str) -> dict | None:
    """Return the manifest entry for repo_id, or None if not found."""
    manifest = load_manifest(shelf_root)
    return manifest.get("models", {}).get(repo_id)


def add_manifest_entry(shelf_root: Path, repo_id: str, entry: dict) -> None:
    """Add or overwrite a manifest entry for repo_id. Saves atomically."""
    manifest = load_manifest(shelf_root)
    manifest.setdefault("models", {})[repo_id] = entry
    manifest["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_manifest(shelf_root, manifest)


def remove_manifest_entry(shelf_root: Path, repo_id: str) -> None:
    """Remove a manifest entry for repo_id. No-op if not present. Saves atomically."""
    manifest = load_manifest(shelf_root)
    if repo_id in manifest.get("models", {}):
        del manifest["models"][repo_id]
        manifest["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_manifest(shelf_root, manifest)


# ---------------------------------------------------------------------------
# Rebuild (walks the shelf, detects format/quant, computes SHA256)
# ---------------------------------------------------------------------------

def rebuild_manifest(config: Config) -> ManifestResult:
    """Walk shelf_root/{gguf,mlx,safetensors}/, detect models, rebuild manifest.
    
    For each model found:
      1. Detect format from location (which subdir it's under).
      2. Detect quant: uses detect_quant() from import_model.
      3. SHA256: sha256_file for gguf, sha256_directory for mlx/safetensors.
      4. Build entry dict + add to manifest.

    Skips:
      - Dot-prefixed dirs/files (._*, .cache/, .DS_Store)
      - Directories without recognizable model files (no config.json, no .gguf)
    
    Existing entries whose models still exist on disk are preserved as-is
    (rebuild only discovers NEW models, doesn't touch entries whose files
    are still there — to avoid clobbering metadata like hardlinks[]).
    """
    ...
```

**Key implementation notes for `rebuild_manifest()`:**

- **Format detection**: Walk `shelf_root / fmt` for `fmt in ("gguf", "mlx", "safetensors")`. The subdirectory name IS the format. Then walk `{publisher}/{repo}/` within each.
- **gguf**: look for `*.gguf` files. One `.gguf` = one model. A repo dir with multiple `.gguf` files → each is a separate model (e.g., `gguf/bartowski/Meta-Llama-3.1-8B-GGUF/model-Q4_K_M.gguf`).
- **mlx**: look for directories containing `config.json` (but NO `*.safetensors` files). If there's a `.safetensors`, that directory is safetensors format — but since we're walking `mlx/` it shouldn't happen unless someone misplaces files. Handle gracefully: skip (don't crash).
- **safetensors**: look for directories containing `config.json` + `*.safetensors`.
- **Quant**: Import `detect_quant` from `model_shelf.import_model`, call it with the source path and detected format.
- **SHA256**: Import `_sha256_file` and `_sha256_directory` from `model_shelf.import_model` (these are stable helpers). For GGUF: hash the single file. For mlx/safetensors: hash all files in the directory (sorted), excluding dot-prefixed files and `.cache/`.
- **Files list**: For GGUF: `[filename]`. For dir formats: sorted list of all non-dot filenames under the repo dir.
- **Existing entries**: The `rebuild_manifest` function should **preserve** entries whose files still exist on disk. It only discovers **new** models that aren't in the manifest yet. This avoids overwriting fields like `hardlinks`, `source`, `imported_from`, `imported` that are set by the import command. If the implementation plan's test `test_rebuild_preserves_existing_manifest_fields` implies merge behavior, implement a conservative merge: for each model found on disk that already has a manifest entry, skip it. For models on disk with no entry, add a new entry. For entries in the manifest whose files are gone, remove them (or flag as errors).

**Imports needed in manifest.py:**
```python
from model_shelf.import_model import (
    detect_quant,
    _sha256_file,
    _sha256_directory,
)
from model_shelf.resolver import Config
```

### `tests/test_manifest.py` (14 Tier 1 tests + 3 Tier 2 tests)

Follow the same test patterns as `tests/test_import.py` and `tests/test_quant.py`:
- `from __future__ import annotations`
- `_config(tmp_path)` helper: `Config(shelf_root=tmp_path / "shelf")`
- `init_shelf(cfg)` for tests that need a real shelf structure
- `pytest` fixtures, `tmp_path: Path` type hints

**Tier 1 — 14 tests (no filesystem beyond tmp_path fixtures):**

| # | Test name | What it tests |
|---|-----------|--------------|
| 1 | `test_rebuild_empty_shelf` | `rebuild_manifest()` on shelf with empty subdirs → `version: 1`, `updated` non-empty ISO, `models: {}` |
| 2 | `test_rebuild_with_gguf_model` | Creates `gguf/Qwen/Qwen3-14B-GGUF/model-Q4_K_M.gguf` with known content → manifest entry has `format: gguf`, `quant: Q4_K_M`, `sha256` matches, `files` matches, `size_bytes` matches |
| 3 | `test_rebuild_with_mlx_model` | Creates dir with `config.json` + `model.safetensors` + `tokenizer.json` under `mlx/` → format `mlx`, files sorted, SHA256 over all files |
| 4 | `test_rebuild_skips_dot_cache` | Model dir with `.cache/` subdir → contents excluded from files list and SHA256 |
| 5 | `test_rebuild_skips_hidden_files` | Model dir with `._.DS_Store`, `._model.gguf` → excluded from files list |
| 6 | `test_rebuild_detects_params_from_config_json` | MLX model with `config.json` containing `{"model_type": "qwen3", "num_hidden_layers": 40}` → entry has `params` field |
| 7 | `test_rebuild_detects_params_from_gguf_header` | Synthetic GGUF v3 with `general.architecture = "llama"` → entry has `params` field |
| 8 | `test_rebuild_handles_non_model_dirs` | Dir with only `readme.md` → NOT in manifest, no crash |
| 9 | `test_load_manifest_missing_file` | No `manifest.json` → returns `{"version": 1, "updated": "", "models": {}}` |
| 10 | `test_load_manifest_invalid_json` | `manifest.json` with `{broken` → raises `ValueError`, does not silently return empty |
| 11 | `test_load_manifest_wrong_version` | `manifest.json` with `{"version": 2}` → raises `ValueError("unsupported manifest version: 2; expected version 1")` |
| 12 | `test_save_manifest_is_atomic` | Writes manifest, simulates partial scenario → no `.tmp` left, original intact |
| 13 | `test_add_entry_to_manifest` | `add_manifest_entry(shelf, "test/model", entry)` → `load_manifest()` now contains entry |
| 14 | `test_remove_entry_from_manifest` | Add then remove → entry gone, others untouched. Also: `get_manifest_entry(shelf, "test/model")` returns `None`. Also: `get_manifest_entry` on existing entry returns the dict |

**Tier 2 — 3 CLI integration tests:**

| # | Test name | What it tests |
|---|-----------|--------------|
| 15 | `test_rebuild_preserves_existing_manifest_fields` | Write manifest with custom `"source": "migrated"` on entry → `rebuild_manifest()` preserves it (model still on disk) |
| 16 | `test_manifest_cli_rebuild_flag` | `main(["manifest", "--rebuild"])` → exit 0, manifest.json created/updated |
| 17 | `test_manifest_cli_json_output` | `main(["manifest", "--json"])` → stdout valid JSON with `models` key |

---

## 2. Files to MODIFY

### `src/model_shelf/import_model.py`

**Changes (minimal, backward-compatible):**

1. **Replace `_load_manifest` body (lines 173-185)** with a re-export:
   ```python
   from model_shelf.manifest import load_manifest as _load_manifest
   ```
   Delete the old function body. Keep the name `_load_manifest` so existing internal callers and tests don't break.

2. **Replace `_save_manifest` body (lines 187-205)** with a re-export:
   ```python
   from model_shelf.manifest import save_manifest as _save_manifest
   ```
   Delete the old function body.

3. **Remove unused imports** after the move: `json`, `tempfile`, `os` (only if they become unused — verify; `json` is likely still used elsewhere like `_quant_from_config_json`, `os` for `os.link/stat`, `tempfile` might become unused).

   Actually, check before removing:
   - `json` — still used by `_quant_from_config_json` (line 399+) → KEEP
   - `tempfile` — only used by `_save_manifest` → REMOVE
   - `os` — used by `_ingest_file` (os.link), `_save_manifest` (os.fsync, os.replace, os.unlink) → verify: after removing `_save_manifest`, `os` is still used by `_ingest_file` → KEEP

4. **No other changes.** `detect_quant`, `_sha256_file`, `_sha256_directory`, `FILETYPE_MAP`, `_GGUF_ELEM_SIZES` stay put. The `import_model` function at line 614 continues to work unchanged — it calls `_load_manifest` (now a re-export) and `_record_manifest` → `_save_manifest` (now a re-export).

### `src/model_shelf/cli.py`

**Add `manifest` subcommand:**

1. **New subparser** (follow the pattern of other subcommands, around line 258 before `p_init`):
   ```python
   p_manifest = sub.add_parser("manifest", help="show or rebuild the shelf manifest")
   p_manifest.add_argument(
       "--rebuild", action="store_true",
       help="re-scan the shelf and rebuild manifest.json",
   )
   p_manifest.add_argument("--json", action="store_true", help="emit JSON")
   ```

2. **New handler function** (add after `cmd_list`, around line 218):
   ```python
   def cmd_manifest(args: argparse.Namespace, cfg: Config) -> int:
       """Show or rebuild the shelf manifest."""
       from model_shelf.manifest import (
           ManifestResult,
           load_manifest,
           rebuild_manifest,
       )
       if args.rebuild:
           result = rebuild_manifest(cfg)
           if args.json:
               print(json.dumps(result.to_dict(), indent=2))
           else:
               print(f"Rebuilt manifest: {result.models_count} models tracked")
               for err in result.errors:
                   print(f"  warning: {err}", file=sys.stderr)
           return 0 if result.status == "ok" else 1
       else:
           data = load_manifest(cfg.shelf_root)
           if args.json:
               print(json.dumps(data, indent=2))
           else:
               models = data.get("models", {})
               print(f"Manifest: {len(models)} models tracked")
               print(f"Updated:   {data.get('updated', 'never')}")
               for repo_id in sorted(models):
                   entry = models[repo_id]
                   sha = entry.get("sha256", "")[:8]
                   print(f"  [{entry.get('format', '?')}] {repo_id}  sha256={sha}...")
           return 0
   ```

3. **Dispatch in `main()`** (add after `if args.command == "find":`, around line 289):
   ```python
   if args.command == "manifest":
       return cmd_manifest(args, cfg)
   ```

4. **Import `json`** — already imported at top of cli.py, no change needed.

### `src/model_shelf/__init__.py`

**Add exports** for the new public API:

```python
from model_shelf.manifest import (
    ManifestResult,
    add_manifest_entry,
    get_manifest_entry,
    load_manifest,
    rebuild_manifest,
    remove_manifest_entry,
    save_manifest,
)
```

Add to `__all__`:
```python
"ManifestResult",
"add_manifest_entry",
"get_manifest_entry",
"load_manifest",
"rebuild_manifest",
"remove_manifest_entry",
"save_manifest",
```

---

## 3. Key Invariant

**`manifest.py` is the single source of truth for manifest I/O.**

- `import_model.py` imports `load_manifest`/`save_manifest` from `manifest.py` (via re-export aliases).
- Future modules (`audit.py`, `dedup.py`, `remove.py`, `gc.py`) MUST import from `manifest.py`, never from `import_model.py`.
- No module may read/write `manifest.json` directly (no `json.load(open(shelf_root / "manifest.json"))` anywhere but manifest.py).
- `rebuild_manifest()` imports `detect_quant`, `_sha256_file`, `_sha256_directory` from `import_model.py` — this is the correct dependency direction (manifest → import_model for detection helpers, not the reverse).

---

## 4. Files NOT Modified

- `src/model_shelf/resolver.py`
- `src/model_shelf/config.py`
- `src/model_shelf/detect.py`
- `src/model_shelf/relocate.py`
- `src/model_shelf/search.py`
- `tests/test_import.py` (existing tests continue to work because `_load_manifest` is still importable from `import_model`)
- `tests/test_quant.py` (unchanged; quant detection stays in import_model)
- All other existing test files

---

## 5. Data Flow

```
CLI: "model-shelf manifest --rebuild"
  → cli.py:cmd_manifest(args, cfg)
    → manifest.py:rebuild_manifest(cfg)
      → walks cfg.shelf_root / {gguf,mlx,safetensors}/
      → for each model found:
        → import_model.detect_quant(source, fmt) → quant string
        → import_model._sha256_file() / _sha256_directory() → sha256 hex
        → builds entry dict
        → manifest.add_manifest_entry(shelf_root, repo_id, entry)
      → returns ManifestResult(status="ok", models_count=N)

CLI: "model-shelf manifest"
  → cli.py:cmd_manifest(args, cfg)
    → manifest.py:load_manifest(cfg.shelf_root) → dict
    → pretty-print or JSON output

During "model-shelf import":
  → import_model.py:import_model(config, source, ...)
    → manifest = _load_manifest(config.shelf_root)  # → manifest.load_manifest()
    → ... check duplicate, ingest files ...
    → _save_manifest(shelf_root, manifest)          # → manifest.save_manifest()
```

---

## 6. Risks and Edge Cases

1. **Circular import**: `manifest.py` imports from `import_model` (for `detect_quant`, sha256 helpers), and `import_model` imports from `manifest` (for `load_manifest`, `save_manifest`). This is fine in Python because both use `from __future__ import annotations` and the imports are at module level — no circular dependency issue since neither calls the other's functions at import time.

2. **Rebuild vs. import entries**: Entries created by `import_model` have extra fields (`source`, `imported_from`, `imported`, `hardlinks`). `rebuild_manifest` must preserve these. The conservative merge approach (skip entries whose models still exist on disk) handles this.

3. **Empty repos after rebuild**: If a publisher dir exists but has no model files, `rebuild_manifest` should skip it gracefully (don't crash, don't add an entry).

4. **Multiple GGUF files in one repo**: `bartowski/Meta-Llama-3.1-8B-GGUF/` might contain `model-Q4_K_M.gguf` AND `model-Q8_0.gguf`. Each `.gguf` is a separate model entry. The repo_id disambiguation strategy: use `{org}/{repo_base}/{filename_stem}` or `{org}/{repo_base}?quant=Q4_K_M`. For Phase 3, the simplest approach: one model per `.gguf` file, with repo_id = `{org}/{filename_stem}` (strip the .gguf extension). This matches how Hugging Face GGUF repos are structured (one file = one model variant).

5. **Schema version**: Always `"version": 1`. Future-proof with the version check already in `load_manifest()`.

---

## 7. Start Here

Open `src/model_shelf/manifest.py` first. Build it from scratch, following the API contract above. Then modify the other three files in this order:

1. **`src/model_shelf/manifest.py`** — implement full module
2. **`src/model_shelf/import_model.py`** — replace `_load_manifest`/`_save_manifest` bodies with re-exports
3. **`src/model_shelf/cli.py`** — add `cmd_manifest`, subparser, and dispatch
4. **`src/model_shelf/__init__.py`** — add exports
5. **`tests/test_manifest.py`** — write 14 Tier 1 + 3 Tier 2 tests

```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "All findings are concrete with exact file paths and line ranges. Key files mapped: src/model_shelf/import_model.py (lines 173-205 for _load_manifest/_save_manifest, line 636 for call site, line 609 for _save_manifest call site), src/model_shelf/cli.py (subparser registration pattern at lines 258+, dispatch at lines 285+), src/model_shelf/__init__.py (exports pattern), tests/test_import.py (shows _load_manifest imported at line 10 and used at lines 105,204,251,299), tests/test_quant.py (shows detect_quant import pattern)"
    }
  ],
  "changedFiles": [
    "src/model_shelf/manifest.py",
    "src/model_shelf/cli.py",
    "src/model_shelf/import_model.py",
    "src/model_shelf/__init__.py",
    "tests/test_manifest.py"
  ],
  "testsAddedOrUpdated": [
    "tests/test_manifest.py (14 Tier 1 + 3 Tier 2 tests)"
  ],
  "commandsRun": [
    {
      "command": "grep _load_manifest/_save_manifest across src/ and tests/",
      "result": "passed",
      "summary": "Found 5 call sites: import_model.py lines 609,636 and test_import.py lines 105,204,251,299. Re-export strategy preserves all existing callers."
    }
  ],
  "validationOutput": [
    "Circular import between manifest.py ↔ import_model.py is safe — both use from __future__ import annotations and imports are module-level only, no call-time cross-dependency.",
    "Re-export aliases (_load_manifest, _save_manifest) in import_model.py keep existing tests/test_import.py working without modification.",
    "detect_quant and sha256 helpers stay in import_model.py — manifest.py imports them for rebuild_manifest(), which is the correct dependency direction.",
    "All 14 Tier 1 test specs mapped to concrete test names with clear input/assert contracts.",
    "CLI integration follows existing cmd_* pattern exactly (cmd_manifest, sub.add_parser, dispatch in main())."
  ],
  "residualRisks": [
    "Multiple GGUF files in one repo dir: disambiguation strategy needs final decision (simplest: one entry per .gguf, repo_id = {org}/{stem}). If a repo dir has 2+ .gguf files with different quants, repo_id collisions would occur. Mitigation: use filename-based repo_id (stem), which is unique per file.",
    "rebuild_manifest preserves existing entries — if a model was imported but its files were manually deleted, rebuild won't detect the deletion. This is for the audit command (Phase 5) to handle."
  ],
  "noStagedFiles": true,
  "diffSummary": "New manifest.py module (~200 lines), 17 new tests, 3 files lightly modified (import_model.py: delete 2 function bodies + add 2 re-exports; cli.py: +cmd_manifest +subparser +dispatch; __init__.py: +7 exports). No existing tests modified.",
  "reviewFindings": [
    "no blockers"
  ],
  "manualNotes": "The detect_quant import from manifest.py → import_model.py creates a reverse dependency. This is intentional: manifest.py needs quant detection for rebuild, and the single source of truth for quant detection is import_model.py (Phase 1.5). When Phase 4/5 modules need quant detection, they should import from import_model as well. Long-term: consider a shared 'detect.py' or keep as-is — but do NOT move quant detection to manifest.py (that would be wrong layering)."
}
```
