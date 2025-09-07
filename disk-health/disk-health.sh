#!/bin/bash

# Parâmetros de linha de comando
TEST_MODE=false
FORCE_SEND=false

# Parse command line arguments
for arg in "$@"; do
    case $arg in
        --test)
            TEST_MODE=true
            ;;
        --f)
            FORCE_SEND=true
            ;;
    esac
done

# Carrega as configurações de alerta
CONFIG_FILE="/etc/disk-alert.conf"
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
else
    echo "Arquivo de configuração $CONFIG_FILE não encontrado."
    exit 1
fi

# Arquivo para armazenar o hash do último estado
HASH_FILE="/tmp/disk-health-hash"
touch "$HASH_FILE"

HOSTNAME=$(hostname)
HAS_ISSUES=false

# Arrays para armazenar informações dos discos
declare -A DISK_INFO
declare -A DISK_STATUS
declare -A DISK_TEMP
declare -A DISK_USAGE

# --- Descoberta de Discos ---
DISKS_TO_CHECK=""
if [ -n "$DISKS" ]; then
    DISKS_TO_CHECK="$DISKS"
else
    # Auto-descoberta de discos (SATA/NVMe/USB)
    for disk in /dev/sd[a-z] /dev/nvme[0-9]n[0-9]; do
        if [ -b "$disk" ]; then
            DISKS_TO_CHECK="$DISKS_TO_CHECK $disk"
        fi
    done
fi

# --- Verificação detalhada de cada disco ---
SMART_ISSUES=""
for disk in $DISKS_TO_CHECK; do
    if [ ! -b "$disk" ]; then
        continue
    fi
    
    disk_name=$(basename "$disk")
    
    # Determinar opções do dispositivo (para docks USB que precisam de SAT)
    device_opts=""
    if [ -n "$MAP_DEVICE_OPTS" ]; then
        for mapping in $MAP_DEVICE_OPTS; do
            dev=$(echo "$mapping" | cut -d'=' -f1)
            opt=$(echo "$mapping" | cut -d'=' -f2)
            if [ "$disk_name" = "$dev" ]; then
                device_opts="$opt"
                break
            fi
        done
    fi
    
    # Verificar status SMART
    health_status=$(smartctl -H $device_opts "$disk" 2>/dev/null | grep "SMART overall-health self-assessment test result" | awk '{print $NF}')
    
    # Obter temperatura
    temperature=""
    temp_line=$(smartctl -A $device_opts "$disk" 2>/dev/null | grep -E "(Temperature|Airflow_Temperature)" | head -1)
    if [ -n "$temp_line" ]; then
        temperature=$(echo "$temp_line" | awk '{print $10}')
        if [ -z "$temperature" ] || ! [[ "$temperature" =~ ^[0-9]+$ ]]; then
            temperature=$(echo "$temp_line" | awk '{print $9}')
        fi
    fi
    
    # Status do disco
    status="✅ OK"
    if [ -n "$health_status" ] && [ "$health_status" != "PASSED" ]; then
        status="❌ $health_status"
        SMART_ISSUES+="$disk_name: $health_status"$'\n'
        HAS_ISSUES=true
    elif [ -n "$temperature" ] && [[ "$temperature" =~ ^[0-9]+$ ]]; then
        # Verificar limites de temperatura
        if [ "$temperature" -ge 70 ]; then
            status="🔥 CRÍTICA (${temperature}°C)"
            HAS_ISSUES=true
        elif [ "$temperature" -ge 55 ]; then
            status="⚠️ ALTA (${temperature}°C)"
            HAS_ISSUES=true
        fi
    fi
    
    DISK_STATUS["$disk_name"]="$status"
    DISK_TEMP["$disk_name"]="$temperature"
done

# --- Verificação de Uso de Disco ---
CRITICAL_USAGE_DISKS=""
WARNING_USAGE_DISKS=""

while IFS= read -r line; do
    if [ -z "$line" ]; then
        continue
    fi
    
    source=$(echo "$line" | awk '{print $1}')
    pcent=$(echo "$line" | awk '{print $2}')
    target=$(echo "$line" | awk '{print $3}')
    usage=$(echo "$pcent" | tr -d '[:space:]%')
    
    if [ "$usage" -ge 85 ]; then
        CRITICAL_USAGE_DISKS+="$target ($source) - ${pcent}"$'\n'
        HAS_ISSUES=true
    elif [ "$usage" -ge 70 ]; then
        WARNING_USAGE_DISKS+="$target ($source) - ${pcent}"$'\n'
        HAS_ISSUES=true
    fi
done < <(df -H --output=source,pcent,target -x tmpfs -x devtmpfs -x squashfs | tail -n +2)

# --- Geração do Estado Atual e Hash (sem timestamp) ---
CURRENT_STATE=""
if [ -n "$SMART_ISSUES" ]; then
    CURRENT_STATE+="SMART_ISSUES:"$'\n'"$SMART_ISSUES"
