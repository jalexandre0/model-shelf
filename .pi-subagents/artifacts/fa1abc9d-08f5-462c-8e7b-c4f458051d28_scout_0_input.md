# Task for scout

Build handoff for Phase 4: dedup command.

**NAVIGATION: Use Serena tools only.**

**Read these files:**
- src/model_shelf/import_model.py (_sha256_file, _sha256_directory, _ingest_file — dedup needs these)
- src/model_shelf/manifest.py (load_manifest, save_manifest — dedup updates manifest hardlinks)
- src/model_shelf/cli.py (cmd_* pattern, subparser registration)
- .serena/memories/implementation_plan.md (Phase 4: dedup section)
- .serena/memories/test_specs.md (Phase 4 section — 18 tests)
- .serena/memories/conventions.md
- /tmp/poc_dedup.py (hardened PoC — reference the working scan logic)

**Write to handoff/dedup-command.md:**

1. Files to CREATE:
   - src/model_shelf/dedup.py (new module)
   - tests/test_dedup.py (18 tests from spec)

2. Files to MODIFY:
   - src/model_shelf/cli.py (add dedup subcommand + cmd_dedup)
   - src/model_shelf/__init__.py (add exports)

3. API contract:
   - DedupGroup dataclass (sha256, files, size_bytes, duplicate_bytes)
   - DedupResult dataclass (groups, total_duplicate_bytes, potential_savings_bytes) with to_dict()
   - find_duplicates(config, include_ollama=False, include_hf_cache=False) -> DedupResult
   - execute_dedup(config, result) -> DedupResult (creates hardlinks, updates manifest)

4. Key logic:
   - Walk shelf + optional external locations, SHA256 all model files
   - Group by SHA256, filter groups with >1 entry
   - Check st_dev for same-fs before hardlink
   - Keep shelf copy as canonical, os.link() others, os.unlink() originals
   - NEVER unlink Ollama blobs or HF cache blobs (external sources)
   - Update manifest hardlinks field

5. Safety constraints:
   - Dry-run default (--execute to actually dedup)
   - Never hardlink across filesystems
   - External blob paths are hardlink destinations, not sources

6. DO NOT MODIFY: manifest.py, import_model.py, resolver.py, config.py, detect.py, relocate.py, search.py, existing tests

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/fa1abc9d-08f5-462c-8e7b-c4f458051d28/handoff/dedup-command.md
This path is authoritative for this run.
Ignore any other output filename or output path mentioned elsewhere, including output destinations in the base agent prompt, system prompt, or task instructions.

## Acceptance Contract
Acceptance level: attested
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Return concrete findings with file paths and severity when applicable

Required evidence: review-findings, residual-risks

Finish with a fenced JSON block tagged `acceptance-report` in this shape:
Use empty arrays when no items apply; array fields contain strings unless object entries are shown.
`criteriaSatisfied[].status` must be exactly one of: satisfied, not-satisfied, not-applicable.
`commandsRun[].result` must be exactly one of: passed, failed, not-run.
`manualNotes` and `notes` are optional strings; an empty string means no note and does not satisfy `manual-notes` evidence.
```acceptance-report
{
  "criteriaSatisfied": [
    {
      "id": "criterion-1",
      "status": "satisfied",
      "evidence": "specific proof"
    }
  ],
  "changedFiles": [
    "src/file.ts"
  ],
  "testsAddedOrUpdated": [
    "test/file.test.ts"
  ],
  "commandsRun": [
    {
      "command": "command",
      "result": "passed",
      "summary": "short result"
    }
  ],
  "validationOutput": [
    "validation output or concise summary"
  ],
  "residualRisks": [
    "none"
  ],
  "noStagedFiles": true,
  "diffSummary": "short description of the diff",
  "reviewFindings": [
    "blocker: file.ts:12 - issue found, or no blockers"
  ],
  "manualNotes": "anything else the parent should know"
}
```