# Reporte de corrección v2

La primera versión usaba `DescargoDispatcher_HOD1108.mac` con acciones `<playmacro>`.
En la prueba real ACS/HOD devolvió: `A chained macro specified in DescargoDispatcher_HOD1108 macro does not exist`.

La versión v2 elimina por completo el encadenamiento. La aplicación inicia directamente
`DescargoLeer_HOD1108`, `DescargoEjecutar_HOD1108` o `DescargoConfirmar_HOD1108` mediante
atajos independientes.

Validaciones locales:

- 3 macros XML bien formados.
- Ninguno contiene `<playmacro>`.
- `[pagedn]` se mantiene para el avance compatible HOD1108.
- Parser y catálogo continúan funcionando.
- Protocolo de lectura, ejecución, agotados y confirmación conserva los mismos marcadores.
- Suite automática: 9 pruebas.
