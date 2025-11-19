#!/usr/bin/env bash
# Start production server using uvicorn and environment PORT
set -e
PORT=${PORT:-3001}
exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 1
