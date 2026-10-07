#!/bin/bash
set -e
cd "$(dirname "$0")"
PY="python3"
if [ -x ".venv/bin/python3" ]; then PY=".venv/bin/python3"; fi
"$PY" -m unittest discover -s tests -v
