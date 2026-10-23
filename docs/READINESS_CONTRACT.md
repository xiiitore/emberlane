# Emberlane readiness gates

This is an acceptance checklist, not a claim that the local Termux setup has passed.

## Success semantics

A queue task is successful only when its structured result contains no explicit failure evidence. Results such as `passed: false`, nonzero `returncode`, `synced: false`, `ok: false`, or `status: blocked` must not unlock dependent planner steps.

Known external capacity limits, including a Codex usage limit, become `deferred`: pause dependent work, do not retry automatically, and do not describe the condition as a repository defect. When capacity is available, use `resume-deferred TASK_ID`; the worker requeues the task and schedules a continuation for a goal plan that was waiting on it. This is explicit resumption, not provider polling.

## Readiness gates

- [ ] Confirm the Termux Python, llama-cli, and configured GGUF paths; verify the model file exists and is readable.
- [ ] Run one minimal local-model prompt with a hard timeout and capture exit code plus output.
- [ ] Confirm context/file limits do not reject required worker inputs.
- [ ] Complete one disposable end-to-end coding task: propose a change, apply it, run a focused test, inspect the diff, and preserve unrelated dirty files.
- [ ] Confirm a real operation/test failure blocks dependent steps.
- [ ] Confirm a known quota limit becomes deferred without a retry loop.
- [ ] Confirm deferred-task resumption continues the waiting plan.
- [ ] Confirm duplicate mailbox delivery is idempotent and interrupted tasks recover without losing task identity.
- [ ] Run the existing unit suite and retain the exact command, exit code, summary, and available log.
- [ ] Independently inspect the published task result, changed paths, test status, redaction, and truncation.
- [ ] Report PASS/FAIL/BLOCKED/UNKNOWN from evidence; never infer success from process exit or a queue label alone.

## Real-model Termux smoke test

Run this only after the unit suite passes. It performs one actual `local_model_edit` against a temporary fixture and deletes that fixture on exit; it does not edit the repository checkout.

```sh
export EMBERLANE_MODEL_PATH="$HOME/models/qwen2.5-coder-0.5b-instruct-q4_0.gguf"
export EMBERLANE_LLAMA_CLI="$(command -v llama-cli)"
python scripts/local-model-edit-smoke.py
```

Keep any `LD_LIBRARY_PATH` required by the local llama.cpp build in the invoking shell. Exit code `0` plus result status `applied_and_verified` is the acceptance condition; a CLI load test alone is not proof of the coding cycle.
## Operating discipline

Reuse prior evidence unless code, configuration, inputs, or environment changed. Run the smallest test that can falsify the current hypothesis, then the existing suite after relevant changes. Preserve the user's working tree. A remote GitHub edit does not prove the local Termux checkout or local model is working.
