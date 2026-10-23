# Task state machine and recovery contract

## Scope

This contract describes the intended meaning of task lifecycle states. If this document and executable behavior disagree, the implementation and tests are authoritative until a code change resolves the discrepancy.

## States

| State | Meaning | Normal execution eligible? |
|---|---|---|
| pending | Persisted and waiting to be claimed | Yes |
| running | Claimed; outcome not yet committed | No while the same worker is active |
| completed | Handler returned a result without recognized explicit failure evidence | No |
| failed | Terminal task failure observed | No; retry requires explicit policy |
| deferred | External wait or explicit postponement prevents execution | No; requires resume policy |
| cancelled | User or supervisor cancelled the task, if implemented | No |

Do not add a state to this table without implementing transitions, persistence, CLI behavior and tests.

## Allowed transitions

- pending -> running
- running -> completed
- running -> failed
- running -> deferred
- running -> pending during restart recovery; at-least-once semantics apply
- deferred -> pending through explicit resume
- pending -> cancelled only if cancellation is implemented

A terminal state must not silently reopen during ordinary polling. Requeueing failed work should record why. Deferred work must not be retried continuously while the external condition remains unchanged.

## Result classification

A normal Python return is not sufficient evidence of success. The classifier should inspect explicit negative indicators:
- boolean false for contract keys such as ok, success, passed, synced, applied or verified;
- failure values in status or state;
- non-zero integer returncode or exit_code; booleans must not count as integers;
- a non-empty error field.

Do not infer success from absent fields when a handler contract requires them. A test handler should return its exit code and concise summary. A sync handler should report whether the expected branch and revision were observed.

Nested results need a deliberate policy. Recursively treating every nested ok=false as fatal is conservative but can misclassify informational sub-results. If nested results are used, define authoritative keys and test both false-positive and false-negative cases.

## External waits and quota handling

A recognized provider quota or rate-limit error should produce a deferred task with the original task ID, preserved attempt count and timestamps, a stable redacted wait reason, no immediate retry loop, and a documented resume path. A new attempt should occur only after explicit resume or a controlled scheduler condition that has been verified.

Do not classify every generic exception containing “limit” as a quota wait. Prefer known exception classes and stable HTTP/status metadata. Keep provider-specific matching in an adapter or small tested classifier.

## Crash recovery

The queue recovers persisted running tasks to pending on load. This is at-least-once execution, not exactly-once execution.

Failure window:
1. a handler performs an external side effect;
2. the process exits before recording completion;
3. restart sees running and requeues the task;
4. the side effect may happen again.

Mitigations:
- make side effects idempotent using a stable idempotency key;
- check remote/local state before applying an operation;
- use an atomic transaction where supported;
- require confirmation for irreversible or high-impact effects;
- otherwise record uncertainty and reconcile instead of blindly retrying.

A task-level idempotency key prevents duplicate enqueueing only if scope and payload-equivalence behavior are correct. It does not automatically make the handler's side effect idempotent.

## Persistence contract

- Serialize complete task records in deterministic JSON-compatible form.
- Write to a temporary file in the same directory, flush and sync it, then atomically replace prior state.
- If writing fails, preserve prior queue state and surface the persistence error.
- Do not initialize an empty queue when an existing queue is malformed.
- Directory metadata durability after rename may require syncing the parent directory; verify platform support before claiming power-loss durability.
- Atomic replacement does not prevent lost updates between concurrent processes.

## Required regression scenarios

1. Successful handler result persists and completes.
2. Explicit ok=false becomes failed.
3. Non-zero return code becomes failed.
4. Nested error result follows the documented policy.
5. Recognized quota error becomes deferred without immediate retry.
6. Unrelated exception becomes failed, not deferred.
7. Explicit resume changes deferred to pending once.
8. Restart recovery requeues running tasks at the documented attempt-count point.
9. Duplicate idempotency key with identical input returns the existing task.
10. Duplicate key with conflicting input is rejected.
11. Corrupt state fails closed and is not overwritten.
12. Failed save leaves the previous state intact.
