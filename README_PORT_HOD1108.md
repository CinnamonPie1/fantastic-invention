# DescargoMedicacion — port macOS / ACS 1.1.8.7 / HOD1108 — v2

## Arquitectura

`gui.py -> HODController -> portapapeles + atajo macOS -> macro HOD directo -> sesión ACS 5250 activa`

No usa PCOMM, win32com, EHLLAPI, Dispatcher ni macros encadenados.

## Macros

- `DescargoLeer_HOD1108.mac` — captura paciente y nota.
- `DescargoEjecutar_HOD1108.mac` — búsqueda y carga de medicamentos.
- `DescargoConfirmar_HOD1108.mac` — confirmación final.

Atajos por defecto:

- Leer: Ctrl+Shift+L
- Descargar: Ctrl+Shift+E
- Confirmar: Ctrl+Shift+C

Consulta `INSTALACION_MACROS_ACS_1187.md` antes de probar.
