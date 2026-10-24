"""Regression tests for the strict GitHub mailbox task envelope contract."""
import json
import unittest

from emberlane.mailbox import _task_from_comment


class MailboxEnvelopeContractTests(unittest.TestCase):
    def test_marker_must_be_the_first_line(self):
        payload = {"kind": "run_tests", "payload": {"test_file": "test_mailbox.py"}}
        body = "EMBERLANE_TASK_JSON\n" + json.dumps(payload)
        self.assertEqual(_task_from_comment(body), payload)

    def test_session_prefix_before_marker_is_not_a_task(self):
        body = '1 | SESSION NOTE\n\nEMBERLANE_TASK_JSON\n{"kind":"run_tests","payload":{}}'
        self.assertIsNone(_task_from_comment(body))

    def test_marker_after_ordinary_prose_is_not_a_task(self):
        body = 'Please review this plan.\nEMBERLANE_TASK_JSON\n{"kind":"run_tests","payload":{}}'
        self.assertIsNone(_task_from_comment(body))


if __name__ == "__main__":
    unittest.main()
