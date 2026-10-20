import base64
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from emberlane.mailbox import GitHubIssueMailbox, MailboxError, _redact_sensitive_text


class TaskLogPublishingTests(unittest.TestCase):
    def setUp(self):
        self.mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        self.mailbox.repository = "owner/repo"

    @patch("emberlane.mailbox.subprocess.run")
    def test_publishes_full_output_redacts_secrets_and_omits_file_content(self, run):
        run.side_effect = [
            subprocess.CompletedProcess(["gh"], 1, "", "HTTP 404: Not Found"),
            subprocess.CompletedProcess(["gh"], 0, "{}", ""),
        ]
        output = "test_alpha ... ok\ntest_beta ... FAIL\n" + ("TRACEBACK_LINE\n" * 4000)
        task = SimpleNamespace(
            task_id="task-123", kind="run_tests", status="completed",
            attempts=1, last_error=None,
            result={
                "output": output, "returncode": 1,
                "nested": {"output": "token=ghp_" + "A" * 35},
                "content": "private file text",
                "source_text": "local source\napi_key=super-secret-value\n" + "ghp_" + "B" * 35,
            },
        )
        result = self.mailbox._publish_task_log(task, "comment-7")
        self.assertEqual(result, {
            "task_log_status": "published",
            "task_log_path": "worker-logs/task-123.md",
        })
        args = run.call_args_list[1].args[0]
        encoded = next(value[len("content="):] for value in args if value.startswith("content="))
        document = base64.b64decode(encoded).decode("utf-8")
        self.assertIn("test_alpha ... ok", document)
        self.assertIn("test_beta ... FAIL", document)
        self.assertIn("test_alpha ... ok\ntest_beta ... FAIL", document)
        self.assertIn("TRACEBACK_LINE", document)
        self.assertNotIn("private file text", document)
        self.assertIn("[OMITTED_FILE_CONTENT]", document)
        self.assertIn("local source", document)
        self.assertIn("[REDACTED]", document)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", document)
        self.assertIn("[SOURCE TEXT IN SECTION: result.source_text]", document)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", document)
        self.assertIn("worker-logs/task-123.md", args[4])
        self.assertTrue(any("feat/local-coding-worker" in value for value in args))

    @patch("emberlane.mailbox.subprocess.run")
    def test_existing_task_log_is_idempotent(self, run):
        previous = '# Emberlane task output\n```json\n{"task_id": "task-123"}\n```'
        api_content = base64.b64encode(previous.encode()).decode()
        run.return_value = subprocess.CompletedProcess(
            ["gh"], 0, json.dumps({"content": api_content}), ""
        )
        task = SimpleNamespace(
            task_id="task-123", kind="run_tests", status="completed",
            attempts=1, last_error=None, result={"output": "ok"},
        )
        result = self.mailbox._publish_task_log(task, "comment-7")
        self.assertEqual(result["task_log_status"], "already_present")
        run.assert_called_once()

    def test_rejects_oversized_log_instead_of_silently_truncating(self):
        task = SimpleNamespace(
            task_id="task-123", kind="run_tests", status="completed",
            attempts=1, last_error=None, result={"output": "x" * 1_100_000},
        )
        with self.assertRaisesRegex(MailboxError, "1 MB"):
            self.mailbox._publish_task_log(task, "comment-7")


    def test_shared_redactor_removes_tokens_authorization_and_secret_values(self):
        raw = (
            "ghp_" + "A" * 35
            + " Authorization: Bearer bearer-value"
            + " api_key=private-value password:secret-value"
        )
        cleaned = _redact_sensitive_text(raw)
        self.assertNotIn("ghp_" + "A" * 35, cleaned)
        self.assertNotIn("bearer-value", cleaned)
        self.assertNotIn("private-value", cleaned)
        self.assertNotIn("secret-value", cleaned)
        self.assertIn("[REDACTED_GITHUB_TOKEN]", cleaned)
        self.assertIn("Authorization: Bearer [REDACTED]", cleaned)
        self.assertIn("api_key=[REDACTED]", cleaned)
        self.assertIn("password:[REDACTED]", cleaned)


    def test_terminal_result_redacts_sensitive_last_error_before_comment(self):
        token = "ghp_" + "C" * 35
        task = SimpleNamespace(
            task_id="task-456", kind="write_file", status="failed",
            attempts=1, last_error=f"request failed with {token}", result={},
        )
        mailbox = GitHubIssueMailbox.__new__(GitHubIssueMailbox)
        mailbox.worker = SimpleNamespace(queue=SimpleNamespace(get=lambda task_id: task))
        mailbox.state = {"handled": [], "active": {"comment-8": "task-456"}}
        replies = []
        mailbox._reply = replies.append
        mailbox._publish_task_log = lambda task, comment_id: {
            "task_log_status": "published", "task_log_path": "worker-logs/task-456.md"
        }
        mailbox._publish_handoff_record = lambda task, comment_id, log_result: {
            "handoff_status": "published"
        }
        mailbox._save_state = lambda: None

        self.assertTrue(mailbox._finish_if_terminal("comment-8", "task-456"))
        self.assertEqual(len(replies), 1)
        self.assertNotIn(token, replies[0])
        self.assertIn("[REDACTED_GITHUB_TOKEN]", replies[0])

if __name__ == "__main__":
    unittest.main()
