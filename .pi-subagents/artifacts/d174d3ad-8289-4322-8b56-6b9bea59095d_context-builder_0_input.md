# Task for context-builder

Build a detailed implementation handoff for adding an `import` command to model-shelf.

**NAVIGATION RULES — USE SERENA TOOLS ONLY:**
- Use `get_symbols_overview`, `find_symbol`, `read_file`, `search_for_pattern` for ALL code exploration.
- NEVER use raw bash/grep/cat/ls for reading code. Serena tools are 5x more token-efficient.
- Read these files for context: src/model_shelf/resolver.py, src/model_shelf/config.py, src/model_shelf/cli.py, tests/test_resolver.py, tests/test_config.py
- Read .serena/memories/implementation_plan.md (focus on Phase 2: import command)
- Read .serena/memories/conventions.md

**What to produce:**
A handoff document at `handoff/import-command.md` containing:

1. **Exact files to create:**
   - src/model_shelf/import_model.py (full spec: API, dataclass, logic)
   - tests/test_import.py (8 test cases, each with description)

2. **Exact files to modify:** NONE in this phase. CLI integration is a separate phase.

3. **API contract for import_model.py:**
   - `ImportResult` dataclass with `to_dict()`
   - `import_model(config: Config, source: Path, *, format: str | None = None, org: str | None = None, hardlink: bool = True) -> ImportResult`
   - Key logic: detect format, infer org/repo, compute SHA256, check manifest for duplicate, create target dir, hardlink/copy, update manifest atomically

4. **Test specifications:** 8 tests covering gguf import, mlx directory import, rejection of dir without config.json, hardlink same-fs, skip duplicate SHA256, manifest update, org override, auto-detect quant

5. **Conventions checklist:** from __future__ import annotations, type hints, dataclasses, pathlib.Path, --json + --dry-run flags

6. **Existing code patterns to follow:** extract examples from resolver.py (Config usage, dataclass pattern, error handling), cli.py (argparse subcommand pattern, cmd_* function signature, exit codes)

Output the handoff to `handoff/import-command.md` with `outputMode: "file-only"`.

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/d174d3ad-8289-4322-8b56-6b9bea59095d/handoff/import-command.md
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