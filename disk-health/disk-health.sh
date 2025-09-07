#!/bin/bash

# Carrega as configurações de alerta
CONFIG_FILE="$(dirname "$0")/disk-alert.conf"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
else
    echo "Arquivo de configuração $CONFIG_FILE não encontrado."
    exit 1
fi

# Arquivo para armazenar o hash do último estado
HASH_FILE="/tmp/disk-health-hash"
touch "$HASH_FILE"

HONAME=$(hostname)
SMART_ISSUES=""
CRITICAL_USAGE_DISKS=""
WARNING_USAGE_DISKS=""
HAS_ISSUES=false

# --- Verificação de Saúde SMART ---
for disk in $(ls /dev/sd[a-z]); do
    # O status é verificado com -H. Qualquer coisa diferente de "PASSED" é um problema.
    health_status=$(smartctl -H "$disk" 2>/dev/null | grep "SMART overall-health self-assessment test result" | awk '{print $NF}')
    
    if [ -n "$health_status" ] && [ "$health_status" != "PASSED" ]; then
        SMART_ISSUES+="$(basename "$disk")": "$health_status"\n"
        HAS_ISSUES=true
    fi
done

# --- Verificação de Uso de Disco ---
# df ignora sistemas de arquivos temporários e loop devices
df -H --output=source,pcent,target -x tmpfs -x devtmpfs -x squashfs | tail -n +2 | while read -r source pcent target; do
    usage=$(echo "$pcent" | tr -d '[:space:]%')
    
    if [ "$usage" -ge 85 ]; then
        CRITICAL_USAGE_DISKS+="$target ($source) at ${pcent}\n"
        HAS_ISSUES=true
    elif [ "$usage" -ge 70 ]; then
        WARNING_USAGE_DISKS+="$target ($source) at ${pcent}\n"
        HAS_ISSUES=true
    fi
done

# --- Geração do Estado Atual e Hash ---
# O estado é uma combinação de todos os problemas encontrados.
CURRENT_STATE=""
if [ -n "$SMART_ISSUES" ]; then
    CURRENT_STATE+="SMART_ISSUES:\n$SMART_ISSUES"
fi
if [ -n "$CRITICAL_USAGE_DISKS" ]; then
    CURRENT_STATE+="CRITICAL_USAGE:\n$CRITICAL_USAGE_DISKS"
fi
if [ -n "$WARNING_USAGE_DISKS" ]; then
    CURRENT_STATE+="WARNING_USAGE:\n$WARNING_USAGE_DISKS"
fi

NEW_HASH=$(echo -e "$CURRENT_STATE" | md5sum | awk '{print $1}')
OLD_HASH=$(cat "$HASH_FILE")

# --- Envio de Alerta ---
# O alerta só é enviado se o hash for diferente E se houver algum problema.
if [ "$NEW_HASH" != "$OLD_HASH" ]; then
    echo "$NEW_HASH" > "$HASH_FILE"
    
    if [ "$HAS_ISSUES" = true ]; then
        MESSAGE="*Disk Alert for ${HOSTNAME}*\n\n"

        if [ -n "$SMART_ISSUES" ]; then
            MESSAGE+="*SMART Status Issues:*\n\`\`\`\n${SMART_ISSUES}\`\`\`\n"
        fi

        if [ -n "$CRITICAL_USAGE_DISKS" ]; then
            MESSAGE+="*CRITICAL Usage (>=85%):* ‼️\n\`\`\`\n${CRITICAL_USAGE_DISKS}\`\`\`\n"
        fi

        if [ -n "$WARNING_USAGE_DISKS" ]; then
            MESSAGE+="*WARNING Usage (>=70%):* ⚠️\n\`\`\`\n${WARNING_USAGE_DISKS}\`\`\`\n"
        fi
        
        # Envia a mensagem para o Telegram
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${TELEGRAM_CHAT_ID}" \
            -d text="${MESSAGE}" \
            -d parse_mode="Markdown" > /dev/null
    fi
fi

exit 0