#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

bash -n "$ROOT_DIR/bulk_log/bulk_log.sh"

echo "bash -n: OK"

if command -v shellcheck >/dev/null 2>&1; then
    shellcheck "$ROOT_DIR/bulk_log/bulk_log.sh"
    echo "shellcheck: OK"
else
    echo "shellcheck: SKIP (not installed)"
fi

if command -v bats >/dev/null 2>&1; then
    bats "$ROOT_DIR/bulk_log/tests/bulk_log.bats"
else
    echo "bats: SKIP (not installed)"
fi
