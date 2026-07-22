# Migration Script — Implementation Result

## Summary

Implemented Phase 6: standalone migration script (`scripts/model-shelf-migrate`) and 12 tests (`tests/test_migrate.py`).

## Changed Files

1. **`scripts/model-shelf-migrate`** (NEW) — 340-line executable Python script (stdlib only, no `.py` extension)
2. **`tests/test_migrate.py`** (NEW) — 12 tests (7 Tier 1 + 4 Tier 2 + 1 Tier 3)

No `src/` files or existing tests were modified.

## Script Capabilities

| Feature | Status |
|---------|--------|
| Shebang `#!/usr/bin/env python3` | ✅ |
| stdlib only (no huggingface_hub, no model_shelf imports) | ✅ |
| `--dry-run` (default), `--execute`, `--json` flags | ✅ |
| Scan 7 locations (models, hf-cache, lmstudio, ollama-blobs, ollama-manifest, omlx, model-shelf) | ✅ |
| SHA256 files >10MB (model-like only) | ✅ |
| Detect format (gguf/mlx/safetensors) — standalone | ✅ |
| Infer org/repo from path — standalone | ✅ |
| Detect quant from filename — standalone | ✅ |
| Cross-reference duplicates by SHA256 | ✅ |
| Print formatted table with size, SHA256 prefix, [ORIGINAL]/[DUPLICATE] tags | ✅ |
| `--execute` mode: calls `model-shelf import <path> --execute --org X --repo Y` via subprocess | ✅ |
| Hardlink duplicates (atomic replace pattern adapted from `dedup.py`) | ✅ |
| Manifest rebuild via subprocess | ✅ |
| Reports: X unique, Y GB recovered | ✅ |

## Validation

- **pytest tests/test_migrate.py -v**: 12/12 passed
- **pytest tests/ -v**: 182/182 passed (zero regressions; baseline was 170)
- **scripts/model-shelf-migrate --help**: works, shows all flags
- **scripts/model-shelf-migrate (dry-run)**: scanned 37,435 files on real machine, started SHA256 computation (timed out after 30s due to I/O but no errors)

## Open Risks

1. **Long scan time**: SHA256 on TBs of model files is I/O-bound. The 10MB cutoff helps. Progress printing to stderr keeps user informed.
2. **Ollama blobs**: Script cross-references by SHA256 but does not import Ollama blobs directly — it imports the GGUF from another location and hardlinks the blob.
3. **LM Studio JSON metadata**: Filtered out by model-like detection (`.json` not in MODEL_EXTENSIONS).
4. **Cross-filesystem**: Atomic hardlink replace with `st_dev` check prevents cross-filesystem links.

## Recommended Next Steps

- Run full `--dry-run` to completion to get the complete migration report
- Review the table output before running `--execute`
- The script is ready for use