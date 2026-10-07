@echo off
setlocal
cd /d "%~dp0"
title Compilar DescargoMedicacion HOD1108

set PYEXE=
where py >nul 2>nul && set PYEXE=py -3
if not defined PYEXE (
    where python >nul 2>nul && set PYEXE=python
)
if not defined PYEXE (
    echo [ERROR] Python no esta instalado.
    pause
    exit /b 1
)

%PYEXE% -m pip install --upgrade pip
if errorlevel 1 goto :fail
%PYEXE% -m pip install -r requirements-build.txt
if errorlevel 1 goto :fail

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
%PYEXE% -m PyInstaller --clean --noconfirm DescargoMedicacion_HOD1108_Windows.spec
if errorlevel 1 goto :fail

echo.
echo EXE creado en:
echo   %CD%\dist\DescargoMedicacionHOD1108.exe
pause
exit /b 0

:fail
echo.
echo [ERROR] No se pudo compilar.
pause
exit /b 1
