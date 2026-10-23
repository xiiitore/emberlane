"""Bounded, auditable supervisor loop for the local Emberlane worker.

This coordinates existing allow-listed tasks; it does not execute shell input,
resume deferred tasks, or imply that a local model is configured.
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
) -> dict[str, Any]:
    """Run a finite batch; idle/deferred queues return immediately without polling."""
    max_tasks = _positive_int(max_tasks, "max_tasks", 1000)
    max_failures = _positive_int(max_failures, "max_failures", 100)
    max_seconds = _positive_int(max_seconds, "max_seconds", 86400)
    audit_path = worker.root / ".emberlane" / "supervisor.jsonl"
    started = time.monotonic()
    deadline = started + max_seconds
    task_ids: list[str] = []
    failures = 0
    deferred_ids: list[str] = []
    status = "task_limit"

    def emit(event: dict[str, Any]) -> bool:
        try:
            _append_event(audit_path, {
                "timestamp": time.time(),
                "pid": os.getpid(),
                **event,
            })
            return True
        except (OSError, ValueError):
            return False

    if not emit({
        "event": "supervisor_started",
        "max_tasks": max_tasks,
        "max_failures": max_failures,
        "max_seconds": max_seconds,
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

        task_started = time.monotonic()
        task = worker.run_one()
        elapsed = round(max(0.0, time.monotonic() - task_started), 3)
        if task is None:
            state = control_state(worker.root)
            status = state if state is not None else "idle"
            break

        task_ids.append(task.task_id)
        if task.status == "failed":
            failures += 1
        if task.status == "deferred":
            deferred_ids.append(task.task_id)
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
        "audit_log": str(audit_path.relative_to(worker.root)),
    }
    if not emit({
        "event": "supervisor_stopped",
        "status": status,
        "processed": len(task_ids),
        "failures": failures,
        "deferred_count": len(deferred_ids),
    }):
        report["status"] = "audit_log_error"
    return report
