# Encrypted Cloud Backup with Restic + rclone

A secure, automated backup solution using **Restic** with **rclone** backend, running in Docker containers on ARM64/Linux systems (Orange Pi compatible).

## Features

- ✅ **Client-side AES-256 encryption** (zero-knowledge)
- ✅ **Incremental & deduplicated** backups
- ✅ **Automated scheduling** (weekly + monthly)
- ✅ **Retention policy** (keep 1 weekly, 1 monthly)
- ✅ **Multiple cloud providers** (Google Drive, OneDrive, S3, etc.)
- ✅ **ARM64 compatible** (Orange Pi, Raspberry Pi)
- ✅ **Health monitoring** with Docker healthchecks
- ✅ **Comprehensive logging** and error handling
- ✅ **Easy restore** functionality

## Quick Start

### 1. Configure rclone (Cloud Provider)

First, configure rclone for your cloud provider:

```bash
# Install rclone locally for configuration
curl https://rclone.org/install.sh | sudo bash

# Configure your cloud provider
rclone config

# Example for Google Drive:
# - Choose "drive" for Google Drive
# - Follow the OAuth flow
# - Name your remote (e.g., "gdrive")

# Test the connection
rclone lsd gdrive:
```

### 2. Setup the Backup System

```bash
# Clone or download this repository
git clone <repository-url>
cd cloud_backup

# Copy and configure environment variables
cp .env.example .env
nano .env  # Edit with your settings

# Build and start the containers
docker compose up -d

# Check container status
docker compose ps
docker compose logs
```

### 3. Test Manual Backup

```bash
# Run a test weekly backup
docker exec backup-restic /scripts/backup.sh weekly --dry-run

# Run actual backup
docker exec backup-restic /scripts/backup.sh weekly

# Check backup status
docker exec backup-restic restic snapshots
```

## Configuration

### Environment Variables (.env)

**Required:**
- `RESTIC_PASSWORD`: Strong encryption password (never lose this!)
- `RESTIC_REPOSITORY`: Repository path (e.g., `rclone:gdrive:/backups/restic`)
- `BACKUP_PATHS`: Colon-separated paths to backup (e.g., `/mnt/raid1:/mnt/m2`)

**Telegram Notifications (Recommended):**
- `TELEGRAM_BOT_TOKEN`: Bot token from @BotFather
- `TELEGRAM_CHAT_ID`: Your chat ID or group/channel ID

**Optional:**
- `NOTIFY_ON_SUCCESS`: Send success notifications (default: true)
- `NOTIFY_ON_FAILURE`: Send failure notifications (default: true)
- `BANDWIDTH_LIMIT`: Upload speed limit (e.g., `--limit-upload 4M`)
- `RESTIC_EXCLUDES`: Files/patterns to exclude
- `TZ`: Timezone (default: `America/Sao_Paulo`)
- `MAX_BACKUP_AGE_HOURS`: Health check threshold (default: 192 hours)

### rclone Headless Configuration

For automated setups, you can configure rclone via environment variables:

#### Google Drive
```bash
# In .env file:
RCLONE_CONFIG_GDRIVE_TYPE=drive
RCLONE_CONFIG_GDRIVE_CLIENT_ID=your-client-id
RCLONE_CONFIG_GDRIVE_CLIENT_SECRET=your-client-secret
RCLONE_CONFIG_GDRIVE_TOKEN={"access_token":"...","refresh_token":"..."}
```

#### OneDrive
```bash
# In .env file:
RCLONE_CONFIG_ONEDRIVE_TYPE=onedrive
RCLONE_CONFIG_ONEDRIVE_TOKEN={"access_token":"...","refresh_token":"..."}
RCLONE_CONFIG_ONEDRIVE_DRIVE_TYPE=personal
```

## Backup Schedule

The system runs automated backups according to this schedule:

- **Weekly Backup**: Every Sunday at 3:00 AM
- **Monthly Backup**: Last day of each month at 3:30 AM
- **Integrity Check**: 15th of each month at 4:00 AM

### Retention Policy

- **Weekly**: Keep 1 most recent weekly backup
- **Monthly**: Keep 1 most recent monthly backup
- Automatic pruning after each backup

## Usage

### Manual Backup Operations

```bash
# Weekly backup
docker exec backup-restic /scripts/backup.sh weekly

# Monthly backup (only on last day of month)
docker exec backup-restic /scripts/backup.sh monthly

# Dry run (test without changes)
docker exec backup-restic /scripts/backup.sh weekly --dry-run

# Check repository status
docker exec backup-restic restic snapshots
docker exec backup-restic restic stats
```

### Health Monitoring

