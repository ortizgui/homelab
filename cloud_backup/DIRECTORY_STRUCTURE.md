# Directory Structure

## Services

- `backup-engine`: runs the operational engine on port `8091`
- `backup-api`: serves the configuration and orchestration API on port `8080`
- `backup-scheduler`: executes scheduled jobs based on saved config
- `backup-web`: serves the UI on port `80`

## Repository layout

```text
cloud_backup/
├── app/                    # Python engine, API and scheduler
├── data/
│   ├── config/
│   │   └── config.json     # Persisted schema-validated config
│   ├── logs/               # JSONL logs for preflight and operations
│   ├── rclone/
│   │   └── rclone.conf     # rclone provider config
│   ├── restore/            # Restore destination root
│   ├── restic-cache/       # restic cache
│   └── state/              # Scheduler and runtime state
├── scripts/                # Compatibility wrappers
├── tests/                  # Basic validation tests
└── web/                    # Static frontend and nginx config
```

## Host persistence

The persistent host directory is configurable with `CLOUD_BACKUP_DATA_DIR`.

Suggested layout for your server:

```text
/mnt/m2/docker/
├── cloud_backup/           # persistent runtime data
│   ├── config/
│   ├── logs/
│   ├── rclone/
│   ├── restore/
│   ├── restic-cache/
│   └── state/
└── git/
    └── homelab/
        └── cloud_backup/   # git checkout with compose/app/web/scripts
```

## Important paths inside containers

- `/source/raid1`
- `/source/m2`
- `/data/config/config.json`
- `/data/rclone/rclone.conf`
- `/data/logs`
- `/data/restore`
- `/host/proc/mdstat`

## Operational split

- Engine operations are implemented in [`app/operations.py`](/Volumes/homeX/git/homelab/cloud_backup/app/operations.py).
- API persistence and import/export live in [`app/api_server.py`](/Volumes/homeX/git/homelab/cloud_backup/app/api_server.py).
- Scheduler logic lives in [`app/scheduler.py`](/Volumes/homeX/git/homelab/cloud_backup/app/scheduler.py).
- The web app is served from [`web/index.html`](/Volumes/homeX/git/homelab/cloud_backup/web/index.html).
