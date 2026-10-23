"""GitHub issue-comment mailbox for a local Emberlane worker.

Tasks are JSON comments from one explicitly configured GitHub account.
Only registered task kinds are accepted; no arbitrary shell commands are run.
Requires the GitHub CLI (gh) to be installed and authenticated locally.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dropbox_output import DropboxOutputError, MAX_LOG_BYTES, upload_task_log

TASK_MARKER = "EMBERLANE_TASK_JSON"
MAX_COMMENT_CHARS = 20_000
MAX_GH_ATTEMPTS = 4
BASE_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 30.0

_RETRYABLE_ERRORS = (
    "rate limit",
    "secondary rate limit",
    "abuse detection",
    "http 429",
    "http 502",
    "http 503",
    "http 504",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "connection reset",
    "connection refused",
    "temporary failure",
    "timed out",
    # gh can expose a truncated/transient HTTP response as this parser error.
    "unexpected end of json input",
    "unexpected eof",
)


def _redact_sensitive_text(value: str) -> str:
    """Redact common GitHub credentials and key/value secrets before publication."""
    value = re.sub(r"(?i)(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})", "[REDACTED_GITHUB_TOKEN]", value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?im)\b(password|passwd|secret|client[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|credential|private[_-]?key)\b(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1\2[REDACTED]", value)
    value = re.sub(r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY_BLOCK]", value)
    return value


_PUBLIC_RESULT_SENSITIVE_KEY_MARKERS = (
    "token", "secret", "password", "passwd", "credential", "apikey",
    "authorization", "privatekey", "cookie", "bearer",
)

class MailboxError(RuntimeError):
    pass


def _retry_after_seconds(message: str) -> float | None:
    """Return a bounded Retry-After delay if a CLI error exposes that header."""
    match = re.search(r"(?im)^\s*retry-after\s*:\s*(\d+(?:\.\d+)?)\s*$", message)
    if not match:
        return None
    try:
        seconds = float(match.group(1))
    except ValueError:
        return None
    return min(MAX_RETRY_DELAY_SECONDS, max(0.0, seconds))


def _is_retryable_error(message: str) -> bool:
    lowered = message.casefold()
    # A generic 403 can indicate missing permissions; retry only when GitHub
    # explicitly identifies a rate limit.
    return any(marker in lowered for marker in _RETRYABLE_ERRORS)


def _gh(args: list[str], *, input_text: str | None = None) -> str:
    """Run gh with bounded retries for transient API/network failures only."""
    for attempt in range(MAX_GH_ATTEMPTS):
        try:
            result = subprocess.run(
                ["gh", *args],
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            message = f"GitHub CLI timed out: {exc}"
            if attempt + 1 >= MAX_GH_ATTEMPTS:
                raise MailboxError(message[:2000]) from exc
            time.sleep(min(BASE_RETRY_DELAY_SECONDS * (2 ** attempt), MAX_RETRY_DELAY_SECONDS))
            continue
        except OSError as exc:
            # Missing executable and local process errors will not improve by retrying.
            raise MailboxError(f"GitHub CLI failed: {exc}") from exc

        if result.returncode == 0:
            return result.stdout

        message = result.stderr.strip() or result.stdout.strip() or f"gh exited {result.returncode}"
        if attempt + 1 >= MAX_GH_ATTEMPTS or not _is_retryable_error(message):
            raise MailboxError(message[:2000])

        retry_after = _retry_after_seconds(message)
        delay = retry_after if retry_after is not None else min(
            BASE_RETRY_DELAY_SECONDS * (2 ** attempt),
            MAX_RETRY_DELAY_SECONDS,
        )
        time.sleep(delay)

    raise MailboxError("GitHub CLI failed after bounded retries")


def _gh_json(args: list[str]) -> Any:
    """Fetch and parse JSON with bounded retries for truncated successful responses.

    Use only for read-only API calls: retrying a malformed response must not
    repeat a write operation.
    """
    for attempt in range(MAX_GH_ATTEMPTS):
        raw = _gh(args)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            if attempt + 1 >= MAX_GH_ATTEMPTS:
                raise MailboxError(
                    f"GitHub returned invalid JSON after {MAX_GH_ATTEMPTS} attempts: {exc}"
                ) from exc
            time.sleep(min(
                BASE_RETRY_DELAY_SECONDS * (2 ** attempt),
                MAX_RETRY_DELAY_SECONDS,
            ))
    raise MailboxError("GitHub returned invalid JSON after bounded retries")


def _task_from_comment(body: str) -> dict[str, Any] | None:
    lines = body.splitlines()
    if not lines or lines[0].strip() != TASK_MARKER:
        return None
    try:
        task = json.loads("\n".join(lines[1:]))
    except json.JSONDecodeError as exc:
        raise MailboxError(f"invalid task JSON: {exc}") from exc
    if not isinstance(task, dict) or set(task) != {"kind", "payload"}:
        raise MailboxError("task must contain exactly 'kind' and 'payload'")
    if not isinstance(task["kind"], str) or not isinstance(task["payload"], dict):
        raise MailboxError("task kind must be a string and payload must be an object")
    return task


class GitHubIssueMailbox:
    """Poll one issue; accept tasks only from the configured GitHub login."""

    def __init__(
        self,
        worker: Any,
        repository: str,
        issue_number: int,
        author: str,
        state_path: str | Path | None = None,
    ):
        if "/" not in repository or issue_number < 1 or not author:
            raise ValueError("repository, positive issue number, and author are required")
        self.worker = worker
        self.repository = repository
        self.issue_number = issue_number
        self.author = author.casefold()
        self.state_path = Path(state_path or worker.root / ".emberlane" / "mailbox-state.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"handled": [], "active": {}}
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("handled"), list) or not isinstance(value.get("active"), dict):
            raise MailboxError("mailbox state has invalid structure")
        return value

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def _comments(self) -> list[dict[str, Any]]:
        endpoint = f"repos/{self.repository}/issues/{self.issue_number}/comments"
        known_ids = list(self.state.get("handled", [])) + list(self.state.get("active", {}).keys())
        numeric_ids = [int(value) for value in known_ids if str(value).isdigit()]
        cursor = max(numeric_ids, default=0)

        # With a persisted high-water mark, fetch newest-first only until the
        # previous frontier is reached. A fresh/empty state still scans all pages.
        if cursor > 0:
            collected: list[dict[str, Any]] = []
            page = 1
            while True:
                query = f"{endpoint}?per_page=100&sort=created&direction=desc&page={page}"
                batch = _gh_json(["api", query])
                if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
                    raise MailboxError("GitHub returned an unexpected comments response")
                reached_cursor = False
                for comment in batch:
                    comment_id = comment.get("id")
                    if isinstance(comment_id, int) and comment_id <= cursor:
                        reached_cursor = True
                        break
                    collected.append(comment)
                if reached_cursor or len(batch) < 100:
                    break
                page += 1
            return sorted(collected, key=lambda item: int(item.get("id", 0)))

        pages = _gh_json(["api", endpoint, "--paginate", "--slurp"])
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise MailboxError("GitHub returned an unexpected comments response")
        return [comment for page in pages for comment in page]

    def _reply(self, body: str) -> None:
        endpoint = f"repos/{self.repository}/issues/{self.issue_number}/comments"
        _gh(["api", "--method", "POST", endpoint, "-f", f"body={body[:MAX_COMMENT_CHARS]}"])

    def _publish_task_log(self, task: Any, comment_id: str) -> dict[str, Any]:
        """Write a complete sanitized local log and publish it to Dropbox."""
        task_id = str(task.task_id)
        if not re.fullmatch(r"[A-Za-z0-9-]{1,100}", task_id):
            raise MailboxError("task id is not safe for a log path")
        result = task.result if isinstance(task.result, dict) else {}
        outputs: list[tuple[str, str]] = []

        def redact(value: str) -> str:
            return _redact_sensitive_text(value)

        def sanitize(value: Any, path: str) -> Any:
            if isinstance(value, str):
                return redact(value)
            if isinstance(value, list):
                return [sanitize(item, f"{path}[{index}]") for index, item in enumerate(value)]
            if isinstance(value, dict):
                cleaned: dict[str, Any] = {}
                for key, item in value.items():
                    child_path = f"{path}.{key}"
                    normalized_key = re.sub(r"[^a-z0-9]", "", str(key).casefold())
                    if normalized_key == "content":
                        cleaned[key] = "[OMITTED_FILE_CONTENT]"
                    elif normalized_key in {"output", "sourcetext"} and isinstance(item, str):
                        outputs.append((child_path, redact(item)))
                        label = "SOURCE TEXT" if normalized_key == "sourcetext" else "FULL OUTPUT"
                        cleaned[key] = f"[{label} IN SECTION: {child_path}]"
                    elif any(marker in normalized_key for marker in _PUBLIC_RESULT_SENSITIVE_KEY_MARKERS):
                        if item is None:
                            cleaned[key] = None
                        elif isinstance(item, str):
                            redacted_value = redact(item)
                            cleaned[key] = redacted_value if redacted_value != item else "[REDACTED]"
                        else:
                            cleaned[key] = "[REDACTED]"
                    else:
                        cleaned[key] = sanitize(item, child_path)
                return cleaned
            return value

        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "source_comment_id": str(comment_id),
            "task_id": task_id,
            "kind": str(task.kind),
            "status": str(task.status),
            "attempts": int(task.attempts),
            "error_present": bool(task.last_error),
            "result": sanitize(result, "result"),
        }
        content = (
            "# Emberlane task output\n\n"
            f"- Task ID: `{task_id}`\n"
            f"- Kind: `{task.kind}`\n"
            f"- Status: `{task.status}`\n"
            f"- Attempts: `{task.attempts}`\n"
            f"- Source comment: `{comment_id}`\n\n"
            "## Result metadata\n\n```json\n"
            + json.dumps(record, ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        for label, output in outputs:
            content += f"\n## Full output: `{label}`\n\n~~~text\n{output}\n~~~\n"
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_LOG_BYTES:
            raise MailboxError("task log exceeds configured 1 MB limit")

        relative_path = f"worker-logs/{task_id}.md"
        local_path = self.worker.root / relative_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = local_path.with_name(f".{task_id}.{time.time_ns()}.tmp")
        try:
            with temporary_path.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                import os
                os.fsync(handle.fileno())
            os.replace(temporary_path, local_path)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

        try:
            dropbox_result = upload_task_log(task_id, content)
        except DropboxOutputError:
            # Keep the complete local log and finish the task with an explicit
            # delivery failure; do not block the mailbox on a missing network.
            return {
                "task_log_status": "local_only",
                "dropbox_status": "failed",
                "dropbox_readback_verified": False,
                "error_present": True,
            }
        return {
            "task_log_status": "published",
            "dropbox_status": dropbox_result.get("status"),
            "dropbox_path": dropbox_result.get("path"),
            "dropbox_sha256": dropbox_result.get("sha256"),
            "dropbox_bytes": dropbox_result.get("bytes"),
            "dropbox_readback_verified": dropbox_result.get("readback_verified") is True,
        }

    def _publish_handoff_record(
        self, task: Any, comment_id: str, task_log_result: dict[str, Any] | None = None
    ) -> dict[str, str]:
        """Avoid a GitHub commit for every task; issue comments are the status ledger."""
        del task, comment_id, task_log_result
        return {"handoff_status": "not_required"}

    def _finish_if_terminal(self, comment_id: str, task_id: str) -> bool:
        task = self.worker.queue.get(task_id)
        if task is None:
            self._reply(f"EMBERLANE_RESULT {comment_id}\nERROR: linked local task was not found.")
            self.state["handled"].append(comment_id)
            self.state["active"].pop(comment_id, None)
            self._save_state()
            return True
        if task.status not in {"completed", "failed"}:
            return False
        # The mailbox issue is public. Emit only explicitly approved scalar
        # metadata; never serialize arbitrary nested task/log/handoff results.
        safe_result: dict[str, Any] = {"result_available": task.result is not None}
        if isinstance(task.result, dict):
            allowed_scalar_fields = {
                "ok", "passed", "returncode", "exit_code", "replacements",
                "bytes_written", "count", "files_changed", "patch_included",
            }
            for key in allowed_scalar_fields:
                value = task.result.get(key)
                if isinstance(value, (bool, int, float)):
                    safe_result[key] = value
        try:
            task_log_result = self._publish_task_log(task, comment_id)
        except Exception:
            task_log_result = {"task_log_status": "failed"}
        if task_log_result.get("task_log_status") not in {"published", "already_present"}:
            return False
        try:
            handoff_result = self._publish_handoff_record(task, comment_id, task_log_result)
        except Exception:
            handoff_result = {"handoff_status": "failed"}
        # Retain only bounded status values; omit paths, exception text and hashes.
        for source, key in ((task_log_result, "task_log_status"),
                            (handoff_result, "handoff_status")):
            value = source.get(key)
            if isinstance(value, str) and value in {"published", "already_present", "failed"}:
                safe_result[key] = value
        if handoff_result.get("handoff_status") not in {"published", "already_present"}:
            return False
        result = {
            "source_comment_id": comment_id,
            "task_id": task.task_id,
            "kind": task.kind,
            "status": task.status,
            "attempts": task.attempts,
            "error_present": task.last_error is not None,
            "result": safe_result,
        }
        self._reply("EMBERLANE_RESULT\\n" + json.dumps(result, ensure_ascii=False, indent=2)[:MAX_COMMENT_CHARS])
        self.state["handled"].append(comment_id)
        self.state["active"].pop(comment_id, None)
        self._save_state()
        return True

    def run_once(self) -> dict[str, Any]:
        comments = self._comments()
        # Resume an already enqueued task first; never enqueue it twice after a restart.
        for comment_id, task_id in list(self.state["active"].items()):
            task = self.worker.queue.get(task_id)
            if task is not None and task.status == "pending":
                self.worker.run_one()
            if self._finish_if_terminal(comment_id, task_id):
                return {"status": "finished", "comment_id": comment_id, "task_id": task_id}

        handled = set(self.state["handled"])
        active = set(self.state["active"])
        for comment in comments:
            comment_id = str(comment.get("id", ""))
            if not comment_id or comment_id in handled or comment_id in active:
                continue
            user = comment.get("user") or {}
            if str(user.get("login", "")).casefold() != self.author:
                continue
            body = comment.get("body") or ""
            try:
                task_data = _task_from_comment(body)
            except MailboxError as exc:
                self._reply(f"EMBERLANE_RESULT {comment_id}\nREJECTED: {exc}")
                self.state["handled"].append(comment_id)
                self._save_state()
                return {"status": "rejected", "comment_id": comment_id, "error": str(exc)}
            if task_data is None:
                continue
            try:
                task = self.worker.submit(
                    task_data["kind"], task_data["payload"],
                    idempotency_key=comment_id,
                )
            except Exception as exc:
                self._reply(f"EMBERLANE_RESULT {comment_id}\nREJECTED: {type(exc).__name__}: {exc}")
                self.state["handled"].append(comment_id)
                self._save_state()
                return {"status": "rejected", "comment_id": comment_id, "error": str(exc)}
            self.state["active"][comment_id] = task.task_id
            self._save_state()
            self.worker.run_one()
            if self._finish_if_terminal(comment_id, task.task_id):
                return {"status": "finished", "comment_id": comment_id, "task_id": task.task_id}
            return {"status": "pending", "comment_id": comment_id, "task_id": task.task_id}
        return {"status": "idle"}
