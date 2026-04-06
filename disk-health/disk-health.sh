#!/bin/bash
#
# disk-health.sh - Script de Monitoramento de Discos
#
# Autor: Guilherme Ortiz
# Data: 2025-09-07
# Versão: 2.0
#
# Descrição:
# Este script monitora a saúde (SMART), temperatura e uso de discos SATA, NVMe e USB.
# Ele envia alertas para o Telegram se problemas forem detectados ou se o estado
# de um disco for alterado (ex: de "OK" para "FALHANDO" ou vice-versa).
#
# Boas Práticas Aplicadas:
# - Modularidade: O script é dividido em funções com responsabilidades únicas (SRP).
# - DRY (Não se Repita): A lógica duplicada foi eliminada e centralizada em funções.
# - Robustez: A análise de comandos (df, smartctl) foi melhorada para ser mais confiável.
# - Legibilidade: O código está estruturado, comentado e usa nomes de variáveis claros.
# - Segurança: `set -eo pipefail` é usado para um tratamento de erros mais estrito.
#

set -eo pipefail

# --- Configurações e Constantes ---
CONFIG_FILE="/etc/disk-alert.conf"
HASH_FILE="/tmp/disk-health-hash"
CRITICAL_TEMP=70
HIGH_TEMP=55
CRITICAL_USAGE_THRESHOLD=85
WARNING_USAGE_THRESHOLD=70

# --- Configurações de relatório semanal ---
# Envio de relatório semanal mesmo sem alterações:
# dia da semana (1=segunda-feira ... 7=domingo), hora e minuto
WEEKLY_REPORT_DOW=${WEEKLY_REPORT_DOW:-1}
WEEKLY_REPORT_HOUR=${WEEKLY_REPORT_HOUR:-9}
WEEKLY_REPORT_MINUTE=${WEEKLY_REPORT_MINUTE:-0}

# --- Variáveis Globais ---
TEST_MODE=false
FORCE_SEND=false
REPORT_ONLY=false
HOSTNAME=$(hostname)

# --- Definição de Funções ---

#
# Imprime uma mensagem de debug se o modo de teste estiver ativo.
#
log_debug() {
    if [ "$TEST_MODE" = true ]; then
        echo "[DEBUG] $1" >&2
    fi
}

#
# Envia uma mensagem de alerta para o Telegram.
# Argumento 1: A mensagem a ser enviada.
#
send_telegram_alert() {
    local message=$1
    log_debug "Enviando mensagem para o Telegram."
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d text="$message" \
        -d parse_mode="Markdown" > /dev/null
}

#
# Descobre os discos a serem monitorados, com base na configuração ou auto-descoberta.
#
discover_disks() {
    local disks_found=""
    if [ -n "$DISKS" ]; then
        log_debug "Usando discos definidos na configuração: $DISKS"
        disks_found="$DISKS"
    else
        log_debug "Fazendo auto-descoberta de discos."
        for disk in /dev/sd[a-z] /dev/nvme[0-9]n[0-9]; do
            if [ -b "$disk" ]; then
                disks_found="$disks_found $disk"
            fi
        done
    fi
    echo "$disks_found"
}

#
# Coleta o status de saúde (SMART) e a temperatura de um disco.
# Argumento 1: O caminho do disco (ex: /dev/sda).
# Argumento 2: Opções extras para smartctl (ex: -d sat).
# Retorna: Uma string com "STATUS TEMPERATURA".
#
get_smart_info() {
    local disk_path=$1
    local device_opts=$2
    local health_status=""
    local temperature=""

    local smart_output
    smart_output=$(smartctl -a ${device_opts} "${disk_path}" 2>/dev/null)

    if [ -z "$smart_output" ]; then
        log_debug "Não foi possível obter dados do smartctl para $disk_path."
        echo "UNKNOWN N/A"
        return
    fi

    # Obter status de saúde
    health_status=$(echo "$smart_output" | grep "SMART overall-health self-assessment test result" | awk '{print $NF}')
    [ -z "$health_status" ] && health_status="PASSED" # Assumir PASSED se não encontrar

    # Obter temperatura (lógica aprimorada para NVMe e SATA)
    local temp_nvme=$(echo "$smart_output" | grep -E '^Temperature:' | awk '{print $2}')
    local temp_sata=$(echo "$smart_output" | grep -E 'Temperature_Celsius' | awk '{print $10}')

    if [[ "$temp_nvme" =~ ^[0-9]+$ ]]; then
        temperature="$temp_nvme"
    elif [[ "$temp_sata" =~ ^[0-9]+$ ]]; then
        temperature="$temp_sata"
    else
        temperature="N/A"
    fi

    echo "$health_status $temperature"
}

#
# Encontra o maior percentual de uso de um disco, verificando suas partições e/ou RAID.
# Argumento 1: O nome do disco (ex: sda).
# Retorna: O percentual de uso (ex: 85%) or "N/A".
#
get_disk_usage() {
    local disk_name=$1
    local max_usage=0

    # Verifica partições montadas do disco (ex: sda1, sda2)
    while read -r source pcent; do
        if [[ "$source" == "/dev/${disk_name}"* ]]; then
            local usage_num=${pcent//%/}
            if [[ "$usage_num" -gt "$max_usage" ]]; then
                max_usage=$usage_num
            fi
        fi
    done < <(df --output=source,pcent | tail -n +2)

    # Se não encontrou uso, verifica se faz parte de um RAID
    if [ "$max_usage" -eq 0 ] && [ -f /proc/mdstat ]; then
        local raid_device=$(grep "$disk_name" /proc/mdstat 2>/dev/null | head -1)
        if [ -n "$raid_device" ]; then
            local md_name=$(echo "$raid_device" | awk '{print $1}')
            log_debug "$disk_name faz parte do RAID: $md_name"
            
            local raid_usage=$(df --output=pcent "/dev/${md_name}" 2>/dev/null | tail -n 1 || echo "0%")
            raid_usage=${raid_usage//[ %]/} # Remove espaço e %
            if [[ "$raid_usage" =~ ^[0-9]+$ ]] && [[ "$raid_usage" -gt "$max_usage" ]]; then
                max_usage=$raid_usage
            fi
        fi
    fi
    
    if [ "$max_usage" -eq 0 ]; then
        echo "N/A"
    else
        echo "${max_usage}%"
    fi
}

#
# Constrói a mensagem final para o Telegram.
#
build_report_message() {
    local disk_report_lines=$1
    local smart_issues=$2
    local critical_usage=$3
    local warning_usage=$4
    local has_issues=$5

    local message=""
    if [ "$TEST_MODE" = true ]; then
        message="🧪 *Teste do Disk Health - ${HOSTNAME}*\n\n"
        message+="✅ *Sistema de monitoramento funcionando corretamente*\n\n"
        message+="📊 *Discos Monitorados:*\n${disk_report_lines}"
        
        if [ "$has_issues" = true ]; then
            message+="\n\n⚠️ *Problemas detectados (modo teste):*"
        else
            message+="\n\n✅ *Status:* Nenhum problema detectado"
        fi
        message+="\n\n🕐 Teste: $(date '+%Y-%m-%d %H:%M:%S')"
    else
        message="🚨 *Disk Report - ${HOSTNAME}*\n\n"
        message+="📊 *Status dos Discos:*\n${disk_report_lines}"
    fi

    if [ -n "$smart_issues" ]; then
        message+="\n\n*🔧 Problemas SMART:*\n```\n${smart_issues}```"
    fi
    if [ -n "$critical_usage" ]; then
        message+="\n\n*🚨 Uso Crítico (≥${CRITICAL_USAGE_THRESHOLD}%):*\n```\n${critical_usage}```"
    fi
    if [ -n "$warning_usage" ]; then
        message+="\n\n*⚠️ Uso Alto (≥${WARNING_USAGE_THRESHOLD}%):*\n```\n${warning_usage}```"
    fi

    echo -e "$message"
}

# --- Lógica Principal de Execução ---
main() {
    # 1. Processar argumentos da linha de comando
    for arg in "$@"; do
        case $arg in
            --test) TEST_MODE=true ;;
            --f) FORCE_SEND=true ;;
            --report) REPORT_ONLY=true ;;
        esac
    done

    # 2. Carregar configuração
    if [ -f "$CONFIG_FILE" ]; then
        source "$CONFIG_FILE"
    else
        echo "ERRO: Arquivo de configuração $CONFIG_FILE não encontrado." >&2
        exit 1
    fi


    touch "$HASH_FILE"

    # 3. Descobrir e verificar cada disco
    local disks_to_check=$(discover_disks)
    log_debug "Discos a serem verificados: $disks_to_check"

    local disk_report_lines=""
    local hash_state=""
    local smart_issues_summary=""
    local has_issues=false

    for disk_path in $disks_to_check; do
        if [ ! -b "$disk_path" ]; then continue; fi
        
        local disk_name=$(basename "$disk_path")
        log_debug "Verificando disco: $disk_path (nome: $disk_name)"

        # Obter opções de dispositivo (para SAT)
        local device_opts=""
        if [ -n "$MAP_DEVICE_OPTS" ]; then
            for mapping in $MAP_DEVICE_OPTS; do
                local dev=$(echo "$mapping" | cut -d'=' -f1)
                local opt=$(echo "$mapping" | cut -d'=' -f2)
                if [ "$disk_name" = "$dev" ]; then
                    device_opts="-d $opt"
                    break
                fi
            done
        fi

        # Coletar informações
        local smart_info=($(get_smart_info "$disk_path" "$device_opts"))
        local health_status=${smart_info[0]}
        local temperature=${smart_info[1]}
        local usage=$(get_disk_usage "$disk_name")
        
        # Determinar o status do disco
        local status_emoji="✅"
        local status_text="OK"
        if [ "$health_status" != "PASSED" ]; then
            status_emoji="❌"
            status_text="$health_status"
            smart_issues_summary+="${disk_name}: $health_status\n"
            has_issues=true
        elif [[ "$temperature" =~ ^[0-9]+$ ]]; then
            if [ "$temperature" -ge "$CRITICAL_TEMP" ]; then
                status_emoji="🔥"
                status_text="CRÍTICA (${temperature}°C)"
                has_issues=true
            elif [ "$temperature" -ge "$HIGH_TEMP" ]; then
                status_emoji="⚠️"
                status_text="ALTA (${temperature}°C)"
                has_issues=true
            fi
        fi
        
        local final_status="$status_emoji $status_text"
        local temp_info=$([ "$temperature" = "N/A" ] && echo "N/A" || echo "${temperature}°C")

        # Construir linha do relatório e estado para o hash
        disk_report_lines+="${disk_name}: ${final_status} | ${usage} | ${temp_info}\n"
        
        local basic_status="OK"
        if [[ "$final_status" == *"❌"* ]]; then basic_status="FAILING";
        elif [[ "$final_status" == *"🔥"* ]]; then basic_status="CRITICAL";
        elif [[ "$final_status" == *"⚠️"* ]]; then basic_status="WARNING";
        fi
        hash_state+="$disk_name:$basic_status\n"
    done

    # 4. Verificar uso de disco globalmente para resumo de alertas
    local critical_usage_summary=""
    local warning_usage_summary=""
    while read -r source pcent target; do
        if [[ "$source" == "tmpfs" || "$source" == "devtmpfs" || "$source" == "squashfs" || "$target" == "/dev" ]]; then
            continue
        fi
        local usage_num=${pcent//%/}
        if [[ "$usage_num" =~ ^[0-9]+$ ]]; then
            if [ "$usage_num" -ge "$CRITICAL_USAGE_THRESHOLD" ]; then
                critical_usage_summary+="$target ($source) - ${pcent}\n"
                has_issues=true
            elif [ "$usage_num" -ge "$WARNING_USAGE_THRESHOLD" ]; then
                warning_usage_summary+="$target ($source) - ${pcent}\n"
                has_issues=true
            fi
        fi
    done < <(df -H --output=source,pcent,target | tail -n +2)


    # 5. Decidir se o alerta deve ser enviado
    local new_hash=$(echo -n -e "$hash_state" | md5sum | awk '{print $1}')
    local old_hash=$(cat "$HASH_FILE")
    log_debug "Novo Hash: $new_hash | Hash Antigo: $old_hash"

    # Verifica horário para possível envio semanal independente de alterações
    now_dow=$(date +%u)
    now_hour=$(date +%H)
    now_minute=$(date +%M)
    log_debug "Hora atual: dia da semana $now_dow, $now_hour:$now_minute"

    local should_send_alert=false
    if [ "$TEST_MODE" = true ] || [ "$FORCE_SEND" = true ]; then
        should_send_alert=true
    elif [ "$new_hash" != "$old_hash" ] || { [ "$now_dow" -eq "$WEEKLY_REPORT_DOW" ] && [ "$now_hour" -eq "$WEEKLY_REPORT_HOUR" ] && [ "$now_minute" -eq "$WEEKLY_REPORT_MINUTE" ]; }; then
        # Envia alerta em qualquer mudança de estado ou no agendamento semanal
        should_send_alert=true
    fi
    
    # 6. Enviar Alerta
    local message=$(build_report_message "$disk_report_lines" "$smart_issues_summary" "$critical_usage_summary" "$warning_usage_summary" "$has_issues")

    if [ "$REPORT_ONLY" = true ]; then
        echo "$message"
        exit 0
    fi

    if [ "$should_send_alert" = true ]; then
        log_debug "Alteração de estado detectada. Enviando alerta."
        if [ "$FORCE_SEND" = false ] && [ "$TEST_MODE" = false ]; then
            echo -n "$new_hash" > "$HASH_FILE"
        fi

        send_telegram_alert "$message"
        
        if [ "$TEST_MODE" = true ]; then
            echo "Mensagem de teste enviada com sucesso!"
        fi
    else
        log_debug "Nenhuma mudança de estado. Alerta não enviado."
    fi
}

# --- Ponto de Entrada do Script ---
# Executa a função principal, passando todos os argumentos da linha de comando.
main "$@"
