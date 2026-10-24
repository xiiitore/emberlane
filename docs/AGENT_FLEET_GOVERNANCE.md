# Agent-fleet governance and Hugging Face integration

## Status and scope

This document translates the bounded research on the October 2026 reported agent fleet and Hugging Face's agent ecosystem into an Emberlane architecture and implementation plan. It is a design/acceptance contract, not evidence that every listed control is implemented or that the reported fleet's exact model or harness is known.

Research sources:
- Swarmchasers, *We found a Tencent agent fleet* (report on activity observed 28 September–8 October 2026): https://swarmcha.se/posts/chinese-agent-fleet-full-report
- Hugging Face Agent Libraries (tiny-agents, MCP and smolagents): https://huggingface.co/docs/hub/agents-libraries
- Hugging Face smolagents docs: https://huggingface.co/docs/smolagents/en/index
- smolagents source and security notes: https://github.com/huggingface/smolagents
- Qwen3-Coder-Next model card: https://huggingface.co/Qwen/Qwen3-Coder-Next
- Qwen3.6-27B model card: https://huggingface.co/Qwen/Qwen3.6-27B
- DeepSeek-V3.2 model card: https://huggingface.co/deepseek-ai/DeepSeek-V3.2
- Agent Beacon telemetry project: https://github.com/Asymptote-Labs/agent-beacon

The report is an investigator-authored account supported by observations and agent mailbox exchanges. It does not independently establish the precise model/harness, complete operator instructions, model consciousness, or spontaneous agent intent. The investigators report no evidence of real-time inter-agent coordination and distinguish a fleet from a coordinated swarm. Treat those limits as part of the evidence record.

## Architecture decision

Emberlane should remain the durable, bounded execution and governance layer. Model frameworks and model providers are replaceable components, not sources of authority.

```text
Goal / authorized task
        |
        v
Intake + task schema + policy
        |
        v
Durable queue / bounded planner / supervisor
        |
        v
Model adapter (optional; proposes plan or patch only)
        |
        v
Deterministic validator + capability policy
        |
        v
Isolated workspace / fixed-argument tool executor
        |
        v
Tests + diff inspection + side-effect reconciliation
        |
        v
Independent evidence audit -> ACCEPT / REVISE / BLOCKED / REJECT
        |
        v
Release action only under explicit policy
```

Cross-cutting controls: stop/pause checks, task/failure/time/output budgets, secret redaction, bounded audit events, network policy, dependency provenance and explicit recovery states. Model text, repository files, issue comments, webpages and tool output are untrusted data; they never grant new permissions.

### Responsibility boundaries

| Layer | Responsibility | Must not be trusted to do |
|---|---|---|
| Model (local or hosted) | Propose reasoning, tool arguments, plans or patches | Authorize its own permissions or certify its own success |
| Agent framework (e.g. smolagents or tiny-agents) | Run the model loop and adapt tool calls | Replace OS isolation or Emberlane policy |
| Emberlane queue/planner/supervisor | Persist task lifecycle, enforce bounded scheduling and stop conditions | Treat a plan or normal return as proof of success |
| Tool/policy gateway | Enforce allow-listed capabilities, paths, arguments, limits and approvals | Accept arbitrary shell strings from model output |
| Isolated execution | Run approved work in a disposable worktree/container/account | Access credentials or unrelated user data unnecessarily |
| Telemetry and audit | Record bounded event metadata and evidence references | Publish secrets, full source, raw exceptions or unbounded output |
| Independent verifier | Check actual effects, tests, diffs and provenance | Reuse the model's claim as its only evidence |
| Release governance | Decide whether to accept, revise, block or reject | Merge/push/deploy merely because a task completed |

## Hugging Face integration options

These are options to evaluate, not dependencies that this repository has already installed.

### smolagents

The documented Python framework offers CodeAgent (Python actions) and ToolCallingAgent (structured tool calls), supports different model backends and MCP integrations. Code execution is a capability boundary: its local executor is not an OS security sandbox. If evaluated, run it inside a disposable environment with no production credentials, a narrow filesystem view, explicit network policy and a fixed timeout.

