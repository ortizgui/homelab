#!/bin/bash

set -euo pipefail

# Restore script for Restic backups
# Usage: restore.sh [command] [options]
#   Commands:
#     list-snapshots                          - List all available snapshots
#     list-files <snapshot-id>               - List files in a specific snapshot
#     restore-snapshot <snapshot-id> <dest> - Restore entire snapshot to destination
#     restore-path <snapshot-id> <path> <dest> - Restore specific path from snapshot
#     latest-snapshot                        - Show latest snapshot info
#     search-file <filename>                 - Search for a file across all snapshots

# Configuration
LOG_DIR="/var/log/backup"
RESTORE_LOG="${LOG_DIR}/restore-$(date +%Y%m%d-%H%M%S).log"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Logging functions
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] RESTORE: $*" | tee -a "$RESTORE_LOG"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] RESTORE ERROR: $*" | tee -a "$RESTORE_LOG" >&2
}

# Cleanup function
cleanup() {
    local exit_code=$?
    if [ $exit_code -ne 0 ]; then
        log_error "Restore operation failed with exit code $exit_code"
    fi
    exit $exit_code
}

trap cleanup EXIT

# Validate environment variables
validate_env() {
    local required_vars=(
        "RESTIC_PASSWORD"
        "RESTIC_REPOSITORY"
    )
    
    for var in "${required_vars[@]}"; do
        if [ -z "${!var:-}" ]; then
            log_error "Required environment variable $var is not set"
            exit 1
        fi
    done
}

# Check if restic repository is accessible
check_repository() {
    log "Checking repository accessibility..."
    
    if ! restic snapshots >/dev/null 2>&1; then
        log_error "Cannot access restic repository: $RESTIC_REPOSITORY"
        exit 1
    fi
    
    log "Repository is accessible"
}

# List all snapshots
list_snapshots() {
    log "Listing all snapshots..."
    
    echo ""
    echo "=== Available Snapshots ==="
    restic snapshots --compact
    echo ""
    
    # Show summary
    local total_snapshots
    total_snapshots=$(restic snapshots --compact | grep -c "^[0-9a-f]" || echo "0")
    log "Total snapshots: $total_snapshots"
}

# List files in a specific snapshot
list_files() {
    local snapshot_id="$1"
    
    if [ -z "$snapshot_id" ]; then
        log_error "Snapshot ID is required"
        show_usage
        exit 1
    fi
    
    log "Listing files in snapshot: $snapshot_id"
    
    echo ""
    echo "=== Files in Snapshot $snapshot_id ==="
    
    if restic ls "$snapshot_id"; then
        echo ""
        log "File listing completed successfully"
    else
        log_error "Failed to list files in snapshot: $snapshot_id"
        exit 1
    fi
}

# Restore entire snapshot
restore_snapshot() {
    local snapshot_id="$1"
    local dest_dir="$2"
    
    if [ -z "$snapshot_id" ] || [ -z "$dest_dir" ]; then
        log_error "Both snapshot ID and destination directory are required"
        show_usage
        exit 1
    fi
    
    # Validate destination directory
    if [ -e "$dest_dir" ]; then
        log_error "Destination already exists: $dest_dir"
        log_error "Please choose a non-existing destination directory to avoid overwrites"
        exit 1
    fi
    
    # Create destination directory
    mkdir -p "$dest_dir"
    
    log "Restoring snapshot $snapshot_id to $dest_dir"
    
    echo ""
    echo "=== Restoring Snapshot $snapshot_id ==="
    
    if restic restore "$snapshot_id" --target "$dest_dir" --verbose; then
        echo ""
        log "Snapshot restored successfully to: $dest_dir"
        
        # Show restore summary
        local restored_files
        restored_files=$(find "$dest_dir" -type f | wc -l)
        log "Total files restored: $restored_files"
        
        local restore_size
        restore_size=$(du -sh "$dest_dir" | cut -f1)
        log "Total size restored: $restore_size"
        
    else
        log_error "Failed to restore snapshot: $snapshot_id"
        exit 1
    fi
}

# Restore specific path from snapshot
restore_path() {
    local snapshot_id="$1"
    local source_path="$2"
    local dest_dir="$3"
    
    if [ -z "$snapshot_id" ] || [ -z "$source_path" ] || [ -z "$dest_dir" ]; then
        log_error "Snapshot ID, source path, and destination directory are required"
        show_usage
        exit 1
    fi
    
    # Validate destination directory
    if [ -e "$dest_dir" ]; then
        log_error "Destination already exists: $dest_dir"
        log_error "Please choose a non-existing destination directory to avoid overwrites"
        exit 1
    fi
    
    # Create destination directory
    mkdir -p "$dest_dir"
    
    log "Restoring path '$source_path' from snapshot $snapshot_id to $dest_dir"
    
    echo ""
    echo "=== Restoring Path from Snapshot $snapshot_id ==="
    echo "Source path: $source_path"
    echo "Destination: $dest_dir"
    echo ""
    
    if restic restore "$snapshot_id" --target "$dest_dir" --include "$source_path" --verbose; then
        echo ""
        log "Path restored successfully to: $dest_dir"
        
        # Show restore summary
        local restored_files
        restored_files=$(find "$dest_dir" -type f | wc -l)
        log "Total files restored: $restored_files"
        
        if [ "$restored_files" -eq 0 ]; then
            log_error "No files were restored. Check if the path exists in the snapshot."
            log "Tip: Use 'list-files $snapshot_id' to see available paths"
        fi
        
    else
        log_error "Failed to restore path: $source_path"
        exit 1
    fi
}

