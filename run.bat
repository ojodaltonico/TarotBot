@echo off
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Faltan dependencias. Ejecuta install.bat primero.
  exit /b 1
)
if not exist "node_backend\node_modules" (
  echo [ERROR] Faltan dependencias Node. Ejecuta install.bat primero.
  exit /b 1
)

start "TarotBot Backend" cmd /k call "%~dp0start_backend.bat"
start "TarotBot WhatsApp Gateway" cmd /k call "%~dp0start_gateway.bat"
echo Backend y gateway iniciados en ventanas separadas.
endlocal
