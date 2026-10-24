#!/usr/bin/env bash
# Smoke tests against the running Toolbox (roadmap S0.3).
#   scripts/smoke.sh                 # all checks incl. headless browser
#   scripts/smoke.sh --no-browser    # HTTP checks only (faster, no chromium needed)
#   TOOLBOX_URL=http://host:8000 scripts/smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."
args=(tests/smoke -q -p no:cacheprovider)
if [[ "${1:-}" == "--no-browser" ]]; then args+=(-m "not browser"); shift; fi
exec python3 -m pytest "${args[@]}" "$@"
