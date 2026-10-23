# Testing and release gates

## Principle

Every claim must be scoped to the evidence supporting it. Unit tests, hosted CI, device preflight, local inference, an end-to-end coding task and unattended operation prove different things.

## Evidence levels

| Level | Evidence | Permitted claim |
|---|---|---|
| E0 — source inspected | Relevant code and configuration read | Implementation inspected; no runtime claim |
| E1 — static checks | Compilation or static analysis | Static checks pass for named revision/checks |
| E2 — unit tests | Exit code zero and full test output retained | Unit tests pass for named environment |
| E3 — hosted CI | Required jobs pass on exact commit | Hosted CI passes for those jobs and versions |
| E4 — device preflight | Read-only checks on target Termux | Basic prerequisites pass; no inference claim |
| E5 — local inference | Exact model loads and completes bounded smoke test | Inference works for tested configuration |
| E6 — isolated edit cycle | Disposable worktree edit, tests and diff review | Local coding cycle passed for tested task |
| E7 — recovery and quota exercise | Forced-stop, duplicate and deferred/resume tests | Named recovery scenarios pass |
| E8 — bounded unattended soak | Defined duration/workload with no lost tasks or uncontrolled retries | Observed soak passed; not universal reliability |

A level does not imply all lower levels unless their evidence is retained for the same revision.

## Minimum merge gate for behavior changes

- [ ] Modules compile.
- [ ] Unit tests pass on supported Python versions.
- [ ] New behavior has focused regression tests.
- [ ] Negative cases are tested, not only happy paths.
- [ ] Persisted schema compatibility is considered.
- [ ] Logs and outputs are bounded and do not expose secrets.
- [ ] Documentation matches the implementation.
- [ ] CI is green for the exact head commit.
- [ ] PR base and dependencies are correct.
- [ ] No device-readiness claim is inferred from hosted CI.

## Minimum local readiness gate

- [ ] Correct repository and branch identified.
- [ ] Existing uncommitted work is preserved or isolated.
- [ ] Python version and dependencies confirmed.
- [ ] Queue parses and is backed up before schema migration.
- [ ] Read-only preflight passes without blockers.
- [ ] Configured CLI version check passes.
- [ ] Exact model file is readable.
- [ ] Minimal inference completes within explicit timeout and output budget.
- [ ] Disposable worktree accepts a trivial patch.
- [ ] Path validation rejects traversal and protected targets.
- [ ] Targeted and full tests pass.
- [ ] Diff contains only intended changes.
- [ ] Forced interruption recovers without silent task loss.
- [ ] Quota wait defers without busy-looping.
- [ ] Explicit resume preserves task identity and triggers one retry.
- [ ] Pause marker stops new work at a defined safe boundary.

Untested boxes are UNKNOWN or BLOCKED, not assumed PASS.

## Regression design

Prefer deterministic tests using temporary directories and fake executables. Normal unit tests should not require a large model, network access, a GitHub token or the user's live repository.

For subprocess handlers test zero exit, non-zero exit, timeout and missing executable; fixed/allow-listed arguments; output bounds; and that secrets are not inherited by default.

For queue behavior test atomic save, malformed-state failure, restart recovery, idempotency conflicts, quota wait, explicit resume, no immediate re-execution and nested result classification.

For workspace behavior test traversal, absolute paths, symlink escape, protected components, oversized content and duplicate batch targets. Verify validation occurs before changes and partial batch failure is reported honestly.

For planner behavior test unknown kinds, duplicate IDs, unknown dependencies, cycles, excessive steps and invalid bounds. Failed/deferred dependencies must block downstream execution, and validation must precede all enqueues.

## Reporting format

Every operational report should include repository and branch, exact commit SHA, runtime version, exact command or workflow URL, exit status, passed/failed/skipped counts, concise failure evidence and scope limitations. Redact secrets and bound logs.

## Release decision

- PASS — required gates are satisfied with evidence.
- REVISE — concrete fixable defects remain.
- BLOCKED — required evidence or environment access is missing.
- REJECT — design violates a non-negotiable safety or correctness constraint.

A draft PR with green CI may be ready for review, but is not merged or released. A local preflight without inference is not model readiness. One successful task is not proof of unattended reliability.
