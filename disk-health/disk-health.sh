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
    # Usar smartctl -a para obter todas as informações, incluindo temperatura de NVMe
    temp_output=$(smartctl -a $device_opts "$disk" 2>/dev/null)

    if [ -n "$temp_output" ]; then
        # Formato NVMe: "Temperature: 42 Celsius"
        temp_nvme=$(echo "$temp_output" | grep -E '^Temperature:' | awk '{print $2}')
        
        # Formato SATA/HDD: "194 Temperature_Celsius ... 42"
        temp_sata=$(echo "$temp_output" | grep -E 'Temperature_Celsius' | awk '{print $10}')

        if [[ "$temp_nvme" =~ ^[0-9]+$ ]]; then
            temperature="$temp_nvme"
        elif [[ "$temp_sata" =~ ^[0-9]+$ ]]; then
            temperature="$temp_sata"
        else
            # Fallback para outros formatos, como Airflow_Temperature_Cel
            temp_other=$(echo "$temp_output" | grep -E '(Temperature|Airflow_Temperature)' | awk '{print $10}')
            if ! [[ "$temp_other" =~ ^[0-9]+$ ]]; then
                temp_other=$(echo "$temp_output" | grep -E '(Temperature|Airflow_Temperature)' | awk '{print $9}')
            fi
            if [[ "$temp_other" =~ ^[0-9]+$ ]]; then
                temperature="$temp_other"
            fi
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

