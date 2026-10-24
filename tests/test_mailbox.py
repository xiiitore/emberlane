import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emberlane.worker import LocalWorker
from emberlane.mailbox import (
    GitHubIssueMailbox,
    MAX_GH_ATTEMPTS,
    MailboxError,
    _gh,
    _gh_json,
    _retry_after_seconds,
    _task_from_comment,
)


class MailboxParsingTests(unittest.TestCase):
    def test_parses_exact_task_envelope(self):
        body = 'EMBERLANE_TASK_JSON\n' + json.dumps({
            "kind": "write_file",
            "payload": {"path": "src/demo.py", "content": "VALUE = 1\\n"},
        })
        self.assertEqual(_task_from_comment(body), {
            "kind": "write_file",
            "payload": {"path": "src/demo.py", "content": "VALUE = 1\\n"},
        })

    def test_ignores_non_task_comment(self):
        self.assertIsNone(_task_from_comment("ordinary discussion"))

    def test_rejects_extra_envelope_fields(self):
        with self.assertRaisesRegex(MailboxError, "exactly"):
            _task_from_comment('EMBERLANE_TASK_JSON\n{"kind":"run_tests","payload":{},"command":"id"}')

    def test_rejects_non_object_payload(self):
        with self.assertRaisesRegex(MailboxError, "payload must be an object"):
            _task_from_comment('EMBERLANE_TASK_JSON\n{"kind":"run_tests","payload":[]}')

    def test_rejects_invalid_json(self):
        with self.assertRaisesRegex(MailboxError, "invalid task JSON"):
            _task_from_comment("EMBERLANE_TASK_JSON\n{broken")


class GitHubRetryTests(unittest.TestCase):
    @staticmethod
    def response(code, stdout="", stderr=""):
        return subprocess.CompletedProcess(["gh"], code, stdout, stderr)

    @patch("emberlane.mailbox.time.sleep")
    @patch("emberlane.mailbox.subprocess.run")
    def test_rate_limit_403_retries_then_succeeds(self, run, sleep):
        run.side_effect = [
            self.response(1, stderr="HTTP 403: API rate limit exceeded"),
            self.response(0, stdout='{"ok": true}'),
        ]
        self.assertEqual(_gh(["api", "repos/example/repo"]), '{"ok": true}')
        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(1.0)

    @patch("emberlane.mailbox.time.sleep")
    @patch("emberlane.mailbox.subprocess.run")
    def test_retry_after_header_is_respected(self, run, sleep):
        run.side_effect = [
            self.response(1, stderr="HTTP 429: rate limit\nRetry-After: 4"),
            self.response(0, stdout="ok"),
        ]
        self.assertEqual(_gh(["api", "endpoint"]), "ok")
        sleep.assert_called_once_with(4.0)

    def test_retry_after_is_bounded(self):
        from emberlane.mailbox import MAX_RETRY_DELAY_SECONDS

        self.assertEqual(_retry_after_seconds("Retry-After: 999"), MAX_RETRY_DELAY_SECONDS)
        self.assertIsNone(_retry_after_seconds("no retry header"))

    @patch("emberlane.mailbox.time.sleep")
    @patch("emberlane.mailbox._gh")
    def test_truncated_successful_json_response_retries_then_succeeds(self, gh, sleep):
        gh.side_effect = ["{\"ok\":", '{"ok": true}']
        self.assertEqual(_gh_json(["api", "repos/example/repo"]), {"ok": True})
        self.assertEqual(gh.call_count, 2)
        sleep.assert_called_once_with(1.0)

    @patch("emberlane.mailbox.time.sleep")
    @patch("emberlane.mailbox.subprocess.run")
    def test_permission_403_fails_without_retry(self, run, sleep):
        run.return_value = self.response(1, stderr="HTTP 403: Resource not accessible by integration")
        with self.assertRaisesRegex(MailboxError, "Resource not accessible"):
            _gh(["api", "endpoint"])
        run.assert_called_once()
        sleep.assert_not_called()

    @patch("emberlane.mailbox.time.sleep")
    @patch("emberlane.mailbox.subprocess.run")
    def test_retry_attempts_are_bounded(self, run, sleep):
        run.return_value = self.response(1, stderr="HTTP 503: Service Unavailable")
        with self.assertRaisesRegex(MailboxError, "Service Unavailable"):
            _gh(["api", "endpoint"])
        self.assertEqual(run.call_count, MAX_GH_ATTEMPTS)
        self.assertEqual(sleep.call_count, MAX_GH_ATTEMPTS - 1)

