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


### Worker task 62bf00d1-def9-40d2-8076-3dba81a8084d

```json
{
  "timestamp_utc": "2026-10-20T10:28:37.101863+00:00",
  "source_comment_id": "6288856194",
  "task_id": "62bf00d1-def9-40d2-8076-3dba81a8084d",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "bytes_written": 25303,
    "path": "emberlane/mailbox.py"
  }
}
```


### Worker task aa07bad2-6745-47c1-b731-5b083f3c3517

```json
{
  "timestamp_utc": "2026-10-20T10:28:52.649205+00:00",
  "source_comment_id": "6288858846",
  "task_id": "aa07bad2-6745-47c1-b731-5b083f3c3517",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "path": "emberlane/mailbox.py",
    "bytes_written": 28341
  }
}
```


### Worker task 8049a08f-b2ed-49b6-aae6-58a7767f8837

```json
{
  "timestamp_utc": "2026-10-20T10:29:13.299428+00:00",
  "source_comment_id": "6288862627",
  "task_id": "8049a08f-b2ed-49b6-aae6-58a7767f8837",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "tests_run": 63,
    "passed": true,
    "returncode": 0,
    "test_summary": "OK"
  }
}
```


### Worker task c733e548-e293-4280-a673-440f6f5dce57

```json
{
  "timestamp_utc": "2026-10-20T10:29:52.899731+00:00",
  "source_comment_id": "6288877475",
  "task_id": "c733e548-e293-4280-a673-440f6f5dce57",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "path": "tests/test_mailbox.py",
    "bytes_written": 11443
  }
}
```


### Worker task 5997cc46-340b-42cd-ab63-c2eecae17933

```json
{
  "timestamp_utc": "2026-10-20T10:30:07.328489+00:00",
  "source_comment_id": "6288880388",
  "task_id": "5997cc46-340b-42cd-ab63-c2eecae17933",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "bytes_written": 14374,
    "path": "tests/test_mailbox.py"
  }
}
```


### Worker task 58bbad45-968f-4ae6-bfd1-e8d40995755a

```json
{
  "timestamp_utc": "2026-10-20T10:30:31.103575+00:00",
  "source_comment_id": "6288883425",
  "task_id": "58bbad45-968f-4ae6-bfd1-e8d40995755a",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "tests_run": 66,
    "passed": true,
    "returncode": 0,
    "test_summary": "OK"
  }
}
```


### Worker task d08109f9-9097-4a48-a343-2dcdb6c5af34

```json
{
  "timestamp_utc": "2026-10-20T10:30:54.549000+00:00",
  "source_comment_id": "6288892716",
  "task_id": "d08109f9-9097-4a48-a343-2dcdb6c5af34",
  "kind": "diagnostics",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "platform": "Android-14-aarch64-64bit-ELF",
    "python_version": "3.13.13 (main, Apr 10 2026, 13:09:22) [Clang 21.0.0 (https://android.googlesource.com/toolchain/llvm-project 5e96669f0",
    "branch_status": "## feat/local-coding-worker...origin/feat/local-coding-worker",
    "working_tree_dirty": true,
    "changed_paths_count": 14,
    "head_commit": "ac1b2ca Fix mailbox rejection reply formatting"
  }
}
```


### Worker task b14c6454-d13d-4c94-91d4-181f675a6584

```json
{
  "timestamp_utc": "2026-10-20T10:31:09.435139+00:00",
  "source_comment_id": "6288894328",
  "task_id": "b14c6454-d13d-4c94-91d4-181f675a6584",
  "kind": "git_status",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "branch_status": "## feat/local-coding-worker...origin/feat/local-coding-worker",
    "working_tree_dirty": true,
    "changed_paths_count": 14,
    "head_commit": "ac1b2ca Fix mailbox rejection reply formatting",
    "status_returncode": 0,
    "head_returncode": 0
  }
}
```


### Worker task 42503cdf-e143-4caf-bf6d-758f5d15f51a

```json
{
  "timestamp_utc": "2026-10-20T10:31:39.881239+00:00",
  "source_comment_id": "6288906246",
  "task_id": "42503cdf-e143-4caf-bf6d-758f5d15f51a",
  "kind": "git_diff",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {}
}
```


