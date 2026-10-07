#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python3" ]; then
  echo "No existe .venv. Ejecutando setup_dev_mac.command..."
  ./setup_dev_mac.command
fi
. .venv/bin/activate

rm -rf build dist
python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name "DescargoMedicacionHOD1108" \
  --add-data "farmacos.csv:." \
  --add-data "config.default.json:." \
  gui.py

mkdir -p dist/ACS_MACROS_HOD1108
cp -f acs_macros/*.mac dist/ACS_MACROS_HOD1108/
cp -f INSTALACION_MACROS_ACS_1187.md dist/ACS_MACROS_HOD1108/

echo
echo "BUILD COMPLETADO"
echo "Aplicación: $PWD/dist/DescargoMedicacionHOD1108.app"
echo "Macros para ACS: $PWD/dist/ACS_MACROS_HOD1108"
echo "IMPORTANTE: importe los 3 .mac y asigne Ctrl+Shift+L, Ctrl+Shift+E y Ctrl+Shift+C."
