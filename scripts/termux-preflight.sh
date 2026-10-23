#!/usr/bin/env bash
# Read-only Termux/Android readiness check. Does not install, edit, sync, or delete anything.
set -u

ROOT="${EMBERLANE_ROOT:-$PWD}"
MODEL_PATH="${EMBERLANE_MODEL_PATH:-}"
LLAMA_BIN="${LLAMA_CLI_BIN:-llama-cli}"
FAIL=0
WARN=0

ok()   { printf 'PASS  %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; WARN=$((WARN + 1)); }
fail() { printf 'BLOCK %s\n' "$*"; FAIL=$((FAIL + 1)); }

printf '%s\n' '=== Emberlane Termux preflight (read-only) ==='
printf 'root: %s\n' "$ROOT"

if [ ! -d "$ROOT" ]; then
  fail "workspace directory does not exist"
  printf 'SUMMARY: BLOCKED (%s blockers, %s warnings)\n' "$FAIL" "$WARN"
  exit 2
fi

if [ -f "$ROOT/pyproject.toml" ] && [ -d "$ROOT/emberlane" ]; then
  ok "Emberlane project structure found"
else
  fail "run from the Emberlane repository root or set EMBERLANE_ROOT"
fi

if command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  PYTHON_BIN=""
fi

if [ -n "$PYTHON_BIN" ]; then
  VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)"
  if "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    ok "Python $VERSION ($PYTHON_BIN)"
  else
    fail "Python 3.11+ required; found ${VERSION:-unknown}"
  fi
else
  fail "Python executable not found"
fi

if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ok "Git worktree available"
  printf '%s\n' '--- worktree summary (no file contents) ---'
  git -C "$ROOT" status --short --branch 2>&1 || warn "git status could not be read"
else
  fail "Git or a Git worktree is unavailable"
fi

if command -v "$LLAMA_BIN" >/dev/null 2>&1; then
  LLAMA_PATH="$(command -v "$LLAMA_BIN")"
  ok "llama-cli executable found ($LLAMA_PATH)"
  if "$LLAMA_BIN" --version >/dev/null 2>&1; then
    ok "llama-cli can start (--version)"
  else
    warn "llama-cli exists but --version failed; shared libraries or runtime may be missing"
  fi
else
  warn "llama-cli not found via LLAMA_CLI_BIN='$LLAMA_BIN'"
fi

if [ -n "$MODEL_PATH" ]; then
  if [ -f "$MODEL_PATH" ] && [ -r "$MODEL_PATH" ]; then
    SIZE="$("$PYTHON_BIN" -c 'import os,sys; print(os.path.getsize(sys.argv[1]))' "$MODEL_PATH" 2>/dev/null || echo unknown)"
    ok "configured model file is readable (bytes=$SIZE)"
  else
    fail "EMBERLANE_MODEL_PATH is set but file is missing or unreadable"
  fi
else
  warn "EMBERLANE_MODEL_PATH is unset; local-model execution is not configured in this shell"
fi

printf '\nSUMMARY: '
if [ "$FAIL" -gt 0 ]; then
  printf 'BLOCKED (%s blockers, %s warnings)\n' "$FAIL" "$WARN"
  exit 2
elif [ "$WARN" -gt 0 ]; then
  printf 'PARTIAL (%s warnings; no blockers found)\n' "$WARN"
  exit 1
else
  printf 'PASS (basic environment checks only)\n'
  printf '%s\n' 'NOTE: this does not prove model inference, code editing, or supervisor recovery.'
fi