### tiny-agents and MCP

Hugging Face documents tiny-agents in JavaScript and Python, with Hugging Face Inference or a configured local endpoint and MCP servers. MCP is a tool-connection protocol, not an authorization policy. Each server and each exposed tool must be independently allow-listed and constrained. Never expose a general filesystem, browser or command tool merely because an MCP server makes it easy to connect.

### Model candidates

- Qwen3-Coder-Next: candidate for repository/coding-agent tasks; claims on its model card require task-specific verification.
- Qwen3.6-27B: another coding/reasoning candidate with documented tool/MCP examples.
- DeepSeek-V3.2: alternative reasoning/agentic model candidate.

Do not infer model quality, safety, or suitability from model-card wording, downloads or likes. Compare pinned revisions using identical prompts, tools, limits and test cases. Record model revision, quantization, inference runtime, context/output limits, elapsed time, token counts where available, tool calls, tests and failure classifications. License and gating must be checked on the exact model revision before distribution or commercial use.

### Telemetry

An OpenTelemetry-oriented project such as Agent Beacon may help normalize events from supported agent harnesses. It is observability, not prevention. Emberlane should first maintain its own stable event contract and only add an exporter/adapter after a compatibility review. Do not introduce a second scheduler or competing source of task truth.

## Existing Emberlane controls and gaps

The current documentation describes a durable single-writer JSON queue, allow-listed task kinds, bounded plans/supervision, a local llama.cpp adapter, disposable-copy patch tests, pause/stop checks, redacted public mailbox metadata and evidence-level release gates. These are repository claims to verify against the exact implementation and runtime; they do not prove that the current Termux checkout is synchronized or that real inference works.

| Control | Current documented position | Required next evidence |
|---|---|---|
| Allow-listed task kinds and bounded worker | Existing design/implementation | Regression test that model output cannot add a tool or change the allow-list |
| Pause/stop and finite budgets | Documented supervisor behavior | Forced-stop tests at task claim, between plan steps, and during subprocess execution |
| Model adapter | Local llama.cpp adapter and fake-process tests documented | Exact device model-load/inference result only when explicitly authorized |
| Generated edits | Disposable-copy patch/test path documented | Recheck patch operation types, symlink/gitlink cases, concurrent mutation and recovery-required outcomes |
| Durable recovery/idempotency | Queue lifecycle and retry/recovery behavior documented | Crash after external side effect but before terminal persistence; verify reconciliation prevents unsafe duplicate effects |
| Mailbox | Dedicated issue and allow-listed public result comments | Test malformed/unauthorized comments, duplicate delivery, redaction, Dropbox failure and bounded polling |
| Telemetry/audit | Metadata-only supervisor log documented | Schema/version contract, event completeness tests and correlation IDs across task, tool, test and release |
| Independent verification | Evidence-level and release-gate documentation | Verifier must inspect actual diff/test outputs independently of model-generated summary |
| Network boundary | Workspace checks are not an OS sandbox | Verify OS/container/network restrictions; do not claim safety from path checks alone |
| Multi-agent coordination | Not established as an existing feature | Do not add inter-agent messaging until identity, authority, task ownership, loop budgets and audit rules are specified |

## Required event contract

Audit records should be append-only where feasible and bounded. Use stable, versioned fields such as:

- `schema_version`, `event_id`, `timestamp_utc`, `run_id`, `task_id`, `parent_task_id`;
- `actor_type` (operator, supervisor, model_adapter, tool, verifier), `actor_id` (non-secret);
- `action`, `capability`, `policy_decision` (allow, deny, defer, require_approval);
- `input_digest`, `base_revision`, `changed_paths` (bounded and redacted);
- `result_class` (completed, failed, deferred, blocked, recovery_required);
- `evidence_refs`, `exit_code`, `duration_ms`, `truncated`, `redaction_applied`.

