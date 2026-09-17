# AUTOPILOT — System Health Supervisor

BASE_MAIN_SHA: 53fb84f06c98b72bcd52dd5c3567f2d5e9ab5f47
STATUS: ACTIVE
AUTOPILOT_AUTOMERGE: NO
PHYSICAL_PI5_VALIDATION: MANDATORY

## Objective
Add one read-only, bounded System Health surface that aggregates Ghostboard runtime/service readiness, STOP state, thermal/power telemetry when available, and existing doctor/hardware diagnostics for CLI and Control Center consumption.

## Existing durable work to preserve
An OFFLINE-PATCH implementation already exists in `/Ghostboard Autopilot/active`. It adds `runtime/system_health.py`, focused tests and schema documentation; focused tests reached 8/8 after repair. Builder must continue that accumulated implementation rather than restart or duplicate it.

## Real affected components
- `runtime/system_health.py` (existing offline implementation to apply/continue)
- existing `ghost-system` CLI dispatch in the runtime/tooling tree, adding `health [--json]`
- `runtime/control_center.py`, consuming structured health without parsing human CLI text
- `tests/test-system-health.py`
- `tests/test-pi5.py`
- `tests/test-control-center.py`
- `docs/autopilot/system-health-schema.md`

## Acceptance criteria
1. Health snapshot is read-only and reports STOP, runtime/service readiness, and optional Pi thermal/power/hardware diagnostics.
2. Individual probe failure/timeout degrades only that probe; external probes are bounded and do not accumulate unbounded refresh jobs.
3. `ghost-system health --json` exposes a stable documented schema.
4. Control Center displays overall health and actionable degraded reasons from structured data.
5. No probe enables camera/hand control, bypasses STOP/F8, changes security settings, escapes MCP workspace, or performs remediation/irreversible operations.
6. Existing Pi5, hand-tracking, MCP and Control Center regression suites remain green.

## Required tests
- `python3 tests/test-system-health.py`
- `python3 tests/test-pi5.py`
- `python3 tests/test-hand-tracking.py`
- `node tests/test-mcp-regressions.js`
- `node tests/test-mcp.js`
- `python3 tests/test-control-center.py`
- `bash -n` for any modified shell script

## Known review state
Resolved in the offline core: sequential-probe latency, missing-thermal semantics, and double STOP read. Still blocking: CLI integration, structured Control Center integration, and full repository regression execution.

## Risks
Blocking subprocesses or overlapping UI refreshes can harm Pi 5 responsiveness; optional hardware must not become a false fatal alarm; existing doctor logic must not be duplicated inconsistently.

## Rollback
Keep changes additive/read-only. Revert supervisor and its CLI/Control Center integration; existing `ghost-system doctor` and `ghost-hardware status` remain fallbacks. No configuration migration.

## Physical Pi 5 validation
Mandatory before hardware-complete merge: validate real thermal zones, `vcgencmd`, systemd service reporting, doctor/hardware output and Control Center responsiveness during failed/timed-out probes. x86 CI is not a substitute.

## Non-goals
No autonomous remediation/restarts, no privileged daemon, no remote camera/hand activation, no STOP/MCP/F8 changes, no Hailo claims.