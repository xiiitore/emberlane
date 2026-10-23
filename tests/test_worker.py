import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emberlane.local_model import LocalModelError
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

    def test_read_file_content_requires_explicit_opt_in(self):
        target = self.root / "source.py"
        target.write_text("VALUE = 7\n")
        self.worker.submit("read_file", {"path": "source.py"})
        default_result = self.worker.run_one()
        self.assertIsNotNone(default_result)
        self.assertEqual(default_result.result["content"], "VALUE = 7\n")
        self.assertNotIn("source_text", default_result.result)

        self.worker.submit("read_file", {"path": "source.py", "include_content": True})
        preview_result = self.worker.run_one()
        self.assertTrue(preview_result.result["content_included"])
        self.assertEqual(preview_result.result["source_text"], "VALUE = 7\n")

    def test_read_file_rejects_non_boolean_content_opt_in(self):
        with self.assertRaisesRegex(ValueError, "include_content"):
            self.worker.submit("read_file", {"path": "source.py", "include_content": "yes"})
        self.assertEqual(self.worker.queue.list_tasks(), [])

    def test_read_file_preview_omits_large_source_explicitly(self):
        (self.root / "large.py").write_text("x" * 20_001)
        self.worker.submit("read_file", {"path": "large.py", "include_content": True})
        result = self.worker.run_one()
        self.assertFalse(result.result["content_included"])
        self.assertEqual(result.result["content_chars"], 20_001)
        self.assertIn("opt-in preview limit", result.result["content_omitted_reason"])
        self.assertNotIn("source_text", result.result)

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

    def test_run_tests_can_target_one_test_file(self):
        (self.root / "tests" / "test_targeted.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n"
            " def test_targeted(self): self.assertEqual(2 * 3, 6)\n"
        )
        self.worker.submit("run_tests", {"test_file": "test_targeted.py"})
        result = self.worker.run_one()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "completed")
        self.assertTrue(result.result["passed"])
        self.assertEqual(
            result.result["command"],
            "python -m unittest discover -s tests -p test_targeted.py -v",
        )
        self.assertIn("test_targeted", result.result["output"])

    def test_run_tests_rejects_unsafe_test_file_before_queueing(self):
        for value in ("../test_worker.py", "test_*.py", "other.py", "test_bad.py\n"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "test_file"):
                    self.worker.submit("run_tests", {"test_file": value})
        self.assertEqual(self.worker.queue.list_tasks(), [])

    def test_run_tests_reports_missing_target_as_failure(self):
        self.worker.submit("run_tests", {"test_file": "test_missing.py"})
        result = self.worker.run_one()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.result["passed"])
        self.assertEqual(result.result["returncode"], 2)
        self.assertEqual(result.result["error"], "test_file_not_found")

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
        self.assertEqual(result.status, "failed")
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
        self.assertEqual(result.status, "failed")
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
        self.assertEqual(result.status, "failed")
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
        self.assertEqual(result.status, "failed")
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
        self.assertEqual(result.status, "failed")
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
        self.assertEqual(result.status, "failed")
        self.assertFalse(result.result["synced"])
        self.assertEqual(result.result["stage"], "matching_worktree_mismatch")
        self.assertEqual(run.call_count, 7)

    def test_git_sync_rejects_invalid_expected_branch_before_enqueue(self):
        with self.assertRaisesRegex(ValueError, "expected_branch"):
            self.worker.submit("git_sync", {"expected_branch": "-c"})
        self.assertEqual(self.worker.queue.list_tasks(), [])

    def test_git_stash_inspect_uses_fixed_read_only_commands(self):
        self.worker.submit("git_stash_inspect", {})
        with patch(
            "emberlane.worker.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess(
                    ["git", "stash", "list", "--format=%gd %gs"], 0,
                    "stash@{0} On feature: recovery\\n"
                ),
                subprocess.CompletedProcess(
                    ["git", "stash", "show", "--stat", "--include-untracked", "stash@{0}"],
                    0, " worker.py | 3 +++\\n 1 file changed, 3 insertions(+)\\n"
                ),
            ],
        ) as run:
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["entries"][0]["ref"], "stash@{0}")
        self.assertIn("worker.py", result.result["entries"][0]["stat"]["output"])
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.kwargs["shell"] is False for call in run.call_args_list))
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["git", "stash", "list", "--format=%gd %gs"],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["git", "stash", "show", "--stat", "--include-untracked", "stash@{0}"],
        )

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


    def test_local_model_task_persists_successful_output(self):
        task = self.worker.submit("local_model", {"prompt": "say hello"})
        fake_result = {
            "ok": True,
            "output": "hello",
            "truncated": False,
            "returncode": 0,
            "elapsed_seconds": 0.01,
        }
        with patch("emberlane.worker.LocalModelConfig.from_env", return_value=object()), patch(
            "emberlane.worker.LocalModelRunner"
        ) as runner:
            runner.return_value.generate.return_value = fake_result
            result = self.worker.run_one()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result, fake_result)
        self.assertEqual(result.attempts, 1)

    def test_local_model_output_redacts_github_tokens_before_persistence(self):
        token = "ghp_" + ("A" * 30)
        self.worker.submit("local_model", {"prompt": "produce test output"})
        with patch("emberlane.worker.LocalModelConfig.from_env", return_value=object()), patch(
            "emberlane.worker.LocalModelRunner"
        ) as runner:
            runner.return_value.generate.return_value = {
                "ok": True, "output": f"example {token}", "truncated": False,
                "returncode": 0, "elapsed_seconds": 0.01,
            }
            result = self.worker.run_one()
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["output"], "example [REDACTED_GITHUB_TOKEN]")
        self.assertTrue(result.result["output_redacted"])
        self.assertNotIn(token, str(result.result))

    def test_local_model_configuration_error_is_terminal_not_retried(self):
        self.worker.submit("local_model", {"prompt": "say hello"})
        with patch(
            "emberlane.worker.LocalModelConfig.from_env",
            side_effect=LocalModelError("not_configured", "model path missing"),
        ):
            result = self.worker.run_one()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.result["error_code"], "not_configured")
        self.assertFalse(result.result["ok"])

    def test_local_model_payload_is_validated_before_enqueue(self):
        for payload in (
            {},
            {"prompt": "   "},
            {"prompt": "x" * 16001},
            {"prompt": "hello", "shell": "not-allowed"},
        ):
            with self.subTest(payload_keys=sorted(payload)):
                with self.assertRaises(ValueError):
                    self.worker.submit("local_model", payload)
        self.assertEqual(self.worker.queue.list_tasks(), [])


    def _initialize_git_repo(self):
        (self.root / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True, shell=False)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True, shell=False)
        subprocess.run(["git", "config", "user.name", "Emberlane Test"], cwd=self.root, check=True, shell=False)
        subprocess.run(["git", "add", "example.py"], cwd=self.root, check=True, shell=False)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=self.root, check=True, shell=False)

    def test_validate_patch_task_uses_disposable_worktree(self):
        self._initialize_git_repo()
        patch = (
            "diff --git a/example.py b/example.py\n"
            "--- a/example.py\n"
            "+++ b/example.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )
        task = self.worker.submit("validate_patch", {"patch": patch})
        result = self.worker.run_one()
        self.assertEqual(result.task_id, task.task_id)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result["status"], "validated")
        self.assertIsNone(result.result["passed"])
        self.assertFalse(result.result["tests_run"])
        self.assertFalse(result.result["original_worktree_modified"])
        self.assertEqual((self.root / "example.py").read_text(), "VALUE = 1\n")

    def test_validate_patch_rejects_dirty_checkout_as_terminal_failure(self):
        self._initialize_git_repo()
        (self.root / "example.py").write_text("LOCAL CHANGE\n", encoding="utf-8")
        patch = (
            "diff --git a/example.py b/example.py\n"
            "--- a/example.py\n"
            "+++ b/example.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )
        self.worker.submit("validate_patch", {"patch": patch})
        result = self.worker.run_one()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.attempts, 1)
        self.assertIn("worktree is dirty", result.result["error"])
        self.assertEqual((self.root / "example.py").read_text(), "LOCAL CHANGE\n")

    def test_validate_patch_payload_is_validated_before_enqueue(self):
        for payload in (
            {},
            {"patch": " "},
            {"patch": "x", "run_tests": "yes"},
            {"patch": "x", "test_timeout": True},
            {"patch": "x", "unexpected": 1},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.worker.submit("validate_patch", payload)
        self.assertEqual(self.worker.queue.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