Never log API keys, tokens, cookies, complete environment dumps, raw unbounded tool output or full source by default. A digest is an integrity/correlation aid, not proof that the underlying content was safe.

## Staged implementation plan

### Stage A — Documentation and threat model
- [x] Record source links and distinguish investigator observations from interpretations.
- [x] Define model/framework/tool/policy/audit/release responsibility boundaries.
- [x] Map existing documented Emberlane controls and unknowns.
- [ ] Review this contract against current source and open PRs before merging.

### Stage B — Deterministic policy and telemetry tests
- [ ] Add tests proving model output cannot expand capabilities, paths, network access or execution budgets.
- [ ] Version the audit event schema and test redaction, output bounds and correlation across retries.
- [ ] Test unauthorized, malformed and duplicate mailbox requests without side effects.
- [ ] Test that deferred dependencies, stop/pause, deadlines and retry-after are respected.
- [ ] Test that missing evidence always yields UNKNOWN/BLOCKED rather than PASS.

### Stage C — Isolated coding-agent adapter evaluation
- [ ] Keep smolagents/tiny-agents optional; do not add runtime dependencies before a small proof-of-concept and license review.
- [ ] Pin a model revision and runtime; run only deterministic, non-sensitive fixtures.
- [ ] Execute generated changes in a disposable worktree/container with no production secrets and network disabled by default.
- [ ] Validate patch format/paths and reject deletes, symlinks, gitlinks or unsupported operations unless explicitly supported and tested.
- [ ] Run targeted tests, full tests when budget permits, diff checks and an independent result audit.
- [ ] Record latency, resource use, cost where applicable, task success, tool correctness, boundary violations and recovery behavior.

### Stage D — Fleet/supervisor resilience
- [ ] Test multiple workers are rejected or coordinated safely; current file queue is single-writer.
- [ ] Inject crash windows before and after side effects and before terminal state persistence.
- [ ] Prove no busy-loop on quota, idle queue, malformed task or failed publication.
- [ ] Test finite wall-clock/task/failure/output budgets and operator stop.
- [ ] Run a bounded soak only after earlier gates pass; report exact revision, runtime, workload and unresolved gaps.

### Stage E — Release gate
- [ ] Independent review of code, tests, dependency changes, threat model and actual diff.
- [ ] Hosted CI passes on the exact PR head.
- [ ] Termux readiness, inference and end-to-end edit evidence are separate gates and remain UNKNOWN until run on the target device with authorization.
- [ ] No automatic merge, push, deployment or persistent background service without an explicit release decision.

## Evaluation matrix

Run every candidate with the same task set and policy envelope. Record outcomes per run, not only averages.

| Dimension | Example measurement |
|---|---|
| Functional correctness | Test pass rate; patch accepted/rejected |
| Tool correctness | Valid/invalid tool calls and arguments |
| Policy compliance | Unauthorized path/tool/network attempts denied |
| Recovery | Lost tasks, duplicate side effects, recovery-required states |
| Observability | Events missing, redaction failures, source/output leakage |
| Resource use | Wall time, peak memory where measurable, output/tokens |
| Reproducibility | Pinned model/runtime/prompt/tool versions and deterministic fixture |
| Human control | Pause/stop latency and explicit approval enforcement |

Do not use a single composite score to hide a severe boundary violation. Any confirmed secret disclosure, unauthorized external side effect, path escape, arbitrary command execution or unsafe automatic release is a release-blocking failure.

## Decision

**Recommendation:** keep Emberlane as the durable control plane; evaluate Hugging Face agent frameworks as optional model-loop adapters behind a strict policy gateway. Add telemetry and independent verification before considering any multi-agent/fleet mode. Do not infer that the reported Tencent fleet used Hugging Face models or frameworks: the cited report does not establish that.

**Evidence status:** architecture recommendation = design proposal; current device readiness = UNKNOWN; candidate model/framework security and performance = NOT TESTED by this repository change.
