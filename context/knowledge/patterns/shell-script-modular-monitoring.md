# Pattern: Shell Script Modular Monitoring

## Description
A Bash-based monitoring pattern with single-responsibility functions, sourced configuration, state tracking for anti-spam, and Telegram integration for alerts.

## When to Use
- System-level monitoring that requires direct hardware access (SMART, mdadm)
- When Python/PHP/etc. dependencies are not desired
- When alerts should be sent via Telegram with deduplication

## Pattern

```bash
#!/bin/bash
set -eo pipefail

# 1. Sourced config with secrets
CONFIG_FILE="/etc/my-monitor.conf"
source "${CONFIG_FILE}"

# 2. State tracking (hash file for anti-spam)
HASH_FILE="/tmp/my-monitor-hash"
compute_state_hash() { ... }

# 3. Single-responsibility functions
discover_devices() { ... }
check_device_health() { ... }
check_raid_status() { ... }

# 4. Telegram notification
send_alert() {
    local message="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d text="$message" \
        -d parse_mode="Markdown" > /dev/null
}

# 5. Main: collect → compare → alert only if changed
main() {
    local report=$(collect_report)
    local hash=$(compute_hash "$report")
    local last_hash=$(cat "$HASH_FILE" 2>/dev/null || echo "")
    
    if [ "$hash" != "$last_hash" ] || [ "$FORCE_SEND" = true ]; then
        send_alert "$report"
        echo "$hash" > "$HASH_FILE"
    fi
}

main "$@"
```

## Files Using This Pattern
- `disk-health/disk-health.sh` - Full implementation with SMART, RAID, temperature, disk usage
- `disk-health/telegram-bot.sh` - Extended pattern with command polling and keyboard responses
- `disk-health/smart-selftest-short.sh` - Simplified pattern for one-shot tasks

## Related
- [Decision: Disk Health Monitoring](../decisions/004-disk-health-monitoring.md)
- [Feature: Disk Health Monitoring](../intent/feature-disk-health.md)

## Status
- **Created**: 2026-05-03
- **Status**: Active
