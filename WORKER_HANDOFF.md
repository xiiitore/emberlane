# Emberlane Worker Handoff

Status: protocol specification; automatic file publishing is not yet implemented.

## Purpose
Provide a compact, auditable handoff from the local Termux worker to the reviewing assistant without requiring the user to copy terminal output.

## Required record format
Each completed task should produce one newest-first record containing:
- timestamp in UTC
- task/comment ID and task kind
- task status and attempt count
- repository branch and HEAD, when available
- files changed (paths only by default)
- concise command/test summary: command, exit code, passed/failed count
- error summary and next recommended action
- whether output was truncated
- verification level: OBSERVED, PASS, FAIL, or UNKNOWN

## Output and safety rules
- Keep each published record at or below 6,000 characters.
- Preserve full raw output locally; publish only a concise, sanitized summary.
- Never publish tokens, credentials, environment values, private keys, or full secret-bearing configuration.
- Do not claim tests passed unless the result includes an observed successful exit code.
- Do not claim a local file is visible to the assistant until it has been published to GitHub and fetched back successfully.
- Do not overwrite prior records; append new records and retain recent history.
- Never discard unrelated working-tree changes or run destructive cleanup as part of handoff.

## Current transport
Until automatic publication of this file is implemented and verified, GitHub Issue #6 is the working result transport:
https://github.com/xiiitore/emberlane/issues/6

The assistant must fetch the relevant Issue #6 comments or published file directly. The user should not need to copy terminal output.

## Completion criteria for automatic file handoff
1. The worker appends one sanitized record after each terminal task result.
2. The record is published to the feat/local-coding-worker branch through an authenticated, conflict-aware mechanism.
3. The assistant fetches the file and verifies the new record's task ID and status.
4. A test proves the record is bounded, sanitized, appended without erasing prior entries, and recoverable after worker restart.
5. If publication fails, the worker retains the record locally and reports the publication failure through Issue #6.


## Test batch — 2026-10-20 (assistant-forwarded worker results)

These records were fetched from Issue #6 after the local worker completed each task. They were appended to this document by the assistant; this test does **not** prove the worker can publish this file itself.

### 1. diagnostics
- Source task comment: 6288630407
- Worker result comment: 6288632617
- Task ID: 6e098641-fbbf-464c-863a-df302d8395ee
- Status: completed
- Attempts: 1
- Return code: 0
- Observed output: Python 3.13.13; Android 14, aarch64
- Verification: OBSERVED
- Output limitation: connector returned a truncated diagnostic string; no additional environment values recorded.

### 2. git_status
- Source task comment: 6288630952
- Worker result comment: 6288636996
- Task ID: 52b0b147-b6fb-4c1a-a624-0a6f86aec4a4
- Status: completed
- Attempts: 1
- Return code: 0
- Branch status: feat/local-coding-worker...origin/feat/local-coding-worker
- Working tree dirty: true
- Changed paths count: 14
- HEAD: ac1b2ca (Fix mailbox rejection reply formatting)
- Verification: OBSERVED

### 3. list_files
- Source task comment: 6288631600
- Worker result comment: 6288641090
- Task ID: 0bc36a91-0f1a-4070-a768-35cd5c3cdd61
- Status: completed
- Attempts: 1
- Result available: true
- Detailed file listing: not present in the returned result; do not infer a listing was delivered.
- Verification: PASS for task completion; UNKNOWN for listing content.
