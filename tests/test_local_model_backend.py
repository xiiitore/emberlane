import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from emberlane.local_model_backend import run_local_model_edit, run_local_model_proposal
from emberlane.workspace import Workspace
from emberlane.worker import LocalWorker


class FakeProcess:
    output_bytes = json.dumps({
        "files": [{"path": "src/allowed.py", "content": "VALUE = 2\n"}],
        "summary": "Changed the value",
    }).encode()

    def __init__(self, command, *, cwd, stdout, **kwargs):
        self.command = command
        self.cwd = Path(cwd)
        self.kwargs = {**kwargs, "cwd": cwd}
        self.returncode = 0
        if stdout == subprocess.PIPE:
            read_fd, write_fd = os.pipe()
            self.stdout = os.fdopen(read_fd, "rb", buffering=0)
            os.write(write_fd, self.output_bytes)
            os.close(write_fd)
        else:
            self.stdout = stdout

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class LocalModelProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "src" / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.model = Path(self.temp.name) / "model.gguf"
        self.model.write_bytes(b"test model placeholder")
        self.workspace = Workspace(self.root)
        self.payload = {"goal": "Change the value", "allowed_paths": ["src/allowed.py"]}

    def run_with_fake(self, process=FakeProcess, payload=None):
        with patch.dict(os.environ, {
            "EMBERLANE_MODEL_PATH": str(self.model),
            "EMBERLANE_LLAMA_CLI": "llama-cli",
            "API_SECRET": "must-not-be-forwarded",
            "LD_LIBRARY_PATH": "/test/lib",
        }, clear=False), patch(
            "emberlane.local_model_backend.subprocess.Popen", process
        ):
            return run_local_model_proposal(
                self.root, payload or self.payload, workspace=self.workspace
            )

    def test_proposes_patch_without_modifying_source(self):
        original = (self.root / "src" / "allowed.py").read_text(encoding="utf-8")
        result = self.run_with_fake()
        self.assertEqual(result["status"], "proposal")
        self.assertEqual(result["proposal"]["changed_paths"], ["src/allowed.py"])
        self.assertIn("VALUE = 2", result["proposal"]["patch"])
        self.assertFalse(result["proposal"]["applied"])
        self.assertEqual(
            result["proposal"]["base_sha256"]["src/allowed.py"],
            hashlib.sha256(original.encode("utf-8")).hexdigest(),
        )
        self.assertEqual((self.root / "src" / "allowed.py").read_text(encoding="utf-8"), original)

    def test_fixed_cli_and_filtered_environment(self):
        processes = []

        def fake(*args, **kwargs):
            process = FakeProcess(*args, **kwargs)
            processes.append(process)
            return process

        result = self.run_with_fake(fake)
        self.assertEqual(result["status"], "proposal")
        process = processes[0]
        self.assertEqual(process.command[0], "llama-cli")
        self.assertIn("-m", process.command)
        self.assertIn(str(self.model), process.command)
        self.assertFalse(process.kwargs["shell"])
        self.assertNotEqual(process.kwargs["cwd"], self.root)
        self.assertNotIn("API_SECRET", process.kwargs["env"])
        self.assertEqual(process.kwargs["env"].get("LD_LIBRARY_PATH"), "/test/lib")

    def test_local_model_edit_accepts_strict_context_option(self):
        (self.root / "src" / "allowed.py").write_text(
            "# " + ("x" * 9000) + "\n", encoding="utf-8"
        )
        with patch("emberlane.local_model_backend.subprocess.Popen") as popen:
            result = run_local_model_edit(
                self.root,
                {**self.payload, "context_size": 4096, "auto_context_size": False},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "input_limit")
        popen.assert_not_called()
    def test_context_budget_grows_automatically_within_termux_limit(self):
        # The default budget is 2 bytes per context token. A source file larger
        # than 8192 bytes should select a larger bounded context, not fail before
        # llama-cli is launched.
        (self.root / "src" / "allowed.py").write_text(
            "# " + ("x" * 9000) + "\n", encoding="utf-8"
        )
        processes = []

        def fake(command, **kwargs):
            process = FakeProcess(command, **kwargs)
            processes.append(process)
            return process

        result = self.run_with_fake(fake, {**self.payload, "context_size": 4096})
        self.assertEqual(result["status"], "proposal")
        self.assertEqual(result["proposal"]["context_size_used"], 8192)
        self.assertEqual(result["proposal"]["context_bytes"], 9003)
        self.assertEqual(processes[0].command[processes[0].command.index("-c") + 1], "8192")

    def test_context_budget_can_be_kept_strict_explicitly(self):
        (self.root / "src" / "allowed.py").write_text(
            "# " + ("x" * 9000) + "\n", encoding="utf-8"
        )
        processes = []

        def fake(command, **kwargs):
            processes.append(FakeProcess(command, **kwargs))
            return processes[-1]

        result = self.run_with_fake(
            fake, {**self.payload, "context_size": 4096, "auto_context_size": False}
        )
        self.assertEqual(result["status"], "input_limit")
        self.assertEqual(result["context_size_used"], 4096)
        self.assertEqual(processes, [])
    def test_missing_model_configuration_does_not_launch_process(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "emberlane.local_model_backend.subprocess.Popen"
        ) as popen:
            result = run_local_model_proposal(self.root, self.payload, workspace=self.workspace)
        self.assertEqual(result["status"], "model_not_configured")
        popen.assert_not_called()

    def test_missing_model_file_is_reported(self):
        with patch.dict(os.environ, {"EMBERLANE_MODEL_PATH": str(self.root / "missing.gguf")}), patch(
            "emberlane.local_model_backend.subprocess.Popen"
        ) as popen:
            result = run_local_model_proposal(self.root, self.payload, workspace=self.workspace)
        self.assertEqual(result["status"], "model_not_found")
        popen.assert_not_called()

    def test_rejects_unsafe_path_before_model_launch(self):
        payload = {"goal": "change", "allowed_paths": ["../outside.py"]}
        with patch("emberlane.local_model_backend.subprocess.Popen") as popen:
            with self.assertRaises(ValueError):
                self.run_with_fake(payload=payload)
        popen.assert_not_called()

    def test_rejects_credential_like_source_without_launching_model(self):
        (self.root / "src" / "allowed.py").write_text('token = "ghp_abcdefghijklmnopqrstuvwxyz123456"\n')
        with patch("emberlane.local_model_backend.subprocess.Popen") as popen:
            result = self.run_with_fake()
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "credential_like_or_binary_context")
        popen.assert_not_called()

    def test_rejects_model_output_outside_allowlist(self):
        class OutsidePathProcess(FakeProcess):
            output_bytes = json.dumps({
                "files": [{"path": "src/other.py", "content": "VALUE = 3\n"}],
                "summary": "changed another file",
            }).encode()

        result = self.run_with_fake(OutsidePathProcess)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "changed_path_outside_allowlist")

    def test_supports_new_allowlisted_file_and_marks_addition(self):
        payload = {"goal": "Add a file", "allowed_paths": ["src/new.py"]}

        class NewFileProcess(FakeProcess):
            output_bytes = json.dumps({
                "files": [{"path": "src/new.py", "content": "VALUE = 3\n"}],
                "summary": "added file",
            }).encode()

        result = self.run_with_fake(NewFileProcess, payload)
        self.assertEqual(result["status"], "proposal")
        self.assertIn("--- /dev/null", result["proposal"]["patch"])
        self.assertIn("+++ b/src/new.py", result["proposal"]["patch"])

    def test_enforces_streamed_output_limit(self):
        class BurstProcess(FakeProcess):
            output_bytes = b"x" * 128

        result = self.run_with_fake(
            BurstProcess, {**self.payload, "max_output_bytes": 10}
        )
        self.assertEqual(result["status"], "output_limit")

    def test_persistent_pause_prevents_model_launch(self):
        marker = self.root / ".emberlane" / "PAUSED"
        marker.parent.mkdir()
        marker.write_text("paused", encoding="utf-8")
        with patch("emberlane.local_model_backend.subprocess.Popen") as popen:
            result = self.run_with_fake()
        self.assertEqual(result["status"], "paused")
        popen.assert_not_called()

    def test_pause_created_during_inference_discards_proposal(self):
        class PauseDuringProcess(FakeProcess):
            def __init__(inner_self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                marker = self.root / ".emberlane" / "PAUSED"
                marker.parent.mkdir(exist_ok=True)
                marker.write_text("paused", encoding="utf-8")

        result = self.run_with_fake(PauseDuringProcess)
        self.assertEqual(result["status"], "paused")
        self.assertIsNone(result["proposal"])

    def _initialize_git(self):
        subprocess.run(["git", "init", "--quiet"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "--force", "-A"], cwd=self.root, check=True)
        subprocess.run([
            "git", "-c", "user.name=Test", "-c", "user.email=test@localhost",
            "commit", "--quiet", "--allow-empty", "-m", "test baseline",
        ], cwd=self.root, check=True)

    def _proposal_for_value(self, value, *, base_hash=None):
        original = (self.root / "src" / "allowed.py").read_bytes()
        patch = (
            "--- a/src/allowed.py\n"
            "+++ b/src/allowed.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            f"+VALUE = {value}\n"
        )
        return {
            "status": "proposal",
            "proposal": {
                "changed_paths": ["src/allowed.py"],
                "patch": patch,
                "patch_bytes": len(patch.encode("utf-8")),
                "base_sha256": {
                    "src/allowed.py": base_hash or hashlib.sha256(original).hexdigest()
                },
                "output": "changed value",
                "output_bytes": 10,
                "applied": False,
            },
        }

    def test_edit_applies_only_after_targeted_tests_pass(self):
        self._initialize_git()
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_feature.py").write_text(
            "import unittest\nfrom src.allowed import VALUE\n"
            "class FeatureTests(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(VALUE, 2)\n",
            encoding="utf-8",
        )
        proposal = self._proposal_for_value(2)
        with patch("emberlane.local_model_backend.run_local_model_proposal", return_value=proposal):
            result = run_local_model_edit(
                self.root,
                {**self.payload, "test_file": "test_feature.py"},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "applied_and_verified")
        self.assertTrue(result["applied"])
        self.assertEqual((self.root / "src" / "allowed.py").read_text(), "VALUE = 2\n")

    def test_failed_tests_leave_working_tree_unchanged(self):
        self._initialize_git()
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_feature.py").write_text(
            "import unittest\nfrom src.allowed import VALUE\n"
            "class FeatureTests(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(VALUE, 999)\n",
            encoding="utf-8",
        )
        proposal = self._proposal_for_value(2)
        with patch("emberlane.local_model_backend.run_local_model_proposal", return_value=proposal):
            result = run_local_model_edit(
                self.root,
                {**self.payload, "test_file": "test_feature.py"},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "tests_failed")
        self.assertFalse(result["applied"])
        self.assertEqual((self.root / "src" / "allowed.py").read_text(), "VALUE = 1\n")

    def test_edit_refuses_source_changed_since_proposal(self):
        self._initialize_git()
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_feature.py").write_text(
            "import unittest\nclass FeatureTests(unittest.TestCase):\n"
            " def test_ok(self): self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )
        proposal = self._proposal_for_value(2, base_hash="0" * 64)
        with patch("emberlane.local_model_backend.run_local_model_proposal", return_value=proposal):
            result = run_local_model_edit(
                self.root,
                {**self.payload, "test_file": "test_feature.py"},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "conflict")
        self.assertFalse(result["applied"])
        self.assertEqual((self.root / "src" / "allowed.py").read_text(), "VALUE = 1\n")

    def test_invalid_model_json_is_rejected(self):
        class InvalidJsonProcess(FakeProcess):
            output_bytes = b"not json"

        result = self.run_with_fake(InvalidJsonProcess)
        self.assertEqual(result["status"], "invalid_model_output")

    def test_boolean_numeric_limits_are_rejected_before_queueing(self):
        worker = LocalWorker(self.root)
        with self.assertRaisesRegex(ValueError, "max_tokens must be an integer"):
            worker.submit("local_model_proposal", {
                **self.payload, "max_tokens": True,
            })
        with self.assertRaisesRegex(ValueError, "test_timeout_seconds must be an integer"):
            worker.submit("local_model_edit", {
                **self.payload, "test_timeout_seconds": True,
            })
        with self.assertRaisesRegex(ValueError, "auto_context_size must be a boolean"):
            worker.submit("local_model_proposal", {
                **self.payload, "auto_context_size": 1,
            })
        self.assertEqual(worker.queue.list_tasks(), [])


if __name__ == "__main__":
    unittest.main()
