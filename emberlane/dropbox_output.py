"""Dropbox output sink for Emberlane task logs.

Uses only the Python standard library. Credentials are read from environment
variables or ~/.config/emberlane/dropbox.env; never log credential values.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"
DEFAULT_CONFIG = Path.home() / ".config" / "emberlane" / "dropbox.env"
MAX_LOG_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 1_000_000


class DropboxOutputError(RuntimeError):
    """Sanitized Dropbox output error."""


def _config() -> dict[str, str]:
    values = dict(os.environ)
    path = Path(values.get("EMBERLANE_DROPBOX_CONFIG", str(DEFAULT_CONFIG))).expanduser()
    if path.exists():
        try:
            if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise DropboxOutputError("Dropbox config permissions are too broad")
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip().strip("\"' ")
                if key.startswith("DROPBOX_") and key not in values:
                    values[key] = value
        except OSError as exc:
            raise DropboxOutputError(f"cannot read Dropbox config ({type(exc).__name__})") from None
    required = ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise DropboxOutputError("BLOCKED_AUTH: missing " + ", ".join(missing))
    configured_root = values.get("DROPBOX_ROOT", "/worker-logs").strip("/")
    root = f"/{configured_root}" if configured_root else ""
    return {
        "app_key": values["DROPBOX_APP_KEY"],
        "app_secret": values["DROPBOX_APP_SECRET"],
        "refresh_token": values["DROPBOX_REFRESH_TOKEN"],
        "root": root,
    }


def _request(url: str, *, headers: dict[str, str], data: bytes = b"",
             timeout: float = 20.0,
             max_response_bytes: int = MAX_RESPONSE_BYTES) -> tuple[bytes, dict[str, str]]:
    if type(max_response_bytes) is not int or max_response_bytes < 0:
        raise ValueError("max_response_bytes must be a non-negative integer")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(max_response_bytes + 1)
            if len(body) > max_response_bytes:
                raise DropboxOutputError("Dropbox response exceeded configured size limit")
            return body, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        # Do not include response body or request headers; they may contain secrets.
        raise DropboxOutputError(f"Dropbox HTTP {exc.code}") from None
    except http.client.HTTPException as exc:
        # Protocol errors such as IncompleteRead may carry partial response data.
        raise DropboxOutputError(f"Dropbox response error ({type(exc).__name__})") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DropboxOutputError(f"Dropbox network error ({type(exc).__name__})") from None


def _access_token(cfg: dict[str, str]) -> str:
    basic = (cfg["app_key"] + ":" + cfg["app_secret"]).encode()
    import base64
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": cfg["refresh_token"],
    }).encode()
    data, _ = _request(
        "https://api.dropbox.com/oauth2/token",
        headers={
            "Authorization": "Basic " + base64.b64encode(basic).decode("ascii"),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=body,
    )
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("OAuth response must be an object")
        token = [REDACTED]
        if not isinstance(token, str) or not token:
            [REDACTED] ValueError("missing access token")
        return token
    except (ValueError, TypeError, UnicodeDecodeError):
        raise DropboxOutputError("Dropbox OAuth response was invalid") from None


def upload_task_log(task_id: str, text: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Upload UTF-8 Markdown and verify the exact remote bytes with read-back."""
    try:
        valid_timeout = (
            not isinstance(timeout, bool)
            and isinstance(timeout, (int, float))
            and math.isfinite(timeout)
            and timeout > 0
        )
    except OverflowError:
        valid_timeout = False
    if not valid_timeout:
        raise ValueError("timeout must be a positive finite number")
    if not task_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in task_id):
        raise ValueError("task_id must contain only letters, digits, hyphen or underscore")
    content = text.encode("utf-8")
    if len(content) > MAX_LOG_BYTES:
        raise ValueError("task log exceeds configured size limit")
    digest = hashlib.sha256(content).hexdigest()
    cfg = _config()
    token = [REDACTED]
    root = cfg["root"]
    if root:
        try:
            _request(
                API + "/files/create_folder_v2",
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                data=json.dumps({"path": root, "autorename": False}, separators=(",", ":")).encode(),
                timeout=timeout,
            )
        except DropboxOutputError as exc:
            # Dropbox returns 409 when the target folder already exists; the upload
            # and read-back below still verify that it is usable.
            if "HTTP 409" not in str(exc):
                raise
    path = (root + "/" if root else "/") + task_id + ".md"
    metadata = {
        "path": path,
        "mode": "overwrite",
        "autorename": False,
        "mute": True,
        "strict_conflict": True,
    }
    _request(
        CONTENT + "/files/upload",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps(metadata, separators=(",", ":")),
        },
        data=content,
        timeout=timeout,
    )
    downloaded, _ = _request(
        CONTENT + "/files/download",
        headers={
            "Authorization": "Bearer " + token,
            "Dropbox-API-Arg": json.dumps({"path": path}, separators=(",", ":")),
        },
        timeout=timeout,
        max_response_bytes=len(content),
    )
    remote_digest = hashlib.sha256(downloaded).hexdigest()
    if remote_digest != digest:
        raise DropboxOutputError("Dropbox read-back SHA-256 mismatch")
    return {
        "status": "published",
        "path": path,
        "sha256": digest,
        "bytes": len(content),
        "readback_verified": True,
    }
