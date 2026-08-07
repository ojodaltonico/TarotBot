@echo off
setlocal
cd /d "%~dp0"
if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Ejecuta install.bat primero.
  exit /b 1
)
backend\.venv\Scripts\python.exe backend\run.py
endlocal
