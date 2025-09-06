#!/usr/bin/env bash
set -euo pipefail
. /etc/disk-alert.conf 2>/dev/null || true
disks=$(lsblk -ndo NAME,TYPE | awk '$2=="disk"{print "/dev/"$1}')
for d in $disks; do
  opt=""
  base=$(basename "$d")
  for pair in ${MAP_DEVICE_OPTS:-}; do k="${pair%%=*}"; v="${pair#*=}"; [ "$k" = "$base" ] && opt="$v"; done
  smartctl -X $opt "$d" >/dev/null 2>&1 || true   # aborta testes antigos
  smartctl -t short $opt "$d" || true
done
