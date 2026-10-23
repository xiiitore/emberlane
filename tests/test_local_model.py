import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from emberlane.local_model import LocalModelConfig, LocalModelError, LocalModelRunner


class LocalModelRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "tiny.gguf"
        self.model.write_bytes(b"test-fixture-not-a-real-model")
        self.executable = self.root / "fake-llama"
        self.write_executable("print('generated answer')\n")
        self.config = LocalModelConfig(
            executable=str(self.executable),
            model_path=self.model,
            context_tokens=512,
            max_tokens=24,
            timeout_seconds=2,
            max_prompt_chars=100,
            max_output_chars=8,
        )

    def write_executable(self, body):
        self.executable.write_text(
            "#!" + os.sys.executable + "\n" + textwrap.dedent(body),
            encoding="utf-8",
        )
        self.executable.chmod(self.executable.stat().st_mode | stat.S_IXUSR)

    def test_success_uses_no_shell_and_bounds_returned_output(self):
        result = LocalModelRunner(self.config).generate("explain the fixture")
        self.assertTrue(result["ok"])
        self.assertEqual(result["output"], "generate")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["context_tokens"], 512)

    def test_large_stdout_and_stderr_are_drained_with_bounded_capture(self):
        self.write_executable(
            "import sys\n"
            "sys.stdout.write('x' * 1000000)\n"
            "sys.stderr.write('diagnostic-' * 100000)\n"
        )
        result = LocalModelRunner(self.config).generate("hello")
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["output"]), self.config.max_output_chars)
        self.assertEqual(result["returncode"], 0)

    def test_missing_model_is_reported_before_process_start(self):
        config = LocalModelConfig(
            str(self.executable), self.root / "missing.gguf", timeout_seconds=1
        )
        with self.assertRaisesRegex(LocalModelError, "does not exist") as caught:
            LocalModelRunner(config).generate("hello")
        self.assertEqual(caught.exception.code, "model_not_found")

    def test_missing_executable_is_reported(self):
        config = LocalModelConfig(
            str(self.root / "missing-cli"), self.model, timeout_seconds=1
        )
        with self.assertRaises(LocalModelError) as caught:
            LocalModelRunner(config).generate("hello")
        self.assertEqual(caught.exception.code, "executable_not_found")

    def test_nonzero_exit_is_reported_with_code(self):
        self.write_executable("import sys\nprint('bad model file', file=sys.stderr)\nsys.exit(9)\n")
        with self.assertRaises(LocalModelError) as caught:
            LocalModelRunner(self.config).generate("hello")
        self.assertEqual(caught.exception.code, "nonzero_exit")
        self.assertEqual(caught.exception.returncode, 9)

    def test_loader_error_has_distinct_classification(self):
        self.write_executable("import sys\nprint('failed to load model', file=sys.stderr)\nsys.exit(1)\n")
        with self.assertRaises(LocalModelError) as caught:
            LocalModelRunner(self.config).generate("hello")
        self.assertEqual(caught.exception.code, "model_load_failed")

    def test_timeout_is_bounded(self):
        self.write_executable("import time\ntime.sleep(2)\n")
        config = LocalModelConfig(
            str(self.executable), self.model, timeout_seconds=1
        )
        with self.assertRaises(LocalModelError) as caught:
            LocalModelRunner(config).generate("hello")
        self.assertEqual(caught.exception.code, "timeout")

    def test_empty_output_is_not_success(self):
        self.write_executable("print('   ')\n")
        with self.assertRaises(LocalModelError) as caught:
            LocalModelRunner(self.config).generate("hello")
        self.assertEqual(caught.exception.code, "empty_output")

    def test_prompt_size_and_blank_prompt_are_rejected(self):
        runner = LocalModelRunner(self.config)
        for prompt in ("", "x" * 101):
            with self.subTest(length=len(prompt)):
                with self.assertRaises(LocalModelError):
                    runner.generate(prompt)

    def test_environment_requires_explicit_model_path(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LocalModelError) as caught:
                LocalModelConfig.from_env()
        self.assertEqual(caught.exception.code, "not_configured")

    def test_environment_accepts_emberlane_cli_alias(self):\n        config = LocalModelConfig.from_env({\n            "EMBERLANE_MODEL_PATH": str(self.model),\n            "EMBERLANE_LLAMA_CLI": str(self.executable),\n            "LLAMA_CLI_BIN": "/ignored/alternative",\n        })\n        self.assertEqual(config.executable, str(self.executable))\n\n    def test_environment_rejects_out_of_range_limits(self):
        with self.assertRaises(LocalModelError) as caught:
            LocalModelConfig.from_env({
                "EMBERLANE_MODEL_PATH": str(self.model),
                "EMBERLANE_MODEL_CONTEXT": "999999",
            })
        self.assertEqual(caught.exception.code, "invalid_configuration")


if __name__ == "__main__":
    unittest.main()
