#!/usr/bin/env bash
# Start the Emergence-Mini server
set -e
cd "$(dirname "$0")"
exec python3 -m uvicorn server:app --host 127.0.0.1 --port 8080 --log-level info
