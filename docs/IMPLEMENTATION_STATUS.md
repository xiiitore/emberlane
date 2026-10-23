# Tracked implementation status

Last evidence review: 2026-10-23 23:08 Europe/Zagreb  
Repository: `xiiitore/emberlane`  
Working branch: `feat/local-coding-worker`  
Latest verified hosted-test head at review time: `5b94680c5e3506ef5c91fd24b01d87b3ac076177`

This file records observed evidence, not intended capability. Update it whenever a gate changes. Do not mark device gates PASS from hosted CI or mock-runtime tests.

## Current gates

| Gate | Status | Evidence / limitation |
|---|---|---|
| Hosted push test suite | PASS | Run [40024215793](https://github.com/xiiitore/emberlane/actions/runs/40024215793): 154 tests passed on Python 3.11, 3.12 and 3.13; all four jobs (including push-smoke) succeeded. |
| Quota classification regression | PASS | Generic `resource exhausted` is no longer sufficient for a quota wait. The regression checks ordinary retry/failure behavior and ensures the task is never `deferred`. Included in the 153-test run above. |
| Local model adapter — deterministic tests | PASS (hosted only) | Fake-process tests cover configuration, CLI/model path errors, bounded stdout/stderr, timeout, parse failures, pause behavior and patch-validation paths. Does not prove inference on the target model. |
| Queue prune implementation | PASS (code/hosted tests only) | `queue_prune` archives the queue before deleting older terminal records, retains a configurable number of terminal tasks, and preserves pending/running/deferred work. |
| Mailbox result publication | PASS (hosted code/CI only) | Public comments use an allow-list of metadata; full sanitized logs are sent to Dropbox, with a local-only fallback if Dropbox is unavailable. |
| Python 3.11/3.12/3.13 matrix on latest verified code head | PASS | Run [40024215793](https://github.com/xiiitore/emberlane/actions/runs/40024215793): all three versions passed 154 tests each. The matrix was triggered by the explicit `[full-matrix]` commit marker. Later status-document-only commits do not change code and are ignored by unit CI. |
| Local Termux queue prune | BLOCKED / UNKNOWN | A `queue_prune` request is still pending on GitHub issue #6; no worker result has confirmed backup path, pruned count, retained terminal count and preserved active-task count. |
| Active Termux checkout reconciliation | BLOCKED | Last observed local status: dirty worktree and 364 commits behind remote. Do not reset, clean, force-sync, or overwrite untracked/local-only files. |
| Termux read-only preflight on target device | UNKNOWN | No fresh result for the current remote revision. |
| Real llama.cpp inference using the configured GGUF model | UNKNOWN | Explicitly not run by operator instruction. Earlier model loading failure remains undiagnosed by fresh device evidence. |
| Full local model → disposable patch validation → test → apply cycle on Termux | UNKNOWN | Hosted tests validate components; no current end-to-end device evidence. |
| Local-only supervisor integration | BLOCKED / UNKNOWN | A prior worker log contains `scripts/codex-autopilot-supervisor.sh`, but the file is not present at that path in the remote branch. Do not replace the local untracked copy without a fresh comparison and backup. Its full lifecycle is not proven by repository CI. |

## Safety and operating rules

- Do not run a model inference smoke test unless explicitly requested.
- Never claim the local queue was cleaned without the local worker's result and a verified backup.
- Preserve local-only files and dirty changes. Remote branch updates do not install themselves into Termux.
- Do not automatically commit, push, merge or delete local changes as part of model editing.
- Keep only high-value deterministic regression tests; avoid repeated full matrices on every push. The current CI runs the suite on Python 3.13 for code/workflow pushes and the 3.11/3.12/3.13 matrix on pull requests. Documentation-only pushes and pull requests skip unit CI to avoid redundant runs.
- After a failure, inspect the exact failing assertion and workflow log, fix the test or implementation based on the observed contract, then verify the new head.

## Next actions

1. Obtain a live local-worker result for the already queued `queue_prune` task; verify archive and counts before reporting cleanup.
2. Reconcile the dirty Termux checkout without losing local-only files; do not use forced sync.
3. Run the full compatibility matrix on the release candidate.
4. Integrate and test supervisor pause/stop/deadline and restart-reconciliation behavior without creating a parallel supervisor.
5. Only after the operator permits it, run the real-model smoke test and bounded end-to-end device cycle.
