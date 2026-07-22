# Task for worker

You are a delegated subagent running from a fork of the parent session. Treat the inherited conversation as reference-only context, not a live thread to continue. Do not continue or answer prior messages as if they are waiting for a reply. Your sole job is to execute the task below and return a focused result for that task using your tools.

Task:
Fix all issues from dedup command review. Read files with Serena tools first.

**SCOPE — ONLY these files:**
- src/model_shelf/dedup.py
- tests/test_dedup.py

**DO NOT TOUCH any other files.**

**FIXES:**

**1. [BLOCKER] HF cache .cache filter dead code**
File: src/model_shelf/dedup.py, find_duplicates() HF cache scan branch
The filter `".cache" in f.parts` unconditionally skips all HF cache blobs because the HF cache root is `~/.cache/huggingface/hub/`. Remove this filter from the HF cache scan branch ONLY (keep it for the shelf scan). Use a relative path check: after computing relative path from hf_cache_root, check if any component is `.cache`.

**2. [NOTE] Cross-fs test doesn't exercise cross-fs**
File: tests/test_dedup.py, test_dedup_skips_across_filesystems
Monkeypatch `os.stat` on the second file to return a different `st_dev`. Use `unittest.mock.patch` or manually overwrite the stat result. Example approach: wrap the second file's stat to return a mock with different st_dev.

**3. [NOTE] include_ollama path untested**
File: tests/test_dedup.py
Add a test that monkeypatches `Path.home()` to return `tmp_path`, creates `tmp_path/.ollama/models/blobs/sha256-xxx` with content identical to a shelf file, then calls find_duplicates with include_ollama=True and asserts the duplicate is found. Restore Path.home() after.

**4. [NOTE] include_hf_cache path untested**
File: tests/test_dedup.py
Same approach as #3 but for `tmp_path/.cache/huggingface/hub/models--test--model/blobs/xxx`. With the blocker fix applied, this should now work.

**5. [NOTE] Weak >= asserts → exact == asserts**
File: tests/test_dedup.py
Change all 10 `>=` asserts to `==` where the test setup is deterministic. In clean tmp_path with exactly N copies, st_nlink should be exactly N, hardlinks_created should be exactly N-1. If there's a legit reason for >= (e.g., tmp_path already has hardlinks from prior test), document it with a comment.

**6. [NOTE] find_duplicates + execute_dedup > 40 lines**
File: src/model_shelf/dedup.py
Extract helper functions to bring both under 40 lines. Candidates:
- _collect_shelf_files(shelf_root) -> list[Path]
- _collect_ollama_blobs() -> list[Path]
- _collect_hf_cache_blobs() -> list[Path]
- _build_sha256_index(paths) -> dict[str, list[Path]]
- _dedup_one_group(group, shelf_root) -> int (returns hardlinks_created)

**7. [NOTE] Only canonical manifest entry updated**
File: src/model_shelf/dedup.py, _update_manifest_for_dedup()
After updating canonical's hardlinks, also iterate all other shelf files in the group and update their manifest entries. For each non-canonical shelf file, resolve its repo_id, add the canonical path to its hardlinks list.

**ACCEPTANCE:**
1. pytest tests/test_dedup.py -v → all tests pass (expect 21+)
2. pytest tests/ -v → zero regressions (expect 140+)
3. include_hf_cache actually finds files (test proves it)
4. include_ollama actually finds files (test proves it)
5. All asserts use == not >=
6. find_duplicates + execute_dedup each < 40 lines

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