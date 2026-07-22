# Task for worker

[Read from: /Users/jeffersonsantos/Projects/model-shelf/context.md, /Users/jeffersonsantos/Projects/model-shelf/plan.md]

Implement Phase 1.5: upgrade quant detection. Read handoff at Output saved to: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/0f0250a1-dcac-42ba-a559-5f65a4b296c3/handoff/detect-quant-upgrade.md (13.2 KB, 284 lines). Read this file if needed..

**NAVIGATION: Use Serena tools only.**

**SCOPE:**
- MODIFY: src/model_shelf/import_model.py — add detect_quant(), _quant_from_gguf_header(), _quant_from_config_json(), FILETYPE_MAP constant
- CREATE: tests/test_quant.py — 19 tests per spec

**DO NOT TOUCH:** resolver.py, config.py, detect.py, relocate.py, search.py, cli.py, __init__.py, existing test files, pyproject.toml

**IMPLEMENTATION:**
1. Add FILETYPE_MAP dict at module level (25 GGUF file_type → quant string mappings)
2. Add _quant_from_gguf_header(path) — parse GGUF v3 binary header, extract general.file_type
3. Add _quant_from_config_json(path) — parse config.json for MLX quantization.bits, safetensors quantization_config, torch_dtype
4. Add detect_quant(source, fmt) — unified: GGUF header → config.json → filename fallback
5. Existing _detect_quant_from_filename stays as-is (used as fallback)
6. Write 19 tests following discipline: fail-open crime, honest fixtures, exact asserts, self-describing names

**ACCEPTANCE:**
1. pytest tests/test_quant.py -v → all 19 tests pass
2. pytest tests/ -v → zero regressions (80+ tests still green)
3. No new dependencies beyond stdlib
4. Follow conventions: from __future__ import annotations, pathlib.Path, type hints

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/0f0250a1-dcac-42ba-a559-5f65a4b296c3/worker/detect-quant-result.md
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