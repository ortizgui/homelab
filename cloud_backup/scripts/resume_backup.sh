#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-180}"
WAIT_INTERVAL="${WAIT_INTERVAL:-5}"
TAG_PREFIX="${TAG_PREFIX:-resume}"
PROGRESS_INTERVAL="${PROGRESS_INTERVAL:-10}"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "docker compose nao encontrado" >&2
  exit 1
fi

tag_suffix="$(date +%Y%m%d-%H%M%S)"
backup_tag="${1:-${TAG_PREFIX}-${tag_suffix}}"

run_compose() {
  "${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" "$@"
}

engine_status() {
  local status
  status="$(run_compose ps --status running --services 2>/dev/null | grep -x 'backup-engine' || true)"
  if [[ "${status}" == "backup-engine" ]]; then
    return 0
  fi
  return 1
}

wait_for_engine() {
  local elapsed=0
  while (( elapsed < WAIT_TIMEOUT )); do
    if engine_status; then
      return 0
    fi
    sleep "${WAIT_INTERVAL}"
    elapsed=$((elapsed + WAIT_INTERVAL))
  done

  echo "backup-engine nao entrou em execucao em ${WAIT_TIMEOUT}s" >&2
  run_compose ps >&2 || true
  return 1
}

run_engine_cli() {
  run_compose exec -T backup-engine python3 -m app.operation_cli "$@"
}

interrupted_state_exists() {
  run_compose exec -T backup-engine sh -lc "test -f /data/state/current-run.json"
}

attempt_repository_unlock() {
  echo "Tentando remover locks pendentes do restic..."
  run_engine_cli unlock
}

print_progress() {
  run_compose exec -T backup-engine python3 -c '
import json
from pathlib import Path

state_file = Path("/data/state/current-run.json")
if not state_file.exists():
    print("Aguardando arquivo de progresso...")
    raise SystemExit(0)

payload = json.loads(state_file.read_text(encoding="utf-8"))
progress = payload.get("progress") or {}
phase = progress.get("phase") or "starting"
percent = progress.get("percent_done")
files_done = progress.get("files_done")
total_files = progress.get("total_files")
bytes_done = progress.get("bytes_done")
total_bytes = progress.get("total_bytes")
current_file = progress.get("current_file") or "-"

parts = [f"fase={phase}"]
if percent is not None:
    parts.append(f"progresso={percent * 100:.2f}%")
if files_done is not None:
    if total_files is not None:
        parts.append(f"arquivos={files_done}/{total_files}")
    else:
        parts.append(f"arquivos={files_done}")
if bytes_done is not None:
    if total_bytes is not None:
        parts.append(f"bytes={bytes_done}/{total_bytes}")
    else:
        parts.append(f"bytes={bytes_done}")
parts.append(f"arquivo_atual={current_file}")
print(" | ".join(parts))
' || true
}

monitor_backup() {
  local backup_pid="$1"
  local last_line=""

  while kill -0 "${backup_pid}" >/dev/null 2>&1; do
    last_line="$(print_progress | tail -n 1)"
    if [[ -n "${last_line}" ]]; then
      printf '%s\n' "${last_line}"
    fi
    sleep "${PROGRESS_INTERVAL}"
  done
}

echo "Subindo a stack de backup..."
run_compose up -d backup-engine backup-api backup-scheduler backup-web

echo "Aguardando o backup-engine ficar disponivel..."
wait_for_engine

if interrupted_state_exists; then
  echo "Execucao interrompida detectada em /data/state/current-run.json."
  echo "O proximo ciclo fara a limpeza de recuperacao antes do backup."
fi

echo "Executando preflight..."
if ! preflight_output="$(run_engine_cli preflight 2>&1)"; then
  printf '%s\n' "${preflight_output}"
  if grep -q '"Repository access failed"' <<<"${preflight_output}"; then
    attempt_repository_unlock
    echo "Reexecutando preflight apos unlock..."
    if ! run_engine_cli preflight; then
      echo "Preflight ainda bloqueou a retomada. Revise a conectividade com o repositorio remoto e rode novamente." >&2
      exit 1
    fi
  else
    echo "Preflight bloqueou a retomada. Revise as validacoes acima e rode novamente." >&2
    exit 1
  fi
else
  printf '%s\n' "${preflight_output}"
fi

echo "Iniciando backup com tag ${backup_tag}..."
backup_output_file="$(mktemp)"
run_engine_cli backup "${backup_tag}" >"${backup_output_file}" 2>&1 &
backup_pid=$!

monitor_backup "${backup_pid}"

if ! wait "${backup_pid}"; then
  cat "${backup_output_file}"
  rm -f "${backup_output_file}"
  exit 1
fi

cat "${backup_output_file}"
rm -f "${backup_output_file}"
