# Decision: Preflight Remote Cache and Scheduler Logging

## Context
Preflight checks ran full remote validation (rclone lsd + restic cat config + restic snapshots) on every invocation — status page reloads, health checks, and scheduled job triggers all hit Google Drive API.

An rclone OAuth token expiry triggered "invalid_grant" errors starting 2026-04-06. The scheduler silently swallowed all exceptions (`except Exception: pass`) with zero logging, making diagnosis impossible. No notification was ever sent because Telegram/webhook were not configured.

## Decision
1. **Preflight remote cache (TTL 15 min)**: Remote connectivity and repository access checks are cached. Local checks (mounts, sources, disk health) always run fresh. If any local check fails, short-circuit before hitting remote API.
2. **Lightweight status endpoint**: `/engine/status` and `/api/status` serve `cached_dashboard_summary()` (zero API calls) instead of running full preflight + snapshots + stats.
3. **Scheduler logging**: `print()` to stdout/stderr for all job triggers, results, and errors. No more silent `except Exception: pass`.
4. **Token expiry detection**: `check_rclone_token_expiry()` parses rclone.conf token on preflight cache miss, warns if expiring within 7 days or already expired.
5. **Existing notification system unchanged**: Telegram/webhook still optional. Failures are now always visible via scheduler logs (`docker logs`) and operations.jsonl.

## Rationale
- Reduce Google API rate limit risk: cached remote checks cut API calls by ~90% during status page refreshes
- Short-circuit on local failure avoids unnecessary API calls when backup is already blocked locally
- Scheduler logging makes container logs actionable for debugging
- Token expiry detection catches auth issues before they block backups

## Alternatives Considered
- **No caching**: Simpler but high API call volume (4-5 calls per status page reload)
- **Redis/memcached**: Overkill for single-server homelab; in-process dict with TTL sufficient
- **Structured logging (logging module)**: print() sufficient for Docker log capture, no extra dependency

## Related
- [Decision: Cloud Backup Architecture](../decisions/002-cloud-backup-architecture.md)
- [Decision: Safety Gate Pattern](../decisions/005-safety-gate-pattern.md)
- [Pattern: Safety Gate Pipeline](../knowledge/patterns/safety-gate-pipeline.md)

## Outcomes
- Preflight now resilient to transient remote failures (cached for 15 min)
- Status page loads no longer generate Google API calls
- Scheduler errors visible in `docker logs cloud-backup-scheduler`
- Token expiry warnings in preflight output help prevent surprise lockouts

## Status
- **Created**: 2026-05-03
- **Status**: Active
