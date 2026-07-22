# Task for reviewer

[Read from: /Users/jeffersonsantos/Projects/model-shelf/plan.md, /Users/jeffersonsantos/Projects/model-shelf/progress.md]

Review dedup command for TEST DISCIPLINE and EDGE CASES.

**Use Serena tools only.**
Worker result: Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/fa1abc9d-08f5-462c-8e7b-c4f458051d28/worker/dedup-result.md (3.4 KB, 54 lines). Read this file if needed.

1. Test discipline (read .serena/memories/test_specs.md Phase 4):
   - Any t.Skip, xfail? (FAIL-OPEN CRIME)
   - Honest fixtures? (real files in tmp_path, not mocked)
   - Exact asserts?
   - Self-describing names?
2. Edge cases:
   - Three-way duplicates?
   - Cross-fs detection (different st_dev)?
   - Empty shelf (no files)?
   - Shelf with only unique models (no duplicates)?
   - Ollama include flag actually scans ollama dir?
   - HF cache include flag actually scans hf cache dir?
3. Anti-patterns: duplicate logic, functions >40 lines, generic names?
4. Follow conventions: from __future__ import annotations, dataclasses, pathlib.Path?

Output: severity, file:line, fix. Do NOT modify files.

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