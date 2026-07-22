# Task for reviewer

[Read from: /Users/jeffersonsantos/Projects/model-shelf/plan.md, /Users/jeffersonsantos/Projects/model-shelf/progress.md]

Review audit/remove/gc for CORRECTNESS and SAFETY.

**Use Serena tools only.**
Worker result: Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/9b95fdee-b168-4000-88fd-9e04e5f69e49/worker/audit-remove-gc-result.md (3.5 KB, 45 lines). Read this file if needed.

AUDIT:
1. Does run_audit() correctly cross-reference manifest vs filesystem?
2. Are MISSING, STALE, UNTRACKED detected correctly?
3. Is it read-only (no writes)?

REMOVE:
4. Does remove_model() check st_nlink before delete?
5. Are empty parent dirs cleaned up?
6. Does --dry-run default prevent actual deletion?
7. Does it only remove the target model (not siblings)?

GC:
8. Does run_gc() find incomplete downloads, orphaned files, empty dirs?
9. Does it skip .cache/ and dot-prefixed dirs?
10. Is --execute required to actually delete?

Run pytest tests/ -v — verify zero regressions.

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