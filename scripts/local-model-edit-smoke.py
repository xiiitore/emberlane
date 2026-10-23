#!/usr/bin/env python3
"""Run one real local-model edit in a disposable fixture, never the repository checkout."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from emberlane.worker import LocalWorker  # noqa: E402


def _result_summary(task: Any) -> dict[str, Any]:
    result = task.result if isinstance(task.result, dict) else {}
    fields = (
        "status", "reason", "stage", "applied", "changed_paths", "test_file",
        "test_returncode", "context_bytes", "context_size_used", "tests",
        "test_output_bytes",
    )
    return {
        "task_id": task.task_id,
        "task_status": task.status,
        "attempts": task.attempts,
        "result": {key: result[key] for key in fields if key in result},
    }


def main() -> int:
    model_value = os.environ.get("EMBERLANE_MODEL_PATH", "").strip()
    if not model_value or not Path(model_value).expanduser().is_file():
        print(json.dumps({
            "status": "blocked",
            "reason": "Set EMBERLANE_MODEL_PATH to an existing local GGUF model file.",
        }, ensure_ascii=False))
        return 2

    print(json.dumps({"stage": "preflight_passed", "python": sys.executable, "model": str(Path(model_value).expanduser())}), flush=True)
    try:
        return _run_smoke()
    except Exception as exc:
        print(json.dumps({
            "status": "failed",
            "stage": "uncaught_exception",
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
        }, ensure_ascii=False), flush=True)
        return 1


def _run_smoke() -> int:
    with tempfile.TemporaryDirectory(prefix="emberlane-local-edit-smoke-") as temporary:
        root = Path(temporary) / "fixture"
        (root / "src").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / "src" / "__init__.py").write_text("", encoding="utf-8")
        (root / "src" / "value.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "tests" / "test_value.py").write_text(
            "import unittest\n"
            "from src.value import VALUE\n"
            "class ValueTests(unittest.TestCase):\n"
            "    def test_value_is_two(self): self.assertEqual(VALUE, 2)\n",
            encoding="utf-8",
        )
        state_path = root / ".emberlane" / "queue.json"
        worker = LocalWorker(root, state_path)
        submitted = worker.submit("local_model_edit", {
            "goal": "Change VALUE in src/value.py from 1 to 2. Preserve the file structure.",
            "allowed_paths": ["src/value.py"],
            "context_size": 4096,
            "max_tokens": 128,
            "timeout_seconds": 180,
            "test_file": "test_value.py",
            "test_timeout_seconds": 30,
        })
        print(json.dumps({"stage": "task_submitted", "task_id": submitted.task_id}), flush=True)
        print(json.dumps({"stage": "model_running", "timeout_seconds": 180}), flush=True)
        task = worker.run_one()
        if task is None:
            print(json.dumps({"status": "failed", "reason": "queue_returned_no_task"}), flush=True)
            return 1
        print(json.dumps(_result_summary(task), ensure_ascii=False, indent=2), flush=True)
        if task.status != "completed" or not isinstance(task.result, dict):
            return 1
        if task.result.get("status") != "applied_and_verified":
            return 1
        value_file = root / "src" / "value.py"
        if not value_file.is_file() or "VALUE = 2" not in value_file.read_text(encoding="utf-8"):
            print(json.dumps({"status": "failed", "reason": "postcondition_mismatch"}), flush=True)
            return 1
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
