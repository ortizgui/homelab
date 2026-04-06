#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DISK_HEALTH_DIR="${REPO_ROOT}/disk-health"
CLOUD_BACKUP_DIR="${REPO_ROOT}/cloud_backup"

require_file() {
    local path="$1"
    if [ ! -f "${path}" ]; then
        echo "ERRO: arquivo nao encontrado: ${path}" >&2
        exit 1
    fi
}

require_file "${DISK_HEALTH_DIR}/disk-health.sh"
require_file "${DISK_HEALTH_DIR}/telegram-bot.sh"
require_file "${DISK_HEALTH_DIR}/smart-selftest-short.sh"
require_file "${DISK_HEALTH_DIR}/disk-health.service"
require_file "${DISK_HEALTH_DIR}/disk-health.timer"
require_file "${DISK_HEALTH_DIR}/telegram-bot.service"
require_file "${DISK_HEALTH_DIR}/telegram-bot.timer"
require_file "${DISK_HEALTH_DIR}/smart-selftest-short.service"
require_file "${DISK_HEALTH_DIR}/smart-selftest-short.timer"
require_file "${CLOUD_BACKUP_DIR}/scripts/backup_status.sh"

echo "Instalando scripts..."
sudo install -m 0755 "${DISK_HEALTH_DIR}/disk-health.sh" /usr/local/sbin/disk-health.sh
sudo install -m 0755 "${DISK_HEALTH_DIR}/telegram-bot.sh" /usr/local/sbin/telegram-bot.sh
sudo install -m 0755 "${DISK_HEALTH_DIR}/smart-selftest-short.sh" /usr/local/sbin/smart-selftest-short.sh

echo "Instalando units do systemd..."
sudo install -m 0644 "${DISK_HEALTH_DIR}/disk-health.service" /etc/systemd/system/disk-health.service
sudo install -m 0644 "${DISK_HEALTH_DIR}/disk-health.timer" /etc/systemd/system/disk-health.timer
sudo install -m 0644 "${DISK_HEALTH_DIR}/telegram-bot.service" /etc/systemd/system/telegram-bot.service
sudo install -m 0644 "${DISK_HEALTH_DIR}/telegram-bot.timer" /etc/systemd/system/telegram-bot.timer
sudo install -m 0644 "${DISK_HEALTH_DIR}/smart-selftest-short.service" /etc/systemd/system/smart-selftest-short.service
sudo install -m 0644 "${DISK_HEALTH_DIR}/smart-selftest-short.timer" /etc/systemd/system/smart-selftest-short.timer

echo "Atualizando link para o status do backup..."
sudo ln -sf "${CLOUD_BACKUP_DIR}/scripts/backup_status.sh" /usr/local/bin/cloud-backup-status.sh
sudo chmod 0755 /usr/local/bin/cloud-backup-status.sh

echo "Recarregando systemd..."
sudo systemctl daemon-reload

echo "Habilitando timers..."
sudo systemctl enable --now disk-health.timer
sudo systemctl enable --now telegram-bot.timer

echo
echo "Atualizacao concluida."
echo "Se ainda nao fez isso, confirme no /etc/disk-alert.conf:"
echo 'BACKUP_STATUS_SCRIPT="/usr/local/bin/cloud-backup-status.sh"'
