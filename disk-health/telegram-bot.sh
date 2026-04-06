#!/bin/bash

set -euo pipefail

CONFIG_FILE="${CONFIG_FILE:-/etc/disk-alert.conf}"
STATE_DIR="${STATE_DIR:-/var/lib/disk-health}"
OFFSET_FILE="${OFFSET_FILE:-${STATE_DIR}/telegram-bot-offset}"
DISK_HEALTH_SCRIPT="${DISK_HEALTH_SCRIPT:-/usr/local/sbin/disk-health.sh}"
BACKUP_STATUS_SCRIPT="${BACKUP_STATUS_SCRIPT:-/usr/local/bin/cloud-backup-status.sh}"
HOSTNAME="$(hostname)"

mkdir -p "${STATE_DIR}"

if [ -f "${CONFIG_FILE}" ]; then
    # shellcheck disable=SC1090
    source "${CONFIG_FILE}"
else
    echo "ERRO: Arquivo de configuração ${CONFIG_FILE} não encontrado." >&2
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "ERRO: jq não encontrado." >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "ERRO: curl não encontrado." >&2
    exit 1
fi

if [ -z "${TELEGRAM_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "ERRO: TELEGRAM_TOKEN e TELEGRAM_CHAT_ID precisam estar configurados." >&2
    exit 1
fi

send_telegram_message() {
    local message="$1"
    local keyboard_json="${2:-}"

    local payload
    if [ -n "${keyboard_json}" ]; then
        payload=$(jq -n \
            --arg chat_id "${TELEGRAM_CHAT_ID}" \
            --arg text "${message}" \
            --argjson reply_markup "${keyboard_json}" \
            '{chat_id: $chat_id, text: $text, parse_mode: "Markdown", reply_markup: $reply_markup}')
    else
        payload=$(jq -n \
            --arg chat_id "${TELEGRAM_CHAT_ID}" \
            --arg text "${message}" \
            '{chat_id: $chat_id, text: $text, parse_mode: "Markdown"}')
    fi

    curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "${payload}" > /dev/null
}

build_keyboard() {
    jq -n '{
        keyboard: [
            [{"text": "Saude dos discos"}],
            [{"text": "Status do backup"}],
            [{"text": "Ajuda"}]
        ],
        resize_keyboard: true,
        one_time_keyboard: false
    }'
}

normalize_command() {
    local text
    text="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    case "${text}" in
        /start|/help|help|ajuda)
            echo "help"
            ;;
        /disks|/disk|discos|saude|saude\ dos\ discos|saúde|saúde\ dos\ discos)
            echo "disks"
            ;;
        /backup|backup|status\ do\ backup|status\ backup)
            echo "backup"
            ;;
        *)
            echo "unknown"
            ;;
    esac
}

disk_report() {
    if [ ! -x "${DISK_HEALTH_SCRIPT}" ]; then
        echo "Nao encontrei o script de saude dos discos em \`${DISK_HEALTH_SCRIPT}\`."
        return
    fi

    "${DISK_HEALTH_SCRIPT}" --report
}

backup_report() {
    if [ ! -x "${BACKUP_STATUS_SCRIPT}" ]; then
        echo "Nao encontrei o script de status do backup em \`${BACKUP_STATUS_SCRIPT}\`."
        return
    fi

    local raw
    if ! raw="$("${BACKUP_STATUS_SCRIPT}" 2>&1)"; then
        printf 'Falha ao consultar o backup.\n\n```\n%s\n```' "${raw}"
        return
    fi

    local status tag started_at phase progress files data elapsed eta current_file timestamp last_success total_processed files_processed snapshot_id data_added detail
    status="$(printf '%s\n' "${raw}" | awk -F': ' '/^STATUS: /{print $2; exit}')"
    tag="$(printf '%s\n' "${raw}" | awk -F': ' '/^TAG: /{print $2; exit}')"
    started_at="$(printf '%s\n' "${raw}" | awk -F': ' '/^STARTED_AT: /{print $2; exit}')"
    phase="$(printf '%s\n' "${raw}" | awk -F': ' '/^PHASE: /{print $2; exit}')"
    progress="$(printf '%s\n' "${raw}" | awk -F': ' '/^PROGRESS: /{print $2; exit}')"
    files="$(printf '%s\n' "${raw}" | awk -F': ' '/^FILES: /{print $2; exit}')"
    data="$(printf '%s\n' "${raw}" | awk -F': ' '/^DATA: /{print $2; exit}')"
    elapsed="$(printf '%s\n' "${raw}" | awk -F': ' '/^ELAPSED: /{print $2; exit}')"
    eta="$(printf '%s\n' "${raw}" | awk -F': ' '/^ETA: /{print $2; exit}')"
    current_file="$(printf '%s\n' "${raw}" | awk -F': ' '/^CURRENT_FILE: /{print $2; exit}')"
    timestamp="$(printf '%s\n' "${raw}" | awk -F': ' '/^TIMESTAMP: /{print $2; exit}')"
    last_success="$(printf '%s\n' "${raw}" | awk -F': ' '/^LAST_SUCCESSFUL_BACKUP: /{print $2; exit}')"
    total_processed="$(printf '%s\n' "${raw}" | awk -F': ' '/^TOTAL_PROCESSED: /{print $2; exit}')"
    files_processed="$(printf '%s\n' "${raw}" | awk -F': ' '/^FILES_PROCESSED: /{print $2; exit}')"
    snapshot_id="$(printf '%s\n' "${raw}" | awk -F': ' '/^SNAPSHOT_ID: /{print $2; exit}')"
    data_added="$(printf '%s\n' "${raw}" | awk -F': ' '/^DATA_ADDED: /{print $2; exit}')"
    detail="$(printf '%s\n' "${raw}" | awk -F': ' '/^DETAIL: /{print $2; exit}')"

    if [ "${status}" = "RUNNING" ]; then
        cat <<EOF
🔄 *Backup em execucao - ${HOSTNAME}*

Tag: ${tag:-"-"}
Iniciado em: ${started_at:-"-"}
Fase: ${phase:-"-"}
Progresso: ${progress:-"-"}
Arquivos: ${files:-"-"}
Dados: ${data:-"-"}
Tempo decorrido: ${elapsed:-"-"}
ETA: ${eta:-"-"}
Arquivo atual: ${current_file:-"-"}
EOF
        return
    fi

    if [ "${status}" = "SUCCESS" ] || [ "${status}" = "FAILED" ]; then
        local icon="✅"
        local title="Ultimo backup concluido"
        if [ "${status}" = "FAILED" ]; then
            icon="❌"
            title="Ultimo backup com falha"
        fi

        cat <<EOF
${icon} *${title} - ${HOSTNAME}*

Tag: ${tag:-"-"}
Horario: ${timestamp:-"-"}
Ultimo sucesso: ${last_success:-"-"}
Snapshot: ${snapshot_id:-"-"}
Arquivos processados: ${files_processed:-"-"}
Dados processados: ${total_processed:-"-"}
Dados adicionados: ${data_added:-"-"}
Detalhe: ${detail:-"-"}
EOF
        return
    fi

    cat <<EOF
ℹ️ *Backup - ${HOSTNAME}*

${detail:-"Nenhum backup registrado ainda."}
EOF
}

help_message() {
    cat <<EOF
🤖 *Bot do Homelab - ${HOSTNAME}*

Escolha uma opcao no teclado ou envie um comando:
/disks para listar a saude dos discos
/backup para ver o status atual do backup

Se nao houver backup em execucao, eu respondo com o ultimo backup registrado.
EOF
}

process_message() {
    local text="$1"
    local command
    command="$(normalize_command "${text}")"
    local keyboard
    keyboard="$(build_keyboard)"

    case "${command}" in
        help)
            send_telegram_message "$(help_message)" "${keyboard}"
            ;;
        disks)
            send_telegram_message "$(disk_report)" "${keyboard}"
            ;;
        backup)
            send_telegram_message "$(backup_report)" "${keyboard}"
            ;;
        *)
            send_telegram_message "$(help_message)" "${keyboard}"
            ;;
    esac
}

current_offset=0
if [ -f "${OFFSET_FILE}" ]; then
    current_offset="$(cat "${OFFSET_FILE}")"
fi

updates="$(curl -sS "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getUpdates?offset=${current_offset}&timeout=0")"
ok="$(printf '%s' "${updates}" | jq -r '.ok')"
if [ "${ok}" != "true" ]; then
    echo "ERRO: falha ao consultar updates do Telegram." >&2
    exit 1
fi

last_update_id=""
while IFS= read -r item; do
    [ -z "${item}" ] && continue
    update_id="$(printf '%s' "${item}" | jq -r '.update_id')"
    message_text="$(printf '%s' "${item}" | jq -r '.message.text // empty')"
    chat_id="$(printf '%s' "${item}" | jq -r '.message.chat.id // empty')"

    last_update_id="${update_id}"

    if [ -z "${message_text}" ] || [ -z "${chat_id}" ]; then
        continue
    fi

    if [ "${chat_id}" != "${TELEGRAM_CHAT_ID}" ]; then
        continue
    fi

    process_message "${message_text}"
done < <(printf '%s' "${updates}" | jq -c '.result[]?')

if [ -n "${last_update_id}" ]; then
    printf '%s' "$((last_update_id + 1))" > "${OFFSET_FILE}"
fi
