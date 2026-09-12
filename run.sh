#!/usr/bin/env bash
# Start the AAC accelerator. Serves the UI and the candidate API on :8000.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt; }
exec ./.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 "$@"
