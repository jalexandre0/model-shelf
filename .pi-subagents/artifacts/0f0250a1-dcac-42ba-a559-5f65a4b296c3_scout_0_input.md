# Task for scout

Build handoff for Phase 1.5: upgrade quant detection.

**NAVIGATION: Use Serena tools only (get_symbols_overview, read_file, find_symbol, search_for_pattern).**

**Read these files:**
- src/model_shelf/import_model.py (current _detect_quant_from_filename, FILETYPE_MAP we'll need)
- .serena/memories/test_specs.md (Phase 1.5 section — 19 tests)
- .serena/memories/implementation_plan.md (quantization detection section with PoC code snippets)
- .serena/memories/conventions.md

**Write to handoff/detect-quant-upgrade.md:**
1. Files to modify: src/model_shelf/import_model.py (add functions, keep existing)
2. Files to create: tests/test_quant.py (19 tests)
3. API: `detect_quant(source: Path, fmt: str) -> str | None` — unified entry point
4. New helpers: _quant_from_gguf_header(), _quant_from_config_json(), FILETYPE_MAP constant
5. Existing _detect_quant_from_filename stays as fallback for GGUF
6. DO NOT modify: resolver.py, config.py, cli.py, __init__.py, existing tests

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/0f0250a1-dcac-42ba-a559-5f65a4b296c3/handoff/detect-quant-upgrade.md
This path is authoritative for this run.
Ignore any other output filename or output path mentioned elsewhere, including output destinations in the base agent prompt, system prompt, or task instructions.

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