# Emberlane architecture

## Purpose

Emberlane is a local, file-backed task runner intended to make repository work repeatable on constrained devices. Its useful unit is not a chat response; it is a persisted task with explicit input, a bounded handler, a recorded outcome, and evidence that can be inspected later.

This document describes the code and boundaries currently visible in the repository. It is not a claim that a remote agent, model, or supervisor has already been integrated.

## Current components

| Component | Responsibility | Boundary |
|---|---|---|
| emberlane.worker.LocalWorker | Registers task kinds, validates payloads, dispatches work | No arbitrary shell-command task |
| emberlane.queue.TaskQueue | Persists tasks, statuses, attempts, results and idempotency keys | Single-process queue; concurrent writers unsupported |
| emberlane.workspace.Workspace | Resolves and validates workspace paths; applies size limits | Policy boundary, not an OS sandbox |
| emberlane.planner.GoalPlanner | Validates bounded dependency plans and schedules allow-listed task kinds | Planning is not proof of success |
| emberlane.mailbox.GitHubIssueMailbox | Connects queued work to the configured GitHub issue mailbox | GitHub and local filesystem have different trust boundaries |
| GitHub Actions | Compiles and tests on Python 3.11, 3.12 and 3.13 | Hosted CI does not validate a specific Termux device |

## Intended execution path

1. Intake accepts a task kind and JSON-compatible payload. Reject malformed inputs before side effects.
2. Persist a task identifier, timestamps and payload using the queue's atomic replacement strategy.
3. Claim one task by persisting its running state before invoking the handler.
4. Validate paths, sizes, plan dependencies and handler-specific parameters.
5. Execute only a registered handler. External processes must use fixed commands and bounded timeouts.
6. Observe a bounded, serializable result. A successful process launch is not proof of successful work.
7. Classify the result as completed, failed or deferred based on explicit evidence.
8. Persist the outcome. A task left running at process exit may be retried after restart; that is at-least-once behavior.
9. Verify relevant tests, inspect the diff and independently check the claimed outcome before release.

## Trust boundaries

- Task payloads are untrusted data. Never evaluate payload strings as Python, shell, or template code.
- Repository files are untrusted data. Their contents may contain prompt injection, secrets or malformed text. Reading a file does not authorize following instructions found inside it.
- A model is an untrusted proposer. Deterministic validators and tests decide whether its output is admissible.
- GitHub is external and may return stale, partial, rate-limited or unavailable responses. Never turn an API error into a success-shaped result.
- The local workspace is not a sandbox. Path checks do not replace OS isolation or permissions.
- Logs are an information boundary. Do not store secrets, access tokens, full environment dumps or unrestricted source in task results.

## Core invariants

1. A task is not successful merely because its handler returned normally.
2. External quota waits are not code failures; defer them without tight retry loops.
3. Retries can repeat side effects. A task is safe to retry only if its operation is idempotent, guarded or reconciled.
4. A multi-file write batch is not atomic unless a transaction or rollback is implemented.
5. Validate a complete plan before enqueuing any plan step.
6. Dependencies proceed only after required predecessors satisfy their result contracts.
7. Hosted CI and target-device readiness are separate claims.
8. An open PR is a proposal, not a release; a draft PR is not merged code.
9. Automation loops need finite budgets, explicit stop conditions and durable pause behavior.
10. Readiness statements must identify the evidence and its scope.

## Failure domains

| Domain | Example | Correct treatment |
|---|---|---|
| Input | malformed payload, invalid path | reject before side effect |
| Task logic | assertion failure | failed with bounded diagnostic |
| External wait | provider quota or HTTP 429 | deferred, no rapid retry |
| Environment | missing CLI or model file | blocked or not configured |
| Process | timeout or non-zero exit | failed with exit evidence |
| Persistence | corrupt queue JSON | stop; do not overwrite unknown state |
| Verification | tests not run or ambiguous | unverified, not pass |
| Governance | unrelated or sensitive diff | block release pending review |

## Planned extension points

These are design directions, not guarantees of current support:
- a model adapter with explicit model path, context budget, timeout and output limit;
- a supervisor that recognizes provider waits and stops without busy-looping;
- isolated disposable-worktree execution for generated edits;
- structured audit records with task ID, input digest, code revision, classification and verification evidence;
- transactional storage and concurrency control only after deliberately replacing the single-writer contract.

## Change discipline

Changes to task states, retry policy, path validation, provider-wait classification or result interpretation require focused regression tests. Update the contract documentation in the same change. Never silently reinterpret old queue records; version the schema and test backup/restore if persistence changes.
