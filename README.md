# Emberlane

A small, standalone Python task runner built from scratch.

## Goals
- Explicit task handlers; no arbitrary shell execution.
- Durable JSON state written atomically.
- Retry with bounded attempts.
- Clear separation between task execution and policy.
- Standard-library-only runtime.

## Requirements
- Python 3.11+

## Run tests
```sh
python -m unittest discover -s tests -v
```

## Current scope
This is a minimal foundation, not a production-ready distributed worker. It has no network listener, credentials, or GitHub integration.


## Worker workspace (v3)

`Workspace` confines file reads/writes/listing to a configured root, rejects
absolute paths, parent traversal, symlink paths, and files over a configurable
byte limit. Writes use a temporary file and atomic replacement.

Example:

```python
from emberlane import Workspace

workspace = Workspace("./worker-workspace", max_file_bytes=200_000)
workspace.write_text("notes/result.txt", "task completed")
print(workspace.list_files())
```

**Security boundary:** this is application-level path validation, not an OS
sandbox. It does not stop hostile code or another process running under the
same OS user. The worker must not execute arbitrary shell commands. For stronger
isolation, run it under a separate OS account or a container with a restricted
filesystem and no secrets mounted into it. Concurrent queue writers are still
unsupported.