class MailboxCommentFetchTests(unittest.TestCase):
    @patch("emberlane.mailbox._gh")
    def test_incremental_fetch_stops_at_persisted_comment_cursor(self, gh):
        mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        mailbox.repository = "owner/repo"
        mailbox.issue_number = 6
        mailbox.state = {"handled": ["100"], "active": {}}
        gh.return_value = json.dumps([
            {"id": 102}, {"id": 101}, {"id": 100},
        ])

        comments = mailbox._comments()

        self.assertEqual([item["id"] for item in comments], [101, 102])
        gh.assert_called_once_with([
            "api",
            "repos/owner/repo/issues/6/comments?per_page=100&sort=created&direction=desc&page=1",
        ])

    @patch("emberlane.mailbox._gh")
    def test_empty_state_preserves_full_history_recovery(self, gh):
        mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        mailbox.repository = "owner/repo"
        mailbox.issue_number = 6
        mailbox.state = {"handled": [], "active": {}}
        gh.return_value = json.dumps([[{"id": 2}, {"id": 1}]])

        comments = mailbox._comments()

        self.assertEqual([item["id"] for item in comments], [2, 1])
        gh.assert_called_once_with([
            "api", "repos/owner/repo/issues/6/comments", "--paginate", "--slurp",
        ])


class MailboxIdempotencyTests(unittest.TestCase):
    def test_recovers_crash_after_queue_submit_without_duplicate_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worker = LocalWorker(root)
            payload = {"path": "src/generated.py", "content": "VALUE = 7\\n"}
            original = worker.submit("write_file", payload, idempotency_key="123")
            worker.run_one()
            self.assertEqual((root / "src/generated.py").read_text(), "VALUE = 7\\n")

            mailbox = GitHubIssueMailbox(worker, "owner/repo", 6, "authorized")
            mailbox._comments = lambda: [{
                "id": 123,
                "user": {"login": "authorized"},
                "body": 'EMBERLANE_TASK_JSON\n' + json.dumps({
                    "kind": "write_file",
                    "payload": payload,
                }),
            }]
            replies = []
            mailbox._reply = replies.append
            mailbox._publish_task_log = lambda task, comment_id: {
                "task_log_status": "published", "task_log_url": "test://task-log"
            }
            mailbox._publish_handoff_record = lambda task, comment_id, log: {
                "handoff_status": "published"
            }
            result = mailbox.run_once()

            self.assertEqual(result["status"], "finished")
            self.assertEqual(result["task_id"], original.task_id)
            self.assertEqual(len(worker.queue.list_tasks()), 1)
            self.assertEqual((root / "src/generated.py").read_text(), "VALUE = 7\\n")
            self.assertEqual(len(replies), 1)



class MailboxPublicationRetryTests(unittest.TestCase):
    def test_terminal_task_stays_active_when_full_log_publication_fails(self):
        from types import SimpleNamespace

        task = SimpleNamespace(
            task_id="task-1",
            kind="run_tests",
            status="completed",
            attempts=1,
            last_error=None,
            result={"passed": 3},
        )
        mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        mailbox.worker = SimpleNamespace(queue=SimpleNamespace(get=lambda task_id: task))
        mailbox.state = {"handled": [], "active": {"123": "task-1"}}
        mailbox._publish_task_log = lambda *_: {
            "task_log_status": "failed",
            "task_log_error": "temporary API failure",
        }
        handoff_calls = []
        mailbox._publish_handoff_record = lambda *args: handoff_calls.append(args) or {"handoff_status": "published"}
        mailbox._save_state = lambda: None
        replies = []
        mailbox._reply = replies.append

        finished = mailbox._finish_if_terminal("123", "task-1")

        self.assertFalse(finished)
        self.assertEqual(mailbox.state["handled"], [])
        self.assertEqual(mailbox.state["active"], {"123": "task-1"})
        self.assertEqual(handoff_calls, [])
        self.assertEqual(replies, [])


    def test_public_result_only_contains_allowlisted_scalars_and_statuses(self):
        from types import SimpleNamespace

        task = SimpleNamespace(
            task_id="task-1",
            kind="git_diff",
            status="completed",
            attempts=1,
            last_error="PRIVATE_EXCEPTION /private/local/path",
            result={
                "passed": True,
                "returncode": 0,
                "nested": {"output": "PRIVATE_OUTPUT", "token": "PRIVATE_TOKEN"},
                "local_path": "/private/local/path",
            },
        )
        mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        mailbox.worker = SimpleNamespace(queue=SimpleNamespace(get=lambda task_id: task))
        mailbox.state = {"handled": [], "active": {"123": "task-1"}}
        mailbox._publish_task_log = lambda *_: {
            "task_log_status": "published",
            "task_log_path": "/private/local/path/log.md",
            "task_log_error": "PRIVATE_LOG_ERROR",
        }
        mailbox._publish_handoff_record = lambda *_: {
            "handoff_status": "published",
            "local_path": "/private/local/path",
        }
        mailbox._save_state = lambda: None
        replies = []
        mailbox._reply = replies.append

        self.assertTrue(mailbox._finish_if_terminal("123", task.task_id))
        reply = replies[0]
        self.assertTrue(reply.startswith("EMBERLANE_RESULT\\n{"))
        self.assertFalse(reply.startswith("EMBERLANE_RESULT\\\\n{"))
        for private_value in (
            "PRIVATE_EXCEPTION", "PRIVATE_OUTPUT", "PRIVATE_TOKEN",
            "/private/local/path", "PRIVATE_LOG_ERROR",
        ):
            self.assertNotIn(private_value, reply)
        self.assertIn('"passed": true', reply)
        self.assertIn('"returncode": 0', reply)
        self.assertIn('"error_present": true', reply)
        self.assertIn('"task_log_status": "published"', reply)
        self.assertIn('"handoff_status": "published"', reply)

    def test_queue_prune_counts_are_public_but_archive_path_is_not(self):
        from types import SimpleNamespace

        task = SimpleNamespace(
            task_id="queue-prune-task",
            kind="queue_prune",
            status="completed",
            attempts=1,
            last_error=None,
            result={
                "pruned_count": 7,
                "kept_terminal_count": 50,
                "preserved_active_count": 12,
                "backup_file": "/private/local/path/queue.json.pre-prune-123.bak",
            },
        )
        mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        mailbox.worker = SimpleNamespace(queue=SimpleNamespace(get=lambda task_id: task))
        mailbox.state = {"handled": [], "active": {"456": task.task_id}}
        mailbox._publish_task_log = lambda *_: {"task_log_status": "published"}
        mailbox._publish_handoff_record = lambda *_: {"handoff_status": "published"}
        mailbox._save_state = lambda: None
        replies = []
        mailbox._reply = replies.append

        self.assertTrue(mailbox._finish_if_terminal("456", task.task_id))
        reply = replies[0]
        self.assertIn('"pruned_count": 7', reply)
        self.assertIn('"kept_terminal_count": 50', reply)
        self.assertIn('"preserved_active_count": 12', reply)
        self.assertNotIn('"backup_file"', reply)
        self.assertNotIn("/private/local/path", reply)

