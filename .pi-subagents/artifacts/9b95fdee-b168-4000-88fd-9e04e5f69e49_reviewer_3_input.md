# Task for reviewer

[Read from: /Users/jeffersonsantos/Projects/model-shelf/plan.md, /Users/jeffersonsantos/Projects/model-shelf/progress.md]

Review audit/remove/gc for TEST DISCIPLINE and COVERAGE.

**Use Serena tools only.**
Worker result: Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/9b95fdee-b168-4000-88fd-9e04e5f69e49/worker/audit-remove-gc-result.md (3.5 KB, 45 lines). Read this file if needed.

1. Test discipline:
   - Any t.Skip, xfail? (FAIL-OPEN CRIME)
   - Honest fixtures? (real files in tmp_path)
   - Exact asserts? (== not >= or len>0)
   - Self-describing names?
2. Coverage gaps:
   - Does audit test all 3 states (clean, dirty, multiple issues)?
   - Does remove test: delete, dry-run, hardlink warn, nonexistent model, sibling preservation?
   - Does gc test: incomplete dirs, empty dirs, orphaned files, reclaimable bytes?
3. Anti-patterns: functions >40 lines, duplicate logic, generic names?
4. All modules self-contained? (no circular imports)

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