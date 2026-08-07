@echo off
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python no esta disponible en PATH.
  exit /b 1
)
node --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js no esta disponible en PATH.
  exit /b 1
)

if not exist "backend\.venv\Scripts\python.exe" (
  python -m venv backend\.venv
  if errorlevel 1 exit /b 1
)

backend\.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 exit /b 1
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1

call npm.cmd --prefix node_backend install
if errorlevel 1 exit /b 1

echo.
echo Instalacion completada. Ejecuta run.bat para iniciar ambos servicios.
endlocal
