# Model-generated coding cycle

The `coding_cycle` task combines local llama.cpp generation with disposable patch validation. It does **not** write generated changes into the active checkout, commit, push, or merge.

## Payload

```json
{
  "prompt": "Change the constant from 1 to 2",
  "context_files": ["src/example.py"],
  "run_tests": false,
  "test_timeout": 120
}
```

- `prompt` is required and limited to 4,000 characters.
- `context_files` is optional, accepts up to five unique safe relative paths, each at most 4,000 characters, with an aggregate content limit of 8,000 characters. Secret-like patterns are redacted before source text is sent to the model.
- `run_tests` defaults to false. Tests execute generated repository code with the worker's OS permissions; use a separate OS/container sandbox for untrusted code.
- `test_timeout` is an integer from 1 to 300 seconds.
- The source checkout must be clean (except Emberlane's own `.emberlane/` runtime files). This is checked before model execution, and patch validation checks again before creating a detached worktree.
- The model must return a standard diff starting with `diff --git `. Explanations, Markdown fences, truncated output, and detected common GitHub credentials are rejected.
- A valid patch is applied only in a temporary detached worktree at the repository's current HEAD. The active checkout is not modified.
- The result contains the complete generated patch (within the configured model output cap), patch SHA-256, touched paths, bounded diff preview, validation status, and optional test status. Common credential patterns are redacted/rejected, but pattern-based checks cannot detect every secret.

## CLI

```sh
python -m emberlane --root . submit coding_cycle --payload '{"prompt":"Change VALUE from 1 to 2","context_files":["example.py"],"run_tests":false}'
python -m emberlane --root . run-one
```

For large payloads, avoid shell quoting and command-line length limits by using the Python API or a future file-backed submission interface.

## Interpretation of results

- `status: validated` with `passed: null` means the patch applied in isolation and passed `git diff --check`; tests were not run.
- `passed: true` means the fixed unittest suite passed in the disposable worktree.
- `passed: false` or a terminal failed task means generation, validation, or tests failed; inspect `stage`, `error`, and the retained patch/diff.
- A successful mocked test does not prove real inference. Run `scripts/local-model-smoke.py` on the target Termux device before claiming local-model readiness.

This is a controlled patch-proposal workflow, not a security sandbox or autonomous release agent. Human review remains required before any change is applied to the active checkout.