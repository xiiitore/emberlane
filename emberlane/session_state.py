"""Generate a compact, privacy-preserving Emberlane continuity snapshot."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dropbox_output import DropboxOutputError, upload_task_log

STATE_NAME = "EMBERLANE_CURRENT_STATE.md"
PUBLISH_ID = "SESSION-CONTINUITY"
RETRY_SECONDS = 300
SAFE_RESULT_FIELDS = (
    "returncode", "exit_code", "passed", "failed", "count",
    "bytes_written", "files_changed", "replacements", "ok",
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _read_json_with_status(path: Path) -> tuple[Any, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), "PASS"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "UNKNOWN"


def _utc(epoch: Any) -> str:
    if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or epoch <= 0:
        return "UNKNOWN"
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError):
        return "UNKNOWN"


def _git_value(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else "UNKNOWN"


def render_state(root: str | Path) -> str:
    """Render deterministic Markdown from local project metadata."""
    project = Path(root).resolve()
    queue_raw, queue_read_status = _read_json_with_status(
        project / ".emberlane" / "queue.json"
    )
    tasks = queue_raw if isinstance(queue_raw, list) else []
    if not isinstance(queue_raw, list):
        queue_read_status = "UNKNOWN"
    valid = [item for item in tasks if isinstance(item, dict)]

    counts: dict[str, int] = {}
    for item in valid:
        status = item.get("status")
        if isinstance(status, str):
            counts[status] = counts.get(status, 0) + 1

    mailbox_raw, mailbox_read_status = _read_json_with_status(
        project / ".emberlane" / "mailbox-state.json"
    )
    mailbox = mailbox_raw if isinstance(mailbox_raw, dict) else {}
    if not isinstance(mailbox_raw, dict):
        mailbox_read_status = "UNKNOWN"

    handled = mailbox.get("handled", [])
    active = mailbox.get("active", {})
    cursor = mailbox.get("cursor", 0)
    handled_count = len(handled) if isinstance(handled, list) else 0
    active_count = len(active) if isinstance(active, dict) else 0
    cursor_text = (
        str(cursor)
        if isinstance(cursor, (str, int)) and not isinstance(cursor, bool)
        else "UNKNOWN"
    )

    recent = sorted(
        valid,
        key=lambda item: (
            item.get("updated_at")
            if isinstance(item.get("updated_at"), (int, float))
            else 0,
            str(item.get("task_id", "")),
        ),
        reverse=True,
    )[:12]

    lines = [
        "# Emberlane Current State",
        "",
        "> Generated from local queue and mailbox metadata. Task payloads and arbitrary output are intentionally excluded.",
        "",
        "- Snapshot is content-addressed; inspect queue/task timestamps below for freshness.",
        f"- Branch: {_git_value(project, 'branch', '--show-current')}",
        f"- HEAD: {_git_value(project, 'rev-parse', '--short=12', 'HEAD')}",
        f"- Queue source read: {queue_read_status}",
        f"- Queue records: {len(valid) if queue_read_status == 'PASS' else 'UNKNOWN'}",
        "- Queue status counts: "
        + (", ".join(f"{key}={counts[key]}" for key in sorted(counts)) if counts else "none"),
        f"- Mailbox source read: {mailbox_read_status}",
        f"- Mailbox handled comments: {handled_count if mailbox_read_status == 'PASS' else 'UNKNOWN'}",
        f"- Mailbox active comments: {active_count if mailbox_read_status == 'PASS' else 'UNKNOWN'}",
        f"- Mailbox high-water cursor: {cursor_text if mailbox_read_status == 'PASS' else 'UNKNOWN'}",
        "",
        "## Recent tasks",
        "",
    ]
    if queue_read_status != "PASS":
        lines.append("- Task list unavailable: queue file missing or invalid; counts are not evidence of an empty queue.")
    elif not recent:
        lines.append("- No task records found.")

    for item in recent:
        task_id = item.get("task_id", "UNKNOWN")
        result = item.get("result")
        summary = []
        if isinstance(result, dict):
            for key in SAFE_RESULT_FIELDS:
                value = result.get(key)
                safe_type = isinstance(value, (str, int, float, bool))
                safe_text = not isinstance(value, str) or len(value) <= 40
                if value is not None and safe_type and safe_text:
                    summary.append(f"{key}={value}")
        lines.append(
            f"- {task_id} | kind={item.get('kind', 'UNKNOWN')} "
            f"| status={item.get('status', 'UNKNOWN')} "
            f"| attempts={item.get('attempts', 'UNKNOWN')} "
            f"| updated={_utc(item.get('updated_at'))} "
            f"| error_present={bool(item.get('last_error'))}"
            + (f" | result: {', '.join(summary)}" if summary else "")
        )

    lines.extend([
        "",
        "## Operating rules",
        "",
        "- This snapshot is an index, not proof that tests passed or a patch was applied.",
        "- Verify the exact task log and source revision before making implementation claims.",
        "- Use PASS / FAIL / BLOCKED / UNKNOWN; completed status alone is insufficient.",
        "- Avoid bulk-fetching the full Issue #6 comment history; use bounded queries and exact log paths.",
        "- Preserve local dirty changes; do not reset, clean, stash, merge, or sync without an evidence-based reason.",
        "- Confirm unresolved claims against fresh logs before acting.",
        "",
    ])
    return "\n".join(lines)


def refresh_session_state(root: str | Path, *, publish: bool = True) -> dict[str, Any]:
    """Write the snapshot and publish changed content with verified read-back."""
    project = Path(root).resolve()
    state_dir = project / ".emberlane"
    state_dir.mkdir(parents=True, exist_ok=True)
    content = render_state(project)
    state_path = project / STATE_NAME
    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, state_path)

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    published_path = state_dir / "session-state.sha256"
    attempt_path = state_dir / "session-state-last-attempt.json"
    try:
        previous = published_path.read_text(encoding="ascii").strip()
    except OSError:
        previous = ""

    if not publish:
        return {"status": "local_only", "path": str(state_path), "sha256": digest}
    if previous == digest:
        return {"status": "unchanged", "path": str(state_path), "sha256": digest}

    last = _read_json(attempt_path, {})
    last = last if isinstance(last, dict) else {}
    attempted_at = last.get("time")
    if (
        last.get("sha256") == digest
        and isinstance(attempted_at, (int, float))
        and time.time() - attempted_at < RETRY_SECONDS
    ):
        return {"status": "retry_deferred", "path": str(state_path), "sha256": digest}

    attempt_path.write_text(
        json.dumps({"sha256": digest, "time": time.time()}, sort_keys=True),
        encoding="utf-8",
    )
    try:
        remote = upload_task_log(PUBLISH_ID, content)
    except (DropboxOutputError, OSError, ValueError) as exc:
        return {
            "status": "publish_failed",
            "path": str(state_path),
            "sha256": digest,
            "error_type": type(exc).__name__,
        }

    if remote.get("readback_verified") is not True or remote.get("status") != "published":
        return {"status": "publish_unverified", "path": str(state_path), "sha256": digest}

    published_path.write_text(digest + "\n", encoding="ascii")
    return {
        "status": "published",
        "path": str(state_path),
        "sha256": digest,
        "remote_path": remote.get("path"),
        "readback_verified": True,
    }
