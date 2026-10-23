# Emberlane

A small, standalone Python task runner with a local coding-workflow worker.

## Requirements

- Python 3.11+
- Standard-library-only runtime

## Install and test

From the repository root:

```sh
python -m unittest discover -s tests -v
python -m emberlane --help
```

## Local worker

The worker processes a durable JSON queue. It supports only explicit task kinds:
`write_file`, `write_files`, `replace_text`, `read_file`, `list_files`,
`run_tests`, `local_model_proposal`, `git_status`, `git_diff`, `git_sync`, `git_stash_inspect`, and `diagnostics`. It does not accept
arbitrary shell commands.

```sh
# Queue a file-writing task (quote the JSON as one argument)
python -m emberlane submit write_file --payload '{"path":"src/example.py","content":"VALUE = 42\\n"}'

# Execute one queued task
python -m emberlane run-one

# Opt in to publishing a redacted source preview in the task's private-to-repo Markdown log
# Only use this for files safe to expose to people with repository access.
python -m emberlane submit read_file --payload '{"path":"src/example.py","include_content":true}'
python -m emberlane run-one

# Queue multiple related files in one task (up to 50 files)
python -m emberlane submit write_files --payload '{"files":[{"path":"src/example.py","content":"VALUE = 42\\n"},{"path":"tests/test_example.py","content":"from src.example import VALUE\\n"}]}'
python -m emberlane run-one

# Make an exact, guarded edit to an existing file (default: exactly one match)
python -m emberlane submit replace_text --payload '{"path":"src/example.py","old":"VALUE = 42","new":"VALUE = 43","expected_count":1}'
python -m emberlane run-one

# Inspect repository state and diff metadata (source patches are not returned)
python -m emberlane submit git_status
python -m emberlane submit git_diff
python -m emberlane submit git_sync --payload '{"expected_branch":"feat/local-coding-worker"}'
python -m emberlane submit git_stash_inspect
python -m emberlane run-one
python -m emberlane submit diagnostics

# Queue and execute the full unittest suite
python -m emberlane submit run_tests
python -m emberlane run-one

# Run only one test file (filename must be test_*.py directly inside tests/)
python -m emberlane submit run_tests --payload '{"test_file":"test_worker.py"}'
python -m emberlane run-one

# Inspect queue state and task results
python -m emberlane status
```

By default, the queue state is stored in `.emberlane/queue.json` under the
project root. Use `--root PATH` to select a project directory and
`--state PATH` to override the queue location. Each task's JSON-compatible
result is persisted with its status. Tasks are processed one at a time; the
queue is not safe for concurrent writers.

File operations are confined to the configured workspace and enforce a size
limit. `replace_text` edits an existing file only when the old text occurs exactly
the requested number of times (one by default); a mismatch leaves the file
unchanged. It rejects protected paths and oversized results. `read_file` omits
source text from logs by default. The explicit `include_content: true` option
adds a source preview to the task Markdown log only when the file is at most
20,000 characters; oversized previews are explicitly omitted. The preview is
redacted using pattern-based rules, which are not a guarantee that every secret
will be detected. Never opt in for files that may contain credentials or private
data. `write_files` accepts
up to 50 distinct workspace-relative paths, checks all targets before writing,
and rejects oversized content before queueing. Each
individual file replacement is atomic; the batch as a whole is not atomic, so a
filesystem failure during the write phase can leave earlier files changed. The
worker blocks writes to common Git metadata, virtual-environment, queue-state,
and environment-secret paths. Test execution uses fixed argument lists with no
shell and a timeout. By default it runs the full suite with
`python -m unittest discover -s tests -v`; an optional `test_file` selects one
exact `test_*.py` filename directly inside `tests/`. Invalid names are rejected
before queueing, and a missing test file returns an explicit failed result
instead of treating zero discovered tests as success. `git_stash_inspect` lists up to ten recent stashes and shows file-change summaries only; it never applies or drops a stash. Project tests are still
executable code: run the worker only in a repository you trust.

## Offline local-model proposals

The optional `local_model_proposal` task uses a local `llama.cpp` `llama-cli` executable and a local GGUF model. It requires no paid API or network call. Install `llama-cli` separately and set `EMBERLANE_MODEL_PATH` to the model file; `EMBERLANE_LLAMA_CLI` can override the executable name (default `llama-cli`).

```sh
export EMBERLANE_MODEL_PATH="$HOME/models/qwen-coder.gguf"
export EMBERLANE_LLAMA_CLI="llama-cli"
python -m emberlane submit local_model_proposal --payload '{"goal":"Make the function handle an empty input","allowed_paths":["src/example.py"]}'
python -m emberlane run-one

# End-to-end edit: test in a disposable copy and apply only if verification passes
python -m emberlane submit local_model_edit --payload '{"goal":"Handle an empty input","allowed_paths":["src/example.py"],"test_file":"test_example.py"}'
python -m emberlane run-one
python -m emberlane status
```

The model sees only explicitly allow-listed UTF-8 files, subject to strict context, output, and time limits. The worker rejects paths outside the allow-list, credential-like context/output, malformed responses, and oversized edits. `local_model_proposal` returns an **unapplied patch** for inspection. `local_model_edit` applies a proposal only after the patch applies cleanly and the selected tests pass in a disposable copy; it then verifies that the source files have not changed since proposal generation before applying the patch to the working tree. If `test_file` is omitted, it runs the full unittest suite. It does not commit or push. A small local model may fail to produce valid JSON or useful edits; those failures are reported rather than silently accepted.

## Security boundary

Workspace path checks protect against accidental path escape and common symlink traversal; they are not an OS sandbox. The worker runs with the same OS permissions as its owner. It does not provide a network listener, remote task submission, or automatic Git commits/pushes. The optional local-model task proposes patches but does not apply them. File-writing tasks must include the exact file path and content in their payload. Use a separate OS account or container for stronger isolation.

## Optional GitHub issue mailbox

The mailbox lets a local worker receive exact, allow-listed task payloads through
comments on one GitHub issue. It requires the `gh` CLI, a local authenticated
GitHub session with permission to read and comment on the selected repository,
and a dedicated issue. The worker accepts task comments only from the explicitly
configured GitHub login.

A task comment must begin with `EMBERLANE_TASK_JSON`, followed by one JSON
object with exactly `kind` and `payload`, for example:

```text
EMBERLANE_TASK_JSON
{"kind":"write_file","payload":{"path":"src/example.py","content":"VALUE = 42\\n"}}
```

One-shot polling:

```sh
python -m emberlane mailbox-once --repo OWNER/REPO --issue ISSUE_NUMBER --author YOUR_GITHUB_LOGIN
```

Repeat that command to process tasks and retries. A result comment is posted to
the same issue when the task reaches a terminal state. Keep the mailbox issue
dedicated to worker requests; issue comments are visible to people with access
to the repository. Do not send secrets or private data through it. This is a
polling bridge, not a process started or controlled directly by ChatGPT; a
local machine must be running the poller for new tasks to execute. Only the
worker's registered task types are supported.
