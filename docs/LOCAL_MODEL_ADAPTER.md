# Local model adapter contract

## Status

The `emberlane.local_model` module provides a bounded subprocess adapter for a locally installed llama.cpp CLI. It does not download weights or install software. This module is currently a library component; it is **not yet registered as a worker task handler** and does not constitute an end-to-end coding agent.

## Configuration

Set these environment variables in the process that invokes the adapter:

- `EMBERLANE_MODEL_PATH`: required absolute or home-relative path to an existing readable GGUF file.
- `LLAMA_CLI_BIN`: optional executable name or path; defaults to `llama-cli`.
- `EMBERLANE_MODEL_CONTEXT`: optional context token limit; defaults to 2048 and accepts 128–32768.
- `EMBERLANE_MODEL_MAX_TOKENS`: optional generation cap; defaults to 256 and accepts 1–4096.
- `EMBERLANE_MODEL_TIMEOUT`: optional wall-clock timeout in seconds; defaults to 120 and accepts 1–3600.

The adapter validates configuration and the model path before starting the process. Missing configuration returns the structured `not_configured` error. Model files must be obtained and installed separately by the operator.

## Invocation contract

`LocalModelRunner(config).generate(prompt)` returns a JSON-compatible mapping containing `ok`, `output`, `truncated`, `returncode`, elapsed time, model path, context size and generation cap.

Expected errors use `LocalModelError.code` to distinguish invalid configuration, missing executable, missing/unreadable model, invalid or oversized prompt, timeout, loader failure, non-zero exit and empty output. A caller should persist the error code and exit status; it must not turn any adapter error into a successful task.

The process is invoked with an argument vector and `shell=False`; stdin is closed. The configured generation and timeout bounds limit normal work, and returned text is capped. The adapter is not a security sandbox and does not prove that generated code is correct or safe.

## Validation

`tests/test_local_model.py` uses a fake executable and a placeholder model file. These tests verify adapter behavior without downloading a model or requiring a GPU. They do not prove that a real llama.cpp binary can load the user's model.

Before declaring local inference ready:

1. Run the hosted unit suite on supported Python versions.
2. Run `llama-cli --version` on the target Termux environment.
3. Configure the exact model path and run a separate opt-in inference smoke test.
4. Record the command, exit code, elapsed time, and bounded output.
5. Run a separate disposable-worktree edit-and-test exercise before claiming coding-agent readiness.

## Integration still required

- Register a dedicated worker task kind and validate the prompt payload.
- Ensure adapter errors become explicit failed task results rather than generic retries.
- Keep model generation separate from file writes; generated patches must be validated and applied through the workspace policy.
- Add output-size enforcement at the process capture boundary, not only after stdout has been collected.
- Test real Termux inference, cancellation, quota/stop behavior and the full isolated edit/test cycle.

Until those gates pass, the status of end-to-end local model execution is UNKNOWN.
