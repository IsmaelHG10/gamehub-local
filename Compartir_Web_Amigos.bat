@echo off
chcp 65001 >nul
setlocal EnableExtensions
title GameHub - Compartir Enlace Publico con Amigos (Sin Registro Cloud)

cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "GAMEHUB_MODE=web"
set "GAMEHUB_REQUIRE_AUTH=true"
set "GAMEHUB_HOST=127.0.0.1"
set "GAMEHUB_PORT=8765"

echo ============================================================================
echo   GameHub - Modo Web Multi-Usuario Instantaneo (Coste 0 EUR / Sin Cuentas)
echo ============================================================================
echo.
set /p "INVITE=Codigo de invitacion opcional para tus amigos (Enter para dejar libre): "
if not "%INVITE%"=="" set "GAMEHUB_INVITE_CODE=%INVITE%"

echo.
echo [1/2] Iniciando servidor GameHub Multi-Usuario en segundo plano (127.0.0.1:8765)...
start "GameHub Backend" /min ".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8765

timeout /t 3 /nobreak >nul

echo [2/2] Creando enlace HTTPS publico gratuito (copia la URL https://...lhr.life que salga abajo)...
echo       (Cierra esta ventana cuando quieras apagar el enlace publico)
echo.
ssh -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -R 80:127.0.0.1:8765 nokey@localhost.run
pause
