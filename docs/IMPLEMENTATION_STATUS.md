# Tracked implementation status

Last evidence review: 2026-10-24 Europe/Zagreb  
Repository: `xiiitore/emberlane`  
Remote source snapshot inspected during this review: `6bd21c7db936fd1eb77124c70734b2b25d92dea4`

This file records observed evidence, not intended capability. Hosted CI, worker-reported results, and target-device verification are distinct evidence classes. Do not mark device gates PASS from hosted CI or mock-runtime tests.

## Current gates

| Gate | Status | Evidence / limitation |
|---|---|---|
| Hosted Python compatibility tests | PASS (historical runs; not a claim about every current head) | Run [40024215793](https://github.com/xiiitore/emberlane/actions/runs/40024215793) passed the 3.11/3.12/3.13 matrix at the then-verified head `5b94680c5e3506ef5c91fd24b01d87b3ac076177`. Later PR-specific runs must not be represented as tests of current main. |
| Local model adapter — deterministic tests | PASS (hosted only) | Fake-process tests cover configuration, CLI/model path errors, bounded output, timeout, parse failures, pause behavior and patch validation. This does not prove inference with the target GGUF model on Termux. |
| Queue-prune implementation | PASS (code/hosted tests only) | The implementation archives the queue before pruning older terminal records and preserves active/nonterminal work in tested code paths. |
| Local Termux queue-prune task | PARTIAL — worker-reported PASS; integrity UNKNOWN | Issue [#36 comment](https://github.com/xiiitore/emberlane/issues/36#issuecomment-6384159014) records task `d473c072-907c-4b63-b154-feefee57aa56` and Dropbox log `/Apps/Emberlane Worker/worker-logs/d473c072-907c-4b63-b154-feefee57aa56.md`. Worker-reported: 617 terminal records pruned, 50 retained, 1 active record preserved; backup path reported as `queue.json.pre-prune-1792832676943354664.bak`. The log has not been independently reconciled against the actual local queue and backup, so archive integrity and counts remain UNKNOWN. |
| Mailbox result publication | PASS (hosted code/CI only) | Public comments use allow-listed metadata; full sanitized logs are sent to Dropbox, with a local-only fallback if Dropbox is unavailable. Redaction is not a guarantee that arbitrary sensitive data cannot appear. |
| Active Termux checkout reconciliation | BLOCKED | Last device-side report: dirty worktree and 364 commits behind remote. This is a prior observation, not a fresh status check. Do not reset, clean, force-sync, or overwrite untracked/local-only files. |
| Termux read-only preflight on target device | UNKNOWN | No fresh preflight result for the reviewed remote source snapshot. |
| Real llama.cpp inference with configured GGUF model | BLOCKED / UNKNOWN | Prior device output reported `no backends are loaded` / `Failed to load the model` (exit 1). A separate worker task reported `model_not_configured`, `applied:false`. These are distinct failures; neither has been resolved by fresh device evidence. |
| Worker receives model configuration | UNKNOWN | Remote backend reads `EMBERLANE_MODEL_PATH` from the Python worker process environment. An export in a separate interactive shell does not prove that an already-running worker/supervisor inherited it. The actual launch boundary has not been verified. |
| Full Termux model → disposable patch validation → tests → apply → Dropbox read-back cycle | UNKNOWN | No current end-to-end device evidence. Hosted component tests do not satisfy this gate. |
| Supervisor pause/stop/deadline and restart reconciliation | PARTIAL / UNKNOWN | The remote `supervise` command is documented as a finite batch, not a permanent background service. Local-only supervisor/loop files may differ from remote source; do not replace them without inspection and backup. |
| Retry-limit recovery for interrupted tasks | PR review pending | Draft [PR #61](https://github.com/xiiitore/emberlane/pull/61) proposes preventing re-execution of recovered `running` tasks after `max_attempts`. Its description reports hosted matrix PASS, but the PR is unmerged; do not count it as current main behavior. |

## Safety and operating rules

- Do not run real model inference unless explicitly requested by the operator.
- Never claim the local queue was cleaned or its backup is valid without independent read-back.
- Preserve local-only files and dirty changes. Remote branch updates do not install themselves into Termux.
- Do not automatically commit, push, merge, or delete local changes as part of model editing.
- Avoid repeated full matrices when no code or workflow behavior changed; verify the exact commit and run before citing CI.
- After a failure, inspect the exact assertion/log, change only the demonstrated cause, and verify the resulting commit.
- Do not weaken symlink/no-follow/path confinement protections merely to silence a workspace error.

## Next actions

1. From the existing worker/device, read back the queue and reported backup without starting a second prune; compare counts and verify the backup is readable and protected.
2. Preserve the dirty Termux checkout. Inspect its exact branch/HEAD/status before any reconciliation; no forced sync.
3. Diagnose llama.cpp backend/runtime loading separately from whether the worker process receives `EMBERLANE_MODEL_PATH`. First inspect the actual launch environment with a redacted boolean probe; do not dump the full environment or restart/duplicate a worker before identifying its lifecycle.
4. Run the read-only Termux preflight against the existing checkout and record exact command, exit status, and sanitized result.
5. Only after explicit operator approval, run one bounded real-model smoke test, then a disposable end-to-end edit/test/apply/read-back cycle.
6. Review PR #61 and supervisor stop/recovery behavior separately; do not merge based solely on the PR description.

Readiness remains BLOCKED until target-device inference, safe edit/test/apply, queue/backup reconciliation, and stop/resume/restart behavior have direct evidence.
