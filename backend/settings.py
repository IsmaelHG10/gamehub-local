"""Rutas y ajustes globales de GameHub Local.

Todas las rutas se pueden sobrescribir con variables de entorno (útil para tests):
  GAMEHUB_DB, GAMEHUB_CONFIG_DIR, GAMEHUB_NO_AUTOSYNC
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
CONFIG_DIR = Path(os.environ.get("GAMEHUB_CONFIG_DIR", ROOT_DIR / "config"))
DATA_DIR = ROOT_DIR / "data"
DB_PATH = Path(os.environ.get("GAMEHUB_DB", DATA_DIR / "gamehub.db"))

SOURCES_FILE = CONFIG_DIR / "sources.json"
DEPENDENCIES_FILE = CONFIG_DIR / "dependencies.json"

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
AUTO_SYNC = os.environ.get("GAMEHUB_NO_AUTOSYNC", "") not in ("1", "true", "yes")
SYNC_INTERVAL_SECONDS = 30 * 60  # Refresco automático de feeds cada 30 min
FEED_KEEP_PER_SOURCE = 600       # Nº máx. de entradas guardadas por feed (histórico para el buscador)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
