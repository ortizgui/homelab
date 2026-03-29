#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.env"

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

DATA_DIR="${1:-$(resolve_data_dir)}"
CONFIG_FILE="${DATA_DIR}/config/config.json"
RCLONE_FILE="${DATA_DIR}/rclone/rclone.conf"
BACKUP_FILE="${CONFIG_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
RESTIC_PASSWORD_FROM_ENV="${RESTIC_PASSWORD:-$(read_env_value "RESTIC_PASSWORD" || true)}"

if [ ! -f "${CONFIG_FILE}" ]; then
  echo "Config file not found: ${CONFIG_FILE}" >&2
  exit 1
fi

cp "${CONFIG_FILE}" "${BACKUP_FILE}"
echo "Backup created: ${BACKUP_FILE}"

python3 - "${CONFIG_FILE}" "${PROJECT_DIR}" "${RESTIC_PASSWORD_FROM_ENV}" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
project_dir = Path(sys.argv[2])
restic_password = sys.argv[3]
sys.path.insert(0, str(project_dir))

from app.configuration import migrate_config, validate_config

config = json.loads(config_path.read_text(encoding="utf-8"))
config = migrate_config(config)

config["sources"] = [
    {"path": "/source/raid1/academic", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/backups", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/documents", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/media", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/onedrive-import", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/personal", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/professional", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/projects", "enabled": True, "allow_empty": True},
    {"path": "/source/raid1/shared", "enabled": True, "allow_empty": False},
    {"path": "/source/raid1/software", "enabled": True, "allow_empty": False},
    {"path": "/source/m2", "enabled": False, "allow_empty": True},
]

provider = config.setdefault("provider", {})
current_password = provider.get("restic_password", "")
if restic_password.strip():
    provider["restic_password"] = restic_password.strip()
elif current_password.strip() in {"", "troque-por-uma-senha-forte-aqui"}:
    print("warning: restic_password is still empty or placeholder")

validate_config(config)
config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Updated sources in {config_path}")
print(f"Enabled source count={sum(1 for source in config['sources'] if source['enabled'])}")
PY

if [ -f "${RCLONE_FILE}" ]; then
  if rg -n 'SEU_CLIENT_ID_AQUI|SEU_CLIENT_SECRET_AQUI|FAKE_ACCESS_TOKEN|FAKE_REFRESH_TOKEN' "${RCLONE_FILE}" >/dev/null 2>&1; then
    echo "warning: ${RCLONE_FILE} still contains placeholder rclone credentials"
  else
    echo "rclone.conf does not contain obvious placeholder markers"
  fi
else
  echo "warning: rclone.conf not found at ${RCLONE_FILE}"
fi

echo "Done. Recomendado validar com:"
echo "  docker compose exec -T backup-engine python3 -m app.operation_cli preflight"
