@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
cd /d "%ROOT%"
if not exist "%ROOT%data" mkdir "%ROOT%data" >nul 2>&1
set "START_LOCK=%ROOT%data\run-start.lock"
mkdir "%START_LOCK%" >nul 2>&1
if errorlevel 1 (
  echo TarotBot ya se esta iniciando en otra ventana. Espera unos segundos y ejecuta run.bat nuevamente si hace falta.
  exit /b 0
)

echo ========================================
echo TAROTBOT - INICIANDO
echo ========================================

if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
  echo [ERROR] Falta backend\.venv. Ejecuta install.bat primero.
  goto :failed
)
if not exist "%ROOT%node_backend\node_modules" (
  echo [ERROR] Faltan dependencias Node. Ejecuta install.bat primero.
  goto :failed
)

echo.
echo [1/3] Backend...
call :health
if not errorlevel 1 (
  echo OK - http://127.0.0.1:5001 ^(ya estaba activo^)
  goto :gateway
)

netstat -ano | findstr /R /C:":5001 .*LISTENING" >nul
if not errorlevel 1 (
  echo [ERROR] El puerto 5001 esta ocupado por otra aplicacion y /health no responde como TarotBot.
  echo Cierra esa aplicacion o configura otro puerto antes de continuar.
  goto :failed
)

start "TarotBot - Backend" cmd /k call "%ROOT%start_backend.bat"
set /a attempts=0
:wait_backend
timeout /t 1 /nobreak >nul
call :health
if not errorlevel 1 (
  echo OK - http://127.0.0.1:5001
  goto :gateway
)
set /a attempts+=1
if %attempts% LSS 30 goto :wait_backend
echo [ERROR] El backend no respondio en 30 segundos. Revisa la ventana "TarotBot - Backend".
goto :failed

:gateway
echo.
echo [2/3] WhatsApp Gateway...
call :gateway_running
if not errorlevel 1 (
  echo OK - gateway ya estaba activo.
  goto :dashboard
)
start "TarotBot - WhatsApp Gateway" cmd /k call "%ROOT%start_gateway.bat"
timeout /t 3 /nobreak >nul
call :gateway_running
if not errorlevel 1 (
  echo iniciado
) else (
  echo [ERROR] El gateway no parece estar activo. Revisa la ventana "TarotBot - WhatsApp Gateway".
  goto :failed
)

:dashboard
echo.
echo [3/3] Dashboard...
if exist "%ROOT%.env" findstr /R /I /C:"^ADMIN_ENABLED[ ]*=[ ]*false" "%ROOT%.env" >nul && (
  echo Dashboard deshabilitado por configuracion.
  goto :done
)
start "" "http://127.0.0.1:5001/admin"
echo abriendo navegador

:done
echo.
echo TarotBot iniciado.
rmdir "%START_LOCK%" >nul 2>&1
exit /b 0

:failed
rmdir "%START_LOCK%" >nul 2>&1
exit /b 1

:health
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:5001/health; if ($r.StatusCode -eq 200 -and $r.Content -match '\"status\"\s*:\s*\"ok\"') { exit 0 }; exit 1 } catch { exit 1 }"
exit /b %errorlevel%

:gateway_running
powershell -NoProfile -Command "$found=$false; foreach($p in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)){if($p.Name -eq 'node.exe' -and $p.CommandLine -like '*index.js*'){$found=$true}}; if($found){exit 0}else{exit 1}"
exit /b %errorlevel%
