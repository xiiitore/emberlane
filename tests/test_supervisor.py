import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from emberlane.supervisor import run_supervisor
from emberlane.worker import LocalWorker
from emberlane.mailbox import GitHubIssueMailbox


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
        # get() returns a detached snapshot; set fixture state on the stored task.
        self.worker.queue._tasks[queued.task_id].status = "deferred"
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

    def test_mailbox_result_stays_bound_to_task_when_older_fifo_task_is_pending(self):
        older = self.worker.submit("write_file", {
            "path": "older.txt", "content": "older queued work"
        })

        class MappedMailbox:
            def __init__(self, worker):
                self.worker = worker
                self.calls = 0
                self.task_id = None
                self.source_comment_id = "source-123"

            def run_once(self, *, execute_tasks=True):
                if execute_tasks is not False:
                    raise AssertionError("supervisor must own task execution")
                self.calls += 1
                if self.task_id is None:
                    task = self.worker.submit(
                        "write_file",
                        {"path": "mailbox.txt", "content": "mapped mailbox work"},
                        idempotency_key=self.source_comment_id,
                    )
                    self.task_id = task.task_id
                task = self.worker.queue.get(self.task_id)
                if task.status in {"completed", "failed", "cancelled", "canceled"}:
                    return {
                        "status": "finished",
                        "comment_id": self.source_comment_id,
                        "task_id": self.task_id,
                    }
                return {
                    "status": "pending",
                    "comment_id": self.source_comment_id,
                    "task_id": self.task_id,
                }

        mailbox = MappedMailbox(self.worker)
        report = run_supervisor(
            self.worker, max_tasks=2, max_failures=2, max_seconds=30, mailbox=mailbox
        )

        self.assertEqual(report["status"], "task_limit")
        self.assertEqual(report["processed"], 2)
        self.assertEqual(report["task_ids"], [older.task_id, mailbox.task_id])
        self.assertEqual(mailbox.calls, 4)
        self.assertEqual(self.worker.queue.get(older.task_id).status, "completed")
        self.assertEqual(self.worker.queue.get(mailbox.task_id).status, "completed")
        self.assertEqual((self.root / "older.txt").read_text(encoding="utf-8"), "older queued work")
        self.assertEqual((self.root / "mailbox.txt").read_text(encoding="utf-8"), "mapped mailbox work")

    def test_real_mailbox_publication_stays_linked_to_mapped_task_under_supervisor_fifo(self):
        older = self.worker.submit("write_file", {
            "path": "older.txt", "content": "older queued work"
        })
        mailbox = GitHubIssueMailbox(self.worker, "owner/repo", 6, "authorized")
        mailbox._comments = lambda: [{
            "id": 456,
            "user": {"login": "authorized"},
            "body": 'EMBERLANE_TASK_JSON\n' + json.dumps({
                "kind": "write_file",
                "payload": {"path": "mailbox.txt", "content": "mapped mailbox work"},
            }),
        }]
        mailbox.state = {"handled": [], "active": {}}
        mailbox._save_state = lambda: None
        mailbox._publish_task_log = lambda *_: {
            "task_log_status": "published", "task_log_url": "test://task-log",
        }
        mailbox._publish_handoff_record = lambda *_: {"handoff_status": "published"}
        replies = []
        mailbox._reply = replies.append

        report = run_supervisor(
            self.worker, max_tasks=2, max_failures=2, max_seconds=30, mailbox=mailbox
        )

        self.assertEqual(report["status"], "task_limit")
        self.assertEqual(report["task_ids"][0], older.task_id)
        self.assertEqual(self.worker.queue.get(older.task_id).status, "completed")
        self.assertEqual(mailbox.state["handled"], ["456"])
        self.assertEqual(mailbox.state["active"], {})
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0].startswith("EMBERLANE_RESULT\n{"))
        published = json.loads(replies[0].split("\n", 1)[1])
        self.assertEqual(published["source_comment_id"], "456")
        self.assertEqual(published["task_id"], report["task_ids"][1])
        self.assertEqual(self.worker.queue.get(published["task_id"]).status, "completed")
        self.assertEqual((self.root / "older.txt").read_text(encoding="utf-8"), "older queued work")
        self.assertEqual((self.root / "mailbox.txt").read_text(encoding="utf-8"), "mapped mailbox work")

    def test_real_mailbox_waits_across_max_tasks_one_batches_before_publishing(self):
        older = self.worker.submit("write_file", {
            "path": "older.txt", "content": "older queued work"
        })
        mailbox = GitHubIssueMailbox(self.worker, "owner/repo", 6, "authorized")
        mailbox._comments = lambda: [{
            "id": 789,
            "user": {"login": "authorized"},
            "body": 'EMBERLANE_TASK_JSON\n' + json.dumps({
                "kind": "write_file",
                "payload": {"path": "mailbox.txt", "content": "mapped mailbox work"},
            }),
        }]
        mailbox.state = {"handled": [], "active": {}}
        mailbox._save_state = lambda: None
        mailbox._publish_task_log = lambda *_: {
            "task_log_status": "published", "task_log_url": "test://task-log",
        }
        mailbox._publish_handoff_record = lambda *_: {"handoff_status": "published"}
        replies = []
        mailbox._reply = replies.append

        first_report = run_supervisor(
            self.worker, max_tasks=1, max_failures=2, max_seconds=30, mailbox=mailbox
        )

        self.assertEqual(first_report["status"], "task_limit")
        self.assertEqual(first_report["task_ids"], [older.task_id])
        self.assertEqual(self.worker.queue.get(older.task_id).status, "completed")
        self.assertEqual(mailbox.state["handled"], [])
        self.assertEqual(set(mailbox.state["active"]), {"789"})
        mailbox_task_id = mailbox.state["active"]["789"]
        self.assertEqual(self.worker.queue.get(mailbox_task_id).status, "pending")
        self.assertEqual(replies, [])
        self.assertFalse((self.root / "mailbox.txt").exists())

        mailbox._comments = lambda: []
        second_report = run_supervisor(
            self.worker, max_tasks=1, max_failures=2, max_seconds=30, mailbox=mailbox
        )

        self.assertEqual(second_report["status"], "task_limit")
        self.assertEqual(second_report["task_ids"], [mailbox_task_id])
        self.assertEqual(self.worker.queue.get(mailbox_task_id).status, "completed")
        self.assertEqual(mailbox.state["handled"], ["789"])
        self.assertEqual(mailbox.state["active"], {})
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0].startswith("EMBERLANE_RESULT\n{"))
        published = json.loads(replies[0].split("\n", 1)[1])
        self.assertEqual(published["source_comment_id"], "789")
        self.assertEqual(published["task_id"], mailbox_task_id)
        self.assertEqual(published["status"], "completed")
        self.assertEqual((self.root / "older.txt").read_text(encoding="utf-8"), "older queued work")
        self.assertEqual((self.root / "mailbox.txt").read_text(encoding="utf-8"), "mapped mailbox work")

    def test_real_mailbox_failed_task_publishes_failed_status_not_success(self):
        task = self.worker.submit("write_file", {
            "path": "will-not-run.txt", "content": "unused"
        })
        # submit() returns a detached snapshot; set fixture state on the stored task.
        self.worker.queue._tasks[task.task_id].status = "failed"
        self.worker.queue._tasks[task.task_id].last_error = "fixture: deliberate terminal failure"
        self.worker.queue._save()

        mailbox = GitHubIssueMailbox(self.worker, "owner/repo", 6, "authorized")
        mailbox._comments = lambda: []
        mailbox.state = {"handled": [], "active": {"790": task.task_id}}
        mailbox._save_state = lambda: None
        mailbox._publish_task_log = lambda *_: {
            "task_log_status": "published", "task_log_url": "test://task-log",
        }
        mailbox._publish_handoff_record = lambda *_: {"handoff_status": "published"}
        replies = []
        mailbox._reply = replies.append

        report = run_supervisor(
            self.worker, max_tasks=1, max_failures=2, max_seconds=30, mailbox=mailbox
        )

        self.assertEqual(report["status"], "mailbox_idle")
        self.assertEqual(report["processed"], 0)
        self.assertEqual(self.worker.queue.get(task.task_id).status, "failed")
        self.assertEqual(mailbox.state["handled"], ["790"])
        self.assertEqual(mailbox.state["active"], {})
        self.assertEqual(len(replies), 1)
        published = json.loads(replies[0].split("\n", 1)[1])
        self.assertEqual(published["source_comment_id"], "790")
        self.assertEqual(published["task_id"], task.task_id)
        self.assertEqual(published["status"], "failed")
        self.assertTrue(published["error_present"])
        self.assertNotEqual(published["status"], "completed")

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