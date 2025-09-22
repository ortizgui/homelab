#!/bin/bash

set -euo pipefail

# Preflight checks for backup system
# Validates connectivity, permissions, and system requirements

# Configuration
LOG_DIR="/var/log/backup"
TEMP_DIR="/tmp/backup-preflight"

# Logging functions
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] PREFLIGHT: $*"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] PREFLIGHT ERROR: $*" >&2
}

log_warning() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] PREFLIGHT WARNING: $*"
}

# Cleanup function
cleanup() {
    [ -d "$TEMP_DIR" ] && rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

# Check if required binaries are available
check_binaries() {
    log "Checking required binaries..."
    
    local required_binaries=("restic" "rclone" "curl" "date")
    local missing_binaries=()
    
    for binary in "${required_binaries[@]}"; do
        if ! command -v "$binary" &>/dev/null; then
            missing_binaries+=("$binary")
        else
            log "✓ $binary: $(command -v "$binary")"
        fi
    done
    
    if [ ${#missing_binaries[@]} -gt 0 ]; then
        log_error "Missing required binaries: ${missing_binaries[*]}"
        return 1
    fi
    
    log "All required binaries are available"
    return 0
}

# Check environment variables
check_environment() {
    log "Checking environment variables..."
    
    local required_vars=(
        "RESTIC_PASSWORD"
        "RESTIC_REPOSITORY"
        "BACKUP_PATHS"
    )
    
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ]; then
            missing_vars+=("$var")
        else
            log "✓ $var is set"
        fi
    done
    
    if [ ${#missing_vars[@]} -gt 0 ]; then
        log_error "Missing required environment variables: ${missing_vars[*]}"
        return 1
    fi
    
    # Check password strength (basic check)
    if [ ${#RESTIC_PASSWORD} -lt 8 ]; then
        log_warning "RESTIC_PASSWORD is less than 8 characters. Consider using a stronger password."
    fi
    
    log "Environment variables check passed"
    return 0
}

# Check network connectivity
check_connectivity() {
    log "Checking network connectivity..."
    
    # Test basic internet connectivity
    if ! curl -s --connect-timeout 10 https://www.google.com >/dev/null; then
        log_error "No internet connectivity"
        return 1
    fi
    
    log "✓ Internet connectivity available"
    
    # Test DNS resolution
    if ! nslookup google.com >/dev/null 2>&1; then
        log_warning "DNS resolution issues detected"
    else
        log "✓ DNS resolution working"
    fi
    
    return 0
}

# Check rclone configuration
check_rclone_config() {
    log "Checking rclone configuration..."
    
    # Extract remote name from RESTIC_REPOSITORY
    if [[ "$RESTIC_REPOSITORY" =~ ^rclone:([^:/]+): ]]; then
        local remote_name="${BASH_REMATCH[1]}"
        log "Detected rclone remote: $remote_name"
        
        # Check if remote is configured
        if ! rclone listremotes | grep -q "^${remote_name}:$"; then
            log_error "rclone remote '$remote_name' not found in configuration"
            log_error "Available remotes: $(rclone listremotes | tr '\n' ' ')"
            return 1
        fi
        
        log "✓ rclone remote '$remote_name' is configured"
        
        # Test remote connectivity with timeout
        log "Testing remote connectivity..."
        if timeout 30 rclone lsd "${remote_name}:" >/dev/null 2>&1; then
            log "✓ rclone remote '$remote_name' is accessible"
        else
            log_error "Cannot access rclone remote '$remote_name'"
            return 1
        fi
        
    else
        log_warning "RESTIC_REPOSITORY doesn't appear to use rclone backend"
    fi
    
    return 0
}

# Check backup source paths
check_backup_paths() {
    log "Checking backup source paths..."
    
    # Parse backup paths
    IFS=':' read -ra PATHS <<< "$BACKUP_PATHS"
    
    local issues=0
    
    for path in "${PATHS[@]}"; do
        if [ ! -d "$path" ]; then
            log_error "Backup path does not exist: $path"
            ((issues++))
            continue
        fi
        
        if [ ! -r "$path" ]; then
            log_error "Cannot read backup path: $path"
            ((issues++))
            continue
        fi
        
        # Check if path has content
        local file_count
        file_count=$(find "$path" -type f 2>/dev/null | wc -l)
        
        if [ "$file_count" -eq 0 ]; then
            log_warning "Backup path appears to be empty: $path"
        else
            log "✓ $path ($file_count files)"
        fi
    done
    
    if [ $issues -gt 0 ]; then
        log_error "$issues backup path issues found"
        return 1
    fi
    
    log "All backup paths are accessible"
    return 0
}

# Check available disk space
check_disk_space() {
    log "Checking disk space..."
    
    mkdir -p "$TEMP_DIR"
    
    # Check available space in temp directory (for restic cache)
    local temp_available
    temp_available=$(df "$TEMP_DIR" | awk 'NR==2 {print $4}')
    temp_available=$((temp_available * 1024))  # Convert to bytes
    
    # Require at least 1GB free space
    local min_required=$((1024 * 1024 * 1024))
    
    if [ "$temp_available" -lt "$min_required" ]; then
        log_error "Insufficient disk space in temp directory. Available: $(numfmt --to=iec $temp_available), Required: $(numfmt --to=iec $min_required)"
        return 1
    fi
    
    log "✓ Sufficient disk space available: $(numfmt --to=iec $temp_available)"
    
    # Check space in backup source paths
    IFS=':' read -ra PATHS <<< "$BACKUP_PATHS"
    
    for path in "${PATHS[@]}"; do
        [ ! -d "$path" ] && continue
        
        local path_size
        path_size=$(du -sb "$path" 2>/dev/null | cut -f1 || echo "0")
        
        if [ "$path_size" -gt 0 ]; then
            log "Source path size: $path = $(numfmt --to=iec $path_size)"
        fi
    done
    
    return 0
}

# Check restic repository accessibility
check_restic_repository() {
    log "Checking restic repository accessibility..."
    
    # Test if we can connect to the repository
    if restic cat config >/dev/null 2>&1; then
        log "✓ Existing repository is accessible"
        
        # Show repository stats
        local stats
        stats=$(restic stats --mode raw-data 2>/dev/null | grep "Total Size" | awk '{print $3, $4}' || echo "unknown")
        log "Repository size: $stats"
        
    elif restic snapshots >/dev/null 2>&1; then
        log "✓ Repository exists but may be empty"
    else
        log "Repository not accessible (will be initialized on first backup)"
    fi
    
    return 0
}

# Check system resources
check_system_resources() {
    log "Checking system resources..."
    
    # Check memory usage
    local mem_available
    if [ -f /proc/meminfo ]; then
        mem_available=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
        mem_available=$((mem_available * 1024))  # Convert to bytes
        
        # Require at least 512MB available memory
        local min_mem=$((512 * 1024 * 1024))
        
        if [ "$mem_available" -lt "$min_mem" ]; then
            log_warning "Low memory available: $(numfmt --to=iec $mem_available)"
        else
            log "✓ Memory available: $(numfmt --to=iec $mem_available)"
        fi
    fi
    
    # Check CPU load
    if [ -f /proc/loadavg ]; then
        local load_avg
        load_avg=$(cut -d' ' -f1 /proc/loadavg)
        log "Current load average: $load_avg"
        
        # Warning if load is high (>2.0)
        if awk "BEGIN {exit !($load_avg > 2.0)}"; then
            log_warning "High system load detected: $load_avg"
        fi
    fi
    
    return 0
}

# Check log directory permissions
check_log_permissions() {
    log "Checking log directory permissions..."
    
    mkdir -p "$LOG_DIR"
    
    if [ ! -w "$LOG_DIR" ]; then
        log_error "Cannot write to log directory: $LOG_DIR"
        return 1
    fi
    
    # Test write access
    local test_file="$LOG_DIR/preflight-test-$$"
    if echo "test" > "$test_file" 2>/dev/null; then
        rm -f "$test_file"
        log "✓ Log directory is writable: $LOG_DIR"
    else
        log_error "Cannot write test file to log directory: $LOG_DIR"
        return 1
    fi
    
    return 0
}

# Main function
main() {
    log "=== Starting Preflight Checks ==="
    
    local checks=(
        "check_binaries"
        "check_environment"
        "check_log_permissions"
        "check_backup_paths"
        "check_disk_space"
        "check_connectivity"
        "check_rclone_config"
        "check_restic_repository"
        "check_system_resources"
    )
    
    local failed_checks=()
    
    for check in "${checks[@]}"; do
        if ! "$check"; then
            failed_checks+=("$check")
        fi
    done
    
    if [ ${#failed_checks[@]} -gt 0 ]; then
        log_error "Preflight checks failed: ${failed_checks[*]}"
        log "=== Preflight Checks FAILED ==="
        exit 1
    fi
    
    log "=== All Preflight Checks PASSED ==="
    exit 0
}

# Check if script is being sourced or executed
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi