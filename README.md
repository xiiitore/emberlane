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
`write_file`, `read_file`, `list_files`, and `run_tests`. It does not accept
arbitrary shell commands.

```sh
# Queue a file-writing task (quote the JSON as one argument)
python -m emberlane submit write_file --payload '{"path":"src/example.py","content":"VALUE = 42\\n"}'

# Execute one queued task
python -m emberlane run-one

# Queue and execute the fixed unittest command
python -m emberlane submit run_tests
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
limit. The worker blocks writes to common Git metadata, virtual-environment,
queue-state, and environment-secret paths. Test execution uses a fixed command
(`python -m unittest discover -s tests -v`) with no shell and a timeout.
Project tests are still executable code: run the worker only in a repository
you trust.

## Security boundary

Workspace path checks protect against accidental path escape and common
symlink traversal; they are not an OS sandbox. The worker runs with the same
OS permissions as its owner. It does not provide a network listener, remote
task submission, automatic Git commits/pushes, or an LLM that independently
writes code from natural-language specifications. File-writing tasks must
include the exact file path and content in their payload. Use a separate OS
account or container for stronger isolation.
