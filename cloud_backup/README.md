# Cloud Backup

Encrypted backup stack built on top of `restic + rclone`, running in containers with a local API, scheduler and web UI.

## What changed

- `restic` remains the backup engine and `rclone` remains the cloud transport.
- The stack is now split into four services:
  - `backup-engine`: executes preflight, backup, forget, prune and restore.
  - `backup-api`: persists configuration and exposes a local HTTP API.
  - `backup-scheduler`: reads the saved schedule and triggers jobs.
  - `backup-web`: serves the UI and proxies `/api`.
- Backup and retention are now separate operations.
- Safety gates block any cloud mutation when mounts, source paths, storage health, remote access or repository access are not safe.

## Safety model

Before `backup`, `forget` or `prune`, the engine validates:

- expected mountpoints exist and are directories
- enabled source paths exist and are readable inside the container
- sources are not unexpectedly empty unless explicitly allowed
- remote connectivity through `rclone`
- repository access through `restic`
- storage health via:
  - optional blocker file
  - optional JSON status file produced by another tool
  - `/proc/mdstat` degraded RAID detection when mounted

If any critical validation fails, the operation aborts, gets logged and is eligible for notification.

## Layout

Persistent data is configurable through `CLOUD_BACKUP_DATA_DIR`.

Default:

- `CLOUD_BACKUP_DATA_DIR=./data`

Recommended for your server layout:

- Git repo: `/mnt/m2/docker/git/homelab/cloud_backup`
- Persistent service data: `/mnt/m2/docker/cloud_backup`

Example `.env`:

```env
CLOUD_BACKUP_DATA_DIR=/mnt/m2/docker/cloud_backup
```

Inside that host directory, the service expects:

- `config/config.json`: persisted application config
- `rclone/rclone.conf`: rclone config
- `logs/`: JSONL operation logs
- `restic-cache/`: restic cache
- `state/`: scheduler and runtime state
- `restore/`: restore target root

## Quick start

```bash
cd /Volumes/homeX/git/homelab/cloud_backup
./setup.sh
docker compose up -d --build
```

If you want persistence outside the Git checkout, edit `.env` first and set:

```env
CLOUD_BACKUP_DATA_DIR=/mnt/m2/docker/cloud_backup
```

Open [http://localhost:8095](http://localhost:8095) unless you changed `CLOUD_BACKUP_WEB_PORT`.

The API is exposed on [http://localhost:8096](http://localhost:8096) by default.

## Default retention

The initial saved configuration starts with:

- `keep-last = 7`
- `keep-daily = 14`
- `keep-weekly = 8`
- `keep-monthly = 3`
- `--skip-if-unchanged` on backup
- default exclusions for temporary/cache files, while `.iso` files remain included

`BANDWIDTH_LIMIT` accepts values like `4M`, `512K`, or `0`. The app converts that to the `restic --limit-upload` format automatically.

`forget` and `prune` are scheduled independently from the normal backup job.

## Main API endpoints

- `GET /api/config`: load saved configuration
- `PUT /api/config`: save configuration
- `POST /api/config/validate`: validate a candidate config
- `GET /api/preflight`: run the safety gate without changing cloud state
- `POST /api/actions/backup`: trigger a manual backup
- `POST /api/actions/forget`: trigger retention cleanup without prune
- `POST /api/actions/prune`: trigger prune
- `GET /api/snapshots`: list snapshots
- `POST /api/actions/restore`: restore a snapshot into `/data/restore/...`
- `GET /api/config/export`: export config bundle
- `POST /api/config/import`: import config bundle with schema validation

## UI coverage

The web UI provides:

- status and safety gate visibility
- cloud/repository configuration
- monitored source selection
- exclusions
- retention settings
- schedule editing
- operation history
- restore trigger
- config export/import

## Local commands

```bash
docker compose exec backup-engine python3 -m app.operation_cli preflight
docker compose exec backup-engine python3 -m app.operation_cli backup manual
docker compose exec backup-engine python3 -m app.operation_cli forget
docker compose exec backup-engine python3 -m app.operation_cli prune
docker compose exec backup-engine python3 -m app.operation_cli restore <snapshot> /data/restore/test
```

Legacy shell wrappers still exist in [`cloud_backup/scripts`](/Volumes/homeX/git/homelab/cloud_backup/scripts), but they now delegate to the Python CLI.

To recover after the containers were paused during a backup, use:

```bash
cd /Volumes/homeX/git/homelab/cloud_backup
./scripts/resume_backup.sh
```

The script brings the backup services back up, waits for `backup-engine`, runs `preflight`, and then starts a new backup. If a previous run left `state/current-run.json`, the engine performs its recovery prune automatically before continuing. When repository access fails after an interrupted run, the script also attempts `restic unlock --remove-all` once before aborting.

## disk-health integration

The stack mounts [`disk-health`](/Volumes/homeX/git/homelab/disk-health) read-only for reuse and supports two simple integration points:

- `CLOUD_BACKUP_DISK_HEALTH_FILE`: JSON status file, for example `{ "status": "ok" }`
- `CLOUD_BACKUP_DISK_HEALTH_BLOCKER_FILE`: if this file exists, cloud-mutating jobs are blocked

This keeps `cloud_backup` conservative even if the disk-health project evolves independently.

## Validation

Useful verification commands:

```bash
python3 -m unittest discover -s /Volumes/homeX/git/homelab/cloud_backup/tests
python3 -m compileall /Volumes/homeX/git/homelab/cloud_backup/app /Volumes/homeX/git/homelab/cloud_backup/tests
docker compose config
```

Notes:

- Runtime services now use the Python package installed into the image, instead of relying on bind-mounted source code.
- Exported config bundles include `restic_password` and inline `rclone_config` so they can be used as full restore backups. Handle these exports as sensitive secrets.
