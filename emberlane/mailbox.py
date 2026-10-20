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
)


def _redact_sensitive_text(value: str) -> str:
    """Redact common GitHub credentials and key/value secrets before publication."""
    value = re.sub(r"(?i)(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})", "[REDACTED_GITHUB_TOKEN]", value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?im)\b(password|passwd|secret|client[_-]?secret|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|token|credential|private[_-]?key)\b(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1\2[REDACTED]", value)
    value = re.sub(r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY_BLOCK]", value)
    return value


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
                batch = json.loads(_gh(["api", query]))
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

        raw = _gh(["api", endpoint, "--paginate", "--slurp"])
        pages = json.loads(raw)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise MailboxError("GitHub returned an unexpected comments response")
        return [comment for page in pages for comment in page]

    def _reply(self, body: str) -> None:
        endpoint = f"repos/{self.repository}/issues/{self.issue_number}/comments"
        _gh(["api", "--method", "POST", endpoint, "-f", f"body={body[:MAX_COMMENT_CHARS]}"])

    def _publish_task_log(self, task: Any, comment_id: str) -> dict[str, str]:
        """Publish complete retained output in readable, per-task Markdown."""
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
                cleaned = {}
                for key, item in value.items():
                    child_path = f"{path}.{key}"
                    if key == "content":
                        cleaned[key] = "[OMITTED_FILE_CONTENT]"
                    elif key in {"output", "source_text"} and isinstance(item, str):
                        outputs.append((child_path, redact(item)))
                        label = "SOURCE TEXT" if key == "source_text" else "FULL OUTPUT"
                        cleaned[key] = f"[{label} IN SECTION: {child_path}]"
                    else:
                        cleaned[key] = sanitize(item, child_path)
                return cleaned
            return value
        record = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "source_comment_id": str(comment_id), "task_id": task_id, "kind": str(task.kind), "status": str(task.status), "attempts": int(task.attempts), "last_error": redact(str(task.last_error)) if task.last_error else None, "result": sanitize(result, "result")}
        content = "# Emberlane task output\n\n" + f"- Task ID: `{task_id}`\n- Kind: `{task.kind}`\n- Status: `{task.status}`\n- Attempts: `{task.attempts}`\n- Source comment: `{comment_id}`\n\n"
        content += "## Result metadata\n\n```json\n" + json.dumps(record, ensure_ascii=False, indent=2) + "\n```\n"
        for label, output in outputs:
            content += f"\n## Full output: `{label}`\n\n~~~text\n{output}\n~~~\n"
        if len(content.encode("utf-8")) > 1_000_000:
            raise MailboxError("task log exceeds GitHub single-file size limit (1 MB)")
        path = f"worker-logs/{task_id}.md"
        endpoint = f"repos/{self.repository}/contents/{path}"
        branch = "feat/local-coding-worker"
        existing = subprocess.run(["gh", "api", f"{endpoint}?ref={branch}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False, shell=False)
        if existing.returncode == 0:
            try:
                previous = base64.b64decode(json.loads(existing.stdout)["content"]).decode("utf-8")
            except (json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError) as exc:
                raise MailboxError("could not inspect existing task log") from exc
            if re.search(r'"task_id"\s*:\s*"' + re.escape(task_id) + r'"', previous):
                return {"task_log_status": "already_present", "task_log_path": path}
            raise MailboxError("task log path exists with unrelated content")
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        _gh(["api", "--method", "PUT", endpoint, "-f", f"message=Publish full task output {task_id}", "-f", f"content={encoded}", "-f", f"branch={branch}"])
        return {"task_log_status": "published", "task_log_path": path}
    def _publish_handoff_record(self, task: Any, comment_id: str, task_log_result: dict[str, str] | None = None) -> dict[str, str]:
        """Append a bounded, sanitized task summary to the handoff file on GitHub."""
        handoff_path = "WORKER_HANDOFF.md"
        branch = "feat/local-coding-worker"
        endpoint = f"repos/{self.repository}/contents/{handoff_path}"
        result = task.result if isinstance(task.result, dict) else {}
        allowed_keys = {
            "returncode", "passed", "failed", "tests_run", "branch_status",
            "working_tree_dirty", "changed_paths_count", "head_commit",
            "files_written", "path", "bytes_written", "result_available",
            "python_version", "platform", "content_returned_to_mailbox",
            "content_truncated",
        }
        summary = {key: result[key] for key in allowed_keys if key in result}
        if isinstance(summary.get("files_written"), list):
            summary["files_written"] = [
                {"path": item.get("path"), "bytes_written": item.get("bytes_written")}
                for item in summary["files_written"] if isinstance(item, dict)
            ]
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "source_comment_id": str(comment_id),
            "task_id": str(task.task_id),
            "kind": str(task.kind),
            "status": str(task.status),
            "attempts": int(task.attempts),
            "error_present": bool(task.last_error),
            "task_log": task_log_result or {"task_log_status": "not_reported"},
            "summary": summary,
        }
        task_log_status = (task_log_result or {}).get("task_log_status")
        task_log_link = (
            f"[Full task output](worker-logs/{task.task_id}.md)"
            if task_log_status in {"published", "already_present"}
            else "Full task output log was not published."
        )
        section = (
            "\n\n### Worker task " + str(task.task_id) + "\n\n"
            + task_log_link + "\n\n"
            + "```json\n"
            + json.dumps(record, ensure_ascii=False, indent=2)[:5000]
            + "\n```\n"
        )
        if len(section) > 6000:
            raise MailboxError("handoff record exceeded 6000 characters")

        for attempt in range(3):
            raw = _gh(["api", f"{endpoint}?ref={branch}"])
            try:
                current_file = json.loads(raw)
                current = base64.b64decode(current_file["content"]).decode("utf-8")
                sha = current_file["sha"]
            except (json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError) as exc:
                raise MailboxError("could not decode existing handoff document") from exc
            if str(task.task_id) in current:
                return {"handoff_status": "already_present"}
            updated = current + section
            encoded = base64.b64encode(updated.encode("utf-8")).decode("ascii")
            try:
                _gh([
                    "api", "--method", "PUT", endpoint,
                    "-f", f"message=Append Emberlane worker result {task.task_id}",
                    "-f", f"content={encoded}",
                    "-f", f"sha={sha}",
                    "-f", f"branch={branch}",
                ])
                return {"handoff_status": "published"}
            except MailboxError as exc:
                message = str(exc).casefold()
                if attempt == 2 or not any(
                    marker in message for marker in ("409", "422", "sha", "conflict")
                ):
                    raise
        raise MailboxError("handoff publish conflict after three attempts")

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
        safe_result = task.result
        if isinstance(safe_result, dict):
            # Do not publish file contents or raw command output in public comments.
            safe_result = {
                key: value for key, value in safe_result.items()
                if key not in {"content", "output", "source_text"}
            }
        try:
            task_log_result = self._publish_task_log(task, comment_id)
        except Exception as exc:
            task_log_result = {"task_log_status": "failed", "task_log_error": f"{type(exc).__name__}: {exc}"[:500]}
        try:
            handoff_result = self._publish_handoff_record(task, comment_id, task_log_result)
        except Exception as exc:
            handoff_result = {"handoff_status": "failed", "handoff_error": f"{type(exc).__name__}: {exc}"[:500]}
        if isinstance(safe_result, dict):
            safe_result.update(task_log_result)
            safe_result.update(handoff_result)
        result = {
            "source_comment_id": comment_id,
            "task_id": task.task_id,
            "kind": task.kind,
            "status": task.status,
            "attempts": task.attempts,
            "last_error": _redact_sensitive_text(str(task.last_error)) if task.last_error else None,
            "result": safe_result,
        }
        self._reply("EMBERLANE_RESULT\n" + json.dumps(result, ensure_ascii=False, indent=2)[:MAX_COMMENT_CHARS])
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
