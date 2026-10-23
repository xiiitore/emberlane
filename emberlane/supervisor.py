"""Bounded, auditable supervisor loop for the local Emberlane worker.

Optional mailbox polling is finite and serial: enqueue one authorized task, run
one queue task, and let the mailbox publish terminal metadata. No auto-resume,
arbitrary shell execution, or unbounded polling is performed.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .pause import control_state


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer from 1 to {maximum}")
    return value


def _append_event(path: Path, event: dict[str, Any]) -> None:
    """Append one bounded metadata-only JSON line and fsync it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    line = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(line) > 4096:
        raise ValueError("supervisor event exceeds size limit")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        view = memoryview(line)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short supervisor audit write")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def run_supervisor(
    worker: Any,
    *,
    max_tasks: int = 10,
    max_failures: int = 3,
    max_seconds: int = 300,
    mailbox: Any | None = None,
    poll_interval_seconds: int = 5,
    max_idle_polls: int = 1,
) -> dict[str, Any]:
    """Run a finite batch; mailbox polling is optional and has an explicit idle budget."""
    max_tasks = _positive_int(max_tasks, "max_tasks", 1000)
    max_failures = _positive_int(max_failures, "max_failures", 100)
    max_seconds = _positive_int(max_seconds, "max_seconds", 86400)
    poll_interval_seconds = _positive_int(poll_interval_seconds, "poll_interval_seconds", 3600)
    max_idle_polls = _positive_int(max_idle_polls, "max_idle_polls", 1000)
    if mailbox is None:
        max_idle_polls = 1

    audit_path = worker.root / ".emberlane" / "supervisor.jsonl"
    started = time.monotonic()
    deadline = started + max_seconds
    task_ids: list[str] = []
    failures = 0
    deferred_ids: list[str] = []
    idle_polls = 0
    status = "task_limit"
    mailbox_status: str | None = None
    safe_mailbox_statuses = {"idle", "pending", "finished", "rejected"}

    def emit(event: dict[str, Any]) -> bool:
        try:
            _append_event(audit_path, {
                "timestamp": time.time(),
                "pid": os.getpid(),
                **event,
            })
            return True
        except (OSError, ValueError, TypeError):
            return False

    if not emit({
        "event": "supervisor_started",
        "max_tasks": max_tasks,
        "max_failures": max_failures,
        "max_seconds": max_seconds,
        "mailbox_enabled": mailbox is not None,
        "poll_interval_seconds": poll_interval_seconds if mailbox is not None else None,
        "max_idle_polls": max_idle_polls,
    }):
        return {"status": "audit_log_error", "processed": 0, "failures": 0, "task_ids": []}

    while True:
        state = control_state(worker.root)
        if state is not None:
            status = state
            break
        if time.monotonic() >= deadline:
            status = "deadline_reached"
            break
        if len(task_ids) >= max_tasks:
            status = "task_limit"
            break
        if failures >= max_failures:
            status = "failure_limit"
            break

        if mailbox is not None:
            try:
                mailbox_result = mailbox.run_once(execute_tasks=False)
                candidate = mailbox_result.get("status") if isinstance(mailbox_result, dict) else None
                mailbox_status = candidate if isinstance(candidate, str) and candidate in safe_mailbox_statuses else "other"
            except Exception as exc:
                status = "mailbox_error"
                if not emit({
                    "event": "mailbox_error",
                    "error_type": type(exc).__name__,
                }):
                    status = "audit_log_error"
                break

        task_started = time.monotonic()
        task = worker.run_one()
        elapsed = round(max(0.0, time.monotonic() - task_started), 3)
        if task is None:
            state = control_state(worker.root)
            if state is not None:
                status = state
                break
            if mailbox is not None and idle_polls + 1 < max_idle_polls:
                idle_polls += 1
                if not emit({
                    "event": "mailbox_idle_poll",
                    "idle_poll": idle_polls,
                    "mailbox_status": mailbox_status,
                }):
                    status = "audit_log_error"
                    break
                time.sleep(min(poll_interval_seconds, max(0.0, deadline - time.monotonic())))
                continue
            status = "idle" if mailbox is None else "mailbox_idle"
            break

        idle_polls = 0
        task_ids.append(task.task_id)
        if task.status == "failed":
            failures += 1
        result_status = (
            task.result.get("status")
            if isinstance(task.result, dict) and isinstance(task.result.get("status"), str)
            else None
        )
        if not emit({
            "event": "task_finished",
            "task_id": task.task_id,
            "kind": task.kind,
            "task_status": task.status,
            "attempts": task.attempts,
            "result_status": result_status,
            "duration_seconds": elapsed,
            "mailbox_status": mailbox_status,
        }):
            status = "audit_log_error"
            break

        if mailbox is not None:
            try:
                mailbox_result = mailbox.run_once(execute_tasks=False)
                candidate = mailbox_result.get("status") if isinstance(mailbox_result, dict) else None
                mailbox_status = candidate if isinstance(candidate, str) and candidate in safe_mailbox_statuses else "other"
            except Exception as exc:
                status = "mailbox_error"
                if not emit({
                    "event": "mailbox_error",
                    "error_type": type(exc).__name__,
                    "after_task_id": task.task_id,
                }):
                    status = "audit_log_error"
                break

    deferred_ids = sorted({task.task_id for task in worker.queue.list_tasks() if task.status == "deferred"})
    report = {
        "status": status,
        "processed": len(task_ids),
        "failures": failures,
        "task_ids": task_ids,
        "deferred_task_ids": deferred_ids,
        "max_tasks": max_tasks,
        "max_failures": max_failures,
        "max_seconds": max_seconds,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
        "mailbox_enabled": mailbox is not None,
        "mailbox_status": mailbox_status,
        "idle_polls": idle_polls,
        "audit_log": str(audit_path.relative_to(worker.root)),
    }
    if not emit({
        "event": "supervisor_stopped",
        "status": status,
        "processed": len(task_ids),
        "failures": failures,
        "deferred_count": len(deferred_ids),
        "mailbox_enabled": mailbox is not None,
    }):
        report["status"] = "audit_log_error"
    return report
