#!/bin/bash

set -euo pipefail

# Backup script for Restic with rclone backend
# Usage: backup.sh [weekly|monthly] [--dry-run]

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/var/log/backup"
LOG_FILE="${LOG_DIR}/backup-$(date +%Y%m%d-%H%M%S).log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Logging functions
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2
}

# Global variable for current backup tag
CURRENT_BACKUP_TAG=""

# Cleanup function
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Backup failed with exit code $exit_code"
        
        # Send failure notification
        local failure_message="❌ *Backup FALHOU!*

🚨 *Detalhes do erro:*
• Exit code: $exit_code
• Tag: ${CURRENT_BACKUP_TAG:-unknown}
• Repositório: ${RESTIC_REPOSITORY:-N/A}
• Paths: ${BACKUP_PATHS:-N/A}

⚠️ Verifique os logs para mais detalhes."
        
        if command -v "$SCRIPT_DIR/notify.sh" >/dev/null 2>&1; then
            "$SCRIPT_DIR/notify.sh" "failure" "$failure_message" "$LOG_FILE"
        fi
    fi
    exit $exit_code
}

trap cleanup EXIT

# Validate environment variables
validate_env() {
    local required_vars=(
        "RESTIC_PASSWORD"
        "RESTIC_REPOSITORY"
        "BACKUP_PATHS"
    )
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ]; then
            log_error "Required environment variable $var is not set"
            exit 1
        fi
    done
}

# Check if it's the last day of the month
is_last_day_of_month() {
    local today tomorrow
    today=$(date +%Y-%m-%d)
    tomorrow=$(date -d "$today + 1 day" +%Y-%m-%d)
    
    # If tomorrow is in a different month, today is the last day
    [ "$(date -d "$today" +%m)" != "$(date -d "$tomorrow" +%m)" ]
}

# Initialize restic repository if it doesn't exist
init_repository() {
    log "Checking repository existence..."
    
    if ! restic snapshots &>/dev/null; then
        log "Repository doesn't exist. Initializing..."
        restic init
        log "Repository initialized successfully"
    else
        log "Repository already exists"
    fi
}

# Parse backup paths from environment variable
parse_backup_paths() {
    IFS=':' read -ra PATHS <<< "$BACKUP_PATHS"
    for path in "${PATHS[@]}"; do
        if [ ! -d "$path" ]; then
            log_error "Backup path does not exist: $path"
            exit 1
        fi
        if [ ! -r "$path" ]; then
            log_error "Cannot read backup path: $path"
            exit 1
        fi
    done
}

# Create exclude file if patterns are provided
create_exclude_file() {
    local exclude_file="/tmp/restic-excludes"
    
    if [ -n "${RESTIC_EXCLUDES:-}" ]; then
        echo "$RESTIC_EXCLUDES" | tr ' ' '\n' > "$exclude_file"
        echo "$exclude_file"
    fi
}

# Perform backup
perform_backup() {
    local tag="$1"
    local dry_run="$2"
    
    log "Starting $tag backup..."
    
    # Parse backup paths
    IFS=':' read -ra PATHS <<< "$BACKUP_PATHS"
    
    # Create exclude file
    local exclude_file
    exclude_file=$(create_exclude_file)
    
    # Build restic command
    local restic_cmd=(
        "restic" "backup"
        "--one-file-system"
        "--tag" "$tag"
        "--verbose"
    )
    
    # Add exclude file if exists
    if [ -n "$exclude_file" ] && [ -f "$exclude_file" ]; then
        restic_cmd+=("--exclude-file" "$exclude_file")
    fi
    
    # Add bandwidth limit if specified
    if [ -n "${BANDWIDTH_LIMIT:-}" ]; then
        restic_cmd+=("$BANDWIDTH_LIMIT")
    fi
    
    # Add dry-run flag if specified
    if [ "$dry_run" = "true" ]; then
        restic_cmd+=("--dry-run")
    fi
    
    # Add paths
    restic_cmd+=("${PATHS[@]}")
    
    log "Executing: ${restic_cmd[*]}"
    
    if "${restic_cmd[@]}"; then
        log "$tag backup completed successfully"
    else
        log_error "$tag backup failed"
        exit 1
    fi
    
    # Cleanup exclude file
    [ -n "$exclude_file" ] && [ -f "$exclude_file" ] && rm -f "$exclude_file"
}

# Apply retention policy
apply_retention() {
    local dry_run="$1"
    
    log "Applying retention policy (keep 1 weekly, 1 monthly)..."
    
    local forget_cmd=(
        "restic" "forget"
        "--keep-weekly" "1"
        "--keep-monthly" "1"
        "--prune"
        "--verbose"
    )
    
    if [ "$dry_run" = "true" ]; then
        forget_cmd+=("--dry-run")
    fi
    
    log "Executing: ${forget_cmd[*]}"
    
    if "${forget_cmd[@]}"; then
        log "Retention policy applied successfully"
    else
        log_error "Failed to apply retention policy"
        exit 1
    fi
}

# Main function
main() {
    local tag="${1:-weekly}"
    local dry_run="false"
    
    # Set global variable for cleanup function
    CURRENT_BACKUP_TAG="$tag"
    
    # Parse arguments
    if [ "${2:-}" = "--dry-run" ]; then
        dry_run="true"
        log "DRY RUN MODE - No changes will be made"
    fi
    
    # Validate tag
    if [[ "$tag" != "weekly" && "$tag" != "monthly" ]]; then
        log_error "Invalid tag: $tag. Must be 'weekly' or 'monthly'"
        exit 1
    fi
    
    # For monthly backups, verify it's actually the last day of the month
    if [ "$tag" = "monthly" ]; then
        if ! is_last_day_of_month; then
            log_error "Monthly backup requested but today is not the last day of the month"
            exit 1
        fi
    fi
    
    log "=== Starting Restic Backup Process ==="
    log "Tag: $tag"
    log "Dry run: $dry_run"
    log "Repository: $RESTIC_REPOSITORY"
    log "Backup paths: $BACKUP_PATHS"
    
    # Run preflight checks
    log "Running preflight checks..."
    if ! "$SCRIPT_DIR/preflight.sh"; then
        log_error "Preflight checks failed"
        exit 1
    fi
    
    # Validate environment
    validate_env
    
    # Parse and validate backup paths
    parse_backup_paths
    
    # Initialize repository if needed
    init_repository
    
    # Perform backup
    perform_backup "$tag" "$dry_run"
    
    # Apply retention policy
    apply_retention "$dry_run"
    
    # Show current snapshots
    log "Current snapshots:"
    restic snapshots --compact | tee -a "$LOG_FILE"
    
    log "=== Backup Process Completed Successfully ==="
    
    # Update last backup timestamp for healthcheck
    if [ "$dry_run" = "false" ]; then
        date +%s > "${LOG_DIR}/last_backup_timestamp"
        
        # Send success notification
        local success_message="Backup $tag realizado com sucesso!

📊 *Estatísticas:*
• Tag: $tag
• Repositório: $RESTIC_REPOSITORY
• Paths: $BACKUP_PATHS

$(restic snapshots --compact | tail -5)"
        
        if command -v "$SCRIPT_DIR/notify.sh" >/dev/null 2>&1; then
            "$SCRIPT_DIR/notify.sh" "success" "$success_message" "$LOG_FILE"
        fi
    fi
}

# Check if script is being sourced or executed
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi