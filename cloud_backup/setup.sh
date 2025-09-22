#!/bin/bash

set -euo pipefail

# Setup script for cloud backup system
# Creates the directory structure and copies files to /mnt/m2/docker/cloud_backup/

# Configuration
BACKUP_BASE_DIR="/mnt/m2/docker/cloud_backup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo -e "${GREEN}[SETUP]${NC} $*"
}

log_warning() {
    echo -e "${YELLOW}[SETUP WARNING]${NC} $*"
}

log_error() {
    echo -e "${RED}[SETUP ERROR]${NC} $*" >&2
}

# Check if running as root or with sufficient permissions
check_permissions() {
    log "Checking permissions for $BACKUP_BASE_DIR..."
    
    # Check if we can create the base directory
    if ! mkdir -p "$BACKUP_BASE_DIR" 2>/dev/null; then
        log_error "Cannot create directory $BACKUP_BASE_DIR"
        log_error "Please run with sudo or ensure you have write permissions"
        exit 1
    fi
    
    log "✓ Permissions OK"
}

# Create directory structure
create_directories() {
    log "Creating directory structure..."
    
    local directories=(
        "$BACKUP_BASE_DIR"
        "$BACKUP_BASE_DIR/scripts"
        "$BACKUP_BASE_DIR/data"
        "$BACKUP_BASE_DIR/data/restic-cache"
        "$BACKUP_BASE_DIR/data/rclone-config"
        "$BACKUP_BASE_DIR/logs"
        "$BACKUP_BASE_DIR/config"
    )
    
    for dir in "${directories[@]}"; do
        if mkdir -p "$dir"; then
            log "✓ Created: $dir"
        else
            log_error "Failed to create: $dir"
            exit 1
        fi
    done
    
    # Set appropriate permissions
    chmod 755 "$BACKUP_BASE_DIR"
    chmod 755 "$BACKUP_BASE_DIR/scripts"
    chmod 750 "$BACKUP_BASE_DIR/data"
    chmod 755 "$BACKUP_BASE_DIR/logs"
    chmod 750 "$BACKUP_BASE_DIR/config"
    
    log "✓ Directory structure created successfully"
}

# Copy scripts
copy_scripts() {
    log "Copying scripts..."
    
    if [ ! -d "$SCRIPT_DIR/scripts" ]; then
        log_error "Scripts directory not found: $SCRIPT_DIR/scripts"
        exit 1
    fi
    
    # Copy all scripts
    if cp -r "$SCRIPT_DIR/scripts/"* "$BACKUP_BASE_DIR/scripts/"; then
        log "✓ Scripts copied successfully"
    else
        log_error "Failed to copy scripts"
        exit 1
    fi
    
    # Make scripts executable
    chmod +x "$BACKUP_BASE_DIR/scripts/"*.sh
    log "✓ Scripts made executable"
}

# Copy configuration files
copy_configs() {
    log "Copying configuration files..."
    
    local config_files=(
        "docker-compose.yml"
        "Dockerfile"
        ".env.example"
        "crontab"
        "README.md"
    )
    
    for file in "${config_files[@]}"; do
        if [ -f "$SCRIPT_DIR/$file" ]; then
            if cp "$SCRIPT_DIR/$file" "$BACKUP_BASE_DIR/"; then
                log "✓ Copied: $file"
            else
                log_error "Failed to copy: $file"
                exit 1
            fi
        else
            log_warning "File not found: $file"
        fi
    done
    
    # Copy .env.example as .env if .env doesn't exist
    if [ ! -f "$BACKUP_BASE_DIR/.env" ] && [ -f "$BACKUP_BASE_DIR/.env.example" ]; then
        cp "$BACKUP_BASE_DIR/.env.example" "$BACKUP_BASE_DIR/.env"
        log "✓ Created .env from .env.example"
        log_warning "Please edit $BACKUP_BASE_DIR/.env with your configuration"
    fi
}

# Create helpful symlinks
create_symlinks() {
    log "Creating helpful symlinks..."
    
    # Create symlink in original directory for convenience
    local symlink_path="$SCRIPT_DIR/config"
    if [ ! -L "$symlink_path" ] && [ ! -e "$symlink_path" ]; then
        if ln -s "$BACKUP_BASE_DIR" "$symlink_path"; then
            log "✓ Created symlink: $symlink_path -> $BACKUP_BASE_DIR"
        else
            log_warning "Could not create symlink: $symlink_path"
        fi
    fi
}