# Obter informações de uso de disco (compatível com Linux e macOS)
if command -v df >/dev/null 2>&1; then
    # Tentar formato Linux primeiro, depois macOS
    df_output=$(df -H --output=source,pcent,target 2>/dev/null || df -H 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        while read -r line; do
            if [ -z "$line" ] || [[ "$line" == "Filesystem"* ]]; then
                continue
            fi
            
            # Para Linux (com --output=source,pcent,target)
            if df -H --output=source,pcent,target >/dev/null 2>&1; then
                source=$(echo "$line" | awk '{print $1}')
                pcent=$(echo "$line" | awk '{print $2}')
                target=$(echo "$line" | awk '{print $3}')
            else
                # Para macOS (formato padrão df -H)
                source=$(echo "$line" | awk '{print $1}')
                pcent=$(echo "$line" | awk '{print $5}')
                target=$(echo "$line" | awk '{print $9}')
            fi
            
            # Pular sistemas de arquivos temporários
            if [[ "$source" == "tmpfs" ]] || [[ "$source" == "devtmpfs" ]] || \
               [[ "$source" == "squashfs" ]] || [[ "$target" == "/dev" ]] || \
               [[ "$target" == *"/System/"* ]] || [[ "$target" == *"CoreSimulator"* ]]; then
                continue
            fi
            
            usage=$(echo "$pcent" | tr -d '[:space:]%')
            
            if [[ "$usage" =~ ^[0-9]+$ ]]; then
                if [ "$usage" -ge 85 ]; then
                    CRITICAL_USAGE_DISKS+="$target ($source) - ${pcent}"$'\n'
                    HAS_ISSUES=true
                elif [ "$usage" -ge 70 ]; then
                    WARNING_USAGE_DISKS+="$target ($source) - ${pcent}"$'\n'
                    HAS_ISSUES=true
                fi
            fi
        done <<< "$df_output"
    fi
fi

# --- Geração do Estado Atual e Hash (nome e status de todos os discos) ---
# Para a hash, consideramos nome e status de TODOS os discos para detectar mudanças
HASH_STATE=""

# Gerar hash baseada no nome e status de cada disco
for disk in $DISKS_TO_CHECK; do
    if [ ! -b "$disk" ]; then
        continue
    fi
    
    disk_name=$(basename "$disk")
    status="${DISK_STATUS[$disk_name]:-"UNKNOWN"}"
    
    # Extrair apenas o status básico (sem temperatura específica)
    basic_status="OK"
    if [[ "$status" == *"❌"* ]]; then
        basic_status="FAILING"
    elif [[ "$status" == *"🔥"* ]]; then
        basic_status="CRITICAL"
    elif [[ "$status" == *"⚠️"* ]]; then
        basic_status="WARNING"
    fi
    
    HASH_STATE+="$disk_name:$basic_status"$'\n'
done

# Adicionar problemas de uso crítico à hash
if [ -n "$CRITICAL_USAGE_DISKS" ]; then
    HASH_STATE+="CRITICAL_USAGE:"$'\n'"$CRITICAL_USAGE_DISKS"
fi

NEW_HASH=$(echo "$HASH_STATE" | md5sum | awk '{print $1}')
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
        usage="N/A"
        max_usage=0
        
        # Debug: mostrar informações se for teste
        if [ "$TEST_MODE" = true ]; then
            echo "[DEBUG] Verificando uso para disco: $disk (nome: $disk_name)" >&2
            echo "[DEBUG] Saída df completa:" >&2
            df -h | grep -E "(Filesystem|$disk)" >&2
        fi
        
        # Buscar uso em todas as partições montadas que pertencem a este disco
        while read -r filesystem size used avail percent mountpoint; do
            if [ -z "$filesystem" ] || [[ "$filesystem" == "Filesystem" ]]; then
                continue
            fi
            
            # Debug: mostrar cada linha processada
            if [ "$TEST_MODE" = true ]; then
                echo "[DEBUG] Analisando: $filesystem -> $percent (mountpoint: $mountpoint)" >&2
            fi
            
            # Verificar se o filesystem pertence ao nosso disco
            # Formatos suportados: /dev/sda1, /dev/sdb2, /dev/nvme0n1p1, etc.
            if [[ "$filesystem" == "$disk"* ]] && [[ "$filesystem" != "$disk" ]]; then
                
                if [ "$TEST_MODE" = true ]; then
                    echo "[DEBUG] *** MATCH encontrado: $filesystem pertence a $disk ***" >&2
                fi
                
                # Extrair apenas o número do percentual
                percent_num=$(echo "$percent" | tr -d '%')
                
                if [[ "$percent_num" =~ ^[0-9]+$ ]] && [ "$percent_num" -gt "$max_usage" ]; then
                    max_usage=$percent_num
                    usage="${percent_num}%"
                    
                    if [ "$TEST_MODE" = true ]; then
                        echo "[DEBUG] *** Uso atualizado para $disk_name: $usage ***" >&2
                    fi
                fi
            fi
        done < <(df -h | tail -n +2)
        
        # Se não encontrou partições montadas, verificar se faz parte de RAID
        if [ "$usage" = "N/A" ]; then
            # Verificar se este disco faz parte de algum device RAID
            if [ -f /proc/mdstat ]; then
                raid_device=$(grep "$disk_name" /proc/mdstat 2>/dev/null | head -1)
                if [ -n "$raid_device" ]; then
                    # Extrair nome do device RAID (md0, md1, etc)
                    md_name=$(echo "$raid_device" | awk '{print $1}' | sed 's/://')
                    
                    if [ "$TEST_MODE" = true ]; then
                        echo "[DEBUG] $disk_name faz parte do RAID: $md_name" >&2
                    fi
                    
                    # Buscar uso do device RAID
                    while read -r filesystem size used avail percent mountpoint; do
                        if [[ "$filesystem" == "/dev/$md_name" ]]; then
                            percent_num=$(echo "$percent" | tr -d '%')
                            if [[ "$percent_num" =~ ^[0-9]+$ ]]; then
                                usage="${percent_num}%"
                                
                                if [ "$TEST_MODE" = true ]; then
                                    echo "[DEBUG] *** Uso RAID encontrado para $disk_name: $usage via $md_name ***" >&2
                                fi
                                break
                            fi
                        fi
                    done < <(df -h | tail -n +2)
                fi
            fi
            
            # Debug se ainda não encontrou
            if [ "$usage" = "N/A" ] && [ "$TEST_MODE" = true ]; then
                echo "[DEBUG] Nenhuma partição montada ou RAID encontrado para $disk" >&2
                echo "[DEBUG] Partições existentes:" >&2
                ls -la ${disk}* 2>/dev/null | head -5 >&2
                echo "[DEBUG] Verificando /proc/mdstat:" >&2
                grep -E "(active|$disk_name)" /proc/mdstat 2>/dev/null >&2
            fi
        fi
        
        # Obter temperatura ou definir como N/A
        temp_info="N/A"
        if [ -n "$temp" ] && [[ "$temp" =~ ^[0-9]+$ ]]; then
            temp_info="${temp}°C"
        fi
        
        # Formato fixo: nome: status | uso% | temperatura
        disk_list+="${disk_name}: ${status} | ${usage} | ${temp_info}"
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
'
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