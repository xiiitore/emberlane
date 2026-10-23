# Model and provider adapter contract

## Status

This document defines a contract for adapter implementations. It does not claim Emberlane currently contains a complete local model backend or provider-neutral API adapter. Before adding an adapter, inspect the actual implementation and test it on the intended runtime.

## Separation of responsibilities

The queue owns durable lifecycle. The worker owns allow-listed dispatch. An adapter owns interaction with one execution engine or model runtime. The planner may propose steps but must not bypass worker validation or execute commands itself.

Recommended flow:

task payload -> schema validation -> adapter request with explicit limits -> bounded raw response -> parser/patch validator -> isolated workspace edit -> deterministic tests -> diff and evidence -> queue classification

No adapter should write arbitrary files directly without passing through workspace policy or an explicitly reviewed isolation boundary.

## Model adapter inputs

Make these values explicit:
- model identifier and resolved absolute model path;
- executable path and runtime/library configuration;
- prompt or structured messages;
- maximum input bytes/tokens and generated tokens;
- context window size;
- wall-clock timeout;
- working directory;
- permitted output mode (patch, JSON plan or text);
- network permission;
- redaction and logging policy.

Missing required configuration should return not_configured before execution. Do not silently choose an arbitrary model file or scan the whole device on every task.

## Model adapter outputs

Return a structured record containing:
- ok boolean;
- status from a finite set: success, invalid_input, not_configured, unavailable, timeout, quota_wait, output_limit, parse_error or execution_error;
- model identifier and non-secret model-path identifier;
- return code where applicable;
- elapsed time;
- bounded stdout/stderr excerpts with secrets redacted;
- input and output size counts;
- explicit truncation flag;
- stable error category and concise diagnostic;
- generated patch or structured plan, not an implicit file write.

A non-zero process exit is failure even if stdout looks plausible. Empty output, truncation, malformed JSON or rejected patches must not count as successful coding results.

## Local llama.cpp-style runtime

A local CLI adapter should:
1. verify the executable exists and can report its version;
2. verify the exact configured model file is readable;
3. invoke a documented, tested CLI argument set;
4. pass explicit context and generation limits;
5. use a timeout and bounded output capture;
6. distinguish loader/runtime errors from prompt/generation errors;
7. avoid loading the model during cheap readiness checks unless inference is explicitly requested;
8. run a minimal disposable inference test before claiming model readiness;
9. capture elapsed time and exit code;
10. keep model files and generated artifacts out of version control unless intentionally packaged.

A successful version check proves only that the CLI starts. It does not prove model loading, inference, adequate context or useful coding performance.

## Remote provider adapters and quota waits

Normalize provider-specific exceptions to a common category while preserving redacted diagnostics and validated retry-after duration when available. Do not guess a reset time.

For recognized quota/rate-limit waits:
- return quota_wait or raise a typed wait exception;
- persist a deferred task state;
- do not count the wait as a code-quality failure;
- avoid immediate retries;
- expose an explicit resume operation;
- keep retry policy separate from output validation.

Authentication errors, invalid model IDs, malformed requests and provider outages are not interchangeable with quota waits.

## Patch acceptance

Generated edits are proposals. Before application:
- require a known base revision;
- validate patch format and target paths;
- reject paths outside workspace and protected files;
- apply in a disposable worktree;
- run relevant tests;
- inspect the diff for unrelated changes and secrets;
- record exact base revision and changed-file list.

A model-generated explanation is not test evidence. A test report without command and exit status is incomplete evidence.

## Adapter conformance suite

Each adapter should test:
1. missing configuration returns not_configured without side effects;
2. missing executable returns a stable error;
3. unreadable model file is reported without inference;
4. non-zero exit is failure;
5. timeout is bounded and distinct;
6. output is bounded and redacted;
7. output truncation is explicit;
8. malformed structured output is rejected;
9. quota wait becomes deferred without a retry storm;
10. unrelated exceptions do not become quota waits;
11. generated paths cannot escape workspace;
12. fake executables support tests without downloading a model;
13. readiness checks do not claim inference success;
14. normal unit tests require no network unless specifically testing an external service.