# Create initial rclone config directory structure
setup_rclone() {
    log "Setting up rclone configuration structure..."
    
    local rclone_config_dir="$BACKUP_BASE_DIR/data/rclone-config"
    
    # Create rclone config file if it doesn't exist
    if [ ! -f "$rclone_config_dir/rclone.conf" ]; then
        touch "$rclone_config_dir/rclone.conf"
        chmod 600 "$rclone_config_dir/rclone.conf"
        log "✓ Created empty rclone.conf"
        log_warning "You need to configure rclone. See README.md for instructions"
    fi
    
    # Create rclone config helper script
    cat > "$BACKUP_BASE_DIR/configure-rclone.sh" << 'EOF'
#!/bin/bash
# Helper script to configure rclone

RCLONE_CONFIG_DIR="/mnt/m2/docker/cloud_backup/data/rclone-config"

echo "Configuring rclone for backup system..."
echo "Config will be saved to: $RCLONE_CONFIG_DIR/rclone.conf"
echo ""

# Run rclone config with custom config location
RCLONE_CONFIG="$RCLONE_CONFIG_DIR/rclone.conf" rclone config

echo ""
echo "rclone configuration completed!"
echo "Config saved to: $RCLONE_CONFIG_DIR/rclone.conf"
echo ""
echo "Next steps:"
echo "1. Edit /mnt/m2/docker/cloud_backup/.env with your settings"
echo "2. Test with: cd /mnt/m2/docker/cloud_backup && docker compose up -d"
EOF
    
    chmod +x "$BACKUP_BASE_DIR/configure-rclone.sh"
    log "✓ Created rclone configuration helper script"
}

# Show completion summary
show_summary() {
    log ""
    log "=== Setup Complete! ==="
    log ""
    log "📁 Base directory: $BACKUP_BASE_DIR"
    log "📁 Configuration: $BACKUP_BASE_DIR/.env"
    log "📁 Scripts: $BACKUP_BASE_DIR/scripts/"
    log "📁 Logs: $BACKUP_BASE_DIR/logs/"
    log "📁 Data: $BACKUP_BASE_DIR/data/"
    log ""
    log "🔧 Next steps:"
    log "1. Configure rclone:"
    log "   $BACKUP_BASE_DIR/configure-rclone.sh"
    log ""
    log "2. Edit configuration:"
    log "   nano $BACKUP_BASE_DIR/.env"
    log ""
    log "3. Start the backup system:"
    log "   cd $BACKUP_BASE_DIR"
    log "   docker compose up -d"
    log ""
    log "4. Test manual backup:"
    log "   docker exec backup-restic /scripts/backup.sh weekly --dry-run"
    log ""
    log "📖 Full documentation: $BACKUP_BASE_DIR/README.md"
    log ""
}

# Show directory structure
show_structure() {
    log "Directory structure created:"
    log ""
    
    if command -v tree >/dev/null 2>&1; then
        tree "$BACKUP_BASE_DIR" -L 3
    else
        find "$BACKUP_BASE_DIR" -type d | sed 's/[^/]*\//  /g'
    fi
    
    log ""
}

# Main function
main() {
    log "Starting backup system setup..."
    log "Target directory: $BACKUP_BASE_DIR"
    log ""
    
    # Pre-setup checks
    check_permissions
    
    # Setup steps
    create_directories
    copy_scripts
    copy_configs
    create_symlinks
    setup_rclone
    
    # Post-setup
    show_structure
    show_summary
    
    log "✅ Setup completed successfully!"
}

# Show usage
show_usage() {
    cat << EOF
Usage: $0 [options]

Setup script for cloud backup system

Options:
  -h, --help     Show this help message
  -f, --force    Force setup even if directory exists

This script will:
1. Create directory structure in /mnt/m2/docker/cloud_backup/
2. Copy all necessary files and scripts
3. Set appropriate permissions
4. Create helper scripts for configuration

EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_usage
            exit 0
            ;;
        -f|--force)
            FORCE_SETUP=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Check if directory exists and handle accordingly
if [ -d "$BACKUP_BASE_DIR" ] && [ "$(ls -A "$BACKUP_BASE_DIR" 2>/dev/null)" ] && [ "${FORCE_SETUP:-false}" != "true" ]; then
    log_warning "Directory $BACKUP_BASE_DIR already exists and is not empty"
    log_warning "Use --force to overwrite, or remove the directory first"
    log "Current contents:"
    ls -la "$BACKUP_BASE_DIR"
    exit 1
fi

# Run main setup
main