# Task for reviewer

[Read from: /Users/jeffersonsantos/Projects/model-shelf/plan.md, /Users/jeffersonsantos/Projects/model-shelf/progress.md]

Final review: CORRECTNESS + DRY-RUN focus.

**Use Serena tools for code reading.**

1. Read the full diff: run `git diff HEAD` and `cat src/model_shelf/import_model.py tests/test_import.py`
2. DRY-RUN evaluation (primary focus):
   - Does --dry-run truly avoid ALL side effects? No files written, no manifest modified, no directories created?
   - Does dry-run still compute SHA256? (It should — user needs to know what WOULD happen)
   - Does dry-run detect duplicates correctly without modifying manifest?
   - What happens on dry-run with a missing source file? With a cross-fs scenario?
3. General correctness: any logic errors, edge case gaps, or regressions?
4. Run `python3 -m pytest tests/ -v` yourself to verify.

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