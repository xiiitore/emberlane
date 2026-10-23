import http.client
import io
import json
import os
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from emberlane import dropbox_output as dropbox


class DropboxOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "missing.env"

    def _env(self, **extra):
        values = {
            "DROPBOX_APP_KEY": "test-app-key",
            "DROPBOX_APP_SECRET": "test-app-secret",
            "DROPBOX_REFRESH_TOKEN": "test-refresh-token",
            "DROPBOX_ROOT": "/worker-logs",
            "EMBERLANE_DROPBOX_CONFIG": str(self.config),
        }
        values.update(extra)
        return patch.dict(os.environ, values, clear=True)

    def test_config_requires_owner_only_posix_permissions(self):
        if os.name != "posix":
            self.skipTest("POSIX file permissions are unavailable")
        self.config.write_text(
            "DROPBOX_APP_KEY=file-app-key\n"
            "DROPBOX_APP_SECRET=file-app-secret\n"
            "DROPBOX_REFRESH_TOKEN=file-refresh-token\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {
            "EMBERLANE_DROPBOX_CONFIG": str(self.config),
            "DROPBOX_ROOT": "/worker-logs",
        }, clear=True):
            self.config.chmod(0o600)
            self.assertEqual(dropbox._config()["app_key"], "file-app-key")
            for mode in (0o640, 0o604, 0o601):
                with self.subTest(mode=oct(mode)):
                    self.config.chmod(mode)
                    with self.assertRaisesRegex(
                        dropbox.DropboxOutputError, "permissions are too broad"
                    ):
                        dropbox._config()

    def test_relative_configured_root_becomes_absolute_dropbox_path(self):
        with self._env(DROPBOX_ROOT="worker-logs///"):
            self.assertEqual(dropbox._config()["root"], "/worker-logs")

    def test_upload_and_readback_verified(self):
        payload = "# task report\ncomplete\n"
        responses = [
            (json.dumps({"access_token": "short-lived-token"}).encode(), {}),
            (b'{"metadata":{}}', {}),
            (b'{"name":"task-1.md"}', {}),
            (payload.encode(), {}),
        ]
        with self._env(), patch.object(dropbox, "_request", side_effect=responses) as request:
            result = dropbox.upload_task_log("task-1", payload)
        self.assertEqual(result["status"], "published")
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["sha256"], __import__("hashlib").sha256(payload.encode()).hexdigest())
        self.assertEqual(result["path"], "/worker-logs/task-1.md")
        self.assertEqual(request.call_count, 4)
        self.assertIn("/files/create_folder_v2", request.call_args_list[1].args[0])
        self.assertIn("/files/upload", request.call_args_list[2].args[0])
        self.assertIn("/files/download", request.call_args_list[3].args[0])
        self.assertEqual(
            request.call_args_list[3].kwargs["max_response_bytes"], len(payload.encode())
        )

    def test_http_error_does_not_expose_response_body(self):
        secret = [REDACTED]
        response_error = urllib.error.HTTPError(
            "https://api.dropboxapi.com/2/upload", 401, "Unauthorized", {},
            io.BytesIO(secret.encode("utf-8")),
        )
        with patch.object(
            dropbox.urllib.request, "urlopen", side_effect=response_error
        ):
            with self.assertRaisesRegex(
                dropbox.DropboxOutputError, "Dropbox HTTP 401"
            ) as caught:
                dropbox._request(
                    "https://api.dropboxapi.com/2/upload", headers={}
                )

        self.assertNotIn(secret, str(caught.exception))

    def test_incomplete_response_is_sanitized(self):
        secret = [REDACTED] refresh_token=[REDACTED]

        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                raise http.client.IncompleteRead(secret, 100)

        with patch.object(dropbox.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(
                dropbox.DropboxOutputError, r"Dropbox response error \(IncompleteRead\)"
            ) as caught:
                dropbox._request("https://example.invalid", headers={})

        self.assertNotIn(secret.decode(), str(caught.exception))

    def test_request_bounds_response_read(self):
        class Response:
            headers = {}

            def __init__(self):
                self.read_sizes = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                self.read_sizes.append(size)
                return b"x" * size

        response = Response()
        with patch.object(dropbox.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(dropbox.DropboxOutputError, "response exceeded"):
                dropbox._request("https://example.invalid", headers={}, max_response_bytes=8)

        self.assertEqual(response.read_sizes, [9])

    def test_upload_rejects_oversized_log_before_network(self):
        with self._env(), patch.object(dropbox, "_request") as request:
            with self.assertRaisesRegex(ValueError, "task log exceeds configured size limit"):
                dropbox.upload_task_log("task-large", "x" * (dropbox.MAX_LOG_BYTES + 1))
        request.assert_not_called()

    def test_missing_auth_is_blocked_without_network(self):
        with self._env(DROPBOX_APP_KEY="", DROPBOX_APP_SECRET="", DROPBOX_REFRESH_TOKEN=""), \
             patch.object(dropbox, "_request") as request:
            with self.assertRaisesRegex(dropbox.DropboxOutputError, "BLOCKED_AUTH"):
                dropbox.upload_task_log("task-2", "report")
        request.assert_not_called()

    def test_oauth_response_must_be_valid_json_object(self):
        cfg = {
            "app_key": "test-app-key",
            "app_secret": "test-app-secret",
            "refresh_token": "test-refresh-token",
        }
        for body in (b"[]", b"\xff"):
            with self.subTest(body=body), patch.object(
                dropbox, "_request", return_value=(body, {})
            ):
                with self.assertRaisesRegex(
                    dropbox.DropboxOutputError, "OAuth response was invalid"
                ):
                    dropbox._access_token(cfg)

    def test_readback_mismatch_fails(self):
        payload = "expected"
        responses = [
            (json.dumps({"access_token": "short-lived-token"}).encode(), {}),
            (b'{"metadata":{}}', {}),
            (b'{"name":"task-3.md"}', {}),
            (b"different", {}),
        ]
        with self._env(), patch.object(dropbox, "_request", side_effect=responses):
            with self.assertRaisesRegex(dropbox.DropboxOutputError, "SHA-256 mismatch"):
                dropbox.upload_task_log("task-3", payload)

    def test_upload_rejects_invalid_timeout_before_network(self):
        invalid_timeouts = (0, -1, True, float("nan"), float("inf"), "20", 10**1000)
        with self._env(), patch.object(dropbox, "_request") as request:
            for timeout in invalid_timeouts:
                with self.subTest(timeout=timeout), self.assertRaisesRegex(
                    ValueError, "positive finite number"
                ):
                    dropbox.upload_task_log("task-timeout", "report", timeout=timeout)
        request.assert_not_called()

    def test_task_id_rejects_path_injection(self):
        with self._env(), patch.object(dropbox, "_request") as request:
            with self.assertRaises(ValueError):
                dropbox.upload_task_log("../other", "report")
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
