@echo off
title Bot de Musica WhatsApp - Ejecutando
color 0A

echo.
echo ============================================================
echo          Bot de Musica WhatsApp - INICIANDO
echo ============================================================
echo.

REM Verificar que las dependencias estén instaladas
if not exist "python_backend\venv" (
    echo [ERROR] Entorno virtual no encontrado
    echo Ejecuta install.bat primero para instalar las dependencias
    pause
    exit /b 1
)

if not exist "node_backend\node_modules" (
    echo [ERROR] Dependencias de Node.js no encontradas
    echo Ejecuta install.bat primero para instalar las dependencias
    pause
    exit /b 1
)

echo [OK] Verificacion de dependencias completada
echo.

REM Iniciar servicios
echo [*] Iniciando servicios...
echo.

REM Iniciar Node.js (WhatsApp)
echo [OK] Iniciando servidor WhatsApp (Node.js)...
start "WhatsApp Bot - Node.js" cmd /k "cd /d %CD%\node_backend && npm start"

REM Esperar un poco para que Node.js se inicialice
timeout /t 5 /nobreak >nul

REM Iniciar Python (Backend + GUI)
echo [OK] Iniciando backend + interfaz grafica (Python)...
start "Bot Musica - Python" cmd /k "cd /d %CD%\python_backend && venv\Scripts\activate && python app.py"

echo.
echo ============================================================
echo              SERVICIOS INICIADOS CORRECTAMENTE
echo ============================================================
echo.
echo  [*] WhatsApp Bot: Escanea el QR en la ventana
echo  [*] Interfaz Grafica: Se abrira automaticamente
echo  [*] Flask API: http://localhost:5000
echo.
echo ============================================================
echo.
echo Presiona cualquier tecla para cerrar esta ventana...
echo (Las otras ventanas seguiran abiertas)
pause >nul