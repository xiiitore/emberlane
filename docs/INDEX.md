# Documentation index

This index separates current implementation instructions from design contracts and device-specific readiness evidence.

## Start here

- [Goal planning guide](GOAL_PLANNING_GUIDE.md) — bounded declarative plans, dependency scheduling and CLI usage.

- [README](../README.md) — installation, existing CLI examples, worker boundaries and GitHub issue mailbox.
- [Termux readiness runbook](TERMUX_READINESS_RUNBOOK.md) — read-only prerequisite checks and a staged local validation sequence.
- [Operations runbook](OPERATIONS_RUNBOOK.md) — start/end-of-session checks and recovery procedures for quota waits, model failures, queue corruption and unsafe task results.

## Architecture and behavior

- [Architecture](ARCHITECTURE.md) — components, execution path, trust boundaries and invariants.
- [Agent-fleet governance and Hugging Face evaluation](AGENT_FLEET_GOVERNANCE.md) — model/framework boundaries, source-backed fleet incident context, telemetry contract and staged acceptance plan.
- [Task state machine](TASK_STATE_MACHINE.md) — status semantics, recovery, retry policy, idempotency and result classification.
- [Model/provider adapter contract](ADAPTER_CONTRACT.md) — explicit adapter inputs/outputs, local runtime readiness and conformance requirements.

## Security and quality

- [Security model](SECURITY_MODEL.md) — assets, threat scenarios, current safeguards, known limitations and release blockers.
- [Testing and release gates](TESTING_AND_RELEASE_GATES.md) — evidence levels E0–E8 and merge/local readiness criteria.
- [Tracked implementation status](IMPLEMENTATION_STATUS.md) — current PASS/PENDING/BLOCKED/UNKNOWN gates with exact revision and evidence boundaries.

## How to interpret claims

- Hosted CI is evidence for the commit and workflow jobs that actually ran; it is not a Termux execution result.
- A read-only preflight does not prove model inference.
- A model inference smoke test does not prove the model can safely edit code.
- A successful edit task does not prove recovery, quota handling or unattended operation.
- Documents marked as contracts or extension points may describe intended behavior that still needs implementation and tests.

## Documentation change rule

When behavior changes, update the relevant contract and regression tests in the same PR. Keep the documentation explicit about what is implemented, what is planned and what remains unverified.
