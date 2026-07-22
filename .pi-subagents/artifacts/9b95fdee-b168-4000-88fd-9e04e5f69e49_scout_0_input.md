# Task for scout

Build handoff for Phase 5: audit, remove, gc commands.

**NAVIGATION: Use Serena tools only.**

**Read these files:**
- src/model_shelf/manifest.py (load_manifest — audit/remove need it)
- src/model_shelf/import_model.py (_sha256_file — audit needs SHA256)
- src/model_shelf/cli.py (cmd_* pattern, subparser registration)
- .serena/memories/implementation_plan.md (Phase 5: audit, remove, gc section)
- .serena/memories/test_specs.md (Phase 5a/5b/5c — 23 tests total)
- .serena/memories/conventions.md

**Write to handoff/audit-remove-gc.md:**

Three modules, one phase:

### AUDIT (src/model_shelf/audit.py)
- AuditResult dataclass (missing, untracked, stale lists)
- run_audit(config) -> AuditResult
- Cross-references manifest entries vs filesystem
- Exit 0 clean, 1 if issues

### REMOVE (src/model_shelf/remove.py)
- RemoveResult dataclass (removed, hardlinks_warn)
- remove_model(config, repo_id, dry_run=True) -> RemoveResult
- st_nlink check before delete, warn on hardlinks
- Clean up empty parent dirs

### GC (src/model_shelf/gc.py)
- GCResult dataclass (incomplete_downloads, orphaned_files, empty_dirs, total_reclaimable_bytes)
- run_gc(config) -> GCResult
- Find: dirs without config.json/.gguf, empty dirs, orphaned .gguf files
- Skip .cache/, dot-prefixed dirs
- Dry-run default

### CLI integration (cli.py)
- Three subcommands: audit, remove, gc
- cmd_audit, cmd_remove, cmd_gc following cmd_* pattern
- --json on all, --dry-run/--execute on destructive ones

### __init__.py exports
- All 3 result dataclasses + 3 main functions

**DO NOT MODIFY:** manifest.py, import_model.py, dedup.py, resolver.py, config.py, detect.py, relocate.py, search.py, existing tests

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/9b95fdee-b168-4000-88fd-9e04e5f69e49/handoff/audit-remove-gc.md
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