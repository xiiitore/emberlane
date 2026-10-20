import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emberlane.worker import LocalWorker
from emberlane.workspace import WorkspaceError


class LocalWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "tests").mkdir()
        self.worker = LocalWorker(self.root)

    def test_write_read_and_result_persists(self):
        task = self.worker.submit("write_file", {
            "path": "src/example.py", "content": "VALUE = 42\n"
        })
        result = self.worker.run_one()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["bytes_written"], len("VALUE = 42\n".encode()))
        restored = LocalWorker(self.root).queue.get(task.task_id)
        self.assertEqual(restored.result, result.result)

        read = self.worker.submit("read_file", {"path": "src/example.py"})
        result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["content"], "VALUE = 42\n")

    def test_blocks_git_metadata_before_enqueue(self):
        with self.assertRaisesRegex(WorkspaceError, "protected paths"):
            self.worker.submit("write_file", {
                "path": ".git/config", "content": "overwrite"
            })
        self.assertEqual(self.worker.queue.list_tasks(), [])

    def test_unknown_task_kind_rejected_before_enqueue(self):
        with self.assertRaises(ValueError):
            self.worker.submit("run_shell", {"command": "id"})

    def test_run_tests_uses_fixed_command(self):
        (self.root / "tests" / "test_ok.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n"
            " def test_ok(self): self.assertEqual(1 + 1, 2)\n"
        )
        task = self.worker.submit("run_tests", {})
        result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.result["passed"])
        self.assertEqual(result.result["returncode"], 0)

    def test_git_status_uses_only_fixed_read_only_commands(self):
        self.worker.submit("git_status", {})
        with patch(
            "emberlane.worker.platform.platform",
            return_value="test-platform",
        ), patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(
                    ["git", "status", "--short", "--branch"], 0, "## test\n"
                ),
                subprocess.CompletedProcess(
                    ["git", "log", "-1", "--oneline"], 0, "abc123 test commit\n"
                ),
            ],
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["status"]["returncode"], 0)
        self.assertIn("## test", result.result["status"]["output"])
        self.assertEqual(result.result["head"]["returncode"], 0)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))
        self.assertEqual(run.call_args_list[0].args[0], ["git", "status", "--short", "--branch"])
        self.assertEqual(run.call_args_list[1].args[0], ["git", "log", "-1", "--oneline"])

    def test_git_sync_refuses_dirty_worktree_before_fetch(self):
        self.worker.submit("git_sync", {"expected_branch": "main"})
        with patch(
            "emberlane.worker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["git", "status", "--porcelain"], 0, " M tracked.py\n"
            ),
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.result["synced"])
        self.assertEqual(result.result["stage"], "preflight_dirty")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["git", "status", "--porcelain"])
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_git_sync_requires_expected_branch_to_match(self):
        self.worker.submit("git_sync", {"expected_branch": "main"})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, ""),
                subprocess.CompletedProcess(["git", "branch", "--show-current"], 0, "feature\n"),
            ],
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.result["synced"])
        self.assertEqual(result.result["stage"], "branch_mismatch")
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))

    def test_git_sync_uses_fixed_fetch_and_fast_forward_commands(self):
        self.worker.submit("git_sync", {"expected_branch": "feature"})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, ""),
                subprocess.CompletedProcess(["git", "branch", "--show-current"], 0, "feature\n"),
                subprocess.CompletedProcess(["git", "fetch", "origin", "feature"], 0, "fetched\n"),
                subprocess.CompletedProcess(["git", "merge", "--ff-only", "FETCH_HEAD"], 0, "Already up to date.\n"),
                subprocess.CompletedProcess(["git", "status", "--short", "--branch"], 0, "## feature\n"),
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, ""),
                subprocess.CompletedProcess(["git", "log", "-1", "--oneline"], 0, "abc123 latest\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "HEAD"], 0, "abc123\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "FETCH_HEAD"], 0, "abc123\n"),
            ],
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.result["synced"])
        self.assertEqual(result.result["stage"], "complete")
        self.assertEqual(run.call_count, 9)
        self.assertEqual(run.call_args_list[2].args[0], ["git", "fetch", "origin", "feature"])
        self.assertEqual(run.call_args_list[3].args[0], ["git", "merge", "--ff-only", "FETCH_HEAD"])
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))

    def test_git_sync_rejects_postflight_head_mismatch(self):
        self.worker.submit("git_sync", {"expected_branch": "feature"})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, ""),
                subprocess.CompletedProcess(["git", "branch", "--show-current"], 0, "feature\n"),
                subprocess.CompletedProcess(["git", "fetch", "origin", "feature"], 0, "fetched\n"),
                subprocess.CompletedProcess(["git", "merge", "--ff-only", "FETCH_HEAD"], 0, "Already up to date.\n"),
                subprocess.CompletedProcess(["git", "status", "--short", "--branch"], 0, "## feature\n"),
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, ""),
                subprocess.CompletedProcess(["git", "log", "-1", "--oneline"], 0, "abc123 latest\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "HEAD"], 0, "abc123\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "FETCH_HEAD"], 0, "def456\n"),
            ],
        ):
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.result["synced"])
        self.assertEqual(result.result["stage"], "postflight_head_mismatch")

    def test_git_sync_rejects_postflight_dirty_worktree(self):
        self.worker.submit("git_sync", {"expected_branch": "feature"})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, ""),
                subprocess.CompletedProcess(["git", "branch", "--show-current"], 0, "feature\n"),
                subprocess.CompletedProcess(["git", "fetch", "origin", "feature"], 0, "fetched\n"),
                subprocess.CompletedProcess(["git", "merge", "--ff-only", "FETCH_HEAD"], 0, "Already up to date.\n"),
                subprocess.CompletedProcess(["git", "status", "--short", "--branch"], 0, "## feature\n"),
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, " M worker.py\n"),
                subprocess.CompletedProcess(["git", "log", "-1", "--oneline"], 0, "abc123 latest\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "HEAD"], 0, "abc123\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "FETCH_HEAD"], 0, "abc123\n"),
            ],
        ):
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.result["synced"])
        self.assertEqual(result.result["stage"], "postflight_dirty")

    def test_git_sync_refuses_matching_worktree_mode_for_staged_or_untracked_changes(self):
        self.worker.submit("git_sync", {"expected_branch": "feature", "allow_matching_worktree": True})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, "?? extra.py\n"),
                subprocess.CompletedProcess(["git", "branch", "--show-current"], 0, "feature\n"),
                subprocess.CompletedProcess(["git", "fetch", "origin", "feature"], 0, "fetched\n"),
                subprocess.CompletedProcess(["git", "diff", "--cached", "--quiet"], 0, ""),
                subprocess.CompletedProcess(["git", "ls-files", "--others", "--exclude-standard"], 0, "extra.py\n"),
                subprocess.CompletedProcess(["git", "diff", "--name-only"], 0, ""),
            ],
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.result["synced"])
        self.assertEqual(result.result["stage"], "matching_worktree_preflight")
        self.assertEqual(run.call_count, 6)
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))

    def test_git_sync_matching_worktree_stashes_verified_duplicate_then_fast_forwards(self):
        self.worker.submit("git_sync", {"expected_branch": "feature", "allow_matching_worktree": True})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, " M emberlane/worker.py\n"),
                subprocess.CompletedProcess(["git", "branch", "--show-current"], 0, "feature\n"),
                subprocess.CompletedProcess(["git", "fetch", "origin", "feature"], 0, "fetched\n"),
                subprocess.CompletedProcess(["git", "diff", "--cached", "--quiet"], 0, ""),
                subprocess.CompletedProcess(["git", "ls-files", "--others", "--exclude-standard"], 0, ""),
                subprocess.CompletedProcess(["git", "diff", "--name-only"], 0, "emberlane/worker.py\n"),
                subprocess.CompletedProcess(["git", "diff", "--quiet", "FETCH_HEAD", "--", "emberlane/worker.py"], 0, ""),
                subprocess.CompletedProcess(["git", "stash", "push", "-m", "emberlane-bootstrap-sync"], 0, "Saved working directory and index state\n"),
                subprocess.CompletedProcess(["git", "merge", "--ff-only", "FETCH_HEAD"], 0, "Updating abc123..def456\n"),
                subprocess.CompletedProcess(["git", "status", "--short", "--branch"], 0, "## feature\n"),
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, ""),
                subprocess.CompletedProcess(["git", "log", "-1", "--oneline"], 0, "def456 latest\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "HEAD"], 0, "def456\n"),
                subprocess.CompletedProcess(["git", "rev-parse", "FETCH_HEAD"], 0, "def456\n"),
            ],
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.result["synced"])
        self.assertTrue(result.result["bootstrap_matching_worktree"])
        self.assertEqual(result.result["stash"]["command"], ["git", "stash", "push", "-m", "emberlane-bootstrap-sync"])
        self.assertEqual(result.result["sync"]["command"], ["git", "merge", "--ff-only", "FETCH_HEAD"])
        self.assertEqual(run.call_count, 14)
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))

    def test_git_sync_matching_worktree_rejects_content_not_equal_to_target(self):
        self.worker.submit("git_sync", {"expected_branch": "feature", "allow_matching_worktree": True})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, " M emberlane/worker.py\n"),
                subprocess.CompletedProcess(["git", "branch", "--show-current"], 0, "feature\n"),
                subprocess.CompletedProcess(["git", "fetch", "origin", "feature"], 0, "fetched\n"),
                subprocess.CompletedProcess(["git", "diff", "--cached", "--quiet"], 0, ""),
                subprocess.CompletedProcess(["git", "ls-files", "--others", "--exclude-standard"], 0, ""),
                subprocess.CompletedProcess(["git", "diff", "--name-only"], 0, "emberlane/worker.py\n"),
                subprocess.CompletedProcess(["git", "diff", "--quiet", "FETCH_HEAD", "--", "emberlane/worker.py"], 1, ""),
            ],
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertFalse(result.result["synced"])
        self.assertEqual(result.result["stage"], "matching_worktree_mismatch")
        self.assertEqual(run.call_count, 7)

    def test_git_sync_rejects_invalid_expected_branch_before_enqueue(self):
        with self.assertRaisesRegex(ValueError, "expected_branch"):
            self.worker.submit("git_sync", {"expected_branch": "-c"})
        self.assertEqual(self.worker.queue.list_tasks(), [])

    def test_diagnostics_returns_runtime_and_git_information(self):
        self.worker.submit("diagnostics", {})
        with patch(
            "emberlane.worker.platform.platform",
            return_value="test-platform",
        ), patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(
                    ["git", "status", "--short", "--branch"], 0, "## test\n"
                ),
                subprocess.CompletedProcess(
                    ["git", "log", "-1", "--oneline"], 0, "abc123 test commit\n"
                ),
            ],
        ):
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["root"], str(self.root))
        self.assertTrue(result.result["python_version"])
        self.assertTrue(result.result["platform"])
        self.assertEqual(result.result["git_status"]["returncode"], 0)
        self.assertEqual(result.result["latest_commit"]["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
