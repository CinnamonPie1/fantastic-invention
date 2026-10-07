@echo off
cd /d "%~dp0"
echo ============================================================
echo  PRUEBA DE PORTAPAPELES - DESCARGO HOD1108 WINDOWS V5
echo ============================================================
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 probar_portapapeles_windows.py
) else (
  python probar_portapapeles_windows.py
)
echo.
pause