### Worker task 482c455e-6f9b-4dfa-bbd5-b9f6bffd6185

```json
{
  "timestamp_utc": "2026-10-20T10:32:09.470537+00:00",
  "source_comment_id": "6288912138",
  "task_id": "482c455e-6f9b-4dfa-bbd5-b9f6bffd6185",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "path": "emberlane/mailbox.py",
    "bytes_written": 29115
  }
}
```


### Worker task 4a3ba494-ffd7-47bc-9a6a-056d912bfc37

```json
{
  "timestamp_utc": "2026-10-20T10:32:25.255764+00:00",
  "source_comment_id": "6288913986",
  "task_id": "4a3ba494-ffd7-47bc-9a6a-056d912bfc37",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "bytes_written": 15203,
    "path": "tests/test_mailbox.py"
  }
}
```


### Worker task b350333f-3382-43b7-b5f2-140a3da904c3

```json
{
  "timestamp_utc": "2026-10-20T10:32:47.106859+00:00",
  "source_comment_id": "6288915271",
  "task_id": "b350333f-3382-43b7-b5f2-140a3da904c3",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "tests_run": 67,
    "passed": false,
    "returncode": 1,
    "test_summary": "FAILED (failures=1)"
  }
}
```


### Worker task a85ff852-9dee-4e68-9c64-13f1a7bd01be

```json
{
  "timestamp_utc": "2026-10-20T10:33:26.184331+00:00",
  "source_comment_id": "6288932142",
  "task_id": "a85ff852-9dee-4e68-9c64-13f1a7bd01be",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "path": "emberlane/mailbox.py",
    "bytes_written": 29123
  }
}
```


### Worker task 90e692d6-e792-429b-b246-17cd296487c9

```json
{
  "timestamp_utc": "2026-10-20T10:33:47.646582+00:00",
  "source_comment_id": "6288933237",
  "task_id": "90e692d6-e792-429b-b246-17cd296487c9",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "tests_run": 67,
    "passed": true,
    "returncode": 0,
    "test_summary": "OK"
  }
}
```


### Worker task 327cc148-5fe3-4c38-a617-3193dd656941

```json
{
  "timestamp_utc": "2026-10-20T10:34:26.556797+00:00",
  "source_comment_id": "6288949254",
  "task_id": "327cc148-5fe3-4c38-a617-3193dd656941",
  "kind": "git_status",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "branch_status": "## feat/local-coding-worker...origin/feat/local-coding-worker",
    "working_tree_dirty": true,
    "changed_paths_count": 14,
    "head_commit": "ac1b2ca Fix mailbox rejection reply formatting",
    "status_returncode": 0,
    "head_returncode": 0
  }
}
```


### Worker task 4c2feca5-fb60-42ff-a8aa-6028bb800e69

```json
{
  "timestamp_utc": "2026-10-20T10:37:56.122516+00:00",
  "source_comment_id": "6289007358",
  "task_id": "4c2feca5-fb60-42ff-a8aa-6028bb800e69",
  "kind": "git_diff",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "files_count": 1,
    "diff_summary": "1 file changed, 349 insertions(+), 8 deletions(-)",
    "patch_included": false
  }
}
```


### Worker task 599fa45f-d169-4bfe-87a8-8c907da9f7f4

```json
{
  "timestamp_utc": "2026-10-20T10:38:10.548635+00:00",
  "source_comment_id": "6289008134",
  "task_id": "599fa45f-d169-4bfe-87a8-8c907da9f7f4",
  "kind": "git_diff",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "files_count": 1,
    "diff_summary": "1 file changed, 204 insertions(+), 5 deletions(-)",
    "patch_included": false
  }
}
```


### Worker task 4f33f327-a33c-468e-9985-7f6b69ecfe3a

```json
{
  "timestamp_utc": "2026-10-20T10:38:54.952319+00:00",
  "source_comment_id": "6289021418",
  "task_id": "4f33f327-a33c-468e-9985-7f6b69ecfe3a",
  "kind": "replace_text",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "bytes_written": 29259,
    "path": "emberlane/mailbox.py"
  }
}
```


