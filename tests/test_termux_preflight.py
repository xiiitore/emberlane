import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO_ROOT / "scripts" / "termux-preflight.sh"


class TermuxPreflightCliConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "repo"
        (self.root / "emberlane").mkdir(parents=True)
        (self.root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

        self.cli = Path(self.temp.name) / "fake-llama-cli"
        self.cli.write_text("#!/bin/sh\nprintf 'fake llama-cli 1.0\\n'\n", encoding="utf-8")
        self.cli.chmod(0o755)

    def run_preflight(self, extra_env):
        env = os.environ.copy()
        env.pop("EMBERLANE_MODEL_PATH", None)
        env.pop("EMBERLANE_LLAMA_CLI", None)
        env.pop("LLAMA_CLI_BIN", None)
        env.update(extra_env)
        env["EMBERLANE_ROOT"] = str(self.root)
        return subprocess.run(
            ["bash", str(PREFLIGHT)],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_backend_variable_is_used_and_takes_precedence(self):
        result = self.run_preflight({
            "EMBERLANE_LLAMA_CLI": str(self.cli),
            "LLAMA_CLI_BIN": "/definitely/missing-legacy-cli",
        })
        self.assertIn(f"model_cli_config: {self.cli}", result.stdout)
        self.assertIn(f"llama-cli executable found ({self.cli})", result.stdout)
        self.assertNotIn("not found via configured executable", result.stdout)

    def test_legacy_variable_remains_a_fallback(self):
        result = self.run_preflight({"LLAMA_CLI_BIN": str(self.cli)})
        self.assertIn(f"model_cli_config: {self.cli}", result.stdout)
        self.assertIn(f"llama-cli executable found ({self.cli})", result.stdout)
        self.assertNotIn("not found via configured executable", result.stdout)


if __name__ == "__main__":
    unittest.main()
