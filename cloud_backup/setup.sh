#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

read_env_value() {
  local key="$1"
  local env_file="$2"

  if [ ! -f "$env_file" ]; then
    return 1
  fi

  awk -F= -v search_key="$key" '
    $1 == search_key {
      sub(/^[^=]+=*/, "", $0)
      print $0
      exit
    }
  ' "$env_file"
}

if [ ! -f "$ROOT_DIR/.env" ]; then
  cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
  echo "Created $ROOT_DIR/.env from .env.example"
fi

DATA_DIR="$(read_env_value "CLOUD_BACKUP_DATA_DIR" "$ROOT_DIR/.env")"
DATA_DIR="${DATA_DIR:-$ROOT_DIR/data}"

case "$DATA_DIR" in
  ./*|../*)
    DATA_DIR="$ROOT_DIR/${DATA_DIR#./}"
    ;;
  *)
    if [ "${DATA_DIR#/}" = "$DATA_DIR" ]; then
      DATA_DIR="$ROOT_DIR/$DATA_DIR"
    fi
    ;;
esac

mkdir -p \
  "$DATA_DIR/config" \
  "$DATA_DIR/logs" \
  "$DATA_DIR/rclone" \
  "$DATA_DIR/restic-cache" \
  "$DATA_DIR/restore" \
  "$DATA_DIR/state"

chmod 700 "$DATA_DIR/config" "$DATA_DIR/rclone" || true
chmod 755 "$DATA_DIR/logs" "$DATA_DIR/restic-cache" "$DATA_DIR/restore" "$DATA_DIR/state" || true

if [ ! -f "$DATA_DIR/rclone/rclone.conf" ]; then
  : > "$DATA_DIR/rclone/rclone.conf"
  chmod 600 "$DATA_DIR/rclone/rclone.conf" || true
fi

echo "Cloud backup directories are ready."
echo "Next steps:"
echo "1. Edit $ROOT_DIR/.env"
echo "2. Start the stack with: docker compose up -d --build"
echo "3. Open http://localhost:\${CLOUD_BACKUP_WEB_PORT:-8095}"
echo ""
echo "Persistent data directory: $DATA_DIR"
