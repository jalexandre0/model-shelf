# Task for reviewer

[Read from: /Users/jeffersonsantos/Projects/model-shelf/plan.md, /Users/jeffersonsantos/Projects/model-shelf/progress.md]

Final review: CODE QUALITY + JEFF'S STANDARDS.

**Use Serena tools for code reading.**

1. Read the full diff + .serena/memories/conventions.md
2. Anti-patterns scan (Jeff's rage-quit list):
   - Unnecessary abstraction? Interface with 1 impl?
   - Generic names (data, info, result)?
   - Comments repeating code?
   - Handler > 200 lines? Function > 40 lines?
   - .env anywhere?
3. Is the code consistent with the existing resolver.py patterns?
4. Are the tests HONEST? (fail-open check: no t.Skip, fixtures use real paths, tests would catch a regression)
5. The manifest.json schema — is it forward-compatible? What breaks if we add fields later?

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