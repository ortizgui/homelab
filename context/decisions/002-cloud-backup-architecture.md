# Decision: Cloud Backup Architecture

## Context
Encrypted backup stack requiring scheduling, safety preflight checks, notification support, configuration UI, and independent operation cycles (backup vs. forget vs. prune).

## Decision
Four-service microservice architecture:
1. **backup-engine** (port 8091): Executes preflight, backup, forget, prune, restore operations. Runs all restic/rclone commands.
2. **backup-api** (port 8080): HTTP API for configuration management, proxies engine operations, persists config to JSON files.
3. **backup-scheduler**: Polls config every 30s, triggers scheduled jobs on engine via HTTP. Runs as background loop.
4. **backup-web** (port 80): nginx serving static files, proxying `/api/` to backup-api.

## Rationale
- Separation of concerns: engine (operations) vs API (persistence + control plane) vs scheduler (time-based) vs web (UI)
- Engine and API can be independently health-checked and restarted
- Safety gate (preflight) runs before each operation, not as a separate service
- JSON config file persistence is simple and human-readable
- Scheduler operates independently of API, survives restarts
- nginx handles static assets efficiently and can be scaled separately

## Alternatives Considered
- **Single monolithic service**: Harder to maintain and restart independently
- **Cron-based scheduling**: Less flexible than config-driven scheduler; migrated from crontab to scheduler
- **Full REST framework**: stdlib http.server sufficient for internal-only API

## Related
- [Project Intent](../intent/project-intent.md)
- [Feature: Cloud Backup](../intent/feature-cloud-backup.md)
- [Decision: Tech Stack](../decisions/001-tech-stack.md)
- [Decision: Safety Gate Pattern](../decisions/005-safety-gate-pattern.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Accepted