# Show latest snapshot information
latest_snapshot() {
    log "Getting latest snapshot information..."
    
    echo ""
    echo "=== Latest Snapshot Information ==="
    
    if restic snapshots --last 1; then
        echo ""
        
        # Get snapshot ID for additional info
        local latest_id
        latest_id=$(restic snapshots --last 1 --json | jq -r '.[0].short_id' 2>/dev/null || echo "")
        
        if [ -n "$latest_id" ]; then
            echo "=== Files in Latest Snapshot ==="
            restic ls "$latest_id" | head -20
            
            local total_files
            total_files=$(restic ls "$latest_id" | wc -l)
            echo ""
            log "Total files in latest snapshot: $total_files"
            
            if [ "$total_files" -gt 20 ]; then
                log "Showing first 20 files. Use 'list-files $latest_id' to see all files."
            fi
        fi
        
    else
        log_error "No snapshots found"
        exit 1
    fi
}

# Search for a file across all snapshots
search_file() {
    local filename="$1"
    
    if [ -z "$filename" ]; then
        log_error "Filename is required"
        show_usage
        exit 1
    fi
    
    log "Searching for file: $filename"
    
    echo ""
    echo "=== Searching for '$filename' across all snapshots ==="
    echo ""
    
    # Get all snapshot IDs
    local snapshots
    snapshots=$(restic snapshots --compact | grep "^[0-9a-f]" | awk '{print $1}')
    
    local found_count=0
    
    while IFS= read -r snapshot_id; do
        [ -z "$snapshot_id" ] && continue
        
        echo "Checking snapshot: $snapshot_id"
        
        # Search for files matching the pattern
        local matches
        matches=$(restic ls "$snapshot_id" | grep -i "$filename" || true)
        
        if [ -n "$matches" ]; then
            echo "  Found in snapshot $snapshot_id:"
            echo "$matches" | sed 's/^/    /'
            echo ""
            ((found_count++))
        fi
        
    done <<< "$snapshots"
    
    if [ $found_count -eq 0 ]; then
        log "File '$filename' not found in any snapshot"
    else
        log "File '$filename' found in $found_count snapshot(s)"
    fi
}

# Interactive restore mode
interactive_restore() {
    log "Starting interactive restore mode..."
    
    echo ""
    echo "=== Interactive Restore Mode ==="
    echo ""
    
    # Show available snapshots
    echo "Available snapshots:"
    restic snapshots --compact
    echo ""
    
    # Get snapshot selection
    read -p "Enter snapshot ID (or 'latest' for most recent): " snapshot_choice
    
    if [ "$snapshot_choice" = "latest" ]; then
        snapshot_choice=$(restic snapshots --last 1 --json | jq -r '.[0].short_id' 2>/dev/null || echo "")
        if [ -z "$snapshot_choice" ]; then
            log_error "Could not determine latest snapshot"
            exit 1
        fi
        echo "Using latest snapshot: $snapshot_choice"
    fi
    
    # Show files in selected snapshot
    echo ""
    echo "Files in snapshot $snapshot_choice (showing first 20):"
    restic ls "$snapshot_choice" | head -20
    echo ""
    
    # Get restore type
    echo "Restore options:"
    echo "1) Restore entire snapshot"
    echo "2) Restore specific path"
    echo ""
    read -p "Choose option (1 or 2): " restore_option
    
    case "$restore_option" in
        1)
            read -p "Enter destination directory: " dest_dir
            restore_snapshot "$snapshot_choice" "$dest_dir"
            ;;
        2)
            read -p "Enter path to restore: " source_path
            read -p "Enter destination directory: " dest_dir
            restore_path "$snapshot_choice" "$source_path" "$dest_dir"
            ;;
        *)
            log_error "Invalid option selected"
            exit 1
            ;;
    esac
}

# Show usage information
show_usage() {
    cat << EOF

Restic Restore Tool

Usage: $0 <command> [options]

Commands:
  list-snapshots                              List all available snapshots
  list-files <snapshot-id>                   List files in a specific snapshot  
  restore-snapshot <snapshot-id> <dest-dir>  Restore entire snapshot to destination
  restore-path <snapshot-id> <path> <dest>   Restore specific path from snapshot
  latest-snapshot                            Show latest snapshot information
  search-file <filename>                     Search for a file across all snapshots
  interactive                                Interactive restore mode

Examples:
  $0 list-snapshots
  $0 list-files a1b2c3d4
  $0 restore-snapshot a1b2c3d4 /tmp/restore
  $0 restore-path a1b2c3d4 /home/user/documents /tmp/restore-docs
  $0 search-file "config.json"
  $0 interactive

Notes:
  - Destination directories must not exist (to prevent accidental overwrites)
  - Use short snapshot IDs (first 8 characters) for convenience
  - All restore operations create detailed logs in $LOG_DIR

EOF
}

# Main function
main() {
    local command="${1:-}"
    
    if [ -z "$command" ]; then
        show_usage
        exit 1
    fi
    
    log "=== Starting Restore Operation: $command ==="
    
    # Validate environment
    validate_env
    
    # Check repository accessibility
    check_repository
    
    # Execute command
    case "$command" in
        list-snapshots)
            list_snapshots
            ;;
        list-files)
            list_files "${2:-}"
            ;;
        restore-snapshot)
            restore_snapshot "${2:-}" "${3:-}"
            ;;
        restore-path)
            restore_path "${2:-}" "${3:-}" "${4:-}"
            ;;
        latest-snapshot)
            latest_snapshot
            ;;
        search-file)
            search_file "${2:-}"
            ;;
        interactive)
            interactive_restore
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            log_error "Unknown command: $command"
            show_usage
            exit 1
            ;;
    esac
    
    log "=== Restore Operation Completed Successfully ==="
}

# Check if script is being sourced or executed
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi