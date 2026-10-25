# Session continuity automation

## Purpose

Keep the Emberlane worker state available when a ChatGPT conversation reaches its context limit or fails. The durable state is generated from the local worker checkout; a chat transcript is not the source of truth.

## Runtime behavior

The supervised worker_loop.py calls emberlane.session_state.refresh_session_state() at startup and after each successful mailbox poll.

The generator:

1. Reads only .emberlane/queue.json and .emberlane/mailbox-state.json metadata.
2. Produces .emberlane/EMBERLANE_CURRENT_STATE.md, which remains excluded from Git by the existing ignore rule.
3. Omits task payloads, arbitrary output, secrets, and nested source contents. It includes only a small allowlist of scalar result fields.
4. Publishes the snapshot through the existing Dropbox output transport as SESSION-CONTINUITY.md.
5. Requires the transport's SHA-256 read-back verification before marking a snapshot as published.
6. Skips uploads when the content hash is unchanged. A failed publication is retried after a bounded cooldown; a changed snapshot is eligible immediately.

The Dropbox destination is controlled by the existing DROPBOX_ROOT configuration. No credentials are written into the state file or logs.

## Evidence semantics

- published means the Dropbox upload was read back and its digest verified.
- unchanged means the current snapshot matches the last verified published digest.
- retry_deferred means the same content recently failed publication and is inside the retry cooldown.
- publish_failed means publication failed; the local snapshot still exists, but remote continuity is not confirmed.
- publish_unverified means the transport did not return the required successful read-back evidence.
- local_only is used when the caller explicitly disables publishing.

A successful worker task or a local state file alone does not prove that Dropbox has the latest snapshot. Check the published result and fetch the exact remote file when verifying continuity.

## New-session recovery

1. Fetch SESSION-CONTINUITY.md from the configured Dropbox output folder.
2. Read only the specific task logs referenced by the snapshot or its open blockers.
3. Confirm current source revision and relevant test output before making claims.
4. Continue from the highest-priority unresolved task; do not re-fetch the entire Issue #6 comment history.
5. If the snapshot is missing or stale, inspect .emberlane/session-state-last-attempt.json, .emberlane/session-state.sha256, and the worker-loop events. Do not infer remote success from local files.

## Limitations

- This is local worker automation, not a ChatGPT background process. It runs only while the Termux loop is active.
- If Termux is stopped, the device is offline, Dropbox authentication expires, or the worker process is not running, the snapshot may become stale.
- The snapshot summarizes metadata and cannot replace exact task logs, source inspection, or test verification.
- The generator does not automatically claim that a test passed merely because a task is marked completed.
