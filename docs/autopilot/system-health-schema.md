# System Health schema

`ghost-system health --json` returns schema version `1` with `overall` (`ok`, `partial`, or `degraded`), `agent_stopped`, `degraded`, and a `probes` object. Probes expose `status`, `ok`, `available`, and optional structured data/reason fields. Optional unavailable Pi telemetry is not fatal. The supervisor is read-only and never enables camera/hand control, changes STOP, remediates services, or writes configuration.
