# Ghostboard Autopilot persistent state

Live state is maintained by gh-aw repo-memory on branch `memory/ghostboard-autopilot`, under `ghostboard/state.json`.

Recommended shape:

```json
{
  "iteration_id": "2026-09-16-system-health",
  "status": "IMPLEMENTING",
  "base_sha": "<real-main-sha>",
  "active_pr": 12,
  "active_branch": "autopilot/system-health",
  "objective": "One concrete scoped objective",
  "repair_count": 0,
  "last_tests": {
    "python3 tests/test-pi5.py": "PASS",
    "python3 tests/test-hand-tracking.py": "PASS"
  },
  "physical_pi5_validation": "RECOMMENDED",
  "next_priority": "Exact next priority",
  "last_run": "2026-09-16T09:00:00Z"
}
```

Allowed status values:

- `PLANNING`
- `IMPLEMENTING`
- `TESTING`
- `REVIEWING`
- `REPAIRING`
- `CI`
- `READY_TO_MERGE`
- `DONE`
- `BLOCKED`

Physical Pi 5 validation values:

- `MANDATORY`
- `RECOMMENDED`
- `NONE`

Never persist invented GitHub identifiers, test results, or hardware evidence.
