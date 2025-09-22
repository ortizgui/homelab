# Directory Structure

This document describes the directory structure used by the cloud backup system.

## Overview

The backup system is designed to store all configuration, data, and logs in a centralized location at `/mnt/m2/docker/cloud_backup/`. This approach provides:

- **Centralized management** - All backup-related files in one location
- **Persistent storage** - Data survives container restarts and rebuilds
- **Easy backup** - Configuration and logs can be backed up separately
- **Clear organization** - Logical separation of different file types

## Directory Structure

```
/mnt/m2/docker/cloud_backup/
├── .env                          # Main configuration file
├── .env.example                  # Configuration template
├── docker-compose.yml            # Container orchestration
├── Dockerfile                    # Custom image definition
├── README.md                     # Documentation
├── crontab                       # Backup schedule
├── setup.sh                     # Initial setup script
├── configure-rclone.sh           # rclone configuration helper
├── scripts/                      # Backup scripts
│   ├── backup.sh                 # Main backup logic
│   ├── preflight.sh              # System checks
│   ├── healthcheck.sh            # Health monitoring
│   ├── restore.sh                # Restore operations
│   └── notify.sh                 # Telegram notifications
├── data/                         # Persistent application data
│   ├── restic-cache/             # Restic cache directory
│   │   ├── locks/                # Repository locks
│   │   ├── snapshots/            # Snapshot metadata cache
│   │   └── index/                # Index cache
│   └── rclone-config/            # rclone configuration
│       └── rclone.conf           # rclone remote configurations
├── logs/                         # Log files
│   ├── backup-YYYYMMDD-HHMMSS.log # Backup operation logs
│   ├── restore-YYYYMMDD-HHMMSS.log # Restore operation logs
│   ├── cron.log                  # Scheduled task logs
│   ├── last_backup_timestamp     # Health check timestamp
│   └── last_check_timestamp      # Integrity check timestamp
└── config/                       # Additional configuration files
    └── (reserved for future use)
```

## Directory Descriptions

### Root Level (`/mnt/m2/docker/cloud_backup/`)

| File/Directory | Purpose | Permissions |
|----------------|---------|-------------|
| `.env` | Main configuration with secrets | `600` (rw-------) |
| `.env.example` | Configuration template | `644` (rw-r--r--) |
| `docker-compose.yml` | Container definitions | `644` (rw-r--r--) |
| `Dockerfile` | Custom image build | `644` (rw-r--r--) |
| `README.md` | Complete documentation | `644` (rw-r--r--) |
| `crontab` | Backup schedule definition | `644` (rw-r--r--) |
| `setup.sh` | Automated setup script | `755` (rwxr-xr-x) |
| `configure-rclone.sh` | rclone setup helper | `755` (rwxr-xr-x) |

### Scripts Directory (`scripts/`)

Contains all executable scripts used by the backup system.

| Script | Purpose | Executed By |
|--------|---------|-------------|
| `backup.sh` | Main backup operations | Container, Cron |
| `preflight.sh` | Pre-backup system checks | `backup.sh` |
| `healthcheck.sh` | Container health monitoring | Docker healthcheck |
| `restore.sh` | Data restoration operations | Manual execution |
| `notify.sh` | Telegram notifications | `backup.sh`, other scripts |

**Permissions:** All scripts have `755` (rwxr-xr-x)

### Data Directory (`data/`)

Stores persistent application data that must survive container restarts.

#### `data/restic-cache/`
- **Purpose**: Restic performance optimization
- **Contents**: Cached metadata, indexes, and locks
- **Size**: Can grow to several GB depending on repository size
- **Cleanup**: Automatically managed by restic
- **Backup**: Not necessary (cache can be rebuilt)

#### `data/rclone-config/`
- **Purpose**: rclone remote configurations
- **Contents**: OAuth tokens, remote settings
- **Security**: Contains sensitive authentication data
- **Permissions**: `600` for `rclone.conf`
- **Backup**: Should be backed up securely

### Logs Directory (`logs/`)

Contains all operational logs and status files.

