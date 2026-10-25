import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emberlane import session_state


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".emberlane").mkdir()
        queue = [{
            "task_id": "task-safe-id",
            "kind": "run_tests",
            "payload": {"private_payload": "DO_NOT_PUBLISH"},
            "status": "completed",
            "attempts": 1,
            "last_error": None,
            "created_at": 100,
            "updated_at": 200,
            "idempotency_key": None,
            "result": {"returncode": 0, "passed": 7, "output": "DO_NOT_PUBLISH"},
        }]
        (self.root / ".emberlane" / "queue.json").write_text(json.dumps(queue), encoding="utf-8")
        (self.root / ".emberlane" / "mailbox-state.json").write_text(
            json.dumps({"handled": ["1", "2"], "active": {"3": {}}, "cursor": 99}),
            encoding="utf-8",
        )
        def fake_git(args, **kwargs):
            output = "feat/local-coding-worker\n" if args[1] == "branch" else "abcdef123456\n"
            return subprocess.CompletedProcess(args, 0, output, "")

        self.git = patch("emberlane.session_state.subprocess.run", side_effect=fake_git)
        self.git.start()
        self.addCleanup(self.git.stop)

    def test_render_state_is_deterministic_and_excludes_payloads(self):
        first = session_state.render_state(self.root)
        second = session_state.render_state(self.root)
        self.assertEqual(first, second)
        self.assertIn("completed=1", first)
        self.assertIn("task-safe-id", first)
        self.assertIn("passed=7", first)
        self.assertNotIn("DO_NOT_PUBLISH", first)
        self.assertNotIn("private_payload", first)

    def test_publish_only_when_content_changes(self):
        with patch(
            "emberlane.session_state.upload_task_log",
            return_value={
                "status": "published",
                "readback_verified": True,
                "path": "/worker-logs/SESSION-CONTINUITY.md",
            },
        ) as upload:
            first = session_state.refresh_session_state(self.root)
            second = session_state.refresh_session_state(self.root)
        self.assertEqual(first["status"], "published")
        self.assertTrue(first["readback_verified"])
        self.assertEqual(second["status"], "unchanged")
        upload.assert_called_once()
        self.assertTrue((self.root / session_state.STATE_NAME).is_file())

    def test_failed_publish_is_not_marked_as_published(self):
        with patch(
            "emberlane.session_state.upload_task_log",
            side_effect=session_state.DropboxOutputError("safe error"),
        ):
            result = session_state.refresh_session_state(self.root)
        self.assertEqual(result["status"], "publish_failed")
        self.assertFalse((self.root / ".emberlane" / "session-state.sha256").exists())

    def test_local_only_mode_does_not_call_dropbox(self):
        with patch("emberlane.session_state.upload_task_log") as upload:
            result = session_state.refresh_session_state(self.root, publish=False)
        self.assertEqual(result["status"], "local_only")
        upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
