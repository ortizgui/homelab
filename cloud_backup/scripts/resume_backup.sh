#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-180}"
WAIT_INTERVAL="${WAIT_INTERVAL:-5}"
TAG_PREFIX="${TAG_PREFIX:-resume}"

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
run_engine_cli backup "${backup_tag}"
