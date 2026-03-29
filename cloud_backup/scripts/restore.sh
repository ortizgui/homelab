#!/bin/bash

set -euo pipefail

if [ $# -lt 2 ]; then
    echo "usage: restore.sh <snapshot-id> <target> [include-path]" >&2
    exit 1
fi

exec python3 -m app.operation_cli restore "$@"
