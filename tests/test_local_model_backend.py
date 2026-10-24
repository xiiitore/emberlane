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
    stderr_bytes = b""

    @staticmethod
    def _pipe(payload):
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd, "rb", buffering=0)
        if payload:
            os.write(write_fd, payload)
        os.close(write_fd)
        return reader

    def __init__(self, command, *, cwd, stdout, stderr, **kwargs):
        self.command = command
        self.cwd = Path(cwd)
        self.kwargs = {**kwargs, "cwd": cwd, "stderr": stderr}
        self.returncode = 0
        self.stdout = self._pipe(self.output_bytes) if stdout == subprocess.PIPE else stdout
        self.stderr = self._pipe(self.stderr_bytes) if stderr == subprocess.PIPE else stderr

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

    def test_termux_prefix_library_path_is_inferred_when_unset(self):
        prefix = Path(self.temp.name) / "termux"
        (prefix / "lib").mkdir(parents=True)
        processes = []

        def fake(*args, **kwargs):
            process = FakeProcess(*args, **kwargs)
            processes.append(process)
            return process

        with patch.dict(os.environ, {
            "EMBERLANE_MODEL_PATH": str(self.model),
            "EMBERLANE_LLAMA_CLI": "llama-cli",
            "PREFIX": str(prefix),
            "LD_LIBRARY_PATH": "",
        }, clear=False), patch(
            "emberlane.local_model_backend.subprocess.Popen", fake
        ):
            result = run_local_model_proposal(
                self.root, self.payload, workspace=self.workspace
            )

        self.assertEqual(result["status"], "proposal")
        self.assertEqual(
            processes[0].kwargs["env"]["LD_LIBRARY_PATH"], str(prefix / "lib")
        )

    def test_model_loader_failure_preserves_stderr_diagnostic(self):
        class FailedProcess(FakeProcess):
            stderr_bytes = b"error while loading shared libraries: libllama.so\\n"

            def __init__(self, command, *, cwd, stdout, **kwargs):
                super().__init__(command, cwd=cwd, stdout=stdout, **kwargs)
                self.returncode = 1

        result = self.run_with_fake(FailedProcess)
        self.assertEqual(result["status"], "runtime_loader_failed")
        self.assertEqual(result["returncode"], 1)
        self.assertIn("libllama.so", result["output"])

    def test_missing_cli_is_distinguished_from_generic_backend_failure(self):
        def missing_cli(*args, **kwargs):
            raise FileNotFoundError("llama-cli")

        result = self.run_with_fake(missing_cli)
        self.assertEqual(result["status"], "model_cli_not_found")
        self.assertNotIn("llama-cli", result["output"])

    def test_unreadable_model_is_rejected_before_launch(self):
        self.model.chmod(0)
        try:
            with patch.dict(os.environ, {
                "EMBERLANE_MODEL_PATH": str(self.model),
                "EMBERLANE_LLAMA_CLI": "llama-cli",
            }, clear=False), patch(
                "emberlane.local_model_backend.subprocess.Popen"
            ) as popen:
                result = run_local_model_proposal(
                    self.root, self.payload, workspace=self.workspace
                )
            self.assertEqual(result["status"], "model_unreadable")
            popen.assert_not_called()
        finally:
            self.model.chmod(0o600)

    def test_stderr_capture_is_bounded(self):
        class BurstStderrProcess(FakeProcess):
            stderr_bytes = b"E" * 128

        with patch("emberlane.local_model_backend.MAX_STDERR_BYTES", 64):
            result = self.run_with_fake(BurstStderrProcess)
        self.assertEqual(result["status"], "stderr_limit")
        self.assertLessEqual(result["stderr_bytes"], 65)

    def test_empty_successful_model_output_has_distinct_status(self):
        class EmptyOutputProcess(FakeProcess):
            output_bytes = b""

        result = self.run_with_fake(EmptyOutputProcess)
        self.assertEqual(result["status"], "empty_model_output")
        self.assertEqual(result["returncode"], 0)

    def test_model_load_failure_is_distinguished_from_runtime_loader_failure(self):
        class FailedModelLoadProcess(FakeProcess):
            stderr_bytes = b"Failed to load the model"

            def __init__(self, command, *, cwd, stdout, **kwargs):
                super().__init__(command, cwd=cwd, stdout=stdout, **kwargs)
                self.returncode = 1

        result = self.run_with_fake(FailedModelLoadProcess)
        self.assertEqual(result["status"], "model_load_failed")
        self.assertEqual(result["returncode"], 1)
        self.assertIn("Failed to load the model", result["output"])

    def test_generic_nonzero_exit_is_not_misclassified_as_loader_failure(self):
        class GenericFailureProcess(FakeProcess):
            stderr_bytes = b"generic execution failure"

            def __init__(self, command, *, cwd, stdout, **kwargs):
                super().__init__(command, cwd=cwd, stdout=stdout, **kwargs)
                self.returncode = 2

        result = self.run_with_fake(GenericFailureProcess)
        self.assertEqual(result["status"], "model_failed")
        self.assertEqual(result["returncode"], 2)
        self.assertIn("generic execution failure", result["output"])

    def test_local_model_edit_accepts_strict_context_option(self):
        (self.root / "src" / "allowed.py").write_text(
            "# " + ("x" * 9000) + "\n", encoding="utf-8"
        )
        with patch.dict(os.environ, {
            "EMBERLANE_MODEL_PATH": str(self.model),
            "EMBERLANE_LLAMA_CLI": "llama-cli",
        }, clear=False), patch("emberlane.local_model_backend.subprocess.Popen") as popen:
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

    def test_relative_model_path_is_rejected_before_launch(self):
        with patch.dict(os.environ, {
            "EMBERLANE_MODEL_PATH": "models/model.gguf",
            "EMBERLANE_LLAMA_CLI": "llama-cli",
        }, clear=False), patch(
            "emberlane.local_model_backend.subprocess.Popen"
        ) as popen:
            result = run_local_model_proposal(
                self.root, self.payload, workspace=self.workspace
            )
        self.assertEqual(result["status"], "model_not_configured")
        self.assertIn("absolute", result["output"])
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

    def test_model_timeout_is_distinguished_from_other_failures(self):
        class HangingProcess(FakeProcess):
            def poll(self):
                return None if self.returncode == 0 else self.returncode

        result = self.run_with_fake(
            HangingProcess, payload={**self.payload, "timeout_seconds": 1}
        )
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result.get("returncode"))
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

    def test_edit_rejects_proposal_outside_requested_allowlist(self):
        other = self.root / "src" / "other.py"
        other.write_text("VALUE = 1\n", encoding="utf-8")
        self._initialize_git()
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_feature.py").write_text(
            "import unittest\nclass FeatureTests(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )
        original = other.read_bytes()
        patch_text = (
            "--- a/src/other.py\n"
            "+++ b/src/other.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )
        proposal = {
            "status": "proposal",
            "proposal": {
                "changed_paths": ["src/other.py"],
                "patch": patch_text,
                "patch_bytes": len(patch_text.encode("utf-8")),
                "base_sha256": {"src/other.py": hashlib.sha256(original).hexdigest()},
                "output": "changed other file",
                "output_bytes": 18,
                "applied": False,
            },
        }
        with patch("emberlane.local_model_backend.run_local_model_proposal", return_value=proposal):
            result = run_local_model_edit(
                self.root,
                {**self.payload, "test_file": "test_feature.py"},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "changed_path_outside_allowlist")
        self.assertFalse(result["applied"])
        self.assertEqual(other.read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_edit_rejects_patch_touching_path_missing_from_changed_paths(self):
        other = self.root / "src" / "other.py"
        other.write_text("VALUE = 1\n", encoding="utf-8")
        self._initialize_git()
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_feature.py").write_text(
            "import unittest\nclass FeatureTests(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(1, 1)\n",
            encoding="utf-8",
        )
        allowed_original = (self.root / "src" / "allowed.py").read_bytes()
        other_original = other.read_bytes()
        patch_text = (
            "--- a/src/allowed.py\n"
            "+++ b/src/allowed.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
            "--- a/src/other.py\n"
            "+++ b/src/other.py\n"
            "@@ -1 +1 @@\n"
            "-VALUE = 1\n"
            "+VALUE = 2\n"
        )
        proposal = {
            "status": "proposal",
            "proposal": {
                "changed_paths": ["src/allowed.py"],
                "patch": patch_text,
                "patch_bytes": len(patch_text.encode("utf-8")),
                "base_sha256": {
                    "src/allowed.py": hashlib.sha256(allowed_original).hexdigest(),
                },
                "output": "changed two files but declared one",
                "output_bytes": 35,
                "applied": False,
            },
        }
        with patch("emberlane.local_model_backend.run_local_model_proposal", return_value=proposal):
            result = run_local_model_edit(
                self.root,
                {**self.payload, "test_file": "test_feature.py"},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "patch_paths_mismatch")
        self.assertFalse(result["applied"])
        self.assertEqual(
            (self.root / "src" / "allowed.py").read_bytes(), allowed_original
        )
        self.assertEqual(other.read_bytes(), other_original)

    def test_edit_rejects_plain_unified_deletion_before_applying(self):
        self._initialize_git()
        target = self.root / "src" / "allowed.py"
        original = target.read_bytes()
        patch_text = (
            "--- a/src/allowed.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-VALUE = 1\n"
        )
        proposal = {
            "status": "proposal",
            "proposal": {
                "changed_paths": ["src/allowed.py"],
                "patch": patch_text,
                "patch_bytes": len(patch_text.encode("utf-8")),
                "base_sha256": {
                    "src/allowed.py": hashlib.sha256(original).hexdigest(),
                },
                "output": "attempted plain unified deletion",
                "output_bytes": 31,
                "applied": False,
            },
        }
        with patch(
            "emberlane.local_model_backend.run_local_model_proposal",
            return_value=proposal,
        ):
            result = run_local_model_edit(
                self.root, self.payload, workspace=self.workspace,
            )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "unsupported_patch_operation")
        self.assertFalse(result["applied"])
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(
            subprocess.run(
                ["git", "status", "--short"], cwd=self.root,
                capture_output=True, text=True, check=True,
            ).stdout,
            "",
        )

    def test_edit_rejects_symlink_patch_before_applying_to_source(self):
        self._initialize_git()
        outside = Path(self.temp.name) / "outside-sentinel.txt"
        outside.write_text("must remain untouched\n", encoding="utf-8")
        symlink_target = str(outside.resolve())
        patch_text = (
            "diff --git a/src/evil-link b/src/evil-link\n"
            "new file mode 120000\n"
            "index 0000000..0000000\n"
            "--- /dev/null\n"
            "+++ b/src/evil-link\n"
            "@@ -0,0 +1 @@\n"
            f"+{symlink_target}\n"
        )
        proposal = {
            "status": "proposal",
            "proposal": {
                "changed_paths": ["src/evil-link"],
                "patch": patch_text,
                "patch_bytes": len(patch_text.encode("utf-8")),
                "base_sha256": {"src/evil-link": None},
                "output": "attempted symlink creation",
                "output_bytes": 25,
                "applied": False,
            },
        }
        payload = {**self.payload, "allowed_paths": ["src/evil-link"]}
        with patch("emberlane.local_model_backend.run_local_model_proposal", return_value=proposal):
            result = run_local_model_edit(self.root, payload, workspace=self.workspace)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "unsupported_patch_operation")
        self.assertFalse(result["applied"])
        self.assertFalse((self.root / "src" / "evil-link").is_symlink())
        self.assertEqual(outside.read_text(encoding="utf-8"), "must remain untouched\n")

    def test_edit_rejects_other_unsupported_patch_operations_before_apply(self):
        self._initialize_git()
        original = (self.root / "src" / "allowed.py").read_bytes()
        unsupported_metadata = [
            "old mode 100644\nnew mode 100755",
            "deleted file mode 100644",
            "rename from src/allowed.py\nrename to src/renamed.py",
            "copy from src/allowed.py\ncopy to src/copied.py",
            "new file mode 160000",
            "GIT binary patch",
        ]
        for metadata in unsupported_metadata:
            with self.subTest(metadata=metadata):
                patch_text = (
                    "diff --git a/src/allowed.py b/src/allowed.py\n"
                    f"{metadata}\n"
                    "--- a/src/allowed.py\n"
                    "+++ b/src/allowed.py\n"
                    "@@ -1 +1 @@\n"
                    "-VALUE = 1\n"
                    "+VALUE = 2\n"
                )
                proposal = {
                    "status": "proposal",
                    "proposal": {
                        "changed_paths": ["src/allowed.py"],
                        "patch": patch_text,
                        "patch_bytes": len(patch_text.encode("utf-8")),
                        "base_sha256": {
                            "src/allowed.py": hashlib.sha256(original).hexdigest(),
                        },
                        "output": "unsupported operation",
                        "output_bytes": 21,
                        "applied": False,
                    },
                }
                with patch(
                    "emberlane.local_model_backend.run_local_model_proposal",
                    return_value=proposal,
                ):
                    result = run_local_model_edit(
                        self.root, self.payload, workspace=self.workspace,
                    )
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["reason"], "unsupported_patch_operation")
                self.assertFalse(result["applied"])
                self.assertEqual(
                    (self.root / "src" / "allowed.py").read_bytes(), original,
                )
                self.assertFalse((self.root / "src" / "renamed.py").exists())
                self.assertFalse((self.root / "src" / "copied.py").exists())

    def test_existing_gitlink_patch_is_rejected_before_apply(self):
        self._initialize_git()
        target = self.root / "src" / "allowed.py"
        original = target.read_bytes()
        # Make the real Git index entry a gitlink (mode 160000), while retaining
        # the regular worktree file to prove rejection preserves both layers.
        subprocess.run(
            ["git", "update-index", "--add", "--cacheinfo",
             "160000,1111111111111111111111111111111111111111,src/allowed.py"],
            cwd=self.root, check=True,
        )
        index_before = subprocess.run(
            ["git", "ls-files", "--stage", "--", "src/allowed.py"],
            cwd=self.root, capture_output=True, text=True, check=True,
        ).stdout
        tree_before = subprocess.run(
            ["git", "write-tree"], cwd=self.root,
            capture_output=True, text=True, check=True,
        ).stdout
        patch_text = (
            "diff --git a/src/allowed.py b/src/allowed.py\n"
            "index 1111111..2222222 160000\n"
            "--- a/src/allowed.py\n"
            "+++ b/src/allowed.py\n"
            "@@ -1 +1 @@\n"
            "-Subproject commit 1111111111111111111111111111111111111111\n"
            "+Subproject commit 2222222222222222222222222222222222222222\n"
        )
        proposal = {
            "status": "proposal",
            "proposal": {
                "changed_paths": ["src/allowed.py"],
                "patch": patch_text,
                "patch_bytes": len(patch_text.encode("utf-8")),
                "base_sha256": {
                    "src/allowed.py": hashlib.sha256(original).hexdigest(),
                },
                "output": "attempt existing gitlink update",
                "output_bytes": 28,
                "applied": False,
            },
        }
        with patch(
            "emberlane.local_model_backend.run_local_model_proposal",
            return_value=proposal,
        ):
            result = run_local_model_edit(
                self.root, self.payload, workspace=self.workspace,
            )
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "unsupported_patch_operation")
        self.assertFalse(result["applied"])
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(
            subprocess.run(
                ["git", "ls-files", "--stage", "--", "src/allowed.py"],
                cwd=self.root, capture_output=True, text=True, check=True,
            ).stdout,
            index_before,
        )
        self.assertEqual(
            subprocess.run(
                ["git", "write-tree"], cwd=self.root,
                capture_output=True, text=True, check=True,
            ).stdout,
            tree_before,
        )

    def test_post_apply_unexpected_mutation_returns_recovery_required(self):
        self._initialize_git()
        tests_dir = self.root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_feature.py").write_text(
            "import unittest\nfrom src.allowed import VALUE\n"
            "class FeatureTests(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(VALUE, 2)\n",
            encoding="utf-8",
        )
        proposal = self._proposal_for_value(2)
        fixed_command = __import__(
            "emberlane.local_model_backend", fromlist=["_fixed_command"]
        )._fixed_command

        def mutate_after_real_apply(command, cwd, **kwargs):
            result = fixed_command(command, cwd, **kwargs)
            if (
                Path(cwd).resolve() == self.root.resolve()
                and command == ["git", "apply", "--whitespace=error", "-"]
                and result is not None
                and result.returncode == 0
            ):
                (self.root / "src" / "allowed.py").write_text(
                    "VALUE = 999\n", encoding="utf-8",
                )
            return result

        with patch(
            "emberlane.local_model_backend.run_local_model_proposal",
            return_value=proposal,
        ), patch(
            "emberlane.local_model_backend._fixed_command",
            side_effect=mutate_after_real_apply,
        ):
            result = run_local_model_edit(
                self.root,
                {**self.payload, "test_file": "test_feature.py"},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "recovery_required")
        self.assertTrue(result["applied"])
        self.assertEqual(
            result["reason"], "working_tree_did_not_match_verified_snapshot",
        )
        self.assertEqual(
            (self.root / "src" / "allowed.py").read_text(encoding="utf-8"),
            "VALUE = 999\n",
        )

    def test_post_apply_symlink_swap_is_not_verified_or_reversed(self):
        self._initialize_git()
        tests_dir = self.root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_feature.py").write_text(
            "import unittest\nfrom src.allowed import VALUE\n"
            "class FeatureTests(unittest.TestCase):\n"
            " def test_value(self): self.assertEqual(VALUE, 2)\n",
            encoding="utf-8",
        )
        outside = self.root.parent / "outside-after-apply.py"
        outside.write_text("VALUE = 2\n", encoding="utf-8")
        target = self.root / "src" / "allowed.py"
        proposal = self._proposal_for_value(2)
        fixed_command = __import__(
            "emberlane.local_model_backend", fromlist=["_fixed_command"]
        )._fixed_command

        def replace_with_symlink_after_real_apply(command, cwd, **kwargs):
            result = fixed_command(command, cwd, **kwargs)
            if (
                Path(cwd).resolve() == self.root.resolve()
                and command == ["git", "apply", "--whitespace=error", "-"]
                and result is not None
                and result.returncode == 0
            ):
                target.unlink()
                target.symlink_to(outside)
            return result

        with patch(
            "emberlane.local_model_backend.run_local_model_proposal",
            return_value=proposal,
        ), patch(
            "emberlane.local_model_backend._fixed_command",
            side_effect=replace_with_symlink_after_real_apply,
        ):
            result = run_local_model_edit(
                self.root,
                {**self.payload, "test_file": "test_feature.py"},
                workspace=self.workspace,
            )
        self.assertEqual(result["status"], "recovery_required")
        self.assertTrue(result["applied"])
        self.assertTrue(target.is_symlink())
        self.assertEqual(outside.read_text(encoding="utf-8"), "VALUE = 2\n")

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
