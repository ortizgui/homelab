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
