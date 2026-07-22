# Task for worker

You are a delegated subagent running from a fork of the parent session. Treat the inherited conversation as reference-only context, not a live thread to continue. Do not continue or answer prior messages as if they are waiting for a reply. Your sole job is to execute the task below and return a focused result for that task using your tools.

Task:
Fix all issues from audit/remove/gc review. Read files with Serena tools first.

**SCOPE — ONLY these files:**
- src/model_shelf/audit.py
- src/model_shelf/remove.py
- src/model_shelf/gc.py
- src/model_shelf/cli.py
- src/model_shelf/manifest.py (add shared helper)
- tests/test_audit.py
- tests/test_remove.py
- tests/test_gc.py

**DO NOT TOUCH other files.**

**FIXES:**

**1. [BLOCKER] run_audit 90 lines → extract helpers**
File: src/model_shelf/audit.py
Extract: _check_manifest_entries(manifest, shelf_root) → missing, stale lists
Extract: _find_untracked_files(shelf_root, tracked_paths) → untracked list
After extraction run_audit should be ~30 lines.

**2. [BLOCKER] remove_model 78 lines → extract helpers**
File: src/model_shelf/remove.py
Extract: _collect_model_files(shelf_root, fmt, org, repo, entry) → list[Path]
Extract: _delete_files_and_warn(paths) → RemoveResult
After extraction remove_model should be ~30 lines.

**3. [BLOCKER] run_gc 118 lines → extract helpers**
File: src/model_shelf/gc.py
Extract: _find_incomplete_downloads(shelf_root) → list
Extract: _find_orphaned_files(shelf_root, tracked_paths, scanned_dirs) → list
Extract: _find_empty_dirs(shelf_root) → list
After extraction run_gc should be ~30 lines.

**4. [BLOCKER] Duplicate _build_manifest_tracked_set**
Files: src/model_shelf/audit.py + src/model_shelf/gc.py
Move to src/model_shelf/manifest.py as `build_tracked_path_set(shelf_root) -> set[str]`.
Update both audit.py and gc.py to import from manifest.py.
Remove the old functions from audit.py and gc.py.

**5. [BLOCKER] Duplicate _cleanup_empty_parents**
Files: src/model_shelf/remove.py + src/model_shelf/cli.py
Move to src/model_shelf/remove.py (keep it there, make it public).
Update cli.py to import from remove.py.
Remove the duplicate from cli.py.

**6. [NOTE] _should_skip_file vs _should_skip_path inconsistency**
Files: src/model_shelf/audit.py + src/model_shelf/gc.py
Unify into a single function in manifest.py: `should_skip_shelf_path(path: Path) -> bool`
Rules: skip ._ prefix, skip .cache exact component match, skip dot-prefixed dirs.
Use the more conservative GC rules (they're stricter = safer).
Update audit.py and gc.py to import from manifest.py.

**7. [NOTE] >= assert in test_remove.py:139**
Change to exact assert. We control st_nlink in the test (clean tmp_path), should be exactly 2.

**8. [NOTE] Publisher-level orphan scan untested**
Add test_gc_finds_orphan_at_publisher_level: create file at shelf/gguf/somepub/stray.bin (no repo subdir), assert it's flagged as orphaned.

**9. [NOTE] Stale SHA256 for MLX/safetensors untested**
Add test_audit_stale_sha256_mlx: create MLX dir, write manifest with wrong SHA256, assert stale.

**ACCEPTANCE:**
1. pytest tests/test_audit.py tests/test_remove.py tests/test_gc.py -v → all pass (expect 25+)
2. pytest tests/ -v → zero regressions (expect 170+)
3. run_audit, remove_model, run_gc all < 40 lines
4. No duplicate functions across modules
5. manifest.py has build_tracked_path_set + should_skip_shelf_path

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