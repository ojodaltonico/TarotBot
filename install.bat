@echo off
title Bot de Musica WhatsApp - Instalador
color 0A

echo.
echo ============================================================
echo          BOT DE MUSICA WHATSAPP - INSTALADOR
echo ============================================================
echo.

REM Verificar si Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no está instalado o no está en el PATH
    echo Descarga Python desde: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Verificar si Node.js está instalado
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js no está instalado o no está en el PATH
    echo Descarga Node.js desde: https://nodejs.org/
    pause
    exit /b 1
)

echo [OK] Python y Node.js detectados correctamente
echo.

REM Crear carpeta de sesiones si no existe
if not exist "node_backend\whatsapp-sessions" (
    mkdir "node_backend\whatsapp-sessions"
    echo [OK] Carpeta de sesiones creada
)

REM Configurar entorno virtual Python
echo [*] Configurando entorno virtual de Python...
if not exist "python_backend\venv" (
    python -m venv "python_backend\venv"
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual
        pause
        exit /b 1
    )
    echo [OK] Entorno virtual creado
) else (
    echo [OK] Entorno virtual ya existe
)

echo.

REM Instalar dependencias de Python
echo [*] Instalando dependencias de Python...
cd python_backend

if not exist "requirements.txt" (
    echo [ERROR] No se encontró requirements.txt
    cd ..
    pause
    exit /b 1
)

call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if errorlevel 1 (
    echo [ERROR] Error instalando dependencias
    cd ..
    pause
    exit /b 1
)

echo [OK] Dependencias de Python instaladas correctamente
cd ..

echo.

REM Instalar dependencias de Node.js
echo [*] Instalando dependencias de Node.js...
cd node_backend

if not exist "node_modules" (
    call npm install
    if errorlevel 1 (
        echo [ERROR] Error instalando dependencias de Node.js
        cd ..
        pause
        exit /b 1
    )
    echo [OK] Dependencias de Node.js instaladas
) else (
    echo [OK] Dependencias de Node.js ya instaladas
)

cd ..

echo.
echo ============================================================
echo            INSTALACION COMPLETADA EXITOSAMENTE
echo ============================================================
echo.
echo  [OK] Entorno virtual Python configurado
echo  [OK] Dependencias de Python instaladas
echo  [OK] Dependencias de Node.js instaladas
echo.
echo  Ahora puedes ejecutar run.bat para iniciar el bot
echo.
echo ============================================================
pause