# Decision: Disk Health Monitoring Approach

## Context
Linux-based server requiring disk health monitoring with remote alerts, RAID degradation detection, and on-demand health status queries.

## Decision
- **Language**: Bash scripts (no Python dependency for system-level monitoring)
- **SMART monitoring**: `smartctl` with auto-discovery of SATA/NVMe/USB-SAT devices, filtering out zram/mtdblock
- **RAID monitoring**: `/proc/mdstat` parsing + `mdadm --detail` for degraded array detection
- **Alerting**: Telegram (curl POST to Bot API) with anti-spam via hash-based state change tracking
- **Scheduling**: systemd timer running every 15 minutes + on boot, short-lived oneshot services
- **Interactive bot**: Separate `telegram-bot.sh` polling Telegram for commands (/disks, /backup, /help)
- **Configuration**: Sourceable shell config file at `/etc/disk-alert.conf` with token, thresholds, disk overrides
- **Temperature thresholds**: Different HDD (warn: 55C, crit: 60C) vs SSD (warn: 65C, crit: 70C)
- **Weekly SMART self-tests**: Optional short self-test every Sunday 03:00

## Rationale
- Bash keeps dependencies minimal (only smartmontools, mdadm, jq, curl)
- systemd is the native Linux init system; no need for Docker for host-level monitoring
- Anti-spam via state hash prevents notification fatigue
- Telegram bot mode allows interactive remote health queries without SSH
- Hash file in /tmp means state resets on reboot (acceptable for alert dedup)
- Separate Telegram bot script keeps the checker and interactive bot concerns isolated

## Alternatives Considered
- **Python script**: Adds Python dependency; Bash is more native for system scripting
- **Docker container**: Would need host device access; direct install is simpler
- **Email alerts**: Telegram is more immediate and mobile-friendly
- **Nagios/Icinga**: Overkill for homelab
- **SMARTD**: Built-in but less flexible for custom logic and Telegram integration

## Related
- [Project Intent](../intent/project-intent.md)
- [Feature: Disk Health Monitoring](../intent/feature-disk-health.md)
- [Pattern: Shell Script Modular Monitoring](../knowledge/patterns/shell-script-modular-monitoring.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Accepted