fi
if [ -n "$CRITICAL_USAGE_DISKS" ]; then
    CURRENT_STATE+="CRITICAL_USAGE:"$'\n'"$CRITICAL_USAGE_DISKS"
fi
if [ -n "$WARNING_USAGE_DISKS" ]; then
    CURRENT_STATE+="WARNING_USAGE:"$'\n'"$WARNING_USAGE_DISKS"
fi

NEW_HASH=$(echo "$CURRENT_STATE" | md5sum | awk '{print $1}')
OLD_HASH=$(cat "$HASH_FILE")

# --- Envio de Alerta ---
SHOULD_SEND_ALERT=false

# Lógica para determinar se deve enviar alerta
if [ "$TEST_MODE" = true ]; then
    SHOULD_SEND_ALERT=true
elif [ "$FORCE_SEND" = true ] || [ "$NEW_HASH" != "$OLD_HASH" ]; then
    if [ "$HAS_ISSUES" = true ]; then
        SHOULD_SEND_ALERT=true
    fi
fi

# Função para gerar listagem de discos
generate_disk_list() {
    local disk_list=""
    for disk in $DISKS_TO_CHECK; do
        if [ ! -b "$disk" ]; then
            continue
        fi
        
        disk_name=$(basename "$disk")
        status="${DISK_STATUS[$disk_name]:-"❓ UNKNOWN"}"
        temp="${DISK_TEMP[$disk_name]}"
        
        # Obter uso de disco se disponível
        usage=""
        while IFS= read -r line; do
            if [[ "$line" == *"$disk"* ]] || [[ "$line" == *"${disk}p"* ]] || [[ "$line" == *"${disk}1"* ]]; then
                pcent=$(echo "$line" | awk '{print $2}')
                usage=" | ${pcent}"
                break
            fi
        done < <(df -H --output=source,pcent -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | tail -n +2)
        
        temp_info=""
        if [ -n "$temp" ] && [[ "$temp" =~ ^[0-9]+$ ]]; then
            temp_info=" | ${temp}°C"
        fi
        
        disk_list+="*${disk_name}*: ${status}${temp_info}${usage}"$'\n'
    done
    echo "$disk_list"
}

# Envia alerta se necessário
if [ "$SHOULD_SEND_ALERT" = true ]; then
    # Atualiza hash apenas se não for modo de força
    if [ "$FORCE_SEND" = false ]; then
        echo "$NEW_HASH" > "$HASH_FILE"
    fi
    
    # Gerar listagem de discos
    DISK_LIST=$(generate_disk_list)
    
    if [ "$TEST_MODE" = true ]; then
        # Mensagem de teste
        MESSAGE="🧪 *Teste do Disk Health - ${HOSTNAME}*

✅ *Sistema de monitoramento funcionando corretamente*

📊 *Discos Monitorados:*
${DISK_LIST}"
        
        if [ "$HAS_ISSUES" = true ]; then
            MESSAGE+="
⚠️ *Problemas detectados (modo teste):*"
            
            if [ -n "$SMART_ISSUES" ]; then
                MESSAGE+="

*🔧 Problemas SMART:*
\`\`\`
${SMART_ISSUES}\`\`\`"
            fi

            if [ -n "$CRITICAL_USAGE_DISKS" ]; then
                MESSAGE+="

*🚨 Uso Crítico (≥85%):*
\`\`\`
${CRITICAL_USAGE_DISKS}\`\`\`"
            fi

            if [ -n "$WARNING_USAGE_DISKS" ]; then
                MESSAGE+="

*⚠️ Uso Alto (≥70%):*
\`\`\`
${WARNING_USAGE_DISKS}\`\`\`"
            fi
        else
            MESSAGE+="

✅ *Status:* Nenhum problema detectado"
        fi
        
        MESSAGE+="

🕐 Teste: $(date '+%Y-%m-%d %H:%M:%S')"
        
    else
        # Mensagem normal de alerta
        MESSAGE="🚨 *Disk Alert - ${HOSTNAME}*

📊 *Status dos Discos:*
${DISK_LIST}"

        if [ -n "$SMART_ISSUES" ]; then
            MESSAGE+="

*🔧 Problemas SMART:*
\`\`\`
${SMART_ISSUES}\`\`\`"
        fi

        if [ -n "$CRITICAL_USAGE_DISKS" ]; then
            MESSAGE+="

*🚨 Uso Crítico (≥85%):*
\`\`\`
${CRITICAL_USAGE_DISKS}\`\`\`"
        fi

        if [ -n "$WARNING_USAGE_DISKS" ]; then
            MESSAGE+="

*⚠️ Uso Alto (≥70%):*
\`\`\`
${WARNING_USAGE_DISKS}\`\`\`"
        fi
    fi
    
    # Envia a mensagem para o Telegram
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d text="$MESSAGE" \
        -d parse_mode="Markdown" > /dev/null
    
    if [ "$TEST_MODE" = true ]; then
        echo "Mensagem de teste enviada com sucesso!"
    fi
fi

exit 0