```bash
# Check system health
docker exec backup-restic /scripts/healthcheck.sh

# Check container health status
docker compose ps

# View logs
docker compose logs backup-restic
docker compose logs scheduler
```

### Preflight Checks

```bash
# Run system diagnostics
docker exec backup-restic /scripts/preflight.sh
```

## Restore Operations

The restore script provides multiple ways to recover your data:

### List Available Snapshots

```bash
docker exec backup-restic /scripts/restore.sh list-snapshots
```

### Restore Entire Snapshot

```bash
# Restore complete snapshot to /tmp/restore
docker exec backup-restic /scripts/restore.sh restore-snapshot a1b2c3d4 /tmp/restore
```

### Restore Specific Path

```bash
# Restore specific directory from snapshot
docker exec backup-restic /scripts/restore.sh restore-path a1b2c3d4 "/home/user/documents" /tmp/restore-docs
```

### Interactive Restore

```bash
# Interactive mode with prompts
docker exec -it backup-restic /scripts/restore.sh interactive
```

### Search for Files

```bash
# Find files across all snapshots
docker exec backup-restic /scripts/restore.sh search-file "config.json"

# List files in specific snapshot
docker exec backup-restic /scripts/restore.sh list-files a1b2c3d4
```

### Example Restore Session

```bash
# 1. List snapshots to find the one you need
docker exec backup-restic /scripts/restore.sh list-snapshots

# Output:
# ID        Time                 Host    Tags        Paths
# a1b2c3d4  2024-01-15 03:00:00  server  weekly      /mnt/raid1, /mnt/m2
# e5f6g7h8  2024-01-08 03:00:00  server  weekly      /mnt/raid1, /mnt/m2

# 2. Restore specific file from latest snapshot
docker exec backup-restic /scripts/restore.sh restore-path a1b2c3d4 "/mnt/raid1/important/config.json" /tmp/restore

# 3. Verify restored file
ls -la /tmp/restore/mnt/raid1/important/config.json
```

## Telegram Bot Setup

### 1. Create Telegram Bot

1. **Start chat with BotFather**:
   - Open Telegram and search for `@BotFather`
   - Send `/start` to begin

