#!/bin/bash

set -euo pipefail

TAG="${1:-manual}"

exec python3 -m app.operation_cli backup "$TAG"
