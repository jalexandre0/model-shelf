# Task for scout

Build handoff for Phase 3: manifest command.

**NAVIGATION: Use Serena tools only.**

**Read these files:**
- src/model_shelf/import_model.py (_load_manifest, _save_manifest — these will be extracted into manifest.py)
- src/model_shelf/cli.py (cmd_* pattern, subparser registration)
- .serena/memories/implementation_plan.md (Phase 3: manifest command section)
- .serena/memories/test_specs.md (Phase 3 section — 14 tests)
- .serena/memories/conventions.md

**Write to handoff/manifest-command.md:**

1. Files to CREATE:
   - src/model_shelf/manifest.py (new module)
   - tests/test_manifest.py (14 tests)

2. Files to MODIFY:
   - src/model_shelf/import_model.py (replace _load_manifest/_save_manifest calls with imports from manifest.py)
   - src/model_shelf/cli.py (add manifest subcommand + cmd_manifest)
   - src/model_shelf/__init__.py (add exports)

3. API contract for manifest.py:
   - load_manifest(shelf_root) -> dict
   - save_manifest(shelf_root, data) -> None (atomic write)
   - rebuild_manifest(config) -> ManifestResult
   - get_manifest_entry(shelf_root, repo_id) -> dict | None
   - add_manifest_entry(shelf_root, repo_id, entry) -> None
   - remove_manifest_entry(shelf_root, repo_id) -> None
   - ManifestResult dataclass with to_dict()

4. rebuild_manifest() logic: walk shelf_root/{gguf,mlx,safetensors}/, detect format, detect quant, SHA256, build entries

5. DO NOT MODIFY: resolver.py, config.py, detect.py, relocate.py, search.py, existing tests

6. Key invariant: manifest.py is the single source of truth for manifest I/O. import_model.py imports from it, doesn't duplicate logic.

---
**Output:**
Write your findings to exactly this path: /Users/jeffersonsantos/Projects/model-shelf/.pi-subagents/artifacts/outputs/23879ee0-a9e2-4be6-acbc-0f7c0a69411c/handoff/manifest-command.md
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