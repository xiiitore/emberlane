import base64
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from emberlane.mailbox import GitHubIssueMailbox, MailboxError


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
        self.assertIn("TRACEBACK_LINE", document)
        self.assertNotIn("private file text", document)
        self.assertIn("[OMITTED_FILE_CONTENT]", document)
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


if __name__ == "__main__":
    unittest.main()
