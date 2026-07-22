# Task for context-builder

You are reviving a previous subagent conversation.

Original run: d174d3ad-8289-4322-8b56-6b9bea59095d
Original agent: context-builder
Original session file: /Users/jeffersonsantos/.pi/agent/sessions/--Users-jeffersonsantos-Projects-model-shelf--/2026-07-21T22-39-32-366Z_019f86d5-960e-723a-b458-913feb781055/26450bd7/run-0/session.jsonl

Use the stored session context as background. Answer the orchestrator's follow-up below. Do not assume the original child process is still alive.

Follow-up:
You failed because you tried to use `web_search` which is NOT available to you. Your available tools are read/grep/find/bash + Serena LSP tools.

DO NOT use web_search. You don't need it — everything you need is in local files.

Continue the task: read the local source files using Serena tools (get_symbols_overview, read_file, find_symbol, search_for_pattern) and write the handoff to `handoff/import-command.md`. You have access to bash for running commands and file writing.

Files you need: src/model_shelf/resolver.py, src/model_shelf/config.py, src/model_shelf/cli.py, tests/test_resolver.py, .serena/memories/implementation_plan.md, .serena/memories/conventions.md

Produce the handoff and exit successfully.

## Acceptance Contract
Acceptance level: reviewed
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Implement the requested change without widening scope
- criterion-2: Return evidence sufficient for an independent acceptance review

Required evidence: changed-files, tests-added, commands-run, validation-output, residual-risks, no-staged-files

Review gate: required by reviewer.

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
    },
    {
      "id": "criterion-2",
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