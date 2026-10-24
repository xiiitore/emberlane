# GitHub mailbox task envelope contract

## Purpose

The mailbox polls issue comments and treats a comment as executable input only when its first line is exactly `EMBERLANE_TASK_JSON`. This deliberately separates human coordination from worker instructions.

## Required wire format

The marker must be the first line. The JSON object must follow on subsequent lines and contain exactly two top-level fields: `kind` (a string) and `payload` (an object).

```text
EMBERLANE_TASK_JSON
{"kind":"run_tests","payload":{"test_file":"test_mailbox.py"}}
```

Do not put a session label, greeting, heading, quotation, or explanatory prose before the marker. A comment such as `1 | ...` followed by the marker is ordinary discussion, not a task envelope. Put coordination in a separate comment, then publish a separate task comment using the exact format above.

## Result correlation

A task request being visible on GitHub does not prove it was enqueued or executed. For every task, preserve and verify the chain:

1. Source comment ID.
2. Queue task ID.
3. Terminal queue status and attempt count.
4. Handler outcome, including whether changes were actually applied and which paths changed.
5. Exact tests and return codes.
6. Log publication and read-back verification, where applicable.

Do not treat queue status `completed` as proof that an edit succeeded. A handler may return a rejected or blocked result without applying a patch.

## Safe coordination

- Use ordinary comments for coordination; use task envelopes only for work intended for the worker.
- Do not post duplicate writing tasks when enqueue state is unknown. Inspect the queue/result evidence first.
- Keep independent tasks from writing overlapping files concurrently.
- Preserve dirty worktrees and stash entries. Do not sync, reset, clean, apply/pop stashes, commit, or push a local checkout without a separate recovery plan.
- Never weaken credential, binary, path, or patch validation to get a task accepted. Diagnose the exact rejection and add a regression test.

## Verification boundary

This document describes the current parser contract and the evidence required for task tracking. It does not prove a worker is running, a task is queued, or a local device is ready. Those claims require fresh runtime evidence.
