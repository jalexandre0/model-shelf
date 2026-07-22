# Task for worker

[Read from: /Users/jeffersonsantos/Projects/model-shelf/context.md, /Users/jeffersonsantos/Projects/model-shelf/plan.md]

Implement Phase 5: audit, remove, gc commands. Read handoff at Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/9b95fdee-b168-4000-88fd-9e04e5f69e49/handoff/audit-remove-gc.md (25.7 KB, 579 lines). Read this file if needed..

**NAVIGATION: Use Serena tools only.**

**SCOPE:**
- CREATE: src/model_shelf/audit.py + tests/test_audit.py (7 tests)
- CREATE: src/model_shelf/remove.py + tests/test_remove.py (8 tests)
- CREATE: src/model_shelf/gc.py + tests/test_gc.py (8 tests)
- MODIFY: src/model_shelf/cli.py (add 3 subcommands)
- MODIFY: src/model_shelf/__init__.py (add exports)

**DO NOT TOUCH:** manifest.py, import_model.py, dedup.py, resolver.py, config.py, detect.py, relocate.py, search.py, existing test files

**KEY RULES:**
1. All destructive commands (remove, gc) default to dry-run — require --execute
2. Remove: check st_nlink, warn on hardlinks, clean empty parent dirs
3. GC: skip .cache/ and dot-prefixed dirs, never delete without --execute
4. Audit: read-only, exit 0 clean / 1 dirty
5. All result dataclasses have to_dict()

**ACCEPTANCE:**
1. pytest tests/test_audit.py tests/test_remove.py tests/test_gc.py -v → 23 tests pass
2. pytest tests/ -v → zero regressions (161+ tests)
3. model-shelf audit --help, model-shelf remove --help, model-shelf gc --help all work
4. Dry-run default enforced on remove and gc

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/9b95fdee-b168-4000-88fd-9e04e5f69e49/worker/audit-remove-gc-result.md
This path is authoritative for this run.
Ignore any other output filename or output path mentioned elsewhere, including output destinations in the base agent prompt, system prompt, or task instructions.

## Acceptance Contract
Acceptance level: checked
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Return concrete findings with file paths and severity when applicable

Required evidence: changed-files, tests-added, commands-run, residual-risks, no-staged-files

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