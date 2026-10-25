# Emberlane task output

- Task ID: `d6c8ebd0-726c-4ef4-ab40-9e0bf4decca3`
- Kind: `run_tests`
- Status: `completed`
- Attempts: `1`
- Source comment: `6402399575`

## Result metadata

```json
{
  "timestamp_utc": "2026-10-25T20:12:22.399688+00:00",
  "source_comment_id": "6402399575",
  "task_id": "d6c8ebd0-726c-4ef4-ab40-9e0bf4decca3",
  "kind": "run_tests",
  "status": "completed",
  "attempts": 1,
  "last_error": null,
  "result": {
    "command": "python -m unittest discover -s tests -v",
    "returncode": 0,
    "passed": true,
    "output": "[FULL OUTPUT IN SECTION: result.output]"
  }
}
```

## Full output: `result.output`

~~~text
test_probe_agy (test_agy_probe.AgyProbeTests.test_probe_agy) ... skipped 'set EMBERLANE_RUN_AGY_PROBE=1 to run the environment-specific agy probe'
test_experimental_id_does_not_call_meta_planner (test_autonomous_loop.AutonomousMetaAdapterTests.test_experimental_id_does_not_call_meta_planner) ... 2026-10-25T20:11:47Z NON_META_RESULT id=EXP-QUEUE-01 status=KILL; meta planner not called
ok
test_real_meta_id_is_recorded (test_autonomous_loop.AutonomousMetaAdapterTests.test_real_meta_id_is_recorded) ... ok
test_stale_meta_result_does_not_mutate_active_task (test_autonomous_loop.AutonomousMetaAdapterTests.test_stale_meta_result_does_not_mutate_active_task) ... 2026-10-25T20:11:47Z META_RESULT_SKIPPED stale or mismatched result; planner state unchanged
ok
test_unknown_meta_namespace_is_rejected (test_autonomous_loop.AutonomousMetaAdapterTests.test_unknown_meta_namespace_is_rejected) ... ok
test_supervisor_script_has_valid_bash_syntax (test_codex_autopilot_supervisor.CodexAutopilotSupervisorTests.test_supervisor_script_has_valid_bash_syntax) ... ok
test_usage_limit_is_terminal_before_generic_failure_counter (test_codex_autopilot_supervisor.CodexAutopilotSupervisorTests.test_usage_limit_is_terminal_before_generic_failure_counter) ... ok
test_usage_limit_stops_supervisor_without_three_retries (test_codex_autopilot_supervisor.CodexAutopilotSupervisorTests.test_usage_limit_stops_supervisor_without_three_retries) ... ok
test_captures_output_from_pipe_within_configured_limit (test_codex_backend.CodexProposalTests.test_captures_output_from_pipe_within_configured_limit) ... ok
test_fixed_command_and_no_inherited_secret_environment (test_codex_backend.CodexProposalTests.test_fixed_command_and_no_inherited_secret_environment) ... ok
test_output_limit_is_enforced_while_streaming (test_codex_backend.CodexProposalTests.test_output_limit_is_enforced_while_streaming) ... ok
test_persistent_pause_prevents_subprocess (test_codex_backend.CodexProposalTests.test_persistent_pause_prevents_subprocess) ... ok
test_proposes_patch_only_from_temp_copy (test_codex_backend.CodexProposalTests.test_proposes_patch_only_from_temp_copy) ... ok
test_redacts_credentials_from_captured_output (test_codex_backend.CodexProposalTests.test_redacts_credentials_from_captured_output) ... ok
test_rejects_binary_file_changes_instead_of_returning_lossy_patch (test_codex_backend.CodexProposalTests.test_rejects_binary_file_changes_instead_of_returning_lossy_patch) ... ok
test_rejects_boolean_numeric_limit_before_queueing (test_codex_backend.CodexProposalTests.test_rejects_boolean_numeric_limit_before_queueing) ... ok
test_rejects_invalid_payload_before_queueing (test_codex_backend.CodexProposalTests.test_rejects_invalid_payload_before_queueing) ... ok
test_rejects_oversized_changed_file_before_loading_its_contents (test_codex_backend.CodexProposalTests.test_rejects_oversized_changed_file_before_loading_its_contents) ... ok
test_rejects_patch_that_exceeds_configured_byte_limit (test_codex_backend.CodexProposalTests.test_rejects_patch_that_exceeds_configured_byte_limit) ... ok
test_rejects_protected_snapshot_paths_before_queueing (test_codex_backend.CodexProposalTests.test_rejects_protected_snapshot_paths_before_queueing) ... ok
test_scans_large_unchanged_files_without_reading_them_into_memory (test_codex_backend.CodexProposalTests.test_scans_large_unchanged_files_without_reading_them_into_memory) ... ok
test_snapshot_excludes_common_ssh_private_key_names_case_insensitively (test_codex_backend.CodexProposalTests.test_snapshot_excludes_common_ssh_private_key_names_case_insensitively) ... ok
test_snapshot_limit_prevents_codex_launch (test_codex_backend.CodexProposalTests.test_snapshot_limit_prevents_codex_launch) ... ok
test_uses_explicit_tmpdir_and_proposal_does_not_modify_source (test_codex_backend.CodexProposalTests.test_uses_explicit_tmpdir_and_proposal_does_not_modify_source) ... ok
test_config_requires_owner_only_posix_permissions (test_dropbox_output.DropboxOutputTests.test_config_requires_owner_only_posix_permissions) ... ok
test_http_error_does_not_expose_response_body (test_dropbox_output.DropboxOutputTests.test_http_error_does_not_expose_response_body) ... ok
test_incomplete_response_is_sanitized (test_dropbox_output.DropboxOutputTests.test_incomplete_response_is_sanitized) ... ok
test_missing_auth_is_blocked_without_network (test_dropbox_output.DropboxOutputTests.test_missing_auth_is_blocked_without_network) ... ok
test_oauth_response_must_be_valid_json_object (test_dropbox_output.DropboxOutputTests.test_oauth_response_must_be_valid_json_object) ... ok
test_readback_mismatch_fails (test_dropbox_output.DropboxOutputTests.test_readback_mismatch_fails) ... ok
test_relative_configured_root_becomes_absolute_dropbox_path (test_dropbox_output.DropboxOutputTests.test_relative_configured_root_becomes_absolute_dropbox_path) ... ok
test_request_bounds_response_read (test_dropbox_output.DropboxOutputTests.test_request_bounds_response_read) ... ok
test_task_id_rejects_path_injection (test_dropbox_output.DropboxOutputTests.test_task_id_rejects_path_injection) ... ok
test_upload_and_readback_verified (test_dropbox_output.DropboxOutputTests.test_upload_and_readback_verified) ... ok
test_upload_rejects_invalid_timeout_before_network (test_dropbox_output.DropboxOutputTests.test_upload_rejects_invalid_timeout_before_network) ... ok
test_upload_rejects_oversized_log_before_network (test_dropbox_output.DropboxOutputTests.test_upload_rejects_oversized_log_before_network) ... ok
test_path_filter_is_applied_to_metadata (test_git_diff.GitDiffTests.test_path_filter_is_applied_to_metadata) ... ok
test_reports_changed_file_and_stat_without_source_patch (test_git_diff.GitDiffTests.test_reports_changed_file_and_stat_without_source_patch) ... ok
test_reports_staged_changes_separately_from_unstaged_changes (test_git_diff.GitDiffTests.test_reports_staged_changes_separately_from_unstaged_changes) ... ok
test_reports_untracked_files_without_reading_their_contents (test_git_diff.GitDiffTests.test_reports_untracked_files_without_reading_their_contents) ... ok
test_auto_context_size_passes_edit_validation (test_local_model_backend.LocalModelProposalTests.test_auto_context_size_passes_edit_validation) ... ok
test_boolean_numeric_limits_are_rejected_before_queueing (test_local_model_backend.LocalModelProposalTests.test_boolean_numeric_limits_are_rejected_before_queueing) ... ok
test_edit_applies_only_after_targeted_tests_pass (test_local_model_backend.LocalModelProposalTests.test_edit_applies_only_after_targeted_tests_pass) ... ok
test_edit_refuses_source_changed_since_proposal (test_local_model_backend.LocalModelProposalTests.test_edit_refuses_source_changed_since_proposal) ... ok
test_enforces_streamed_output_limit (test_local_model_backend.LocalModelProposalTests.test_enforces_streamed_output_limit) ... ok
test_failed_tests_leave_working_tree_unchanged (test_local_model_backend.LocalModelProposalTests.test_failed_tests_leave_working_tree_unchanged) ... ok
test_fixed_cli_and_filtered_environment (test_local_model_backend.LocalModelProposalTests.test_fixed_cli_and_filtered_environment) ... ok
test_invalid_model_json_is_rejected (test_local_model_backend.LocalModelProposalTests.test_invalid_model_json_is_rejected) ... ok
test_missing_model_configuration_does_not_launch_process (test_local_model_backend.LocalModelProposalTests.test_missing_model_configuration_does_not_launch_process) ... ok
test_missing_model_file_is_reported (test_local_model_backend.LocalModelProposalTests.test_missing_model_file_is_reported) ... ok
test_pause_created_during_inference_discards_proposal (test_local_model_backend.LocalModelProposalTests.test_pause_created_during_inference_discards_proposal) ... ok
test_persistent_pause_prevents_model_launch (test_local_model_backend.LocalModelProposalTests.test_persistent_pause_prevents_model_launch) ... ok
test_proposes_patch_without_modifying_source (test_local_model_backend.LocalModelProposalTests.test_proposes_patch_without_modifying_source) ... ok
test_rejects_credential_like_source_without_launching_model (test_local_model_backend.LocalModelProposalTests.test_rejects_credential_like_source_without_launching_model) ... ok
test_rejects_model_output_outside_allowlist (test_local_model_backend.LocalModelProposalTests.test_rejects_model_output_outside_allowlist) ... ok
test_rejects_unsafe_path_before_model_launch (test_local_model_backend.LocalModelProposalTests.test_rejects_unsafe_path_before_model_launch) ... ok
test_supports_new_allowlisted_file_and_marks_addition (test_local_model_backend.LocalModelProposalTests.test_supports_new_allowlisted_file_and_marks_addition) ... ok
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
test_existing_task_log_is_idempotent (test_mailbox_logs.TaskLogPublishingTests.test_existing_task_log_is_idempotent) ... ok
test_handoff_includes_small_sanitized_output_inline (test_mailbox_logs.TaskLogPublishingTests.test_handoff_includes_small_sanitized_output_inline) ... ok
test_handoff_publication_failure_keeps_task_active (test_mailbox_logs.TaskLogPublishingTests.test_handoff_publication_failure_keeps_task_active) ... ok
test_handoff_uses_full_log_for_output_over_inline_limit (test_mailbox_logs.TaskLogPublishingTests.test_handoff_uses_full_log_for_output_over_inline_limit) ... ok
test_local_task_log_does_not_follow_temporary_symlink (test_mailbox_logs.TaskLogPublishingTests.test_local_task_log_does_not_follow_temporary_symlink) ... ok
test_local_task_log_rejects_symlinked_log_directory (test_mailbox_logs.TaskLogPublishingTests.test_local_task_log_rejects_symlinked_log_directory) ... ok
test_malformed_readback_response_raises_mailbox_error (test_mailbox_logs.TaskLogPublishingTests.test_malformed_readback_response_raises_mailbox_error) ... ok
test_publishes_full_output_redacts_secrets_and_omits_file_content (test_mailbox_logs.TaskLogPublishingTests.test_publishes_full_output_redacts_secrets_and_omits_file_content) ... ok
test_readback_accepts_wrapped_base64_content (test_mailbox_logs.TaskLogPublishingTests.test_readback_accepts_wrapped_base64_content) ... ok
test_readback_failure_after_put_raises_mailbox_error (test_mailbox_logs.TaskLogPublishingTests.test_readback_failure_after_put_raises_mailbox_error) ... ok
test_rejects_oversized_log_before_redacting_or_assembling (test_mailbox_logs.TaskLogPublishingTests.test_rejects_oversized_log_before_redacting_or_assembling) ... ok
test_shared_redactor_removes_tokens_authorization_and_secret_values (test_mailbox_logs.TaskLogPublishingTests.test_shared_redactor_removes_tokens_authorization_and_secret_values) ... ok
test_task_log_publication_failure_keeps_task_active (test_mailbox_logs.TaskLogPublishingTests.test_task_log_publication_failure_keeps_task_active) ... ok
test_terminal_result_redacts_sensitive_last_error_before_comment (test_mailbox_logs.TaskLogPublishingTests.test_terminal_result_redacts_sensitive_last_error_before_comment) ... ok
test_backlog_exhaustion (test_meta_planner.MetaPlannerTests.test_backlog_exhaustion) ... ok
test_blocked_is_terminal_for_task (test_meta_planner.MetaPlannerTests.test_blocked_is_terminal_for_task) ... ok
test_first_task_is_persisted (test_meta_planner.MetaPlannerTests.test_first_task_is_persisted) ... ok
test_kill_is_terminal_for_task (test_meta_planner.MetaPlannerTests.test_kill_is_terminal_for_task) ... ok
test_next_resumes_active_task (test_meta_planner.MetaPlannerTests.test_next_resumes_active_task) ... ok
test_pass_advances_backlog (test_meta_planner.MetaPlannerTests.test_pass_advances_backlog) ... ok
test_rejects_insufficient_evidence (test_meta_planner.MetaPlannerTests.test_rejects_insufficient_evidence) ... ok
test_rejects_wrong_task_id (test_meta_planner.MetaPlannerTests.test_rejects_wrong_task_id) ... ok
test_dangling_pause_marker_symlink_still_pauses (test_pause.PauseTests.test_dangling_pause_marker_symlink_still_pauses) ... ok
test_pause_marker_persists_until_resume (test_pause.PauseTests.test_pause_marker_persists_until_resume) ... ok
test_paused_mailbox_does_not_fetch_comments (test_pause.PauseTests.test_paused_mailbox_does_not_fetch_comments) ... ok
test_paused_worker_keeps_queued_task_pending (test_pause.PauseTests.test_paused_worker_keeps_queued_task_pending) ... ok
test_set_paused_does_not_write_through_temporary_symlink (test_pause.PauseTests.test_set_paused_does_not_write_through_temporary_symlink) ... ok
test_set_paused_rejects_non_boolean_values_without_creating_marker (test_pause.PauseTests.test_set_paused_rejects_non_boolean_values_without_creating_marker) ... ok
test_completed_local_model_edit_failure_requires_review (test_planner.PlannerTests.test_completed_local_model_edit_failure_requires_review) ... ok
test_empty_queue_recommends_explicit_task (test_planner.PlannerTests.test_empty_queue_recommends_explicit_task) ... ok
test_failed_tasks_are_reported_not_retried (test_planner.PlannerTests.test_failed_tasks_are_reported_not_retried) ... ok
test_missing_queue_is_reported (test_planner.PlannerTests.test_missing_queue_is_reported) ... ok
test_pause_takes_precedence (test_planner.PlannerTests.test_pause_takes_precedence) ... ok
test_pending_task_is_reported_without_execution (test_planner.PlannerTests.test_pending_task_is_reported_without_execution) ... ok
test_running_tasks_are_flagged_for_review (test_planner.PlannerTests.test_running_tasks_are_flagged_for_review) ... ok
test_verified_local_model_edit_does_not_require_review (test_planner.PlannerTests.test_verified_local_model_edit_does_not_require_review) ... ok
test_concurrent_idempotent_submits_create_one_task (test_queue.TaskQueueTests.test_concurrent_idempotent_submits_create_one_task) ... ok
test_concurrent_runners_execute_only_one_handler_at_a_time (test_queue.TaskQueueTests.test_concurrent_runners_execute_only_one_handler_at_a_time) ... ok
test_cross_process_idempotent_submits_create_one_task (test_queue.TaskQueueTests.test_cross_process_idempotent_submits_create_one_task) ... {
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-002",
    "slug": "rollback-integrity",
    "goal": "Verify repair rollback restores exact original bytes."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-003",
    "slug": "planner-liveness",
    "goal": "Ensure planner discovers actionable work after inbox exhaustion."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-004",
    "slug": "independent-acceptance",
    "goal": "Require evidence-based acceptance checks for completed tasks."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-005",
    "slug": "recovery-idempotency",
    "goal": "Verify task recovery does not duplicate side effects."
  }
}
{
  "status": "BACKLOG_EXHAUSTED",
  "remaining": 0
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-002",
    "slug": "rollback-integrity",
    "goal": "Verify repair rollback restores exact original bytes."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-002",
    "slug": "rollback-integrity",
    "goal": "Verify repair rollback restores exact original bytes."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "goal": "Prevent false-positive repair test results.",
    "id": "META-001",
    "slug": "repair-test-validity"
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-002",
    "slug": "rollback-integrity",
    "goal": "Verify repair rollback restores exact original bytes."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
{
  "status": "ACTIVE",
  "task": {
    "id": "META-001",
    "slug": "repair-test-validity",
    "goal": "Prevent false-positive repair test results."
  }
}
ok
test_cross_process_runners_serialize_task_handlers (test_queue.TaskQueueTests.test_cross_process_runners_serialize_task_handlers) ... ok
test_duplicate_task_ids_are_rejected_on_load (test_queue.TaskQueueTests.test_duplicate_task_ids_are_rejected_on_load) ... ok
test_failure_retries_then_fails (test_queue.TaskQueueTests.test_failure_retries_then_fails) ... ok
test_idempotency_key_cannot_be_reused_for_different_task (test_queue.TaskQueueTests.test_idempotency_key_cannot_be_reused_for_different_task) ... ok
test_idempotency_survives_restart (test_queue.TaskQueueTests.test_idempotency_survives_restart) ... ok
test_idempotent_submit_returns_existing_task (test_queue.TaskQueueTests.test_idempotent_submit_returns_existing_task) ... ok
test_infinite_results_are_rejected (test_queue.TaskQueueTests.test_infinite_results_are_rejected) ... ok
test_json_result_survives_restart (test_queue.TaskQueueTests.test_json_result_survives_restart) ... ok
test_long_lived_queue_sees_external_submission (test_queue.TaskQueueTests.test_long_lived_queue_sees_external_submission) ... ok
test_malformed_task_record_reports_its_list_index (test_queue.TaskQueueTests.test_malformed_task_record_reports_its_list_index) ... ok
test_max_attempts_must_be_a_positive_integer (test_queue.TaskQueueTests.test_max_attempts_must_be_a_positive_integer) ... ok
test_nested_infinite_results_are_rejected (test_queue.TaskQueueTests.test_nested_infinite_results_are_rejected) ... ok
test_nested_non_finite_result_is_rejected (test_queue.TaskQueueTests.test_nested_non_finite_result_is_rejected) ... ok
test_non_finite_result_is_rejected (test_queue.TaskQueueTests.test_non_finite_result_is_rejected) ... ok
test_none_result_survives_restart_as_completed (test_queue.TaskQueueTests.test_none_result_survives_restart_as_completed) ... ok
test_registered_handler_completes_task (test_queue.TaskQueueTests.test_registered_handler_completes_task) ... ok
test_rejects_bad_arguments (test_queue.TaskQueueTests.test_rejects_bad_arguments) ... ok
test_rejects_empty_task_id (test_queue.TaskQueueTests.test_rejects_empty_task_id) ... ok
test_rejects_invalid_task_idempotency_key (test_queue.TaskQueueTests.test_rejects_invalid_task_idempotency_key) ... ok
test_rejects_invalid_task_kind_and_payload (test_queue.TaskQueueTests.test_rejects_invalid_task_kind_and_payload) ... ok
test_rejects_malformed_json_state_file (test_queue.TaskQueueTests.test_rejects_malformed_json_state_file) ... ok
test_rejects_malformed_task_record (test_queue.TaskQueueTests.test_rejects_malformed_task_record) ... ok
test_rejects_non_finite_payload_values_without_adding_task (test_queue.TaskQueueTests.test_rejects_non_finite_payload_values_without_adding_task) ... ok
test_rejects_non_finite_values_in_loaded_payload (test_queue.TaskQueueTests.test_rejects_non_finite_values_in_loaded_payload) ... ok
test_rejects_non_finite_values_in_loaded_result (test_queue.TaskQueueTests.test_rejects_non_finite_values_in_loaded_result) ... ok
test_rejects_non_integer_task_attempts (test_queue.TaskQueueTests.test_rejects_non_integer_task_attempts) ... ok
test_rejects_non_list_state_file (test_queue.TaskQueueTests.test_rejects_non_list_state_file) ... ok
test_rejects_non_numeric_task_timestamp (test_queue.TaskQueueTests.test_rejects_non_numeric_task_timestamp) ... ok
test_rejects_non_object_task_record (test_queue.TaskQueueTests.test_rejects_non_object_task_record) ... ok
test_rejects_non_string_task_last_error (test_queue.TaskQueueTests.test_rejects_non_string_task_last_error) ... ok
test_rejects_nonstandard_json_constants (test_queue.TaskQueueTests.test_rejects_nonstandard_json_constants) ... ok
test_rejects_unknown_task_status (test_queue.TaskQueueTests.test_rejects_unknown_task_status) ... ok
test_reports_invalid_utf8_state_file (test_queue.TaskQueueTests.test_reports_invalid_utf8_state_file) ... ok
test_reports_unreadable_state_file (test_queue.TaskQueueTests.test_reports_unreadable_state_file) ... ok
test_returned_tasks_cannot_mutate_queue_state (test_queue.TaskQueueTests.test_returned_tasks_cannot_mutate_queue_state) ... ok
test_running_task_is_recovered_after_restart (test_queue.TaskQueueTests.test_running_task_is_recovered_after_restart) ... ok
test_submit_detaches_payload_from_caller (test_queue.TaskQueueTests.test_submit_detaches_payload_from_caller) ... ok
test_submit_during_handler_preserves_running_task_and_new_task (test_queue.TaskQueueTests.test_submit_during_handler_preserves_running_task_and_new_task) ... ok
test_submit_survives_restart (test_queue.TaskQueueTests.test_submit_survives_restart) ... ok
test_unknown_handler_fails_closed (test_queue.TaskQueueTests.test_unknown_handler_fails_closed) ... ok
test_mismatch_leaves_file_unchanged (test_replace_text.ReplaceTextTests.test_mismatch_leaves_file_unchanged) ... ok
test_oversized_result_leaves_file_unchanged (test_replace_text.ReplaceTextTests.test_oversized_result_leaves_file_unchanged) ... ok
test_rejects_invalid_expected_count_before_queueing (test_replace_text.ReplaceTextTests.test_rejects_invalid_expected_count_before_queueing) ... ok
test_rejects_oversized_replacement_before_queueing (test_replace_text.ReplaceTextTests.test_rejects_oversized_replacement_before_queueing) ... ok
test_rejects_protected_path_before_queueing (test_replace_text.ReplaceTextTests.test_rejects_protected_path_before_queueing) ... ok
test_replaces_multiple_occurrences_only_when_count_matches (test_replace_text.ReplaceTextTests.test_replaces_multiple_occurrences_only_when_count_matches) ... ok
test_replaces_one_exact_occurrence_through_queue (test_replace_text.ReplaceTextTests.test_replaces_one_exact_occurrence_through_queue) ... ok
test_stale_replace_text_fails_without_retries (test_replace_text.ReplaceTextTests.test_stale_replace_text_fails_without_retries) ... ok
test_blocks_credential_paths_before_enqueue (test_worker.LocalWorkerTests.test_blocks_credential_paths_before_enqueue) ... ok
test_blocks_git_metadata_before_enqueue (test_worker.LocalWorkerTests.test_blocks_git_metadata_before_enqueue) ... ok
test_diagnostics_model_smoke_checks_model_with_bounded_commands (test_worker.LocalWorkerTests.test_diagnostics_model_smoke_checks_model_with_bounded_commands) ... ok
test_diagnostics_returns_runtime_and_git_information (test_worker.LocalWorkerTests.test_diagnostics_returns_runtime_and_git_information) ... ok
test_git_stash_inspect_uses_fixed_read_only_commands (test_worker.LocalWorkerTests.test_git_stash_inspect_uses_fixed_read_only_commands) ... ok
test_git_status_uses_only_fixed_read_only_commands (test_worker.LocalWorkerTests.test_git_status_uses_only_fixed_read_only_commands) ... ok
test_git_sync_matching_worktree_rejects_content_not_equal_to_target (test_worker.LocalWorkerTests.test_git_sync_matching_worktree_rejects_content_not_equal_to_target) ... ok
test_git_sync_matching_worktree_stashes_verified_duplicate_then_fast_forwards (test_worker.LocalWorkerTests.test_git_sync_matching_worktree_stashes_verified_duplicate_then_fast_forwards) ... ok
test_git_sync_refuses_dirty_worktree_before_fetch (test_worker.LocalWorkerTests.test_git_sync_refuses_dirty_worktree_before_fetch) ... ok
test_git_sync_refuses_matching_worktree_mode_for_staged_or_untracked_changes (test_worker.LocalWorkerTests.test_git_sync_refuses_matching_worktree_mode_for_staged_or_untracked_changes) ... ok
test_git_sync_rejects_invalid_expected_branch_before_enqueue (test_worker.LocalWorkerTests.test_git_sync_rejects_invalid_expected_branch_before_enqueue) ... ok
test_git_sync_rejects_postflight_dirty_worktree (test_worker.LocalWorkerTests.test_git_sync_rejects_postflight_dirty_worktree) ... ok
test_git_sync_rejects_postflight_head_mismatch (test_worker.LocalWorkerTests.test_git_sync_rejects_postflight_head_mismatch) ... ok
test_git_sync_requires_expected_branch_to_match (test_worker.LocalWorkerTests.test_git_sync_requires_expected_branch_to_match) ... ok
test_git_sync_uses_fixed_fetch_and_fast_forward_commands (test_worker.LocalWorkerTests.test_git_sync_uses_fixed_fetch_and_fast_forward_commands) ... ok
test_read_file_content_requires_explicit_opt_in (test_worker.LocalWorkerTests.test_read_file_content_requires_explicit_opt_in) ... ok
test_read_file_preview_omits_large_source_explicitly (test_worker.LocalWorkerTests.test_read_file_preview_omits_large_source_explicitly) ... ok
test_read_file_rejects_invalid_excerpt_ranges_before_queueing (test_worker.LocalWorkerTests.test_read_file_rejects_invalid_excerpt_ranges_before_queueing) ... ok
test_read_file_rejects_non_boolean_content_opt_in (test_worker.LocalWorkerTests.test_read_file_rejects_non_boolean_content_opt_in) ... ok
test_read_file_returns_bounded_line_numbered_excerpt (test_worker.LocalWorkerTests.test_read_file_returns_bounded_line_numbered_excerpt) ... ok
test_run_tests_can_target_one_test_file (test_worker.LocalWorkerTests.test_run_tests_can_target_one_test_file) ... ok
test_run_tests_rejects_symlink_target (test_worker.LocalWorkerTests.test_run_tests_rejects_symlink_target) ... ok
test_run_tests_rejects_symlinked_tests_directory (test_worker.LocalWorkerTests.test_run_tests_rejects_symlinked_tests_directory) ... ok
test_run_tests_rejects_unsafe_test_file_before_queueing (test_worker.LocalWorkerTests.test_run_tests_rejects_unsafe_test_file_before_queueing) ... ok
test_run_tests_reports_missing_target_as_failure (test_worker.LocalWorkerTests.test_run_tests_reports_missing_target_as_failure) ... ok
test_run_tests_uses_fixed_command (test_worker.LocalWorkerTests.test_run_tests_uses_fixed_command) ... ok
test_unknown_task_kind_rejected_before_enqueue (test_worker.LocalWorkerTests.test_unknown_task_kind_rejected_before_enqueue) ... ok
test_write_read_and_result_persists (test_worker.LocalWorkerTests.test_write_read_and_result_persists) ... ok
test_atomic_write_replaces_existing_file (test_workspace.WorkspaceTests.test_atomic_write_replaces_existing_file) ... ok
test_enforces_file_size_limit (test_workspace.WorkspaceTests.test_enforces_file_size_limit) ... ok
test_file_size_limit_accepts_exact_utf8_byte_boundary (test_workspace.WorkspaceTests.test_file_size_limit_accepts_exact_utf8_byte_boundary) ... ok
test_list_excludes_protected_runtime_and_git_paths (test_workspace.WorkspaceTests.test_list_excludes_protected_runtime_and_git_paths) ... ok
test_list_files_does_not_follow_symlinked_directories (test_workspace.WorkspaceTests.test_list_files_does_not_follow_symlinked_directories) ... ok
test_max_file_bytes_must_be_a_positive_integer (test_workspace.WorkspaceTests.test_max_file_bytes_must_be_a_positive_integer) ... ok
test_rejects_absolute_path (test_workspace.WorkspaceTests.test_rejects_absolute_path) ... ok
test_rejects_noncanonical_relative_paths (test_workspace.WorkspaceTests.test_rejects_noncanonical_relative_paths) ... ok
test_rejects_parent_traversal (test_workspace.WorkspaceTests.test_rejects_parent_traversal) ... ok
test_rejects_symlink (test_workspace.WorkspaceTests.test_rejects_symlink) ... ok
test_validate_write_path_rejects_nul_and_backslash (test_workspace.WorkspaceTests.test_validate_write_path_rejects_nul_and_backslash) ... ok
test_write_read_and_list (test_workspace.WorkspaceTests.test_write_read_and_list) ... ok
test_blocks_credential_directories_and_key_files (test_workspace_security.WorkspacePathSecurityTests.test_blocks_credential_directories_and_key_files) ... ok
test_rejects_absolute_paths_for_read_and_write (test_workspace_security.WorkspacePathSecurityTests.test_rejects_absolute_paths_for_read_and_write) ... ok
test_rejects_parent_traversal_for_read_and_write (test_workspace_security.WorkspacePathSecurityTests.test_rejects_parent_traversal_for_read_and_write) ... ok
test_rejects_symlink_to_outside_for_read_and_write (test_workspace_security.WorkspacePathSecurityTests.test_rejects_symlink_to_outside_for_read_and_write) ... ok
test_rejects_symlinked_parent_directory (test_workspace_security.WorkspacePathSecurityTests.test_rejects_symlinked_parent_directory) ... ok
test_duplicate_paths_rejected_before_queueing (test_write_files.WriteFilesTests.test_duplicate_paths_rejected_before_queueing) ... ok
test_invalid_entry_rejected_before_queueing (test_write_files.WriteFilesTests.test_invalid_entry_rejected_before_queueing) ... ok
test_invalid_later_target_does_not_create_earlier_directories (test_write_files.WriteFilesTests.test_invalid_later_target_does_not_create_earlier_directories) ... ok
test_oversized_file_rejected_before_queueing (test_write_files.WriteFilesTests.test_oversized_file_rejected_before_queueing) ... ok
test_protected_paths_rejected (test_write_files.WriteFilesTests.test_protected_paths_rejected) ... ok
test_writes_multiple_files (test_write_files.WriteFilesTests.test_writes_multiple_files) ... ok

----------------------------------------------------------------------
Ran 221 tests in 35.101s

OK (skipped=1)

~~~
