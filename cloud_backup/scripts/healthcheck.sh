#!/bin/bash

set -euo pipefail

# Health check script for backup system
# Returns 0 if system is healthy, 1 if unhealthy

# Configuration
LOG_DIR="/var/log/backup"
LAST_BACKUP_FILE="${LOG_DIR}/last_backup_timestamp"
MAX_BACKUP_AGE_HOURS=${MAX_BACKUP_AGE_HOURS:-192}  # 8 days by default
MAX_CHECK_AGE_HOURS=${MAX_CHECK_AGE_HOURS:-720}    # 30 days by default

# Logging functions
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] HEALTHCHECK: $*"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] HEALTHCHECK ERROR: $*" >&2
}

# Check if required binaries are available
check_binaries() {
    local required_binaries=("restic" "rclone")
    
    for binary in "${required_binaries[@]}"; do
        if ! command -v "$binary" &>/dev/null; then
            log_error "Required binary not found: $binary"
            return 1
        fi
    done
    
    return 0
}

# Check environment variables
check_environment() {
    local required_vars=(
        "RESTIC_PASSWORD"
        "RESTIC_REPOSITORY"
    )
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ]; then
            log_error "Required environment variable not set: $var"
            return 1
        fi
    done
    
    return 0
}

# Check if last backup is within acceptable age
check_last_backup_age() {
    if [ ! -f "$LAST_BACKUP_FILE" ]; then
        log_error "Last backup timestamp file not found: $LAST_BACKUP_FILE"
        return 1
    fi
    
    local last_backup_timestamp
    last_backup_timestamp=$(cat "$LAST_BACKUP_FILE")
    
    if ! [[ "$last_backup_timestamp" =~ ^[0-9]+$ ]]; then
        log_error "Invalid timestamp in last backup file: $last_backup_timestamp"
        return 1
    fi
    
    local current_timestamp
    current_timestamp=$(date +%s)
    
    local age_seconds
    age_seconds=$((current_timestamp - last_backup_timestamp))
    
    local max_age_seconds
    max_age_seconds=$((MAX_BACKUP_AGE_HOURS * 3600))
    
    if [ $age_seconds -gt $max_age_seconds ]; then
        local age_hours
        age_hours=$((age_seconds / 3600))
        log_error "Last backup is too old: ${age_hours} hours ago (max: ${MAX_BACKUP_AGE_HOURS} hours)"
        return 1
    fi
    
    local age_hours
    age_hours=$((age_seconds / 3600))
    log "Last backup age: ${age_hours} hours ago (within ${MAX_BACKUP_AGE_HOURS} hour limit)"
    
    return 0
}

# Check repository connectivity
check_repository_connectivity() {
    log "Checking repository connectivity..."
    
    # Test basic connectivity with timeout
    if ! timeout 30 restic snapshots --last 1 >/dev/null 2>&1; then
        log_error "Cannot connect to restic repository"
        return 1
    fi
    
    log "Repository is accessible"
    return 0
}

# Check repository integrity (if due)
check_repository_integrity() {
    local check_file="${LOG_DIR}/last_check_timestamp"
    local current_timestamp
    current_timestamp=$(date +%s)
    
    # Check if integrity check is due
    if [ -f "$check_file" ]; then
        local last_check_timestamp
        last_check_timestamp=$(cat "$check_file")
        
        if [[ "$last_check_timestamp" =~ ^[0-9]+$ ]]; then
            local check_age_seconds
            check_age_seconds=$((current_timestamp - last_check_timestamp))
            
            local max_check_age_seconds
            max_check_age_seconds=$((MAX_CHECK_AGE_HOURS * 3600))
            
            if [ $check_age_seconds -lt $max_check_age_seconds ]; then
                local check_age_hours
                check_age_hours=$((check_age_seconds / 3600))
                log "Repository integrity last checked ${check_age_hours} hours ago (within ${MAX_CHECK_AGE_HOURS} hour limit)"
                return 0
            fi
        fi
    fi
    
    log "Running repository integrity check..."
    
    # Run integrity check with timeout
    if timeout 300 restic check --read-data-subset=5% >/dev/null 2>&1; then
        log "Repository integrity check passed"
        echo "$current_timestamp" > "$check_file"
        return 0
    else
        log_error "Repository integrity check failed"
        return 1
    fi
}

