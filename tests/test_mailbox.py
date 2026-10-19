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

class MailboxIdempotencyTests(unittest.TestCase):
    def test_recovers_crash_after_queue_submit_without_duplicate_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            worker = LocalWorker(root)
            payload = {"path": "src/generated.py", "content": "VALUE = 7\\n"}
            original = worker.submit("write_file", payload, idempotency_key="comment-123")
            worker.run_one()
            self.assertEqual((root / "src/generated.py").read_text(), "VALUE = 7\\n")

            mailbox = GitHubIssueMailbox(worker, "owner/repo", 6, "authorized")
            mailbox._comments = lambda: [{
                "id": 123,
                "user": {"login": "authorized"},
                "body": 'EMBERLANE_TASK_JSON\\n' + json.dumps({
                    "kind": "write_file",
                    "payload": payload,
                }),
            }]
            replies = []
            mailbox._reply = replies.append
            result = mailbox.run_once()

            self.assertEqual(result["status"], "finished")
            self.assertEqual(result["task_id"], original.task_id)
            self.assertEqual(len(worker.queue.list_tasks()), 1)
            self.assertEqual((root / "src/generated.py").read_text(), "VALUE = 7\\n")
            self.assertEqual(len(replies), 1)


if __name__ == "__main__":
    unittest.main()
