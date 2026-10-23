import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from emberlane.dropbox_output import DropboxOutputError
from emberlane.mailbox import GitHubIssueMailbox, MailboxError, _redact_sensitive_text


class TaskLogPublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        self.mailbox.worker = SimpleNamespace(root=self.root)

    @patch("emberlane.mailbox.upload_task_log")
    def test_publishes_sanitized_log_to_dropbox_and_keeps_local_copy(self, upload):
        token = "ghp_" + "A" * 35
        task = SimpleNamespace(
            task_id="task-123",
            kind="run_tests",
            status="completed",
            attempts=1,
            last_error="PRIVATE_EXCEPTION /private/path " + token,
            result={
                "output": "test_alpha ... ok\ntoken=" + token,
                "returncode": 1,
                "nested": {"output": "authorization=Bearer private-value"},
                "content": "private file text",
                "source_text": "local source\napi_key=super-secret-value\n" + "ghp_" + "B" * 35,
            },
        )
        upload.return_value = {
            "status": "published",
            "path": "/worker-logs/task-123.md",
            "sha256": "a" * 64,
            "bytes": 900,
            "readback_verified": True,
        }

        result = self.mailbox._publish_task_log(task, "comment-7")

        self.assertEqual(result["task_log_status"], "published")
        self.assertEqual(result["dropbox_status"], "published")
        self.assertTrue(result["dropbox_readback_verified"])
        upload.assert_called_once()
        self.assertEqual(upload.call_args.args[0], "task-123")
        content = upload.call_args.args[1]
        local_log = self.root / "worker-logs" / "task-123.md"
        self.assertTrue(local_log.is_file())
        self.assertEqual(local_log.read_text(encoding="utf-8"), content)
        self.assertIn("test_alpha ... ok", content)
        self.assertIn("[OMITTED_FILE_CONTENT]", content)
        self.assertIn("[SOURCE TEXT IN SECTION: result.source_text]", content)
        self.assertNotIn("private file text", content)
        self.assertNotIn("super-secret-value", content)
        self.assertNotIn("PRIVATE_EXCEPTION", content)
        self.assertNotIn("/private/path", content)
        self.assertNotIn(token, content)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", content)
        self.assertIn('"error_present": true', content)

    @patch("emberlane.mailbox.upload_task_log", side_effect=DropboxOutputError("private network error"))
    def test_dropbox_failure_keeps_local_log_and_reports_local_only(self, upload):
        task = SimpleNamespace(
            task_id="task-local",
            kind="diagnostics",
            status="failed",
            attempts=2,
            last_error="PRIVATE_EXCEPTION /private/path",
            result={"output": "diagnostic output"},
        )

        result = self.mailbox._publish_task_log(task, "comment-8")

        self.assertEqual(result["task_log_status"], "local_only")
        self.assertEqual(result["dropbox_status"], "failed")
        self.assertFalse(result["dropbox_readback_verified"])
        upload.assert_called_once()
        local_log = self.root / "worker-logs" / "task-local.md"
        self.assertIn("diagnostic output", local_log.read_text(encoding="utf-8"))
        self.assertNotIn("PRIVATE_EXCEPTION", local_log.read_text(encoding="utf-8"))

    @patch("emberlane.mailbox.upload_task_log")
    def test_rejects_oversized_log_before_writing_or_uploading(self, upload):
        task = SimpleNamespace(
            task_id="task-large",
            kind="run_tests",
            status="completed",
            attempts=1,
            last_error=None,
            result={"output": "x" * 1_100_000},
        )

        with self.assertRaisesRegex(MailboxError, "1 MB limit"):
            self.mailbox._publish_task_log(task, "comment-9")

        upload.assert_not_called()
        self.assertFalse((self.root / "worker-logs" / "task-large.md").exists())

    def test_shared_redactor_removes_tokens_authorization_and_secret_values(self):
        token = "ghp_" + "Z" * 35
        cleaned = _redact_sensitive_text(
            f"token={token} Authorization: Bearer abc123 api_key=xyz "
            "-----BEGIN PRIVATE KEY-----private-----END PRIVATE KEY-----"
        )
        self.assertNotIn(token, cleaned)
        self.assertNotIn("abc123", cleaned)
        self.assertNotIn("xyz", cleaned)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", cleaned)
        self.assertIn("[REDACTED_PRIVATE_KEY_BLOCK]", cleaned)

    def test_terminal_result_omits_sensitive_last_error_from_public_comment(self):
        token = "ghp_" + "C" * 35
        task = SimpleNamespace(
            task_id="task-456",
            kind="write_file",
            status="failed",
            attempts=1,
            last_error=f"request failed with {token}",
            result={},
        )
        mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        mailbox.worker = SimpleNamespace(queue=SimpleNamespace(get=lambda task_id: task))
        mailbox.state = {"handled": [], "active": {"comment-8": "task-456"}}
        replies = []
        mailbox._reply = replies.append
        mailbox._publish_task_log = lambda task, comment_id: {
            "task_log_status": "published",
            "dropbox_status": "published",
            "dropbox_readback_verified": True,
            "dropbox_sha256": "b" * 64,
        }
        mailbox._publish_handoff_record = lambda task, comment_id, log_result: {
            "handoff_status": "not_required"
        }
        mailbox._save_state = lambda: None

        self.assertTrue(mailbox._finish_if_terminal("comment-8", "task-456"))
        self.assertEqual(len(replies), 1)
        self.assertNotIn(token, replies[0])
        self.assertNotIn("[REDACTED_GITHUB_TOKEN]", replies[0])
        self.assertIn('"error_present": true', replies[0])
        self.assertIn('"dropbox_readback_verified": true', replies[0])
        self.assertNotIn("dropbox_path", replies[0])
        self.assertNotIn("task_log_path", replies[0])


if __name__ == "__main__":
    unittest.main()
