# Decision: Safety Gate Pattern

## Context
Backup operations that mutate cloud storage (backup, forget, prune) must be protected against data corruption scenarios: unmounted filesystems, empty source directories, degraded disks, or unreachable remote storage.

## Decision
**Preflight safety gate**: A mandatory validation pipeline that runs before every cloud-mutating operation. The pipeline checks, in order:
1. **Mount points**: Expected mount paths exist and are directories (not empty mount points)
2. **Source paths**: Enabled source directories exist, are readable, and are not unexpectedly empty
3. **Remote connectivity**: rclone can reach the remote storage provider
4. **Storage health**: Either a JSON status file says OK, or /proc/mdstat shows no degraded RAID, and no blocker file exists
5. **Repository access**: restic can access the repository (cat config or list snapshots)

If ANY check fails, the operation is blocked and logged. Notification is sent.

## Rationale
- Prevents silent data corruption from backing up empty or missing directories
- Ensures cloud operations don't run during degraded storage conditions
- Clear, actionable failure messages for troubleshooting
- Integration point with disk-health project via JSON status file and blocker file
- Each check is independent; failures are aggregated for complete reporting

## Alternatives Considered
- **Check as part of each operation**: Less clear; separate preflight improves observability
- **Continuous validation in background**: Wastes resources; on-demand before each operation is sufficient

## Related
- [Project Intent](../intent/project-intent.md)
- [Feature: Cloud Backup](../intent/feature-cloud-backup.md)
- [Pattern: Safety Gate Pipeline](../knowledge/patterns/safety-gate-pipeline.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Accepted
