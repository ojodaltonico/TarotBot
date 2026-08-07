@echo off
setlocal
cd /d "%~dp0node_backend"
if not exist "node_modules" (
  echo [ERROR] Ejecuta install.bat primero.
  exit /b 1
)
call npm.cmd start
endlocal
