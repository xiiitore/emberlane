# Termux readiness runbook

Purpose: prepare a single, low-friction evidence pass for the local Emberlane worker. This runbook does not install packages, change configuration, start a persistent loop, commit, or push anything.

## 1. Fetch the reviewed branch only when ready

Do not overwrite a dirty working tree. Inspect the current branch and changes first. If local changes exist, preserve them and use a separate worktree or backup before switching branches.

## 2. Run the read-only preflight

From the Emberlane repository root in Termux:

```sh
bash scripts/termux-preflight.sh
```

Optional explicit configuration for this shell:

```sh
export EMBERLANE_MODEL_PATH="/absolute/path/to/the-existing-model.gguf"
export LLAMA_CLI_BIN="llama-cli"
bash scripts/termux-preflight.sh
```

Use the actual existing model path; the example path is a placeholder. Do not put credentials or tokens in these variables. Exit status 0 means basic checks passed, 1 means warnings remain, and 2 means a blocker was found. The script is read-only and reports Git status without printing file contents.

## 3. Verify the repository code separately

```sh
python -m compileall -q emberlane tests
python -m unittest discover -s tests -v
python -m emberlane --help
```

Record the exact command, exit status, and final test summary. A successful remote CI run is useful evidence for the committed branch but is not evidence about the Termux runtime.

## 4. Prove local-model execution before enabling any loop

1. Confirm the configured model file is readable and the CLI can start.
2. Run one bounded inference using the backend's documented command and capture its exit code.
3. Run a disposable coding task in a clean temporary worktree or copy.
4. Inspect the diff and run the smallest relevant test, then the full suite.
5. Confirm explicit failed results do not unlock dependent steps.
6. Simulate an external quota wait: it must become `deferred`, with no retry loop. Resume only after the external limit has cleared using `resume-deferred TASK_ID`.
7. Confirm a waiting goal schedules its next planner cycle after explicit resumption.

Do not run destructive Git commands or test the edit cycle against the only copy of a dirty working tree.

## 5. Readiness decision

- **PASS:** all required local checks and the disposable edit cycle passed with recorded evidence.
- **BLOCKED:** a required dependency is missing or a required test failed.
- **UNKNOWN:** a check was not run or its output is incomplete.
- **PARTIAL:** basic checks ran, but model inference or end-to-end recovery remains unverified.

Do not label the system autonomous or ready for unattended operation until the real Termux model, edit/test cycle, deferred recovery, and supervisor stop/resume behavior are demonstrated.
