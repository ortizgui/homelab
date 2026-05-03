# Feature: Cloud Backup

## What
Automated encrypted backup system that securely copies selected data directories to cloud storage, with safety gates that prevent data loss, scheduled operations, and a web interface for configuration and monitoring.

## Why
Protect critical data against hardware failure, accidental deletion, and disasters. Ensure backups never silently corrupt data by validating mount points, source paths, remote connectivity, and storage health before every cloud mutation.

## Acceptance Criteria
- [ ] Backup runs on schedule (default: Mon/Thu at 03:00)
- [ ] Forget and prune run independently from backup
- [ ] Preflight safety gate validates mounts, sources, remote, disk health, and repo access before any cloud mutation
- [ ] Failed backup triggers automatic recovery prune
- [ ] Notifications sent on success and failure (Telegram or webhook)
- [ ] Configuration editable via web UI or API
- [ ] Retention policy configurable (keep-last, keep-daily, keep-weekly, keep-monthly)
- [ ] Snapshot restore available via API/CLI

## Related
- [Decision: Tech Stack](../decisions/001-tech-stack.md)
- [Decision: Cloud Backup Architecture](../decisions/002-cloud-backup-architecture.md)
- [Decision: Safety Gate Pattern](../decisions/005-safety-gate-pattern.md)
- [Pattern: Safety Gate Pipeline](../knowledge/patterns/safety-gate-pipeline.md)
- [Pattern: JSON HTTP API Server](../knowledge/patterns/json-http-api-server.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Active (already implemented)
