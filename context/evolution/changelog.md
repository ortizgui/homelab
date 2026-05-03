# Changelog

## [Current State] - Context Mesh Added

### Existing Features (documented)
- **Cloud Backup** - Encrypted backup stack (restic + rclone) with safety gates, scheduling, web UI, and API
- **Disk Health Monitoring** - SMART health, temperature, and RAID monitoring with Telegram alerts and bot
- **Network Connectivity Monitoring (Netpulse)** - TCP/DNS probing, status classification, SQLite storage, web dashboard
- **VPN Remote Access** - Tailscale-based secure remote LAN access with subnet routing and exit nodes

### Tech Stack (documented)
- Python 3.11+ (Flask, dnspython, stdlib http.server)
- Bash + smartmontools + mdadm + jq + curl
- Docker + Docker Compose (multi-arch)
- restic v0.17.3 + rclone v1.69.2
- SQLite
- Tailscale v1.92.5 (WireGuard)
- systemd timers/services
- nginx
- Vanilla HTML/CSS/JS

### Patterns Identified
- Safety Gate Pipeline
- JSON HTTP API Server (stdlib)
- SQLite Rollup Tables
- Shell Script Modular Monitoring

---
*Context Mesh added: 2026-05-03*
*This changelog documents the state when Context Mesh was added.*
*Future changes will be tracked below.*

## [2026-05-03] Preflight Caching, Scheduler Logging, Token Detection

### Changed
- **Preflight remote cache** (TTL 15 min): Remote connectivity and repository access checks cached. Local checks always fresh. Short-circuit on local failure before hitting Google API.
- **Lightweight status endpoints**: `/engine/status` and `/api/status` return cached dashboard summary (zero API calls).
- **Scheduler logging**: Startup, job triggers, results, and errors now logged to stdout/stderr. Visible via `docker logs cloud-backup-scheduler`.

### Added
- **Token expiry detection**: `check_rclone_token_expiry()` parses rclone.conf OAuth token on preflight cache miss, warns if expiring within 7 days.
- **Preflight cache helpers**: `_get_preflight_cache()`, `_set_preflight_cache()`, `_invalidate_preflight_cache()` with thread-safe lock.

### Fixed
- Silent exception swallowing in scheduler (`except Exception: pass` → errors now logged to stderr).
- Status page triggering full preflight + snapshots + stats on every load (4-5 Google API calls per reload).

### Related
- [Decision: Preflight Remote Cache and Scheduler Logging](../decisions/006-preflight-cache.md)
