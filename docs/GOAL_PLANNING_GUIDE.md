# Goal planning guide

## Purpose

The goal planner turns a bounded list of task steps into queue work. It does not generate code by itself, run arbitrary shell commands, or override the worker's allow-list. A plan is a declarative sequence of existing task kinds with explicit dependencies.

## Submit a plan

From the project root, submit a JSON object as the plan_goal payload. Example:

    python -m emberlane submit plan_goal --payload '{"goal_id":"inspect-and-test","steps":[{"id":"inspect","kind":"diagnostics","payload":{}},{"id":"tests","kind":"run_tests","payload":{},"depends_on":["inspect"]}],"max_steps_per_cycle":2,"max_cycles":5}'

Then execute one task at a time:

    python -m emberlane run-one
    python -m emberlane status

Repeat the run-one/status cycle under a bounded supervisor. The planner may enqueue a continuation task when additional cycles are needed. Do not start multiple workers against the same queue file.

## Plan schema

Top-level fields:
- goal_id: required non-empty string, maximum 120 characters;
- steps: required list of 1–50 step objects;
- max_steps_per_cycle: optional integer from 1 to 10; default 3;
- max_failures: optional integer from 1 to 5; default 2;
- max_cycles: optional integer from 1 to 50; default 20;
- cycle: optional integer from 0 through max_cycles; default 0.

Each step:
- id: unique non-empty string, maximum 120 characters;
- kind: must be a registered task kind allowed by the planner;
- payload: object; defaults to an empty object;
- depends_on: list of other step IDs; defaults to an empty list.

The planner rejects duplicate step IDs, unknown dependencies, duplicate dependency entries, self-dependencies, dependency cycles, unregistered task kinds, malformed payload objects and out-of-range limits before enqueuing steps.

## Dependencies and scheduling

A step with no dependencies can be scheduled when the plan is advanced. A dependent step remains blocked until all required predecessors have completed successfully according to their task results. A predecessor that is failed or returns explicit negative result evidence blocks dependent work. A deferred predecessor represents a wait, not success; dependent work must not run until the prerequisite is resumed and succeeds.

The planner schedules no more than max_steps_per_cycle new steps in one cycle. A continuation task advances the next cycle when work remains. Both the total step count and total cycle count are bounded. These limits protect against runaway plans but do not replace a supervisor-level wall-clock deadline or stop marker.

## Idempotency

The planner assigns stable idempotency keys to goal steps and continuation cycles. Replaying the same cycle should not duplicate an already-enqueued step with the same key and payload. Reusing an idempotency key with a different kind or payload is an error.

Idempotent enqueueing does not guarantee that the side effect itself is exactly once. A process can stop after writing a file or contacting an external system but before persisting completion. Use guarded writes, remote state reconciliation or disposable worktrees for operations that may repeat.

## Safe workflow pattern

1. Start with a diagnostics or read-only inspection step.
2. Use small bounded edits rather than a single large opaque operation.
3. Run targeted tests after an edit.
4. Run the full suite only when the targeted result is meaningful and the device budget permits it.
5. Inspect changed files and diff metadata before release.
6. Keep commit, push, merge and external publication as explicit release steps.
7. Preserve the task IDs and final statuses in the handoff report.

## Important limitations

- A goal plan is not an LLM coding agent. It schedules tasks that are already registered.
- The planner does not prove the task payload is semantically correct; handlers must validate their own inputs.
- The queue is file-backed and single-writer.
- Generic exceptions may be retried according to queue policy; invalid plans should be corrected rather than continuously resubmitted.
- The CLI run-one command executes at most one task.
- Hosted tests do not prove Termux-specific behavior.
