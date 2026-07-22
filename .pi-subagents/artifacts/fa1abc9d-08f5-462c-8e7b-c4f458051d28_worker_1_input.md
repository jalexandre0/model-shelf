# Task for worker

[Read from: /Users/jeffersonsantos/Projects/model-shelf/context.md, /Users/jeffersonsantos/Projects/model-shelf/plan.md]

Implement Phase 4: dedup command. Read handoff at Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/fa1abc9d-08f5-462c-8e7b-c4f458051d28/handoff/dedup-command.md (18.5 KB, 447 lines). Read this file if needed..

**NAVIGATION: Use Serena tools only.**

**SCOPE:**
- CREATE: src/model_shelf/dedup.py
- CREATE: tests/test_dedup.py (18 tests from spec)
- MODIFY: src/model_shelf/cli.py (add dedup subcommand + cmd_dedup)
- MODIFY: src/model_shelf/__init__.py (add exports)

**DO NOT TOUCH:** manifest.py, import_model.py, resolver.py, config.py, detect.py, relocate.py, search.py, existing test files

**KEY SAFETY RULES:**
1. Default dry-run — --execute required to actually hardlink/delete
2. Check st_dev before os.link() — never hardlink across filesystems
3. External blobs (Ollama, HF cache) are hardlink DESTINATIONS — never unlink them
4. Shelf copy is canonical KEEP — hardlink externals to it, then unlink external copies only if safe
5. Update manifest["models"][repo_id]["hardlinks"] after dedup

**ACCEPTANCE:**
1. pytest tests/test_dedup.py -v → all 18 tests pass
2. pytest tests/ -v → zero regressions (137+ tests still green)
3. model-shelf dedup --help works
4. model-shelf dedup (dry-run default) reports duplicates without changes
5. model-shelf dedup --execute creates hardlinks

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/fa1abc9d-08f5-462c-8e7b-c4f458051d28/worker/dedup-result.md
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