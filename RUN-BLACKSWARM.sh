#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'BLACKSWARM requires Python 3. No system changes have been made.' >&2
  exit 1
fi
exec python3 run.py "$@"
