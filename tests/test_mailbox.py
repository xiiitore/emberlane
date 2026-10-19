import json
import unittest

from emberlane.mailbox import MailboxError, _task_from_comment


class MailboxParsingTests(unittest.TestCase):
    def test_parses_exact_task_envelope(self):
        body = 'EMBERLANE_TASK_JSON\n' + json.dumps({
            "kind": "write_file",
            "payload": {"path": "src/demo.py", "content": "VALUE = 1\\n"},
        })
        self.assertEqual(_task_from_comment(body), {
            "kind": "write_file",
            "payload": {"path": "src/demo.py", "content": "VALUE = 1\\n"},
        })

    def test_ignores_non_task_comment(self):
        self.assertIsNone(_task_from_comment("ordinary discussion"))

    def test_rejects_extra_envelope_fields(self):
        with self.assertRaisesRegex(MailboxError, "exactly"):
            _task_from_comment('EMBERLANE_TASK_JSON\n{"kind":"run_tests","payload":{},"command":"id"}')

    def test_rejects_non_object_payload(self):
        with self.assertRaisesRegex(MailboxError, "payload must be an object"):
            _task_from_comment('EMBERLANE_TASK_JSON\n{"kind":"run_tests","payload":[]}')

    def test_rejects_invalid_json(self):
        with self.assertRaisesRegex(MailboxError, "invalid task JSON"):
            _task_from_comment("EMBERLANE_TASK_JSON\n{broken")


if __name__ == "__main__":
    unittest.main()
