import json
import tempfile
import unittest
from pathlib import Path

from emberlane.supervisor import run_supervisor
from emberlane.worker import LocalWorker


class BoundedSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tests").mkdir()
        self.worker = LocalWorker(self.root)

    def test_runs_only_the_configured_task_budget_and_redacts_payload_from_audit(self):
        first = self.worker.submit("write_file", {
            "path": "one.txt", "content": "SECRET_CONTENT=do-not-log"
        })
        second = self.worker.submit("write_file", {
            "path": "two.txt", "content": "second"
        })
        report = run_supervisor(self.worker, max_tasks=1, max_failures=2, max_seconds=30)
        self.assertEqual(report["status"], "task_limit")
        self.assertEqual(report["processed"], 1)
        self.assertEqual(report["task_ids"], [first.task_id])
        self.assertEqual(self.worker.queue.get(first.task_id).status, "completed")
        self.assertEqual(self.worker.queue.get(second.task_id).status, "pending")
        audit = (self.root / ".emberlane" / "supervisor.jsonl").read_text(encoding="utf-8")
        events = [json.loads(line) for line in audit.splitlines()]
        self.assertEqual([event["event"] for event in events], [
            "supervisor_started", "task_finished", "supervisor_stopped"
        ])
        self.assertIn(first.task_id, audit)
        self.assertNotIn("SECRET_CONTENT", audit)
        self.assertNotIn("do-not-log", audit)

    def test_pause_marker_prevents_claiming_any_task(self):
        task = self.worker.submit("write_file", {"path": "blocked.txt", "content": "no"})
        marker = self.root / ".emberlane" / "PAUSED"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        report = run_supervisor(self.worker, max_tasks=5, max_failures=2, max_seconds=30)
        self.assertEqual(report["status"], "paused")
        self.assertEqual(report["processed"], 0)
        self.assertEqual(self.worker.queue.get(task.task_id).status, "pending")
        self.assertEqual(self.worker.queue.get(task.task_id).attempts, 0)
        self.assertFalse((self.root / "blocked.txt").exists())

    def test_deferred_only_queue_returns_idle_without_resuming_it(self):
        task = self.worker.submit("write_file", {"path": "later.txt", "content": "later"})
        queued = self.worker.queue.get(task.task_id)
        queued.status = "deferred"
        self.worker.queue._save()
        report = run_supervisor(self.worker, max_tasks=5, max_failures=2, max_seconds=30)
        self.assertEqual(report["status"], "idle")
        self.assertEqual(report["processed"], 0)
        self.assertEqual(report["deferred_task_ids"], [task.task_id])
        self.assertEqual(self.worker.queue.get(task.task_id).status, "deferred")
        self.assertEqual(self.worker.queue.get(task.task_id).attempts, 0)

    def test_invalid_limits_are_rejected_before_start(self):
        for kwargs in (
            {"max_tasks": 0},
            {"max_failures": True},
            {"max_seconds": 86401},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run_supervisor(self.worker, **kwargs)
        self.assertFalse((self.root / ".emberlane" / "supervisor.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