#### Log Files
- **`backup-*.log`**: Detailed backup operation logs
- **`restore-*.log`**: Restore operation logs  
- **`cron.log`**: Scheduled task execution logs

#### Status Files
- **`last_backup_timestamp`**: Unix timestamp of last successful backup
- **`last_check_timestamp`**: Unix timestamp of last integrity check

#### Log Rotation
- Logs are automatically created with timestamps
- Old logs should be manually cleaned or use logrotate
- Default retention: Keep logs for 30 days (configurable)

### Config Directory (`config/`)

Reserved for future configuration files or custom settings.

## Volume Mounts

The Docker containers mount these directories as follows:

| Host Path | Container Path | Mode | Purpose |
|-----------|----------------|------|---------|
| `/mnt/m2/docker/cloud_backup/scripts` | `/scripts` | `ro` | Script execution |
| `/mnt/m2/docker/cloud_backup/data/restic-cache` | `/root/.cache/restic` | `rw` | Restic cache |
| `/mnt/m2/docker/cloud_backup/data/rclone-config` | `/root/.config/rclone` | `rw` | rclone config |
| `/mnt/m2/docker/cloud_backup/logs` | `/var/log/backup` | `rw` | Log storage |
| `/mnt/m2/docker/cloud_backup/crontab` | `/etc/crontabs/root` | `ro` | Cron schedule |

## Backup Sources

The system backs up these directories (configured in `.env`):

| Host Path | Container Path | Mode | Purpose |
|-----------|----------------|------|---------|
| `/mnt/raid1` | `/backup-sources/raid1` | `ro` | Primary storage |
| `/mnt/m2` | `/backup-sources/m2` | `ro` | Secondary storage |

**Note**: Backup sources are mounted read-only for safety.

## Security Considerations

### File Permissions

- **Configuration files**: `600` (owner read/write only)
- **Scripts**: `755` (owner read/write/execute, others read/execute)
- **Logs**: `644` (owner read/write, others read)
- **Data directories**: `750` (owner full access, group read/execute)

### Sensitive Data

The following files contain sensitive information:
- `.env` - Contains passwords and API tokens
- `data/rclone-config/rclone.conf` - Contains OAuth tokens
- `logs/*.log` - May contain repository paths and error details

### Access Control

- Use appropriate user/group ownership
- Consider SELinux/AppArmor contexts if enabled
- Ensure backup system runs with minimal required privileges

## Maintenance

### Cleanup Tasks

```bash
# Clean old logs (older than 30 days)
find /mnt/m2/docker/cloud_backup/logs -name "*.log" -mtime +30 -delete

# Clean restic cache if too large (>5GB)
du -sh /mnt/m2/docker/cloud_backup/data/restic-cache
# If needed: rm -rf /mnt/m2/docker/cloud_backup/data/restic-cache/*

# Backup configuration
tar -czf backup-config-$(date +%Y%m%d).tar.gz \
  /mnt/m2/docker/cloud_backup/.env \
  /mnt/m2/docker/cloud_backup/data/rclone-config/
```

### Monitoring

```bash
# Check directory sizes
du -sh /mnt/m2/docker/cloud_backup/*

# Check permissions
ls -la /mnt/m2/docker/cloud_backup/

# Check recent activity
ls -lat /mnt/m2/docker/cloud_backup/logs/
```

## Migration from Previous Setup

If migrating from the previous Docker volume-based setup:

```bash
# 1. Stop containers
docker compose down

# 2. Run setup script
./setup.sh

# 3. Copy existing data (if any)
docker run --rm -v backup-restic_restic-cache:/old-cache \
  -v /mnt/m2/docker/cloud_backup/data/restic-cache:/new-cache \
  alpine cp -a /old-cache/. /new-cache/

# 4. Update .env configuration
cp .env /mnt/m2/docker/cloud_backup/.env

# 5. Start new setup
cd /mnt/m2/docker/cloud_backup
docker compose up -d
```

This structure provides a clean, maintainable, and scalable approach to managing the backup system configuration and data.