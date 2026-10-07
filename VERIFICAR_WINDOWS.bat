@echo off
setlocal
cd /d "%~dp0"
title Verificacion DescargoMedicacion HOD1108

set PYEXE=
where py >nul 2>nul && set PYEXE=py -3
if not defined PYEXE (
    where python >nul 2>nul && set PYEXE=python
)
if not defined PYEXE (
    echo [ERROR] Python no esta instalado o no esta en PATH.
    pause
    exit /b 1
)

echo [1/3] Version de Python...
%PYEXE% --version
if errorlevel 1 goto :fail

echo.
echo [2/3] Comprobando Tkinter...
%PYEXE% -c "import tkinter; print('Tkinter OK - Tcl/Tk', tkinter.TclVersion)"
if errorlevel 1 (
    echo [ERROR] Tkinter no esta disponible. Usa el instalador oficial de Python para Windows.
    goto :fail
)

echo.
echo [3/3] Ejecutando pruebas internas...
%PYEXE% -m unittest tests.test_port -v
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo TODO OK. Ya puedes abrir INICIAR_WINDOWS.bat
 echo ============================================================
pause
exit /b 0

:fail
echo.
echo La verificacion fallo. Copia el error y enviamelo.
pause
exit /b 1
