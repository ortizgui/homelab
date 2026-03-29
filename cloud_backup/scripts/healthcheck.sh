#!/bin/bash

set -euo pipefail

exec python3 -m app.operation_cli healthcheck
