@echo off
chcp 65001 >nul
setlocal EnableExtensions
title GameHub Local - Centro de Mando PC Gaming

cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist ".venv\Scripts\python.exe" (
    echo [GameHub] Creando entorno virtual local por primera vez...
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] No se encontro Python 3.11+ en el sistema.
        echo Instala Python desde https://www.python.org/downloads/ marcando "Add python.exe to PATH".
        pause
        exit /b 1
    )
    python -m venv .venv
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, feedparser, bs4" >nul 2>nul
if errorlevel 1 (
    echo [GameHub] Instalando dependencias ligeras de Python...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --timeout 15 --retries 1 -r requirements.txt
    if errorlevel 1 (
        echo [GameHub] PyPI principal no responde; usando espejo alternativo de respaldo...
        ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
    )
)

".venv\Scripts\python.exe" -m backend.launcher
if errorlevel 1 (
    echo.
    echo [ERROR] GameHub Local se detuvo con un error.
    pause
)