class MailboxRejectionTests(unittest.TestCase):
    def test_invalid_task_kind_reply_uses_real_newline(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = LocalWorker(Path(temp))
            mailbox = GitHubIssueMailbox(worker, "owner/repo", 6, "authorized")
            mailbox._comments = lambda: [{
                "id": 123,
                "user": {"login": "authorized"},
                "body": 'EMBERLANE_TASK_JSON\n' + json.dumps({
                    "kind": "unsupported_kind",
                    "payload": {},
                }),
            }]
            replies = []
            mailbox._reply = replies.append

            result = mailbox.run_once()


            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["error_code"], "task_validation_failed")
            self.assertEqual(replies[0], "EMBERLANE_RESULT 123\nREJECTED: task_validation_failed")
            self.assertNotIn("unsupported_kind", replies[0])

    def test_invalid_json_payload_is_not_echoed_to_public_comment(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = LocalWorker(Path(temp))
            mailbox = GitHubIssueMailbox(worker, "owner/repo", 6, "authorized")
            mailbox._comments = lambda: [{
                "id": 124,
                "user": {"login": "authorized"},
                "body": "EMBERLANE_TASK_JSON\n{SECRET_PAYLOAD_TOKEN: private}",
            }]
            replies = []
            mailbox._reply = replies.append

            result = mailbox.run_once()

            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["error_code"], "invalid_task_envelope")
            self.assertEqual(replies[0], "EMBERLANE_RESULT 124\nREJECTED: invalid_task_envelope")
            self.assertNotIn("SECRET_PAYLOAD_TOKEN", replies[0])
            self.assertNotIn("private", replies[0])

    def test_worker_validation_exception_message_is_not_published(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = LocalWorker(Path(temp))
            def fail_submit(*args, **kwargs):
                raise ValueError("PRIVATE_TOKEN=/secret/path")
            worker.submit = fail_submit
            mailbox = GitHubIssueMailbox(worker, "owner/repo", 6, "authorized")
            mailbox._comments = lambda: [{
                "id": 125,
                "user": {"login": "authorized"},
                "body": "EMBERLANE_TASK_JSON\n" + json.dumps({
                    "kind": "write_file",
                    "payload": {"path": "safe.txt", "content": "safe"},
                }),
            }]
            replies = []
            mailbox._reply = replies.append

            result = mailbox.run_once()

            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["error_code"], "task_validation_failed")
            self.assertEqual(result["error_type"], "ValueError")
            self.assertNotIn("PRIVATE_TOKEN", replies[0])
            self.assertNotIn("/secret/path", replies[0])


    def test_enqueue_only_mode_leaves_execution_to_supervisor(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = LocalWorker(Path(temp))
            mailbox = GitHubIssueMailbox(worker, "owner/repo", 6, "authorized")
            mailbox._comments = lambda: [{
                "id": 126,
                "user": {"login": "authorized"},
                "body": 'EMBERLANE_TASK_JSON\n' + json.dumps({
                    "kind": "write_file",
                    "payload": {"path": "queued.txt", "content": "queued"},
                }),
            }]
            replies = []
            mailbox._reply = replies.append
            worker.run_one = lambda: (_ for _ in ()).throw(AssertionError("mailbox must not execute tasks"))

            result = mailbox.run_once(execute_tasks=False)

            self.assertEqual(result["status"], "pending")
            task = worker.queue.get(result["task_id"])
            self.assertEqual(task.status, "pending")
            self.assertEqual(task.attempts, 0)
            self.assertFalse((Path(temp) / "queued.txt").exists())
            self.assertEqual(replies, [])



if __name__ == "__main__":
    unittest.main()
