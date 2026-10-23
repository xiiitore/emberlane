import json
import tempfile
import unittest
from unittest.mock import patch
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


    def test_mailbox_supervision_enqueues_executes_and_finalizes_within_budget(self):
        class FakeMailbox:
            def __init__(self, worker):
                self.worker = worker
                self.calls = 0
            def run_once(self, *, execute_tasks=True):
                if execute_tasks is not False:
                    raise AssertionError("supervisor must own task execution")
                self.calls += 1
                if self.calls == 1:
                    task = self.worker.submit("write_file", {
                        "path": "mailbox.txt", "content": "from mailbox"
                    })
                    return {"status": "pending", "task_id": task.task_id}
                return {"status": "finished"}

        mailbox = FakeMailbox(self.worker)
        report = run_supervisor(
            self.worker, max_tasks=1, max_failures=2, max_seconds=30, mailbox=mailbox
        )
        self.assertEqual(report["status"], "task_limit")
        self.assertEqual(report["processed"], 1)
        self.assertTrue(report["mailbox_enabled"])
        self.assertEqual(report["mailbox_status"], "finished")
        self.assertEqual(mailbox.calls, 2)
        self.assertEqual((self.root / "mailbox.txt").read_text(encoding="utf-8"), "from mailbox")

    def test_mailbox_idle_polling_is_bounded_and_waits_between_polls(self):
        class IdleMailbox:
            def __init__(self):
                self.calls = 0
            def run_once(self, *, execute_tasks=True):
                self.calls += 1
                return {"status": "idle"}

        mailbox = IdleMailbox()
        with patch("emberlane.supervisor.time.sleep") as sleep:
            report = run_supervisor(
                self.worker, max_tasks=5, max_failures=2, max_seconds=30,
                mailbox=mailbox, poll_interval_seconds=7, max_idle_polls=3,
            )
        self.assertEqual(report["status"], "mailbox_idle")
        self.assertEqual(mailbox.calls, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(all(call.args[0] <= 7 for call in sleep.call_args_list))

    def test_mailbox_poll_failure_stops_without_logging_exception_message(self):
        class BrokenMailbox:
            def run_once(self, *, execute_tasks=True):
                raise RuntimeError("private diagnostic at /tmp/private")

        report = run_supervisor(
            self.worker, max_tasks=5, max_failures=2, max_seconds=30, mailbox=BrokenMailbox()
        )
        self.assertEqual(report["status"], "mailbox_error")
        audit = (self.root / ".emberlane" / "supervisor.jsonl").read_text(encoding="utf-8")
        self.assertIn("RuntimeError", audit)
        self.assertNotIn("private diagnostic", audit)
        self.assertNotIn("/tmp/private", audit)



if __name__ == "__main__":
    unittest.main()
