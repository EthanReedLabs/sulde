#!/bin/bash
# Compatibility entry: Python owns isolation, assertions and evidence.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -B "$SCRIPT_DIR/test_r3_normal_pair.py" "$@"
