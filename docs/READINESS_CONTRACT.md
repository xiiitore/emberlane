# Emberlane readiness gates

This is an acceptance checklist, not a claim that the local Termux setup has passed.

## Success semantics
Queue status `completed` means a handler returned without raising. It does not prove the operation succeeded. Structured results such as `passed: false`, nonzero `returncode`, `synced: false`, `ok: false`, or `status: blocked` must block dependent planner steps and must not be reported as PASS. Expected external capacity limits (for example, a known Codex usage limit) must be returned as `status: deferred` or `status: rate_limited`: pause dependent work without retry loops, do not mislabel the condition as a code defect, and resume only when capacity is available.

## Tomorrow's release gates
- [ ] Resolve the actual Termux Python, llama-cli path, and configured GGUF path; verify the model file exists and is readable.
- [ ] Run one minimal local-model prompt with a hard timeout and capture exit code plus output.
- [ ] Confirm source/context limits do not reject the worker's own required files; missing model, oversized input, malformed output, and timeout must be explicit failures.
- [ ] Run a disposable end-to-end coding task: propose change, apply it, run a focused test, inspect the diff, and preserve unrelated dirty files.
- [ ] Confirm a real test failure blocks the goal and prevents dependent steps from running.
- [ ] Confirm an expected provider quota/usage limit yields a waiting/deferred state with no automatic retry loop or claim that the repository code is broken.
- [ ] Prove duplicate mailbox delivery is idempotent and interrupted tasks recover without losing task identity.
- [ ] Prove the supervisor continues to the next valid task after one task fails.
- [ ] Run the full unittest suite and retain the exact command, exit code, test summary, and complete available log.
- [ ] Fetch the published result and full task log from GitHub; independently verify the task ID, changed paths, tests, redaction, and truncation.
- [ ] Report PASS/FAIL/BLOCKED/UNKNOWN from evidence. Never infer success from a process exiting or a queue label alone.

## Operating discipline
Reuse prior evidence unless code, configuration, inputs, or environment changed. Run the smallest test that can falsify the current hypothesis; run the full suite after relevant changes. Preserve the user's working tree. Never claim that a remote GitHub edit proves the local Termux checkout or local model is working.
