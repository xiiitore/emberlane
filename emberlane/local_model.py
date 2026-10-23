"""Bounded local llama.cpp adapter.

This module never invokes a shell and never downloads models. Runtime readiness is
reported from the actual subprocess result, not inferred from executable presence.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_CONTEXT_TOKENS = 2048
DEFAULT_MAX_TOKENS = 256
DEFAULT_MAX_PROMPT_CHARS = 16_000
DEFAULT_MAX_OUTPUT_CHARS = 20_000
MAX_CONTEXT_TOKENS = 32_768
MAX_GENERATION_TOKENS = 4_096


class LocalModelError(RuntimeError):
    """Expected, safe-to-report local model failure."""

    def __init__(self, code: str, message: str, *, returncode: int | None = None):
        super().__init__(message)
        self.code = code
        self.returncode = returncode


@dataclass(frozen=True)
class LocalModelConfig:
    executable: str
    model_path: Path
    context_tokens: int = DEFAULT_CONTEXT_TOKENS
    max_tokens: int = DEFAULT_MAX_TOKENS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LocalModelConfig":
        values = os.environ if env is None else env
        executable = values.get("LLAMA_CLI_BIN", "llama-cli").strip()
        raw_model = values.get("EMBERLANE_MODEL_PATH", "").strip()
        if not raw_model:
            raise LocalModelError(
                "not_configured",
                "EMBERLANE_MODEL_PATH must point to an existing local model file",
            )
        try:
            context = int(values.get("EMBERLANE_MODEL_CONTEXT", str(DEFAULT_CONTEXT_TOKENS)))
            tokens = int(values.get("EMBERLANE_MODEL_MAX_TOKENS", str(DEFAULT_MAX_TOKENS)))
            timeout = int(values.get("EMBERLANE_MODEL_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
            max_output = int(values.get("EMBERLANE_MODEL_MAX_OUTPUT", str(DEFAULT_MAX_OUTPUT_CHARS)))
        except (TypeError, ValueError) as exc:
            raise LocalModelError("invalid_configuration", "model numeric settings must be integers") from exc
        if not executable:
            raise LocalModelError("invalid_configuration", "LLAMA_CLI_BIN must not be empty")
        if not 128 <= context <= MAX_CONTEXT_TOKENS:
            raise LocalModelError("invalid_configuration", f"context must be 128..{MAX_CONTEXT_TOKENS}")
        if not 1 <= tokens <= MAX_GENERATION_TOKENS:
            raise LocalModelError("invalid_configuration", f"max tokens must be 1..{MAX_GENERATION_TOKENS}")
        if not 1 <= timeout <= 3600:
            raise LocalModelError("invalid_configuration", "timeout must be 1..3600 seconds")
        if not 1 <= max_output <= 200_000:
            raise LocalModelError("invalid_configuration", "max output must be 1..200000 characters")
        return cls(
            executable,
            Path(raw_model).expanduser().resolve(),
            context,
            tokens,
            timeout,
            max_output_chars=max_output,
        )


def _read_bounded_stream(stream, limit: int, *, keep_tail: bool = False) -> tuple[bytes, bool]:
    """Drain a child pipe fully while retaining only a bounded amount of data."""
    retained = bytearray()
    truncated = False
    while True:
        chunk = stream.read(4096)
        if not chunk:
            break
        if len(retained) + len(chunk) <= limit:
            retained.extend(chunk)
        else:
            truncated = True
            if keep_tail:
                retained.extend(chunk)
                if len(retained) > limit:
                    del retained[:-limit]
            else:
                remaining = max(0, limit - len(retained))
                if remaining:
                    retained.extend(chunk[:remaining])
    return bytes(retained), truncated


def _run_bounded_process(command: list[str], *, timeout: int, stdout_limit: int) -> tuple[int, str, str, bool]:
    """Run a child with concurrent, bounded stdout/stderr capture and a hard timeout."""
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=os.environ.copy(),
        )
    except OSError as exc:
        raise LocalModelError(
            "execution_error",
            f"could not start local model ({type(exc).__name__})",
        ) from exc

    assert process.stdout is not None
    assert process.stderr is not None
    captured: dict[str, tuple[bytes, bool]] = {}

    def drain(name: str, stream, limit: int, keep_tail: bool = False) -> None:
        try:
            captured[name] = _read_bounded_stream(stream, limit, keep_tail=keep_tail)
        finally:
            stream.close()

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout, stdout_limit), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr, 8192, True), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        for reader in readers:
            reader.join()
        raise LocalModelError(
            "timeout",
            f"local model exceeded {timeout}-second timeout",
        ) from exc
    for reader in readers:
        reader.join()

    stdout_bytes, stdout_truncated = captured.get("stdout", (b"", False))
    stderr_bytes, stderr_truncated = captured.get("stderr", (b"", False))
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if stderr_truncated:
        stderr = "[stderr tail retained; earlier bytes omitted]\n" + stderr
    return (
        returncode,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr,
        stdout_truncated,
    )


class LocalModelRunner:
    def __init__(self, config: LocalModelConfig):
        self.config = config

    def generate(self, prompt: str) -> dict[str, object]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise LocalModelError("invalid_prompt", "prompt must be a non-empty string")
        if len(prompt) > self.config.max_prompt_chars:
            raise LocalModelError(
                "prompt_too_large",
                f"prompt exceeds {self.config.max_prompt_chars} characters",
            )
        executable = self.config.executable
        resolved_executable = shutil.which(executable) if not Path(executable).is_absolute() else executable
        if not resolved_executable or not Path(resolved_executable).is_file():
            raise LocalModelError("executable_not_found", "configured llama.cpp executable was not found")
        model = self.config.model_path
        if not model.is_file():
            raise LocalModelError("model_not_found", "configured model file does not exist")
        if not os.access(model, os.R_OK):
            raise LocalModelError("model_unreadable", "configured model file is not readable")

        command = [
            str(resolved_executable), "--model", str(model),
            "--prompt", prompt,
            "--predict", str(self.config.max_tokens),
            "--ctx-size", str(self.config.context_tokens),
            "--no-conversation", "--simple-io",
        ]
        started = time.monotonic()
        try:
            returncode, stdout, stderr, capture_truncated = _run_bounded_process(
                command,
                timeout=self.config.timeout_seconds,
                stdout_limit=self.config.max_output_chars * 4 + 4,
            )
        except LocalModelError:
            raise

        elapsed = round(time.monotonic() - started, 3)
        stdout = stdout or ""
        stderr = stderr or ""
        if returncode != 0:
            lowered = stderr.lower()
            code = "model_load_failed" if any(
                marker in lowered for marker in ("failed to load", "error loading model", "cannot open model")
            ) else "nonzero_exit"
            raise LocalModelError(
                code,
                f"llama.cpp exited with code {returncode}; stderr: {stderr[-2000:]}",
                returncode=returncode,
            )
        output = stdout.strip()
        if not output:
            raise LocalModelError("empty_output", "llama.cpp returned no generated text")
        truncated = capture_truncated or len(output) > self.config.max_output_chars
        if truncated:
            output = output[:self.config.max_output_chars]
        return {
            "ok": True,
            "output": output,
            "truncated": truncated,
            "returncode": returncode,
            "elapsed_seconds": elapsed,
            "model_path": str(model),
            "context_tokens": self.config.context_tokens,
            "max_tokens": self.config.max_tokens,
        }
