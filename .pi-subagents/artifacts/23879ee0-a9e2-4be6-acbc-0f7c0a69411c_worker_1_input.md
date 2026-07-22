# Task for worker

[Read from: /Users/jeffersonsantos/Projects/model-shelf/context.md, /Users/jeffersonsantos/Projects/model-shelf/plan.md]

Implement Phase 3: manifest command. Read handoff at Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/23879ee0-a9e2-4be6-acbc-0f7c0a69411c/handoff/manifest-command.md (18.1 KB, 395 lines). Read this file if needed..

**NAVIGATION: Use Serena tools only.**

**SCOPE:**
- CREATE: src/model_shelf/manifest.py
- CREATE: tests/test_manifest.py (14 tests from spec)
- MODIFY: src/model_shelf/import_model.py (replace _load_manifest/_save_manifest with imports from manifest)
- MODIFY: src/model_shelf/cli.py (add manifest subcommand + cmd_manifest)
- MODIFY: src/model_shelf/__init__.py (add exports)

**DO NOT TOUCH:** resolver.py, config.py, detect.py, relocate.py, search.py, existing tests (except test_import.py may need import path updates)

**KEY CONSTRAINT:** manifest.py is the canonical manifest I/O module. import_model.py must IMPORT from it, not duplicate _load_manifest/_save_manifest.

**ACCEPTANCE:**
1. pytest tests/test_manifest.py -v → all 14 tests pass
2. pytest tests/ -v → zero regressions (102+ tests still green)
3. import_model.py imports manifest functions (no duplicate _load_manifest/_save_manifest)
4. model-shelf manifest --help works
5. model-shelf manifest --rebuild works (walks shelf, generates manifest.json)
6. model-shelf manifest --json emits valid JSON

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/23879ee0-a9e2-4be6-acbc-0f7c0a69411c/worker/manifest-result.md
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