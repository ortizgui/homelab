#!/usr/bin/env bash
set -euo pipefail

# Alguns pacotes chamam o executável de localsend_app, outros podem expor "localsend".
if command -v localsend_app >/dev/null 2>&1; then
  BIN="localsend_app"
elif command -v localsend >/dev/null 2>&1; then
  BIN="localsend"
else
  echo "Não achei o binário do LocalSend no PATH."
  echo "Tente: ls -la /usr/bin | grep -i localsend (ajustar no start.sh)"
  exit 1
fi

# Xvfb cria um display fake só pra app não morrer por falta de GUI
exec xvfb-run -a "$BIN"