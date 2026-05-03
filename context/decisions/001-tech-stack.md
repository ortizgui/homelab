# Decision: Tech Stack

## Context
Multi-service homelab environment requiring containerized deployment, data persistence, remote access, and system-level monitoring.

## Decision
- **Backup engine**: restic v0.17.3 + rclone v1.69.2 (baked into Alpine-based Docker image)
- **Backup API & UI**: Python 3.11+ with stdlib http.server (ThreadingHTTPServer), no external web framework
- **Connectivity monitor**: Python 3.12, Flask 3.1.0 for web dashboard, dnspython 2.7.0 for DNS probes
- **Disk monitoring**: Bash scripts with smartmontools, mdadm, jq, curl
- **Data storage**: SQLite for time-series data (Netpulse), JSON files for configuration (Cloud Backup)
- **Deployment**: Docker + Docker Compose, multi-arch images (amd64, arm64, armv7)
- **VPN**: Tailscale v1.92.5 Docker image with kernel networking
- **Process supervision**: systemd timers + services (disk-health)
- **Web proxy**: nginx for static file serving and API reverse proxy (Cloud Backup)
- **Frontend**: Vanilla HTML/CSS/JS (no framework)

## Rationale
- restic and rclone are proven, well-maintained tools for encrypted cloud backups
- Python stdlib was chosen over Flask for backup API to minimize dependencies in Alpine containers
- Flask chosen for Netpulse for rapid dashboard development with templates
- Bash for disk monitoring because it needs direct system access (SMART, mdadm)
- SQLite is sufficient for single-node logging; no need for external databases
- Docker Compose for simple orchestration without Kubernetes overhead
- Multi-arch Docker images needed for mixed environment (x86_64 + ARM)
- systemd is the native init system; no need for additional process supervisors
- Vanilla frontend avoids JavaScript framework churn and build tooling

## Alternatives Considered
- **BorgBackup**: Inferior to restic for cloud-storage scenarios due to no native rclone support
- **Prometheus + Grafana**: Overkill for simple connectivity monitoring; Netpulse is self-contained
- **PostgreSQL**: Unnecessary for single-node; SQLite is simpler to manage
- **Kubernetes**: Heavy for homelab; Docker Compose is sufficient
- **React/Vue**: Unnecessary complexity for simple dashboards

## Outcomes
Stack has proven reliable in production homelab use. No changes needed.

## Related
- [Project Intent](../intent/project-intent.md)
- [Feature: Cloud Backup](../intent/feature-cloud-backup.md)
- [Feature: Network Connectivity Monitoring](../intent/feature-netpulse.md)

## Status
- **Created**: 2026-05-03 (Phase: Intent)
- **Status**: Accepted
