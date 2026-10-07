#!/bin/bash
set -e
cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
python - <<'PY'
import tkinter
print("Tkinter OK - Tcl/Tk", tkinter.TclVersion)
PY

echo
echo "Entorno listo. Inicia con: ./start_dev_mac.command"
