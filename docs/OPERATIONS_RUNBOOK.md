# Emberlane operations runbook

## Operating rules

- Run one worker process per queue file.
- Keep the project root explicit; do not launch from an unknown directory.
- Preserve local modifications; inspect status before synchronization or reset.
- Prefer a disposable worktree for generated edits and tests.
- Bound loops by task count, wall-clock time and failure count.
- Check pause/stop before claiming work and between plan steps.
- Do not use unbounded retries to compensate for provider quota.
- Do not report success without persisted result and verification evidence.

## Start-of-session checks

From the repository root, run:

    pwd
    git status --short --branch
    git rev-parse --show-toplevel
    git rev-parse HEAD
    python --version
    python -m emberlane --help

Confirm the root and branch are correct. If valuable modifications exist, do not stash, reset, clean or overwrite them automatically.

Run the read-only preflight when available:

    bash scripts/termux-preflight.sh

Review warnings and exit status. A successful CLI version check does not prove model loading.

## Basic task lifecycle

Check the CLI help first because options can change. Typical commands are:

    python -m emberlane status
    python -m emberlane submit diagnostics
    python -m emberlane run-one
    python -m emberlane status

For a bounded batch, use `python -m emberlane supervise --max-tasks 10 --max-failures 3 --max-seconds 300`. It exits on an idle queue, pause/stop, deadline, task budget, or failure budget. It does not resume deferred work automatically. Review `.emberlane/supervisor.jsonl` for metadata-only audit events; the file deliberately excludes task payloads and raw exception text. Run one supervisor process per queue file. To include the GitHub mailbox, pass `--mailbox-repo xiiitore/emberlane --mailbox-issue 6 --mailbox-author xiiitore --poll-interval 5 --max-idle-polls 3`. This requires preconfigured GitHub CLI authentication. Mailbox polling is bounded; it stops after the configured idle-poll budget and never resumes deferred tasks automatically.

Guarded publishing is explicit: `git_commit` accepts only an explicit list of changed paths, refuses pre-staged changes, and runs the full test suite before committing. `git_push` requires a clean worktree, verifies that the remote head is an ancestor, never force-pushes, and verifies the remote SHA. Neither operation is triggered automatically by `supervise`.

Inspect the persisted result for the exact task ID. Diagnose failed tasks before resubmitting. If deferred, resume only through the supported explicit path after the external wait has changed.

## Before a code-writing task

1. Identify target files and intended change.
2. Check branch and worktree.
3. Ensure a backup or disposable worktree exists.
4. Confirm path and size constraints.
5. Apply one bounded patch or small batch.
6. Inspect changed paths and run git diff --check.
7. Run the narrowest relevant test first.
8. Run the full suite when feasible.
9. Inspect the final diff, not just test output.
10. Record the result; commit, push and merge remain explicit release steps.

A batch of writes is not necessarily atomic and is not a substitute for a transaction.

## Incident: provider quota or rate limit

1. Stop new provider calls.
2. Verify the task is deferred and record its ID and redacted reason.
3. Confirm the supervisor is waiting rather than polling rapidly.
4. Preserve queue state and logs.
5. Resume only through the explicit supported path after the wait condition changes.
6. Confirm one resumed execution and verify its final result.

Do not guess a reset time. Use provider-supplied retry-after only when present and validated. Authentication errors and invalid requests are not quota waits.

## Incident: model not configured or fails to load

Distinguish missing CLI, runtime/library failure, unset model path, unreadable model, unsupported format, memory/context limits, timeout, and malformed/truncated output.

Check the exact configuration before retrying. Do not scan the whole device or automatically download another large model. A version check proves only that the executable starts. Use a bounded inference smoke test in a disposable context before claiming readiness.

## Incident: queue corruption or unexpected state

1. Stop all writers.
2. Copy the queue and related logs before repair.
3. Record file size, timestamp and hash.
4. Inspect a copy; do not replace malformed state with an empty queue.
5. Recover only through a documented migration or reviewed manual procedure.
6. Validate IDs, statuses, attempts and idempotency keys.
7. Test recovery against a copy before resuming.

If multiple processes wrote the same file, assume possible lost updates; atomic rename does not fix concurrent-write races.

## Incident: completed task but verification failed

1. Preserve the original result and log.
2. Record test command and exit code.
3. Treat outcome as untrusted and stop dependent plan steps.
4. Add a regression test for the misclassification.
5. Fix the classifier and test failing and successful cases.
6. Rerun on the exact revision and inspect dependent behavior.

## Incident: worker loop does not stop

1. Use the documented pause/stop mechanism, if implemented.
2. Verify it is checked before new work and between steps.
3. If necessary, terminate the process without deleting queue or logs.
4. Inspect running tasks after restart; recovery may repeat handlers.
5. Determine whether a side effect occurred before interruption.
6. Add a bounded stop test before re-enabling unattended execution.

## End-of-session record

Record branch and commit, processed task IDs and statuses, tests and exit codes, changed files and diff summary, deferred tasks and reasons, unresolved blockers, pause state, and next safe action. Never claim completion while tasks remain deferred or verification is missing.

## Queue maintenance

Use the allow-listed `queue_prune` task only when the queue has accumulated terminal records. It creates a local backup before rewriting the queue, removes only old `completed`, `failed`, or cancelled records, and keeps the newest configured number of terminal records. Pending, running and deferred tasks are preserved. The backup remains local and can contain task payloads; do not publish it. Example: `python -m emberlane submit queue_prune --payload '{"keep_terminal":50}'`, then execute one task with `python -m emberlane run-one`.
