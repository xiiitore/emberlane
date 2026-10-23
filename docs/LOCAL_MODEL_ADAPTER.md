# Local model adapter contract

## Status

The `emberlane.local_model` module provides a bounded subprocess adapter for a locally installed llama.cpp CLI. It does not download weights or install software. The `local_model` task is registered with the worker and CLI, but it only generates text: it does not edit files or constitute an end-to-end coding agent.

## Configuration

Set these environment variables in the process that invokes the adapter:

- `EMBERLANE_MODEL_PATH`: required absolute or home-relative path to an existing readable GGUF file.
- `EMBERLANE_LLAMA_CLI`: optional executable name or path, compatible with the existing Termux backend configuration.
- `LLAMA_CLI_BIN`: optional fallback executable name or path; defaults to `llama-cli`.
- `EMBERLANE_MODEL_CONTEXT`: optional context token limit; defaults to 2048 and accepts 128–32768.
- `EMBERLANE_MODEL_MAX_TOKENS`: optional generation cap; defaults to 256 and accepts 1–4096.
- `EMBERLANE_MODEL_TIMEOUT`: optional wall-clock timeout in seconds; defaults to 120 and accepts 1–3600.

The adapter validates configuration and the model path before starting the process. Missing configuration returns the structured `not_configured` error. Model files must be obtained and installed separately by the operator.

## Invocation contract

`LocalModelRunner(config).generate(prompt)` returns a JSON-compatible mapping containing `ok`, `output`, `truncated`, `returncode`, elapsed time, model path, context size and generation cap.

Expected errors use `LocalModelError.code` to distinguish invalid configuration, missing executable, missing/unreadable model, invalid or oversized prompt, timeout, loader failure, non-zero exit and empty output. A caller should persist the error code and exit status; it must not turn any adapter error into a successful task.

The process is invoked with an argument vector and `shell=False`; stdin is closed. Stdout and stderr are drained concurrently, with retained output bounded while the child runs; stderr retains only a bounded tail for diagnostics. The configured timeout kills the child process. This is process-output control, not a security sandbox, and it does not prove that generated code is correct or safe.

## Validation

`tests/test_local_model.py` uses a fake executable and placeholder model file, including a large stdout/stderr regression case. `tests/test_worker.py` verifies task registration, success persistence, payload validation and terminal error classification. These deterministic tests do not prove that a real llama.cpp binary can load the user's model.

Before declaring local inference ready:

1. Run the hosted unit suite on supported Python versions.
2. Run `llama-cli --version` on the target Termux environment.
3. Configure the exact model path and run a separate opt-in inference smoke test.
4. Record the command, exit code, elapsed time, and bounded output.
5. Run a separate disposable-worktree edit-and-test exercise before claiming coding-agent readiness.

## Run it

Configure the exact model path in the same shell that runs Emberlane:

```sh
export EMBERLANE_MODEL_PATH="/absolute/path/to/model.gguf"
export LLAMA_CLI_BIN="llama-cli"
python scripts/local-model-smoke.py
```

The smoke test performs one short inference and prints a JSON result; it does not modify files. The worker task can also be queued explicitly:

```sh
python -m emberlane --root . submit local_model --payload '{"prompt":"Reply with exactly: hello"}'
python -m emberlane --root . run-one
```

The worker stores generated text as task output only. Model/configuration errors are returned as explicit failed results, not successful completions or generic retry loops. Do not submit secrets in prompts.

## Remaining readiness gates

- Run hosted tests on supported Python versions and inspect the exact workflow jobs.
- Run `llama-cli --version` and the smoke test on the target Termux environment; record the real exit code, elapsed time and output.
- Test cancellation/stop behavior during a running model process.
- Build a separate disposable-worktree coding cycle where generated changes are treated as untrusted, reviewed as a diff, and tested before any file application.
- Verify quota handling and interrupted-task recovery in the complete supervisor path.

The worker integration and capture-boundary output limit are implemented in this branch; real Termux inference and end-to-end isolated coding remain UNKNOWN.
