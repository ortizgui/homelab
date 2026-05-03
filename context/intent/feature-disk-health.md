# Feature: Disk Health Monitoring

## What
Automated disk and RAID health monitoring that periodically checks SMART status, temperature, and mdadm RAID state, sending Telegram alerts on state changes and supporting interactive Telegram bot commands for on-demand health checks.

## Why
Prevent data loss by detecting disk failures early (SMART attributes, temperature thresholds, RAID degradation). Provide actionable alerts without noise (anti-spam via state change detection) and enable remote inspection via Telegram bot.

## Acceptance Criteria
- [ ] Auto-discovers disks (filters out zram, mtdblock)
- [ ] Checks SMART overall health, temperature, and key attributes (Reallocated_Sector_Ct, Current_Pending_Sector, Offline_Uncorrectable)
- [ ] Monitors mdadm RAID status for degraded arrays
- [ ] Sends Telegram alerts only on state changes (anti-spam)
- [ ] Supports Telegram bot commands: /disks, /backup, /help
- [ ] Weekly SMART short tests available
- [ ] Systemd timer (every 15 min + on boot) and service
- [ ] Optional weekly report even without changes

## Related
- [Decision: Disk Health Monitoring](../decisions/004-disk-health-monitoring.md)
- [Decision: Safety Gate Pattern](../decisions/005-safety-gate-pattern.md)
- [Pattern: Shell Script Modular Monitoring](../knowledge/patterns/shell-script-modular-monitoring.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Active (already implemented)
