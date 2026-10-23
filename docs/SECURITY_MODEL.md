# Security model and threat boundaries

## Objective

Prevent routine coding tasks from escaping the configured workspace, executing payload-provided commands, corrupting queue state silently, or publishing sensitive material through logs. This is defense in depth, not a claim of hostile-code sandboxing.

## Assets

- repository source, tests and uncommitted user changes;
- credentials in environment variables, home directory or Git configuration;
- queue state, task results and audit logs;
- GitHub repository write permissions and issue/PR content;
- model inputs, outputs and generated patches;
- device availability, battery and storage.

## Threats and controls

| Source | Hazard | Required control |
|---|---|---|
| Malformed task payload | path traversal, oversized writes, invalid plan | schema checks, resolved paths, byte limits |
| Prompt-injected repository content | model follows embedded instructions | treat files as data; model cannot expand tool permissions |
| Generated code | destructive effects during tests | disposable worktree, fixed test command, timeout, diff review |
| Compromised dependency/tool | arbitrary code execution | minimal dependencies, verified releases, no secrets in test environment |
| External API/provider | quota, stale result, duplicate request | explicit wait state, bounded retries, idempotency/reconciliation |
| Concurrent workers | lost queue updates | enforce one writer or use transactional storage |
| Logs and comments | source or secret disclosure | allow-listed public metadata, recursive secret redaction, bounded output; raw exception text omitted |
| Task-log delivery | lost logs or commit amplification | local log first, Dropbox upload with SHA-256 read-back verification; no per-task GitHub file commits |
| Device pressure | runaway loops, full storage, battery drain | finite budgets, pause marker, deadlines, log rotation |

## Safeguards visible in current source

- Explicit task-handler registry; README does not expose a generic arbitrary-shell task kind.
- Workspace abstraction validates file operations and enforces a configured size limit.
- Worker policy blocks known protected path components and names.
- Test execution uses a fixed unittest command and timeout rather than a payload-supplied shell string.
- Queue persistence uses a same-directory temporary file, flush/sync and atomic replacement.
- Plans are bounded and only allow registered task kinds.
- CI compiles modules and runs unit tests across Python 3.11–3.13.

These controls do not constitute an OS sandbox. A compromised Python process can use filesystem and network permissions available to its account.

## Known limitations; do not overclaim

- Path checks do not prevent malicious test code from making direct system calls.
- Atomic replacement does not coordinate multiple queue writers.
- Multi-file writes are not one transaction; failure halfway through may leave a partial batch.
- Tests execute repository code and must not receive production credentials.
- Git synchronization can change the worktree; validate branch and dirty-worktree policy first.
- Logs can contain sensitive output unless each handler bounds and redacts it.
- Model output can be incomplete, invalid or unsafe.
- A readable model file does not prove that it loads, fits memory or generates useful code.
- Passing Linux CI does not prove Android/Termux compatibility.
- A pause marker is useful only if every relevant loop checks it at safe boundaries.

## Policy for generated edits

1. Start from a known revision in a disposable worktree whenever possible.
2. Never overwrite the only copy of uncommitted user work.
3. Reject targets outside the repository root and symlink escapes after resolving paths.
4. Preflight all paths and content sizes before multi-file writes.
5. Keep tests offline by default and remove secrets from the child environment.
6. Run targeted tests first, then the full suite when feasible.
7. Inspect diff check, changed-file list and diff before proposing a commit.
8. Do not auto-merge or push generated code to the default branch without explicit release policy.
9. Missing test results mean unverified, not pass.
10. Preserve rollback and identify exactly which files a task may change.

## Secrets policy

Never write tokens, API keys, private keys, cookies or full environment dumps to queue state, logs, issue comments or PR descriptions. Redaction is defense in depth, not permission to collect secrets. Do not upload local prompts or source files to a remote provider unless the task explicitly authorizes transfer. Prefer minimum GitHub permissions and separate read/write capabilities.

## Release-blocking security checks

Block release if path traversal or symlink escape is reproducible; payload can select arbitrary executables; a secret appears in a log; ambiguous results are marked completed; quota causes rapid retries; recovery repeats a non-idempotent side effect without reconciliation; tests mutate the only copy of user work without warning; or local readiness is claimed without local evidence.
