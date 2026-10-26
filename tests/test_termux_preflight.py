import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "termux-preflight.sh"


class TermuxPreflightCliOverrideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.bin = Path(self.temp.name) / "bin"
        self.root.mkdir()
        self.bin.mkdir()
        (self.root / "pyproject.toml").write_text("[project]\nname='preflight-test'\n")
        (self.root / "emberlane").mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.original_path = os.environ.get("PATH", "")

        for name in ("preferred-cli", "fallback-cli"):
            executable = self.bin / name
            executable.write_text("#!/bin/sh\nprintf '%s\\n' 'fake llama-cli 1.0'\n")
            executable.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def run_preflight(self, **extra_env):
        env = os.environ.copy()
        env.update({
            "PATH": f"{self.bin}:{self.original_path}",
            "EMBERLANE_ROOT": str(self.root),
        })
        env.pop("EMBERLANE_MODEL_PATH", None)
        env.pop("EMBERLANE_LLAMA_CLI", None)
        env.pop("LLAMA_CLI_BIN", None)
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_runtime_override_takes_precedence_over_legacy_override(self):
        result = self.run_preflight(
            EMBERLANE_LLAMA_CLI="preferred-cli",
            LLAMA_CLI_BIN="fallback-cli",
        )
        self.assertIn(f"llama-cli executable found ({self.bin / 'preferred-cli'})", result.stdout)
        self.assertNotIn(f"llama-cli executable found ({self.bin / 'fallback-cli'})", result.stdout)

    def test_legacy_override_remains_supported(self):
        result = self.run_preflight(LLAMA_CLI_BIN="fallback-cli")
        self.assertIn(f"llama-cli executable found ({self.bin / 'fallback-cli'})", result.stdout)


if __name__ == "__main__":
    unittest.main()
