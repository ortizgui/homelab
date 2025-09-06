#!/usr/bin/env bash
set -euo pipefail

CONF="/etc/disk-alert.conf"
STATE_DIR="/var/lib/disk-health"
STATE_FILE="$STATE_DIR/last.json"
LOG_TAG="disk-health"
mkdir -p "$STATE_DIR"

# ===== util =====
log(){ logger -t "$LOG_TAG" -- "$*"; }
load_conf(){ [ -f "$CONF" ] && . "$CONF"; }

send_tg(){
  local text="$1"
  [ -z "${TELEGRAM_TOKEN:-}" ] && { log "TELEGRAM_TOKEN não definido"; return 1; }
  [ -z "${TELEGRAM_CHAT_ID:-}" ] && { log "TELEGRAM_CHAT_ID não definido"; return 1; }
  curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d chat_id="$TELEGRAM_CHAT_ID" \
    -d parse_mode="Markdown" \
    --data-urlencode "text=${text}" >/dev/null
}

hash_payload(){ printf '%s' "$1" | sha256sum | awk '{print $1}'; }

is_ssd_like(){
  # heurística simples: nvme = SSD; para /dev/sdX checa rota rota/rota/queue/rotational == 0
  local devnode="$1"
  if [[ "$devnode" == /dev/nvme* ]]; then echo "1"; return; fi
  local base; base=$(basename "$devnode")
  local rot_file="/sys/block/$base/queue/rotational"
  if [ -f "$rot_file" ] && [ "$(cat "$rot_file" 2>/dev/null)" = "0" ]; then echo "1"; else echo "0"; fi
}

smart_for(){
  # tenta sem opção; se falhar e for sdX, tenta -d sat
  local dev="$1" opts="${2:-}"
  if smartctl -j -A $opts "$dev" >/dev/null 2>&1; then
    smartctl -j -H -A $opts "$dev"
  else
    smartctl -j -H -A "$dev"
  fi
}

discover_disks(){
  if [ -n "${DISKS:-}" ]; then
    echo "$DISKS"
    return
  fi
  lsblk -ndo NAME,TYPE | awk '$2=="disk"{print "/dev/"$1}' \
    | grep -Ev '^/dev/(mtdblock|zram)'
}

device_opts_for(){
  local dev="$1"
  local base; base=$(basename "$dev")
  local map="${MAP_DEVICE_OPTS:-}"
  if [ -n "$map" ]; then
    for pair in $map; do
      local k="${pair%%=*}"; local v="${pair#*=}"
      if [ "$k" = "$base" ]; then echo "$v"; return; fi
    done
  fi
  # heurística: para /dev/sdX atrás de USB, -d sat costuma ser necessário
  if [[ "$dev" == /dev/sd* ]]; then
    local transport
    transport=$(lsblk -ndo TRAN "$dev" 2>/dev/null || true)
    if [ "$transport" = "usb" ]; then
      echo "-d sat"
      return
    fi
  fi
  echo ""
}

check_smart(){
  local dev="$1" opts="$2"
  smart_for "$dev" "$opts" | jq -c '
    . as $root
    | {
        device: ($root.device.name // "'"$dev"'"),
        health: ($root.smart_status.passed // false),
        temp: (
          if $root.temperature.current? then $root.temperature.current
          elif $root.nvme_smart_health_information_log.temperature? then ($root.nvme_smart_health_information_log.temperature|tonumber)
          elif ($root.ata_smart_attributes.table[]? | select(.name=="Temperature_Celsius").raw.value?) then
            ($root.ata_smart_attributes.table[] | select(.name=="Temperature_Celsius").raw.value)
          else null end
        ),
        reallocated: (
          ($root.ata_smart_attributes.table[]? | select(.name=="Reallocated_Sector_Ct").raw.value?) // 0
        ),
        pending: (
          ($root.ata_smart_attributes.table[]? | select(.name=="Current_Pending_Sector").raw.value?) // 0
        ),
        uncorrect: (
          ($root.ata_smart_attributes.table[]? | select(.name=="Offline_Uncorrectable").raw.value?) // 0
        )
      }'
}

check_raid(){
  local summary="" status="" detail=""
  # mdstat pode não existir em alguns SOs (ou vazio)
  if [ -r /proc/mdstat ]; then
    # Use cat entre aspas para preservar quebras de linha
    summary="$(cat /proc/mdstat || true)"
  fi

  # Coleta arrays conhecidos sem derrubar o script se mdadm não existir
  local arrays=""
  arrays="$( (mdadm --detail --scan 2>/dev/null | awk '{print $2}') || true )"

  if [ -n "$arrays" ]; then
    local a
    for a in $arrays; do
      local d
      d="$(mdadm --detail "$a" 2>/dev/null || true)"
      [ -n "$d" ] && detail+=$'\n'"$d"$'\n'
      # Marca crítico se degradado
      if echo "$d" | grep -qi "degraded"; then
        status="CRITICAL"
      fi
    done
  fi

  # Se mdstat indicar algo como [U_] ou [_U], marca crítico
  if printf '%s\n' "$summary" | grep -qE '\[[U_]{2,}\]'; then
    if printf '%s\n' "$summary" | grep -q '\[U_'; then status="CRITICAL"; fi
    if printf '%s\n' "$summary" | grep -q '\[_U'; then status="CRITICAL"; fi
  fi

  # Emite dump (sem linhas vazias extras)
  printf '%s\n%s\n' "$summary" "$detail" | sed '/^$/d'

  # Flag de status para o caller
  [ -n "$status" ] && echo "::STATUS=$status"
}

main(){
  load_conf
  local disks; disks=$(discover_disks)
  local results=""; local overall="OK"
  while read -r dev; do
    [ -z "$dev" ] && continue
    local ssd_like; ssd_like=$(is_ssd_like "$dev")
    local warn_t crit_t
    if [ "$ssd_like" = "1" ]; then
      warn_t=${SSD_WARN_TEMP:-65}; crit_t=${SSD_CRIT_TEMP:-70}
    else
      warn_t=${HDD_WARN_TEMP:-55}; crit_t=${HDD_CRIT_TEMP:-60}
    fi
    local opts; opts=$(device_opts_for "$dev")
    if ! out=$(check_smart "$dev" "$opts" 2>/dev/null); then
      results+=$'\n'"*${dev}*: não foi possível ler SMART."
      overall="WARN"
      continue
    fi
    local health temp realloc pending uncorr
    health=$(jq -r '.health' <<<"$out")
    temp=$(jq -r '.temp // "null"' <<<"$out")
    realloc=$(jq -r '.reallocated // 0' <<<"$out")
    pending=$(jq -r '.pending // 0' <<<"$out")
    uncorr=$(jq -r '.uncorrect // 0' <<<"$out")

    local status="OK"; local msgs=()
    [ "$health" != "true" ] && status="CRITICAL" && msgs+=("SMART overall *FAIL*")
    if [ "$temp" != "null" ]; then
      if [ "$temp" -ge "$crit_t" ]; then status="CRITICAL"; msgs+=("Temp ${temp}°C ≥ ${crit_t}°C")
      elif [ "$temp" -ge "$warn_t" ]; then status="WARN"; msgs+=("Temp ${temp}°C ≥ ${warn_t}°C"); fi
    fi
    if [ "$realloc" -gt 0 ]; then status="${status/OK/WARN}"; msgs+=("Reallocated=$realloc"); fi
    if [ "$pending" -gt 0 ]; then status="CRITICAL"; msgs+=("Pending=$pending"); fi
    if [ "$uncorr" -gt 0 ]; then status="CRITICAL"; msgs+=("Uncorrectable=$uncorr"); fi

    [ "$status" = "CRITICAL" ] && overall="CRITICAL"
    [ "$status" = "WARN" ] && [ "$overall" = "OK" ] && overall="WARN"

    if [ "${#msgs[@]}" -eq 0 ]; then
      results+=$'\n'"*${dev}*: OK"
    else
      results+=$'\n'"*${dev}*: ${status} — $(IFS='; '; echo "${msgs[*]}")"
    fi
  done <<<"$disks"

  # RAID
  local raid_dump raid_status
  raid_dump=$(check_raid || true)
  if echo "$raid_dump" | grep -q "::STATUS=CRITICAL"; then
    overall="CRITICAL"
    raid_dump=$(echo "$raid_dump" | sed '/::STATUS=.*/d')
    results+=$'\n\n''*RAID*: CRITICAL'
  else
    results+=$'\n\n''*RAID*: OK'
  fi
  results+=$'\n''```\n'"$raid_dump"$'\n```'

  # Monta payload final
  local host; host=$(hostname)
  local emoji="🟢"
  [ "$overall" = "WARN" ] && emoji="🟡"
  [ "$overall" = "CRITICAL" ] && emoji="🔴"
  local payload="*${emoji} Disk Health — ${host}*\nStatus: *${overall}*\n${results}"

  # Evita spam
  local h; h=$(hash_payload "$payload")
  local last=""
  [ -f "$STATE_FILE" ] && last=$(jq -r '.hash // empty' "$STATE_FILE" || true)
  if [ "${1:-}" = "--test" ] || [ "$h" != "$last" ]; then
    send_tg "$payload" || true
    jq -n --arg hash "$h" --arg payload "$payload" '{hash:$hash, payload:$payload, ts:now|todate}' > "$STATE_FILE"
    log "Alert enviado (status=$overall)"
  else
    log "Sem mudanças; nenhum alerta enviado."
  fi
}

main "$@"
