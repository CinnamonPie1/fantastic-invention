@echo off
setlocal
cd /d "%~dp0"
title DescargoMedicacion HOD1108 - Windows

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 gui.py
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python gui.py
    goto :end
)

echo.
echo [ERROR] No se encontro Python.
echo Instala Python 3.10 o superior desde python.org y marca "Add Python to PATH".
echo.
pause
:end
if not %errorlevel%==0 pause
endlocal
