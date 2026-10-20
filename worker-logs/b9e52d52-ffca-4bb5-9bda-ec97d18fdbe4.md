# Emberlane task output

- Task ID: `b9e52d52-ffca-4bb5-9bda-ec97d18fdbe4`
- Kind: `git_sync`
- Status: `completed`
- Attempts: `1`
- Source comment: `6290084053`

## Result metadata

```json
{
  "timestamp_utc": "2026-10-20T11:44:19.783815+00:00",
  "source_comment_id": "6290084053",
  "task_id": "b9e52d52-ffca-4bb5-9bda-ec97d18fdbe4",
  "kind": "git_sync",
  "status": "completed",
  "attempts": 1,
  "last_error": null,
  "result": {
    "synced": false,
    "stage": "matching_worktree_mismatch",
    "path": "emberlane/worker.py",
    "comparison": {
      "command": [
        "git",
        "diff",
        "--quiet",
        "FETCH_HEAD",
        "--",
        "emberlane/worker.py"
      ],
      "returncode": 1,
      "output": "[FULL OUTPUT IN SECTION: result.comparison.output]"
    }
  }
}
```

## Full output: `result.comparison.output`

~~~text

~~~
