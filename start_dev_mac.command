#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ -x ".venv/bin/python3" ]; then
  PY=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "ERROR: no se encontró python3."
  exit 1
fi

exec "$PY" gui.py --catalog "farmacos.csv"
