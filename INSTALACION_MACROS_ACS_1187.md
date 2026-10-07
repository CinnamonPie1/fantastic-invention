# Instalación corregida — ACS 1.1.8.7 / HOD1108 (macOS)

## Cambio importante de esta versión

Esta versión **NO usa `DescargoDispatcher_HOD1108` ni `<playmacro>`**.
El error `A chained macro specified ... does not exist` se elimina de raíz.
La aplicación dispara directamente cada macro mediante un atajo distinto.

## 1. Instalar únicamente estos 3 macros

- `DescargoLeer_HOD1108.mac`
- `DescargoEjecutar_HOD1108.mac`
- `DescargoConfirmar_HOD1108.mac`

No instales ni asignes `DescargoDispatcher_HOD1108.mac` de la versión anterior.

## 2. Asignar los atajos en ACS

En la sesión 5250, abre **Edit > Preferences > Keyboard** y asigna:

- `DescargoLeer_HOD1108` → **Ctrl + Shift + L**
- `DescargoEjecutar_HOD1108` → **Ctrl + Shift + E**
- `DescargoConfirmar_HOD1108` → **Ctrl + Shift + C**

Los modificadores y letras también pueden cambiarse desde la configuración de la app,
pero para la primera prueba usa exactamente los valores anteriores.

## 3. Verificar cada macro

Abre cada uno en el editor de macros y ejecuta **Verify**. Los tres deben verificar
sin errores antes de probar la aplicación.

## 4. Permiso de Accesibilidad de macOS

Ve a **Ajustes del Sistema > Privacidad y seguridad > Accesibilidad** y autoriza
la aplicación, o Terminal/Python si ejecutas desde código fuente.

## 5. Primera prueba

1. Abre la sesión 5250 y entra a una nota conocida.
2. Ejecuta manualmente **Ctrl+Shift+L**.
3. Si el macro está instalado correctamente, ya no debe aparecer ningún mensaje de
   “chained macro”.
4. Después abre la aplicación y prueba **Leer**.
5. Continúa con un descargo de 1 medicamento, luego 2, 3 y 4.
6. Finalmente prueba la confirmación.

## Por qué se cambió

HOD solo puede encadenar macros que estén disponibles en la misma ubicación de macros
y los nombres son sensibles a mayúsculas/minúsculas. En ACS esa resolución puede variar
según si el macro está en Current Session, Personal Library o una User Library. Esta
versión evita completamente esa dependencia: cada macro se inicia directamente.
