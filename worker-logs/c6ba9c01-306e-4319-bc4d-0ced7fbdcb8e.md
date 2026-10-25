# Emberlane task output

- Task ID: `c6ba9c01-306e-4319-bc4d-0ced7fbdcb8e`
- Kind: `run_tests`
- Status: `completed`
- Attempts: `1`
- Source comment: `6401361783`

## Result metadata

```json
{
  "timestamp_utc": "2026-10-25T18:20:31.333871+00:00",
  "source_comment_id": "6401361783",
  "task_id": "c6ba9c01-306e-4319-bc4d-0ced7fbdcb8e",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "last_error": null,
  "result": {
    "command": "python -m unittest discover -s tests -p test_mailbox.py -v",
    "returncode": 0,
    "passed": true,
    "output": "[FULL OUTPUT IN SECTION: result.output]"
  }
}
```

## Full output: `result.output`

~~~text
test_permission_403_fails_without_retry (test_mailbox.GitHubRetryTests.test_permission_403_fails_without_retry) ... ok
test_rate_limit_403_retries_then_succeeds (test_mailbox.GitHubRetryTests.test_rate_limit_403_retries_then_succeeds) ... ok
test_retry_after_header_is_respected (test_mailbox.GitHubRetryTests.test_retry_after_header_is_respected) ... ok
test_retry_after_is_bounded (test_mailbox.GitHubRetryTests.test_retry_after_is_bounded) ... ok
test_retry_attempts_are_bounded (test_mailbox.GitHubRetryTests.test_retry_attempts_are_bounded) ... ok
test_empty_state_preserves_full_history_recovery (test_mailbox.MailboxCommentFetchTests.test_empty_state_preserves_full_history_recovery) ... ok
test_fetches_and_sorts_all_paginated_comments (test_mailbox.MailboxCommentFetchTests.test_fetches_and_sorts_all_paginated_comments) ... ok
test_recovers_crash_after_queue_submit_without_duplicate_task (test_mailbox.MailboxIdempotencyTests.test_recovers_crash_after_queue_submit_without_duplicate_task) ... ok
test_ignores_non_task_comment (test_mailbox.MailboxParsingTests.test_ignores_non_task_comment) ... ok
test_parses_exact_task_envelope (test_mailbox.MailboxParsingTests.test_parses_exact_task_envelope) ... ok
test_rejects_deeply_nested_json_without_leaking_recursion_error (test_mailbox.MailboxParsingTests.test_rejects_deeply_nested_json_without_leaking_recursion_error) ... ok
test_rejects_extra_envelope_fields (test_mailbox.MailboxParsingTests.test_rejects_extra_envelope_fields) ... ok
test_rejects_invalid_json (test_mailbox.MailboxParsingTests.test_rejects_invalid_json) ... ok
test_rejects_non_object_payload (test_mailbox.MailboxParsingTests.test_rejects_non_object_payload) ... ok
test_rejects_nonstandard_json_constants (test_mailbox.MailboxParsingTests.test_rejects_nonstandard_json_constants) ... ok
test_rejects_oversized_task_comment_before_json_parsing (test_mailbox.MailboxParsingTests.test_rejects_oversized_task_comment_before_json_parsing) ... ok
test_rejects_task_payload_beyond_nesting_limit (test_mailbox.MailboxParsingTests.test_rejects_task_payload_beyond_nesting_limit) ... ok
test_invalid_task_kind_reply_uses_real_newline (test_mailbox.MailboxRejectionTests.test_invalid_task_kind_reply_uses_real_newline) ... ok
test_requested_read_file_source_is_chunked_and_redacted (test_mailbox.MailboxSourceChunkTests.test_requested_read_file_source_is_chunked_and_redacted) ... ok
test_deduplicates_handled_comment_ids_in_order (test_mailbox.MailboxStateTests.test_deduplicates_handled_comment_ids_in_order) ... ok
test_malformed_json_state_raises_mailbox_error (test_mailbox.MailboxStateTests.test_malformed_json_state_raises_mailbox_error) ... ok
test_rejects_malformed_active_task_id (test_mailbox.MailboxStateTests.test_rejects_malformed_active_task_id) ... ok
test_rejects_non_string_state_entries (test_mailbox.MailboxStateTests.test_rejects_non_string_state_entries) ... ok
test_state_save_preserves_previous_file_if_replace_fails (test_mailbox.MailboxStateTests.test_state_save_preserves_previous_file_if_replace_fails) ... ok
test_state_save_round_trips_to_a_fresh_mailbox (test_mailbox.MailboxStateTests.test_state_save_round_trips_to_a_fresh_mailbox) ... ok
test_existing_task_log_with_same_id_but_different_content_is_rejected (test_mailbox.TaskLogPublicationTests.test_existing_task_log_with_same_id_but_different_content_is_rejected) ... ok

----------------------------------------------------------------------
Ran 26 tests in 2.658s

OK

~~~
