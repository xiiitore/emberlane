# Disposable patch validation

The `validate_patch` worker task validates a proposed unified Git diff in a temporary detached worktree. It never applies the patch to the configured checkout and never commits, pushes, merges, or publishes it.

## Task payload

```json
{
  "patch": "diff --git a/example.py b/example.py\n...",
  "run_tests": false,
  "test_timeout": 120
}
```

- `patch` is required and limited to 256,000 UTF-8 bytes.
- `run_tests` defaults to false. Set it to true only when authorized to execute code from the patch; tests run with the worker's operating-system permissions.
- `test_timeout` is an integer from 1 to 300 seconds.
- Only standard, unquoted Git diff path headers are accepted. Absolute paths, traversal, Windows-style paths, and protected paths (`.git`, `.emberlane`, `.venv`, secret/key filenames) are rejected.
- The original checkout must be a clean Git worktree root. If it is dirty, validation fails closed instead of guessing which state to test.
- The patch is checked and applied in a detached worktree at the original HEAD. The worker reports the base SHA, patch SHA-256, touched paths, diff summary, test status and bounded test-output preview. The temporary worktree is removed in cleanup.
- With `run_tests: false`, status `validated` means only that the patch applies cleanly and passes `git diff --check`; it does not mean the code works.
- With `run_tests: true`, a fixed `python -m unittest discover -s tests -v` command runs in the temporary worktree. Test failures are terminal failures.

## CLI example

For a small patch, submit JSON through the CLI:

```sh
python -m emberlane --root . submit validate_patch --payload '{"patch":"diff --git a/example.py b/example.py\n--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-OLD\n+NEW\n","run_tests":false}'
python -m emberlane --root . run-one
```

Large diffs may exceed the operating system's command-line argument limit; for those, use the Python API or a future file-backed payload interface rather than truncating the patch.

## Security boundary

A temporary Git worktree protects the active checkout from patch application; it is **not an OS sandbox**. When `run_tests` is true, code in the patch—including tests, build hooks or imports—can execute with the worker's permissions. Do not run untrusted patches with tests enabled unless the environment is separately isolated. This feature does not auto-commit, push or merge. Human review of the returned diff remains required.