# Check available disk space
check_disk_space() {
    local log_dir_space
    log_dir_space=$(df "$LOG_DIR" | awk 'NR==2 {print $4}')
    log_dir_space=$((log_dir_space * 1024))  # Convert to bytes
    
    # Require at least 100MB free space
    local min_required=$((100 * 1024 * 1024))
    
    if [ "$log_dir_space" -lt "$min_required" ]; then
        log_error "Insufficient disk space in log directory. Available: $(numfmt --to=iec $log_dir_space)"
        return 1
    fi
    
    log "Sufficient disk space available: $(numfmt --to=iec $log_dir_space)"
    return 0
}

# Check for critical errors in recent logs
check_recent_logs() {
    local recent_logs
    recent_logs=$(find "$LOG_DIR" -name "backup-*.log" -mtime -1 2>/dev/null | head -5)
    
    if [ -z "$recent_logs" ]; then
        log "No recent backup logs found"
        return 0
    fi
    
    local error_count=0
    
    while IFS= read -r log_file; do
        [ ! -f "$log_file" ] && continue
        
        local errors
        errors=$(grep -c "ERROR:" "$log_file" 2>/dev/null || echo "0")
        
        if [ "$errors" -gt 0 ]; then
            error_count=$((error_count + errors))
        fi
    done <<< "$recent_logs"
    
    if [ $error_count -gt 0 ]; then
        log_error "Found $error_count errors in recent backup logs"
        return 1
    fi
    
    log "No errors found in recent backup logs"
    return 0
}

# Check restic cache size
check_cache_size() {
    local cache_dir="${HOME}/.cache/restic"
    
    if [ -d "$cache_dir" ]; then
        local cache_size
        cache_size=$(du -sb "$cache_dir" 2>/dev/null | cut -f1 || echo "0")
        
        # Warn if cache is larger than 5GB
        local max_cache_size=$((5 * 1024 * 1024 * 1024))
        
        if [ "$cache_size" -gt "$max_cache_size" ]; then
            log_error "Restic cache is very large: $(numfmt --to=iec $cache_size). Consider cleaning."
            return 1
        fi
        
        log "Restic cache size: $(numfmt --to=iec $cache_size)"
    else
        log "Restic cache directory not found (may be first run)"
    fi
    
    return 0
}

# Show backup statistics
show_backup_stats() {
    log "=== Backup Statistics ==="
    
    # Show snapshot count
    local snapshot_count
    snapshot_count=$(restic snapshots --compact 2>/dev/null | grep -c "^[0-9a-f]" || echo "0")
    log "Total snapshots: $snapshot_count"
    
    # Show latest snapshot info
    if [ "$snapshot_count" -gt 0 ]; then
        local latest_snapshot
        latest_snapshot=$(restic snapshots --last 1 --json 2>/dev/null | jq -r '.[0].time' 2>/dev/null || echo "unknown")
        log "Latest snapshot: $latest_snapshot"
        
        # Show repository size
        local repo_size
        repo_size=$(restic stats --mode raw-data 2>/dev/null | grep "Total Size" | awk '{print $3, $4}' || echo "unknown")
        log "Repository size: $repo_size"
    fi
    
    log "========================="
}

# Main function
main() {
    local exit_code=0
    
    # Ensure log directory exists
    mkdir -p "$LOG_DIR"
    
    log "=== Starting Health Check ==="
    
    # Define checks that must pass
    local critical_checks=(
        "check_binaries"
        "check_environment"
        "check_repository_connectivity"
        "check_last_backup_age"
        "check_disk_space"
    )
    
    # Define checks that are warnings only
    local warning_checks=(
        "check_recent_logs"
        "check_cache_size"
    )
    
    # Run critical checks
    for check in "${critical_checks[@]}"; do
        if ! "$check"; then
            exit_code=1
        fi
    done
    
    # Run warning checks (don't fail health check)
    for check in "${warning_checks[@]}"; do
        "$check" || log "Warning check failed: $check"
    done
    
    # Run integrity check if needed (don't fail health check if it fails)
    check_repository_integrity || log "Integrity check failed or skipped"
    
    # Show statistics if repository is accessible
    if [ $exit_code -eq 0 ]; then
        show_backup_stats
    fi
    
    if [ $exit_code -eq 0 ]; then
        log "=== Health Check PASSED ==="
    else
        log_error "=== Health Check FAILED ==="
    fi
    
    exit $exit_code
}

# Check if script is being sourced or executed
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi