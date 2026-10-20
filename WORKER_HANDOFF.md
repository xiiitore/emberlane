# Emberlane Worker Handoff

Status: automatic publishing implemented and verified by live worker tasks on 2026-10-20.

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
GitHub Issue #6 remains the task intake and fallback result transport; completed task summaries are also published automatically to this file:
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


### Worker task 11b0518c-b9fe-44ca-8eac-2a1ba1b786ff

```json
{
  "timestamp_utc": "2026-10-20T10:20:36.945351+00:00",
  "source_comment_id": "6288723220",
  "task_id": "11b0518c-b9fe-44ca-8eac-2a1ba1b786ff",
  "kind": "diagnostics",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "platform": "Android-14-aarch64-64bit-ELF",
    "python_version": "3.13.13 (main, Apr 10 2026, 13:09:22) [Clang 21.0.0 (https://android.googlesource.com/toolchain/llvm-project 5e96669f0"
  }
}
```


### Worker task 31f4d712-a070-46c8-bf34-03456fa15bd6

```json
{
  "timestamp_utc": "2026-10-20T10:20:52.039159+00:00",
  "source_comment_id": "6288730672",
  "task_id": "31f4d712-a070-46c8-bf34-03456fa15bd6",
  "kind": "git_status",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {}
}
```


### Worker task dff4c011-6bc0-4794-beca-f126fc1b2cd7

```json
{
  "timestamp_utc": "2026-10-20T10:21:11.720762+00:00",
  "source_comment_id": "6288731404",
  "task_id": "dff4c011-6bc0-4794-beca-f126fc1b2cd7",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "tests_run": 63,
    "returncode": 1,
    "passed": false
  }
}
```


### Worker task 3bc62d52-ee11-4a84-8c80-982d2e57d5e5

```json
{
  "timestamp_utc": "2026-10-20T10:21:51.723906+00:00",
  "source_comment_id": "6288745258",
  "task_id": "3bc62d52-ee11-4a84-8c80-982d2e57d5e5",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "bytes_written": 25092,
    "path": "emberlane/mailbox.py"
  }
}
```


### Worker task 3c0e65ac-0fec-4a47-8b3c-3e56e626750b

```json
{
  "timestamp_utc": "2026-10-20T10:22:28.665145+00:00",
  "source_comment_id": "6288752388",
  "task_id": "3c0e65ac-0fec-4a47-8b3c-3e56e626750b",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "returncode": 0,
    "tests_run": 63,
    "passed": true
  }
}
```


### Worker task 695b974a-8ef3-4d09-b729-4ab2d834835a

```json
{
  "timestamp_utc": "2026-10-20T10:25:22.562651+00:00",
  "source_comment_id": "6288803085",
  "task_id": "695b974a-8ef3-4d09-b729-4ab2d834835a",
  "kind": "diagnostics",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "python_version": "3.13.13 (main, Apr 10 2026, 13:09:22) [Clang 21.0.0 (https://android.googlesource.com/toolchain/llvm-project 5e96669f0",
    "platform": "Android-14-aarch64-64bit-ELF"
  }
}
```


### Worker task e6fd7daa-d734-4acf-a1f5-dc53a10809f2

```json
{
  "timestamp_utc": "2026-10-20T10:26:07.593116+00:00",
  "source_comment_id": "6288813270",
  "task_id": "e6fd7daa-d734-4acf-a1f5-dc53a10809f2",
  "kind": "git_status",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {}
}
```


### Worker task 914fbb2d-d954-4095-952b-5716fcee2d68

```json
{
  "timestamp_utc": "2026-10-20T10:26:22.643047+00:00",
  "source_comment_id": "6288813756",
  "task_id": "914fbb2d-d954-4095-952b-5716fcee2d68",
  "kind": "list_files",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {}
}
```
