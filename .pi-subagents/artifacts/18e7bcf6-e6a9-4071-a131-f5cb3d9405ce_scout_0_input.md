# Task for scout

Build a detailed implementation handoff for adding an `import` command to model-shelf. You are doing LOCAL codebase recon only.

**NAVIGATION RULES:**
- Use Serena LSP tools (get_symbols_overview, find_symbol, read_file, search_for_pattern) for code exploration.
- Use bash only for running commands.
- You DO NOT have web_search. Do NOT attempt to use it. Everything needed is in local files.

**Files to read:**
- src/model_shelf/resolver.py (patterns: Config usage, dataclass, ResolveResult)
- src/model_shelf/config.py (patterns: write_config for manifest)
- src/model_shelf/cli.py (patterns: subcommand registration, cmd_* signature)
- tests/test_resolver.py (patterns: _config helper, tmp_path, test structure)
- .serena/memories/implementation_plan.md (Phase 2: import command spec)
- .serena/memories/conventions.md

**Write to `handoff/import-command.md` containing:**
1. Exact files to create: src/model_shelf/import_model.py, tests/test_import.py
2. API contract: ImportResult dataclass with to_dict(), import_model() function signature
3. Key logic: detect format, infer org/repo from path, SHA256, check manifest, hardlink/copy, atomic manifest write
4. 8 test specs: gguf import, mlx dir import, reject no-config dir, hardlink same-fs, skip duplicate SHA256, manifest update, org override, auto-detect quant
5. Convention patterns extracted from existing code
6. Files NOT to touch (all existing files)

---
Create and maintain progress at: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/progress/18e7bcf6-e6a9-4071-a131-f5cb3d9405ce/progress.md

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/18e7bcf6-e6a9-4071-a131-f5cb3d9405ce/handoff/import-command.md
This path is authoritative for this run.
Ignore any other output filename or output path mentioned elsewhere, including output destinations in the base agent prompt, system prompt, or task instructions.

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