2. **Create new bot**:
   ```
   /newbot
   ```
   - Choose a name for your bot (e.g., "My Backup Bot")
   - Choose a username ending in "bot" (e.g., "mybackup_bot")
   - Save the **bot token** (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Get Chat ID

1. **Start chat with your bot**:
   - Search for your bot username in Telegram
   - Send `/start` to your bot

2. **Get your chat ID**:
   ```bash
   # Replace YOUR_BOT_TOKEN with actual token
   curl https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
   - Look for `"chat":{"id":123456789` in the response
   - Save this number as your `TELEGRAM_CHAT_ID`

### 3. Test Notifications

```bash
# Test notification after configuring .env
docker exec backup-restic /scripts/notify.sh success "Test message from backup system"
```

### 4. Notification Examples

**Success Notification:**
```
✅ Backup SUCESSO

🖥️ Host: `orange-pi`
⏰ Horário: `22/09/2024 03:00:15`
📂 Repositório: `rclone:gdrive:/backups/restic`

📝 Detalhes:
Backup weekly realizado com sucesso!

📊 Estatísticas:
• Tag: weekly
• Repositório: rclone:gdrive:/backups/restic
• Paths: /mnt/raid1:/mnt/m2
```

**Failure Notification:**
```
❌ Backup ERRO

🖥️ Host: `orange-pi`
⏰ Horário: `22/09/2024 03:15:30`
📂 Repositório: `rclone:gdrive:/backups/restic`

📝 Detalhes:
❌ Backup FALHOU!

🚨 Detalhes do erro:
• Exit code: 1
• Tag: weekly
• Repositório: rclone:gdrive:/backups/restic
• Paths: /mnt/raid1:/mnt/m2

⚠️ Verifique os logs para mais detalhes.

📄 Últimas linhas do log:
```
[ERROR] Cannot connect to repository
[ERROR] Network timeout after 30 seconds
```
```

### 5. Group/Channel Notifications (Optional)

**For Groups:**
1. Add your bot to the group
2. Make bot an admin (if needed)
3. Get group ID from `/getUpdates` (negative number)

**For Channels:**
1. Add bot to channel as admin
2. Use channel username `@yourchannel` or numeric ID

## Cloud Provider Setup

### Google Drive

1. **Create Google Cloud Project**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create new project or select existing
   - Enable Google Drive API

2. **Create OAuth Credentials**:
   - Go to APIs & Services > Credentials
   - Create OAuth 2.0 Client ID
   - Application type: Desktop application
   - Note the Client ID and Client Secret

3. **Configure rclone**:
   ```bash
   rclone config
   # Choose: New remote → drive → Enter credentials → Follow OAuth flow
   ```

### OneDrive

1. **Microsoft App Registration**:
   - Go to [Azure Portal](https://portal.azure.com/)
   - Azure Active Directory > App registrations > New registration
   - Note Application (client) ID

2. **Configure rclone**:
   ```bash
   rclone config
   # Choose: New remote → onedrive → Follow OAuth flow
   ```

### Amazon S3

```bash
rclone config
# Choose: s3 → AWS → Enter access key and secret → Choose region
```

## Troubleshooting

### Common Issues

**1. "Cannot access repository"**
```bash
# Check rclone connectivity
docker exec backup-restic rclone lsd gdrive:

# Check restic repository
docker exec backup-restic restic snapshots
```

**2. "Permission denied on backup paths"**
```bash
# Check mounted volumes in docker-compose.yml
# Ensure paths exist and are readable
ls -la /mnt/raid1
```

**3. "Backup takes too long"**
```bash
# Add bandwidth limit
BANDWIDTH_LIMIT=--limit-upload 2M

# Check system resources
docker exec backup-restic /scripts/preflight.sh
```

**4. "Rate limited by cloud provider"**
```bash
# Add delays between operations
# Check provider-specific rate limits
# Consider using multiple remotes
```

### Log Analysis

```bash
# View recent backup logs
docker exec backup-restic find /var/log/backup -name "backup-*.log" -mtime -1

# View specific log
docker exec backup-restic tail -f /var/log/backup/backup-20240115-030000.log

# Check for errors
docker exec backup-restic grep -r "ERROR" /var/log/backup/
```

### Performance Optimization

**For ARM64/Orange Pi systems:**

1. **Limit concurrent operations**:
   ```bash
   # In .env:
   BANDWIDTH_LIMIT=--limit-upload 2M
   ```

2. **Exclude unnecessary files**:
   ```bash
   RESTIC_EXCLUDES="*.tmp *.cache /proc /sys /tmp node_modules .git"
   ```

3. **Monitor system resources**:
   ```bash
   # Check during backup
   htop
   iotop -a
   ```

## Security Considerations

### Encryption
- **Client-side encryption**: Data encrypted before leaving your system
- **Password security**: Use strong, unique passwords (consider `openssl rand -base64 32`)
- **Zero-knowledge**: Cloud provider cannot decrypt your data

### Access Control
```bash
# Secure .env file
chmod 600 .env

# Run containers as non-root
# (Already configured in Dockerfile)

# Regular key rotation
# Note: Changing password requires new repository
```

### Backup Verification
```bash
# Regular integrity checks
docker exec backup-restic restic check

# Test restore procedures monthly
docker exec backup-restic /scripts/restore.sh list-snapshots

# Verify critical files
docker exec backup-restic /scripts/restore.sh search-file "important-config.json"
```

## Maintenance

### Password Rotation

⚠️ **Warning**: Changing the restic password requires creating a new repository and re-uploading all data.

```bash
# 1. Create new repository with new password
RESTIC_PASSWORD=new-password restic init

# 2. Backup current data to new repository
# 3. Update .env with new password
# 4. Delete old repository (optional)
```

### Upgrading

```bash
# Update container images
docker compose pull
docker compose up -d

# Check for script updates
git pull origin main
docker compose restart
```

### Monitoring

```bash
# Health check status
docker compose ps

# Backup history
docker exec backup-restic restic snapshots

# Repository statistics
docker exec backup-restic restic stats

# Recent errors
docker exec backup-restic grep -r "ERROR" /var/log/backup/ | tail -10
```

## Architecture

### Components

- **backup-restic**: Main backup container with restic and rclone
- **scheduler**: Cron-based task scheduler
- **notify**: Optional notification service

### Data Flow

1. **Scheduler** triggers backup script at configured times
2. **Preflight checks** validate system state and connectivity
3. **Backup process** reads source paths (read-only) and uploads to cloud
4. **Retention policy** applied automatically after each backup
5. **Health checks** monitor backup freshness and repository integrity

### File Structure

```
cloud_backup/
├── docker-compose.yml      # Container orchestration
├── Dockerfile             # Custom restic+rclone image
├── .env.example           # Configuration template
├── crontab                # Backup schedule
├── scripts/
│   ├── backup.sh          # Main backup logic
│   ├── preflight.sh       # System checks
│   ├── healthcheck.sh     # Health monitoring
│   └── restore.sh         # Restore operations
└── README.md              # This file
```

## Support

For issues, questions, or improvements:

1. Check the troubleshooting section
2. Review logs for error details
3. Test with `--dry-run` mode first
4. Verify cloud provider connectivity

## License

This project is open source. Use at your own risk and ensure you test restore procedures regularly.