### Worker task 7ff63917-85cc-421e-ab3b-1cf61fce892c

```json
{
  "timestamp_utc": "2026-10-20T10:39:10.644581+00:00",
  "source_comment_id": "6289026837",
  "task_id": "7ff63917-85cc-421e-ab3b-1cf61fce892c",
  "kind": "write_file",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "bytes_written": 1966,
    "path": "tests/test_handoff_retry.py"
  }
}
```


### Worker task 16973895-f3a9-482f-bdd3-2fc3b19748fc

```json
{
  "timestamp_utc": "2026-10-20T10:39:30.075018+00:00",
  "source_comment_id": "6289030645",
  "task_id": "16973895-f3a9-482f-bdd3-2fc3b19748fc",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "error_present": false,
  "summary": {
    "passed": false,
    "returncode": 1,
    "tests_run": 68,
    "test_summary": "FAILED (failures=6)"
  }
}
```


### Worker task 078c2411-381a-47b2-85a0-ae60665a3e08

```json
{
  "timestamp_utc": "2026-10-20T10:40:40.336782+00:00",
  "source_comment_id": "6289043797",
  "task_id": "078c2411-381a-47b2-85a0-ae60665a3e08",
  "kind": "replace_text",
  "status": "failed",
  "attempts": 3,
  "error_present": true,
  "summary": {}
}
```


### Worker task 75f7ca47-fb5a-4c8c-a694-d722e7aa6400

```json
{
  "timestamp_utc": "2026-10-20T10:41:55.324481+00:00",
  "source_comment_id": "6289061381",
  "task_id": "75f7ca47-fb5a-4c8c-a694-d722e7aa6400",
  "kind": "replace_text",
  "status": "failed",
  "attempts": 3,
  "error_present": true,
  "summary": {}
}
```


### Worker task d740fc13-6508-4d3d-b2bd-8a5509818bcb

```json
{
  "timestamp_utc": "2026-10-20T10:42:26.405226+00:00",
  "source_comment_id": "6289062477",
  "task_id": "d740fc13-6508-4d3d-b2bd-8a5509818bcb",
  "kind": "replace_text",
  "status": "failed",
  "attempts": 3,
  "error_present": true,
  "summary": {}
}
```


### Worker task 8b3b0ab4-52ac-4d0c-9372-0db28f629ade

```json
{
  "timestamp_utc": "2026-10-20T10:42:55.743323+00:00",
  "source_comment_id": "6289063771",
  "task_id": "8b3b0ab4-52ac-4d0c-9372-0db28f629ade",
  "kind": "replace_text",
  "status": "failed",
  "attempts": 3,
  "error_present": true,
  "summary": {}
}
```


### Worker task cae562b1-5455-4d7e-9134-4013bf91aa4c

```json
{
  "timestamp_utc": "2026-10-20T10:43:25.425089+00:00",
  "source_comment_id": "6289065081",
  "task_id": "cae562b1-5455-4d7e-9134-4013bf91aa4c",
  "kind": "replace_text",
  "status": "failed",
  "attempts": 3,
  "error_present": true,
  "summary": {}
}
```


### Worker task 7900f0ea-87c7-481b-9f17-492df5b62c14

```json
{
  "timestamp_utc": "2026-10-20T10:43:58.256270+00:00",
  "source_comment_id": "6289066057",
  "task_id": "7900f0ea-87c7-481b-9f17-492df5b62c14",
  "kind": "replace_text",
  "status": "failed",
  "attempts": 3,
  "error_present": true,
  "summary": {}
}
```


### Worker task 99fc4a32-2012-4d45-a13f-a63d73dc3425

```json
{
  "timestamp_utc": "2026-10-20T10:44:25.704411+00:00",
  "source_comment_id": "6289078275",
  "task_id": "99fc4a32-2012-4d45-a13f-a63d73dc3425",
  "kind": "replace_text",
  "status": "failed",
  "attempts": 3,
  "error_present": true,
  "summary": {}
}
```
