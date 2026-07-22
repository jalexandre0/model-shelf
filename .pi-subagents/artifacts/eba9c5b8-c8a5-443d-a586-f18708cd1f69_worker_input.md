# Task for worker

You are a delegated subagent running from a fork of the parent session. Treat the inherited conversation as reference-only context, not a live thread to continue. Do not continue or answer prior messages as if they are waiting for a reply. Your sole job is to execute the task below and return a focused result for that task using your tools.

Task:
Fix all issues from review of detect_quant upgrade. Read files with Serena tools first.

**SCOPE — ONLY these files:**
- src/model_shelf/import_model.py
- tests/test_quant.py
- tests/test_import.py

**DO NOT TOUCH any other files.**

**FIXES:**

**1. [BLOCKER] regex misses Q2_K, Q6_K, Q8_K**
File: src/model_shelf/import_model.py, _detect_quant_from_filename()
Add pattern `r"(q[2-8]_k)(?![a-z0-9])"` before the existing `r"(q[2-8]_[klo]_[ms])"` pattern.
These are single-segment K quants without third component.
Add 3 tests: test_detect_quant_from_filename_q2_k, test_detect_quant_from_filename_q6_k, test_detect_quant_from_filename_q8_k

**2. [NOTE] FILETYPE_MAP missing types 25-31**
File: src/model_shelf/import_model.py, FILETYPE_MAP dict
Add entries: 25:'IQ4_NL', 26:'IQ3_S', 27:'IQ3_M', 28:'IQ2_S', 29:'IQ2_M', 30:'IQ4_K_S', 31:'IQ4_K_M'
Update test_gguf_filetype_map_is_exhaustive to loop range(0, 32) instead of range(0, 25)

**3. [NOTE] Remove duplicate _detect_quant_from_filename tests from test_import.py**
File: tests/test_import.py
Remove tests: test_detect_quant_q4_k_m, test_detect_quant_q5_0, test_detect_quant_f16, test_detect_quant_none
(These are now canonically in test_quant.py — spec forbids duplicate contracts)

**4. [NOTE] Add Tier 3 real-model smoke test**
File: tests/test_quant.py
Add test_gguf_header_real_model_nomic:
- Path: ~/.lmstudio/.internal/bundled-models/nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf
- Assert _quant_from_gguf_header returns "Q4_K_M"
- Skip if file not found (this is acceptable — real model may not exist in CI)
- Read-only, non-destructive

**5. [NOTE] Remove unused tensor_count variable**
File: src/model_shelf/import_model.py, _quant_from_gguf_header()
Change: `tensor_count = struct.unpack("<Q", tensor_raw)[0]` → `_ = struct.unpack("<Q", tensor_raw)[0]`  
Or just read and discard: `f.read(8)` is cleaner since we already read tensor_raw.

**6. [NOTE] elem_sizes as module constant**
File: src/model_shelf/import_model.py
Move `elem_sizes` dict from inside _skip_gguf_value() to module level, near FILETYPE_MAP.
Rename to `_GGUF_ELEM_SIZES` (private module constant).

**ACCEPTANCE:**
1. pytest tests/test_quant.py -v → all tests pass (expect 25 tests now)
2. pytest tests/ -v → zero regressions (expect 105+ tests)
3. Q2_K/Q6_K/Q8_K regex works
4. No duplicate quant tests between test_import.py and test_quant.py
5. FILETYPE_MAP covers 0-31

## Acceptance Contract
Acceptance level: reviewed
Completion is not accepted from prose alone. End with a structured acceptance report.

Criteria:
- criterion-1: Implement the requested change without widening scope
- criterion-2: Return evidence sufficient for an independent acceptance review

Required evidence: changed-files, tests-added, commands-run, validation-output, residual-risks, no-staged-files

Review gate: optional by reviewer.

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