# Task for worker

[Read from: /Users/jeffersonsantos/Projects/model-shelf/context.md, /Users/jeffersonsantos/Projects/model-shelf/plan.md]

Implement the import command. Read the handoff at Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/18e7bcf6-e6a9-4071-a131-f5cb3d9405ce/handoff/import-command.md (22.5 KB, 676 lines). Read this file if needed. using serena read_file.

**NAVIGATION RULES:**
- Use Serena LSP tools (get_symbols_overview, find_symbol, read_file, search_for_pattern) for ALL code reading.
- NEVER use raw bash grep/cat for reading code.

**CREATE these files:**
- src/model_shelf/import_model.py
- tests/test_import.py

**DO NOT TOUCH:** resolver.py, config.py, detect.py, relocate.py, search.py, cli.py, __init__.py, any existing test file, pyproject.toml

**ACCEPTANCE:**
1. pytest tests/test_import.py -v → all 8 tests pass
2. pytest tests/ -v → zero regressions (existing 27 tests still green)
3. No new external dependencies beyond stdlib + huggingface_hub
4. Follow conventions: from __future__ import annotations, dataclasses, pathlib.Path, type hints

**HANDOFF must include:** changed files list, pytest output (test_import + full suite), surprises/risks

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/18e7bcf6-e6a9-4071-a131-f5cb3d9405ce/worker/import-result.md
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