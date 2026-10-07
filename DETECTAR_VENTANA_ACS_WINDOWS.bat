@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py detectar_ventanas_acs.py
) else (
  python detectar_ventanas_acs.py
)
