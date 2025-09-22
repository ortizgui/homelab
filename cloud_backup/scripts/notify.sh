#!/bin/bash

set -euo pipefail

# Notification script for backup events
# Usage: notify.sh <event> <message> [log_file]

# Configuration
WEBHOOK_URL="${WEBHOOK_URL:-}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
NOTIFY_ON_SUCCESS="${NOTIFY_ON_SUCCESS:-false}"
NOTIFY_ON_FAILURE="${NOTIFY_ON_FAILURE:-true}"

# Colors for console output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] NOTIFY: $*"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] NOTIFY ERROR: $*${NC}" >&2
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] NOTIFY: $*${NC}"
}

log_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] NOTIFY WARNING: $*${NC}"
}

# Send Telegram notification
send_telegram() {
    local event="$1"
    local message="$2"
    local log_file="${3:-}"
    
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
        log_warning "Telegram bot token or chat ID not configured, skipping Telegram notification"
        return 0
    fi
    
    # Determine if we should send notification
    case "$event" in
        "success")
            if [ "$NOTIFY_ON_SUCCESS" != "true" ]; then
                log "Success notification disabled, skipping"
                return 0
            fi
            ;;
        "failure"|"error")
            if [ "$NOTIFY_ON_FAILURE" != "true" ]; then
                log "Failure notification disabled, skipping"
                return 0
            fi
            ;;
    esac
    
    # Prepare emoji and formatting based on event type
    local emoji
    local status_text
    case "$event" in
        "success")
            emoji="✅"
            status_text="*SUCESSO*"
            ;;
        "failure"|"error")
            emoji="❌"
            status_text="*ERRO*"
            ;;
        "warning")
            emoji="⚠️"
            status_text="*AVISO*"
            ;;
        *)
            emoji="ℹ️"
            status_text="*INFO*"
            ;;
    esac
    
    # Format message for Telegram (Markdown)
    local telegram_message
    telegram_message=$(cat <<EOF
${emoji} *Backup ${status_text}*

🖥️ *Host:* \`$(hostname)\`
⏰ *Horário:* \`$(date '+%d/%m/%Y %H:%M:%S')\`
📂 *Repositório:* \`${RESTIC_REPOSITORY:-"N/A"}\`

📝 *Detalhes:*
${message}
EOF
)
    
    # Add log snippet if provided and file exists
    if [ -n "$log_file" ] && [ -f "$log_file" ]; then
        local recent_logs
        recent_logs=$(tail -10 "$log_file" 2>/dev/null | sed 's/</\&lt;/g; s/>/\&gt;/g' | head -5)
        if [ -n "$recent_logs" ]; then
            telegram_message="${telegram_message}"$'\n\n'"📄 *Últimas linhas do log:*"$'\n'"[emoji=📝]"$'\n'"\`\`\`"$'\n'"${recent_logs}"$'\n'"\`\`\`"
        fi
    fi
    
    # Telegram API URL
    local api_url="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Prepare JSON payload
    local payload
    payload=$(cat <<EOF | jq -c .
{
    "chat_id": "$TELEGRAM_CHAT_ID",
    "text": $(echo "$telegram_message" | jq -R -s .),
    "parse_mode": "Markdown",
    "disable_web_page_preview": true
}
EOF
)
    
    # Send to Telegram with retries
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        local response
        local http_code
        
        response=$(curl -s -w "%{http_code}" \
            -X POST \
            -H "Content-Type: application/json" \
            -d "$payload" \
            --max-time 30 \
            "$api_url" 2>/dev/null || echo "000")
        
        http_code="${response: -3}"
        response_body="${response%???}"
        
        if [ "$http_code" = "200" ]; then
            log_success "Telegram notification sent successfully"
            return 0
        else
            ((retry_count++))
            log_warning "Telegram notification attempt $retry_count failed (HTTP: $http_code)"
            
            # Log error details if available
            if [ -n "$response_body" ] && command -v jq >/dev/null 2>&1; then
                local error_desc
                error_desc=$(echo "$response_body" | jq -r '.description // "Unknown error"' 2>/dev/null || echo "Parse error")
                log_warning "Telegram API error: $error_desc"
            fi
            
            if [ $retry_count -lt $max_retries ]; then
                sleep $((retry_count * 3))  # Exponential backoff
            fi
        fi
    done
    
    log_error "Failed to send Telegram notification after $max_retries attempts"
    return 1
}

# Send webhook notification
send_webhook() {
    local event="$1"
    local message="$2"
    local log_file="${3:-}"
    
    if [ -z "$WEBHOOK_URL" ]; then
        log_warning "No webhook URL configured, skipping notification"
        return 0
    fi
    
    # Determine if we should send notification
    case "$event" in
        "success")
            if [ "$NOTIFY_ON_SUCCESS" != "true" ]; then
                log "Success notification disabled, skipping"
                return 0
            fi
            ;;
        "failure"|"error")
            if [ "$NOTIFY_ON_FAILURE" != "true" ]; then
                log "Failure notification disabled, skipping"
                return 0
            fi
            ;;
    esac
    
    # Prepare payload based on webhook type
    local payload
    local content_type="application/json"
    
    # Detect webhook type and format accordingly
    if [[ "$WEBHOOK_URL" == *"hooks.slack.com"* ]]; then
        # Slack webhook
        local color
        case "$event" in
            "success") color="good" ;;
            "failure"|"error") color="danger" ;;
            *) color="warning" ;;
        esac
        
        payload=$(cat <<EOF
{
    "username": "Backup Bot",
    "icon_emoji": ":floppy_disk:",
    "attachments": [
        {
            "color": "$color",
            "title": "Backup $event",
            "text": "$message",
            "footer": "Restic Backup System",
            "ts": $(date +%s)
        }
    ]
}
EOF
)
    elif [[ "$WEBHOOK_URL" == *"discord.com"* ]]; then
        # Discord webhook
        local color_code
        case "$event" in
            "success") color_code=65280 ;;  # Green
            "failure"|"error") color_code=16711680 ;;  # Red
            *) color_code=16776960 ;;  # Yellow
        esac
        
        payload=$(cat <<EOF
{
    "username": "Backup Bot",
    "avatar_url": "https://restic.net/favicon.ico",
    "embeds": [
        {
            "title": "Backup $event",
            "description": "$message",
            "color": $color_code,
            "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)",
            "footer": {
                "text": "Restic Backup System"
            }
        }
    ]
}
EOF
)
    elif [[ "$WEBHOOK_URL" == *"office.com"* ]] || [[ "$WEBHOOK_URL" == *"outlook.office365.com"* ]]; then
        # Microsoft Teams webhook
        local theme_color
        case "$event" in
            "success") theme_color="00FF00" ;;
            "failure"|"error") theme_color="FF0000" ;;
            *) theme_color="FFFF00" ;;
        esac
        
        payload=$(cat <<EOF
{
    "@type": "MessageCard",
    "@context": "https://schema.org/extensions",
    "summary": "Backup $event",
    "themeColor": "$theme_color",
    "sections": [
        {
            "activityTitle": "Backup $event",
            "activitySubtitle": "Restic Backup System",
            "text": "$message",
            "facts": [
                {
                    "name": "Time",
                    "value": "$(date)"
                },
                {
                    "name": "Host",
                    "value": "$(hostname)"
                }
            ]
        }
    ]
}
EOF
)
    else
        # Generic webhook (simple JSON)
        payload=$(cat <<EOF
{
    "event": "$event",
    "message": "$message",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)",
    "hostname": "$(hostname)",
    "service": "restic-backup"
}
EOF
)
    fi
    
    # Send webhook with retries
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        if curl -X POST \
            -H "Content-Type: $content_type" \
            -d "$payload" \
            --max-time 30 \
            --retry 2 \
            "$WEBHOOK_URL" >/dev/null 2>&1; then
            
            log_success "Notification sent successfully"
            return 0
        else
            ((retry_count++))
            log_warning "Notification attempt $retry_count failed"
            
            if [ $retry_count -lt $max_retries ]; then
                sleep $((retry_count * 2))  # Exponential backoff
            fi
        fi
    done
    
    log_error "Failed to send notification after $max_retries attempts"
    return 1
}

# Send email notification (if configured)
send_email() {
    local event="$1"
    local message="$2"
    local log_file="${3:-}"
    
    # Check if email is configured
    if [ -z "${EMAIL_TO:-}" ] || [ -z "${EMAIL_FROM:-}" ]; then
        log "Email not configured, skipping"
        return 0
    fi
    
    # Check if sendmail/mail is available
    if ! command -v mail >/dev/null 2>&1; then
        log_warning "mail command not available, skipping email notification"
        return 0
    fi
    
    local subject="Backup $event - $(hostname)"
    local body
    
    body=$(cat <<EOF
Backup Event: $event
Time: $(date)
Host: $(hostname)
Message: $message

EOF
)
    
    # Add log file content if provided and exists
    if [ -n "$log_file" ] && [ -f "$log_file" ]; then
        body="$body"$'\n'"Recent log entries:"$'\n'
        body="$body$(tail -50 "$log_file")"
    fi
    
    # Send email
    if echo "$body" | mail -s "$subject" "${EMAIL_TO}"; then
        log_success "Email notification sent to ${EMAIL_TO}"
    else
        log_error "Failed to send email notification"
        return 1
    fi
}

# Show usage
show_usage() {
    cat << EOF
Usage: $0 <event> <message> [log_file]

Events:
  success   - Backup completed successfully
  failure   - Backup failed
  error     - System error
  warning   - Warning condition
  info      - Informational message

Examples:
  $0 success "Weekly backup completed"
  $0 failure "Backup failed: network error" /var/log/backup/error.log
  $0 warning "Low disk space detected"

Configuration (via environment variables):
  TELEGRAM_BOT_TOKEN  - Telegram bot token (primary notification method)
  TELEGRAM_CHAT_ID    - Telegram chat/channel ID
  NOTIFY_ON_SUCCESS   - Send notifications on success (true/false)
  NOTIFY_ON_FAILURE   - Send notifications on failure (true/false)
  WEBHOOK_URL         - Webhook URL for notifications (fallback)
  EMAIL_TO           - Email address for notifications
  EMAIL_FROM         - From email address

Telegram Setup:
  1. Create bot with @BotFather
  2. Get bot token
  3. Start chat with bot and send /start
  4. Get chat ID from https://api.telegram.org/bot<TOKEN>/getUpdates

EOF
}

# Main function
main() {
    local event="${1:-}"
    local message="${2:-}"
    local log_file="${3:-}"
    
    if [ -z "$event" ] || [ -z "$message" ]; then
        show_usage
        exit 1
    fi
    
    log "Sending notification: $event - $message"
    
    local notification_sent=false
    
    # Send Telegram notification (primary method)
    if send_telegram "$event" "$message" "$log_file"; then
        notification_sent=true
    fi
    
    # Send webhook notification (fallback)
    if [ "$notification_sent" = "false" ] || [ -n "$WEBHOOK_URL" ]; then
        send_webhook "$event" "$message" "$log_file"
    fi
    
    # Send email notification (additional channel if configured)
    send_email "$event" "$message" "$log_file"
    
    log "Notification processing completed"
}

# Check if script is being sourced or executed
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi