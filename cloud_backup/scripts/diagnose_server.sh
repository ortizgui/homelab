#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"
ENV_FILE="${PROJECT_DIR}/.env"
OUTPUT_DIR="${PROJECT_DIR}/diagnostics"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="${OUTPUT_DIR}/cloud_backup_diagnose_${TIMESTAMP}.log"

mkdir -p "${OUTPUT_DIR}"

section() {
  printf '\n===== %s =====\n' "$1" | tee -a "${REPORT_FILE}"
}

line() {
  printf '%s\n' "$1" | tee -a "${REPORT_FILE}"
}

sanitize_stream() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c "$(cat <<'PY'
import re
import sys

text = sys.stdin.read()
patterns = [
    (r"(?m)^(\s*RESTIC_PASSWORD=).*$", r"\1[REDACTED]"),
    (r'("restic_password"\s*:\s*")[^"]*(")', r"\1[REDACTED]\2"),
    (r'(\\"restic_password\\"\s*:\s*\\")[^\\"]*(\\")', r"\1[REDACTED]\2"),
    (r"(?m)^(\s*client_secret\s*=\s*).*$", r"\1[REDACTED]"),
    (r'("client_secret"\s*:\s*")[^"]*(")', r"\1[REDACTED]\2"),
    (r'(\\"client_secret\\"\s*:\s*\\")[^\\"]*(\\")', r"\1[REDACTED]\2"),
    (r"(?m)^(\s*token\s*=\s*).*$", r"\1[REDACTED]"),
    (r'("token"\s*:\s*)\{.*?\}', r"\1\"[REDACTED]\""),
    (r'(\\"token\\"\s*:\s*\\")(\{.*?\})(\\")', r"\1[REDACTED]\3"),
    (r'("access_token"\s*:\s*")[^"]*(")', r"\1[REDACTED]\2"),
    (r'(\\"access_token\\"\s*:\s*\\")[^\\"]*(\\")', r"\1[REDACTED]\2"),
    (r'("refresh_token"\s*:\s*")[^"]*(")', r"\1[REDACTED]\2"),
    (r'(\\"refresh_token\\"\s*:\s*\\")[^\\"]*(\\")', r"\1[REDACTED]\2"),
]

for pattern, replacement in patterns:
    text = re.sub(pattern, replacement, text, flags=re.DOTALL)

sys.stdout.write(text)
PY
)" 2>/dev/null
    return
  fi

  sed -E \
    -e 's|^(RESTIC_PASSWORD=).*$|\1[REDACTED]|' \
    -e 's|^([[:space:]]*client_secret[[:space:]]*=[[:space:]]*).*$|\1[REDACTED]|' \
    -e 's|^([[:space:]]*token[[:space:]]*=[[:space:]]*).*$|\1[REDACTED]|'
}

run_cmd() {
  local title="$1"
  shift
  section "${title}"
  if command -v "$1" >/dev/null 2>&1; then
    "$@" 2>&1 | sanitize_stream | tee -a "${REPORT_FILE}"
    local status=${PIPESTATUS[0]}
    line "[exit_code] ${status}"
    return "${status}"
  fi
  line "Command not found: $1"
  return 127
}

read_env_value() {
  local key="$1"
  if [ ! -f "${ENV_FILE}" ]; then
    return 1
  fi
  awk -F= -v search_key="${key}" '
    $1 == search_key {
      sub(/^[^=]+=*/, "", $0)
      print $0
      exit
    }
  ' "${ENV_FILE}"
}

resolve_data_dir() {
  local raw
  raw="$(read_env_value "CLOUD_BACKUP_DATA_DIR" || true)"
  if [ -z "${raw}" ]; then
    printf '%s\n' "${PROJECT_DIR}/data"
    return
  fi
  case "${raw}" in
    /*) printf '%s\n' "${raw}" ;;
    ./*) printf '%s\n' "${PROJECT_DIR}/${raw#./}" ;;
    *) printf '%s\n' "${PROJECT_DIR}/${raw}" ;;
  esac
}

compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" "$@"
    return
  fi
  docker-compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" "$@"
}

run_compose() {
  local title="$1"
  shift
  section "${title}"
  if command -v docker >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1; then
    compose_cmd "$@" 2>&1 | sanitize_stream | tee -a "${REPORT_FILE}"
    local status=${PIPESTATUS[0]}
    line "[exit_code] ${status}"
    return "${status}"
  fi
  line "Docker Compose is not available"
  return 127
}

run_http_check() {
  local title="$1"
  local url="$2"
  section "${title}"
  if command -v curl >/dev/null 2>&1; then
    curl -sS -i --max-time 20 "${url}" 2>&1 | sanitize_stream | tee -a "${REPORT_FILE}"
    local status=${PIPESTATUS[0]}
    line "[exit_code] ${status}"
    return "${status}"
  fi
  line "curl not available"
  return 127
}

inspect_file() {
  local title="$1"
  local path="$2"
  section "${title}"
  if [ -e "${path}" ]; then
    ls -ld "${path}" | tee -a "${REPORT_FILE}"
    if [ -f "${path}" ]; then
      sed -n '1,220p' "${path}" 2>&1 | sanitize_stream | tee -a "${REPORT_FILE}"
    fi
    line "[exists] yes"
    return 0
  fi
  line "[exists] no"
  return 1
}

validate_config_json() {
  local config_file="$1"
  section "Config JSON Validation"
  if [ ! -f "${config_file}" ]; then
    line "Config file not found: ${config_file}"
    return 1
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "${config_file}" "${PROJECT_DIR}" <<'PY' 2>&1 | sanitize_stream | tee -a "${REPORT_FILE}"
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
project_dir = Path(sys.argv[2])
sys.path.insert(0, str(project_dir))

try:
    from app.configuration import migrate_config, validate_config
except Exception as exc:
    print(f"failed_to_import_validation: {exc}")
    raise

raw = json.loads(config_path.read_text(encoding="utf-8"))
print(f"config_keys={sorted(raw.keys())}")
migrated = migrate_config(raw)
validate_config(migrated)
print("validation=ok")
print(f"schema_version={migrated.get('schema_version')}")
print(f"authorized_roots={migrated.get('general', {}).get('authorized_roots')}")
print(f"sources={len(migrated.get('sources', []))}")
missing_top_level = sorted(set(migrated.keys()) - set(raw.keys()))
print(f"missing_top_level_keys_added_by_migration={missing_top_level}")
PY
    local status=${PIPESTATUS[0]}
    line "[exit_code] ${status}"
    return "${status}"
  fi

  if command -v jq >/dev/null 2>&1; then
    jq . "${config_file}" 2>&1 | tee -a "${REPORT_FILE}"
    local status=${PIPESTATUS[0]}
    line "[exit_code] ${status}"
    return "${status}"
  fi

  line "Neither python3 nor jq is available to validate JSON"
  return 127
}

main() {
  : > "${REPORT_FILE}"

  local data_dir config_file rclone_file web_port api_port primary_path secondary_path
  data_dir="$(resolve_data_dir)"
  config_file="${data_dir}/config/config.json"
  rclone_file="${data_dir}/rclone/rclone.conf"
  web_port="$(read_env_value "CLOUD_BACKUP_WEB_PORT" || true)"
  api_port="$(read_env_value "CLOUD_BACKUP_API_PORT" || true)"
  primary_path="$(read_env_value "PRIMARY_SOURCE_PATH" || true)"
  secondary_path="$(read_env_value "SECONDARY_SOURCE_PATH" || true)"
  web_port="${web_port:-8095}"
  api_port="${api_port:-8096}"

  line "Cloud Backup diagnostic report"
  line "generated_at=$(date -Iseconds)"
  line "project_dir=${PROJECT_DIR}"
  line "compose_file=${COMPOSE_FILE}"
  line "env_file=${ENV_FILE}"
  line "data_dir=${data_dir}"
  line "report_file=${REPORT_FILE}"

  run_cmd "Host Summary" uname -a
  run_cmd "Current User" id
  run_cmd "Disk Usage" df -h
  run_cmd "Mounts" mount

  inspect_file ".env" "${ENV_FILE}"
  inspect_file "Compose File" "${COMPOSE_FILE}"
  inspect_file "Persisted Config" "${config_file}"
  inspect_file "rclone.conf" "${rclone_file}"

  validate_config_json "${config_file}"

  section "Expected Host Paths"
  for path in "${data_dir}" "${data_dir}/config" "${data_dir}/logs" "${data_dir}/state" "${primary_path}" "${secondary_path}"; do
    if [ -n "${path}" ]; then
      if [ -e "${path}" ]; then
        ls -ld "${path}" | tee -a "${REPORT_FILE}"
      else
        line "missing=${path}"
      fi
    fi
  done

  run_cmd "Docker Version" docker version
  run_compose "Compose Config" config
  run_compose "Compose PS" ps
  run_compose "Compose Logs: backup-web" logs --tail=200 backup-web
  run_compose "Compose Logs: backup-api" logs --tail=200 backup-api
  run_compose "Compose Logs: backup-engine" logs --tail=200 backup-engine
  run_compose "Compose Logs: backup-scheduler" logs --tail=200 backup-scheduler

  run_http_check "HTTP Check: web /" "http://127.0.0.1:${web_port}/"
  run_http_check "HTTP Check: web /api/config" "http://127.0.0.1:${web_port}/api/config"
  run_http_check "HTTP Check: web /api/status" "http://127.0.0.1:${web_port}/api/status"
  run_http_check "HTTP Check: api /healthz" "http://127.0.0.1:${api_port}/healthz"
  run_http_check "HTTP Check: api /api/config" "http://127.0.0.1:${api_port}/api/config"
  run_http_check "HTTP Check: api /api/status" "http://127.0.0.1:${api_port}/api/status"

  run_compose "Engine Healthcheck" exec -T backup-engine python3 -m app.operation_cli healthcheck
  run_compose "Engine Preflight" exec -T backup-engine python3 -m app.operation_cli preflight
  inspect_file "Operations Log" "${data_dir}/logs/operations.jsonl"
  inspect_file "Preflight Log" "${data_dir}/logs/preflight.jsonl"

  section "Likely Failure Hints"
  if [ -f "${config_file}" ] && command -v python3 >/dev/null 2>&1; then
    python3 - "${config_file}" <<'PY' 2>&1 | tee -a "${REPORT_FILE}"
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for key in ("notifications", "security", "limits"):
    print(f"has_{key}={key in config}")
print(f"has_schema_version={'schema_version' in config}")
print(f"placeholder_restic_password={config.get('provider', {}).get('restic_password', '').strip() in {'', 'troque-por-uma-senha-forte-aqui'}}")
PY
    line "[exit_code] ${PIPESTATUS[0]}"
  else
    line "Skipped structured hint check"
  fi

  section "rclone Placeholder Check"
  if [ -f "${rclone_file}" ]; then
    if command -v rg >/dev/null 2>&1; then
      rg -n 'SEU_CLIENT_ID_AQUI|SEU_CLIENT_SECRET_AQUI|FAKE_ACCESS_TOKEN|FAKE_REFRESH_TOKEN' "${rclone_file}" 2>&1 | tee -a "${REPORT_FILE}"
      line "[exit_code] ${PIPESTATUS[0]}"
    else
      line "rg not available"
    fi
  else
    line "rclone.conf not found"
  fi

  line ""
  line "Diagnostic finished. Share this file for analysis:"
  line "${REPORT_FILE}"
}

main "$@"
