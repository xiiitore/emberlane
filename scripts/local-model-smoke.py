#!/usr/bin/env python3
"""Opt-in local llama.cpp smoke test; does not edit the repository."""
from __future__ import annotations

import argparse
import json
import sys

from emberlane.local_model import LocalModelConfig, LocalModelError, LocalModelRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: EMBERLANE_LOCAL_MODEL_OK",
        help="small smoke-test prompt (do not include secrets)",
    )
    args = parser.parse_args(argv)
    try:
        config = LocalModelConfig.from_env()
        result = LocalModelRunner(config).generate(args.prompt)
    except LocalModelError as exc:
        print(json.dumps({
            "status": "failed",
            "error_code": exc.code,
            "error": str(exc),
            "returncode": exc.returncode,
        }, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "passed", **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
